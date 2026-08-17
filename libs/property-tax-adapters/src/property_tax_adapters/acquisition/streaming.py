"""Acquire one artifact by streaming it, hashing as it goes.

The complete response never becomes a value.  Bytes arrive in bounded chunks,
each one hashed and handed to the sink and then dropped, so peak memory is the
chunk size rather than the artifact size — an 11.5 GB Denton export and a 4 KB
fixture cost the same.

Three rules shape the control flow:

**Validate before contacting.**  Every URL, initial and redirected alike, passes
the policy before a connection exists.  Validating a destination after reaching
it is not validation; the request has already been sent.

**Bound the read.**  A server that never stops sending, or that sends more than
it declared, is stopped at the ceiling rather than believed.

**Leave nothing behind.**  Any failure — timeout, truncation, an over-long body,
a mismatched checksum, or an interruption — aborts the sink.  A partial object
that survived a failure would be indistinguishable from a complete one.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from property_tax_application.acquisition import (
    AcquiredArtifact,
    AcquisitionError,
    AcquisitionFailure,
    AcquisitionPolicy,
    ArtifactSink,
    RedirectHop,
    ResponseMetadata,
    sanitize_headers,
)

from property_tax_adapters.acquisition.transport import (
    HttpResponse,
    HttpTransport,
    StdlibHttpTransport,
    resolve_location,
)

__all__ = ["acquire_artifact"]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def acquire_artifact(
    *,
    url: str,
    sink: ArtifactSink,
    policy: AcquisitionPolicy,
    transport: HttpTransport | None = None,
    expected_sha256: str | None = None,
) -> AcquiredArtifact:
    """Stream one artifact into `sink` and return what the acquisition proved.

    Keyword-only: `url` and `expected_sha256` are both strings, and a positional
    signature would let a caller transpose them and have it type-check.

    The sink is entered and left here.  A caller that had to remember to abort
    on every failure path would eventually not, and the partial object would
    outlive the failure that created it.
    """

    if expected_sha256 is not None and _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal characters")

    client = transport if transport is not None else StdlibHttpTransport()
    redirects: list[RedirectHop] = []
    current = url

    with sink as opened:
        try:
            for _ in range(policy.max_redirects + 1):
                _require_permitted(current, policy)
                with client.open(current, timeout=policy.timeout_seconds) as response:
                    status = response.status
                    if status in _REDIRECT_STATUSES:
                        current = _hop(response, current, policy, redirects)
                        continue
                    if status != 200:
                        raise AcquisitionError(AcquisitionFailure.UNSUPPORTED_STATUS, str(status))
                    return _drain(
                        response=response,
                        sink=opened,
                        policy=policy,
                        final_url=current,
                        redirects=tuple(redirects),
                        expected_sha256=expected_sha256,
                    )
            raise AcquisitionError(AcquisitionFailure.TOO_MANY_REDIRECTS, str(policy.max_redirects))
        except BaseException:
            # BaseException, not Exception: a KeyboardInterrupt or a cancelled
            # task leaves exactly the same partial object as a timeout does, and
            # the reason it stopped does not change what has to be cleaned up.
            opened.abort()
            raise


def _require_permitted(url: str, policy: AcquisitionPolicy) -> None:
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        raise AcquisitionError(AcquisitionFailure.UNAPPROVED_HOST, "no host in URL")
    policy.permits(parts.scheme, host)


def _hop(
    response: HttpResponse,
    current: str,
    policy: AcquisitionPolicy,
    redirects: list[RedirectHop],
) -> str:
    """Validate one redirect and record it, or refuse before contacting it."""

    location = response.location()
    if location is None:
        raise AcquisitionError(AcquisitionFailure.MISSING_REDIRECT_TARGET, "no Location header")

    destination = resolve_location(current, location)
    # Validated here, before the next iteration opens a connection, and recorded
    # only once it passed: a chain never holds a destination that was refused.
    _require_permitted(destination, policy)
    redirects.append(RedirectHop(from_url=current, to_url=destination, status=response.status))
    return destination


def _drain(
    *,
    response: HttpResponse,
    sink: ArtifactSink,
    policy: AcquisitionPolicy,
    final_url: str,
    redirects: tuple[RedirectHop, ...],
    expected_sha256: str | None,
) -> AcquiredArtifact:
    """Read the body in bounded chunks, hashing and writing each one."""

    metadata = ResponseMetadata(
        status=response.status,
        headers=sanitize_headers(response.headers_as_dict()),
    )
    declared = metadata.declared_length
    if declared is not None and declared > policy.max_artifact_bytes:
        # Refused on the declaration, before a single byte is read: the server
        # has already said it will not fit.
        raise AcquisitionError(AcquisitionFailure.ARTIFACT_TOO_LARGE, str(declared))

    digest = hashlib.sha256()
    received = 0
    while True:
        try:
            chunk = response.read_chunk(policy.chunk_bytes)
        except AcquisitionError:
            raise
        except Exception as error:
            raise AcquisitionError(
                AcquisitionFailure.REQUEST_FAILED, type(error).__name__
            ) from error
        if not chunk:
            break
        received += len(chunk)
        if received > policy.max_artifact_bytes:
            # Enforced against what has arrived, not against what was promised:
            # a server that under-declares its length is exactly the case a
            # ceiling exists for.
            raise AcquisitionError(
                AcquisitionFailure.ARTIFACT_TOO_LARGE, str(policy.max_artifact_bytes)
            )
        digest.update(chunk)
        try:
            sink.write(chunk)
        except Exception as error:
            raise AcquisitionError(AcquisitionFailure.SINK_FAILED, type(error).__name__) from error

    if declared is not None and received != declared:
        failure = (
            AcquisitionFailure.TRUNCATED_ARTIFACT
            if received < declared
            else AcquisitionFailure.DECLARED_LENGTH_MISMATCH
        )
        raise AcquisitionError(failure, f"{received} of {declared}")

    checksum = digest.hexdigest()
    if expected_sha256 is not None and checksum != expected_sha256:
        # Neither checksum is in the detail: one is the caller's own input and
        # the other is about to be discarded with the object it describes.
        raise AcquisitionError(AcquisitionFailure.CHECKSUM_MISMATCH, "content identity differs")

    try:
        sink.commit()
    except Exception as error:
        raise AcquisitionError(AcquisitionFailure.SINK_FAILED, type(error).__name__) from error

    return AcquiredArtifact(
        sha256=checksum,
        byte_count=received,
        final_url=final_url,
        response=metadata,
        redirects=redirects,
    )
