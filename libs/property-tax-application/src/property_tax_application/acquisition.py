"""The acquisition boundary: what a download may learn, and where its bytes go.

Two halves, deliberately separate.  `AcquisitionPolicy` states what a request is
permitted to contact and how much it may read, and it is checked *before* every
connection rather than after, because a host that has already been contacted has
already received the request.  `ArtifactSink` is where bytes go without ever
becoming a value in memory — implemented against S3 by a later task, and against
a local file by the tests here.

Nothing in this module performs I/O.  It is the port an adapter implements and
the contract a caller reads, so the security rules live where both can see them
rather than inside one transport's control flow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType
from typing import Protocol, runtime_checkable

__all__ = [
    "ACQUISITION_CONTRACT_VERSION",
    "AcquiredArtifact",
    "AcquisitionError",
    "AcquisitionFailure",
    "AcquisitionPolicy",
    "ArtifactSink",
    "RedirectHop",
    "ResponseMetadata",
    "SANITIZED_HEADERS",
    "sanitize_headers",
]

#: The contract this boundary implements, pinned so a consumer can tell which.
ACQUISITION_CONTRACT_VERSION: int = 1

#: The only response headers preserved.  An allowlist rather than a denylist:
#: a new header a server invents is not preserved by default, which is the
#: opposite of what a `Set-Cookie`-style exclusion list would do.  Every one of
#: these describes the representation; none identifies a person or a session.
SANITIZED_HEADERS: frozenset[str] = frozenset(
    {"content-length", "content-type", "etag", "last-modified", "accept-ranges"}
)

#: A preserved header value is bounded, so a hostile server cannot make the
#: manifest large by answering with a megabyte of `ETag`.
MAX_HEADER_VALUE_CHARS: int = 512

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class AcquisitionFailure(StrEnum):
    """Why an acquisition stopped, named rather than described.

    A code is what an orchestrator can branch on and a message is not, and the
    retry decision is a property of the code rather than of the text.
    """

    UNAPPROVED_SCHEME = "unapproved_scheme"
    UNAPPROVED_HOST = "unapproved_host"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    MISSING_REDIRECT_TARGET = "missing_redirect_target"
    UNSUPPORTED_STATUS = "unsupported_status"
    REQUEST_FAILED = "request_failed"
    ARTIFACT_TOO_LARGE = "artifact_too_large"
    TRUNCATED_ARTIFACT = "truncated_artifact"
    DECLARED_LENGTH_MISMATCH = "declared_length_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    SINK_FAILED = "sink_failed"

    @property
    def retryable(self) -> bool:
        """A transport that may succeed later, as against a rule that will not.

        A validation failure repeated is the same failure; retrying an
        unapproved host only contacts it again.
        """

        return self in {
            AcquisitionFailure.REQUEST_FAILED,
            AcquisitionFailure.TRUNCATED_ARTIFACT,
            AcquisitionFailure.SINK_FAILED,
        }


class AcquisitionError(Exception):
    """A named acquisition failure.

    Carries a code and a bounded, non-identifying detail.  It never carries the
    response body, a credential, or a header outside the allowlist.
    """

    def __init__(self, failure: AcquisitionFailure, detail: str = "") -> None:
        self.failure = failure
        self.detail = detail
        super().__init__(f"{failure.value}: {detail}" if detail else failure.value)


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    """What a request may contact, and how much it may read.

    Defaults are the production posture: HTTPS only, an explicit host
    allowlist, a hop limit, and a byte ceiling.  A test may widen the scheme and
    host sets to reach a local fixture; nothing widens them at runtime, because
    the policy is frozen and supplied by the caller.
    """

    allowed_hosts: frozenset[str]
    allowed_schemes: frozenset[str] = frozenset({"https"})
    max_redirects: int = 5
    max_artifact_bytes: int = 8 * 1024 * 1024 * 1024
    chunk_bytes: int = 1024 * 1024
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must name at least one host")
        if not self.allowed_schemes:
            raise ValueError("allowed_schemes must name at least one scheme")
        if any(host != host.casefold() for host in self.allowed_hosts):
            raise ValueError("allowed_hosts must be lowercase, since a host compares casefolded")
        if any(scheme != scheme.casefold() for scheme in self.allowed_schemes):
            raise ValueError("allowed_schemes must be lowercase")
        for name, value in (
            ("max_redirects", self.max_redirects),
            ("max_artifact_bytes", self.max_artifact_bytes),
            ("chunk_bytes", self.chunk_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an int")
        if self.max_redirects < 0:
            raise ValueError("max_redirects must not be negative")
        if self.chunk_bytes < 1:
            raise ValueError("chunk_bytes must be positive, so a read makes progress")
        if self.max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        if self.chunk_bytes > self.max_artifact_bytes:
            raise ValueError("chunk_bytes must not exceed max_artifact_bytes")
        if not isinstance(self.timeout_seconds, int | float) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def permits(self, scheme: str, host: str) -> None:
        """Raise unless this scheme and host may be contacted.

        Called before every connection, including every redirect, so no
        destination is validated only after the request that reached it.
        """

        if scheme.casefold() not in self.allowed_schemes:
            raise AcquisitionError(AcquisitionFailure.UNAPPROVED_SCHEME, scheme.casefold()[:64])
        if host.casefold() not in self.allowed_hosts:
            raise AcquisitionError(AcquisitionFailure.UNAPPROVED_HOST, host.casefold()[:255])


def sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Keep the allowlisted headers, bounded, lowercased, and control-free.

    Case-insensitive because header names are, and last-wins because a repeated
    header is a server's own inconsistency rather than something to preserve
    twice.
    """

    kept: dict[str, str] = {}
    for name, value in headers.items():
        folded = name.casefold()
        if folded not in SANITIZED_HEADERS:
            continue
        cleaned = _CONTROL_CHARACTERS.sub("", str(value)).strip()
        kept[folded] = cleaned[:MAX_HEADER_VALUE_CHARS]
    return kept


@dataclass(frozen=True, slots=True)
class ResponseMetadata:
    """Bounded, sanitized facts about one response."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise ValueError("status must be an int")
        if not 100 <= self.status <= 599:
            raise ValueError(f"status must be a valid HTTP status, got {self.status}")
        unknown = set(self.headers) - SANITIZED_HEADERS
        if unknown:
            raise ValueError(f"headers outside the allowlist: {sorted(unknown)}")

    @property
    def declared_length(self) -> int | None:
        """`Content-Length` when the server stated a usable one, else `None`."""

        raw = self.headers.get("content-length")
        if raw is None or not raw.isdigit():
            return None
        return int(raw)

    @property
    def media_type(self) -> str | None:
        """The media type without its parameters, which carry charset and boundary."""

        raw = self.headers.get("content-type")
        return raw.split(";")[0].strip().casefold() or None if raw else None


@dataclass(frozen=True, slots=True)
class RedirectHop:
    """One validated hop, kept as provenance.

    The location is recorded only after the policy admitted it, so a chain can
    never contain a destination this process refused to contact.
    """

    from_url: str
    to_url: str
    status: int

    def __post_init__(self) -> None:
        if not self.from_url or not self.to_url:
            raise ValueError("a redirect hop needs both of its endpoints")
        if not 300 <= self.status <= 399:
            raise ValueError(f"a redirect hop must carry a 3xx status, got {self.status}")


@dataclass(frozen=True, slots=True)
class AcquiredArtifact:
    """What one complete, verified acquisition established.

    There is no partial form of this value: it is constructed after the byte
    count and checksum are final, so holding one is the evidence that the
    artifact completed.
    """

    sha256: str
    byte_count: int
    final_url: str
    response: ResponseMetadata
    redirects: tuple[RedirectHop, ...] = ()
    acquisition_contract_version: int = ACQUISITION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if isinstance(self.byte_count, bool) or not isinstance(self.byte_count, int):
            raise ValueError("byte_count must be an int")
        if self.byte_count < 0:
            raise ValueError("byte_count must not be negative")
        if not isinstance(self.response, ResponseMetadata):
            raise ValueError("response must be a ResponseMetadata")
        if not isinstance(self.redirects, tuple) or not all(
            isinstance(hop, RedirectHop) for hop in self.redirects
        ):
            raise ValueError("redirects must be a tuple of RedirectHop")
        if (
            isinstance(self.acquisition_contract_version, bool)
            or not isinstance(self.acquisition_contract_version, int)
            or self.acquisition_contract_version != ACQUISITION_CONTRACT_VERSION
        ):
            raise ValueError(
                f"acquisition_contract_version must be the int {ACQUISITION_CONTRACT_VERSION}"
            )
        declared = self.response.declared_length
        if declared is not None and declared != self.byte_count:
            raise ValueError("byte_count must equal the declared content length when one was given")

    @property
    def media_type(self) -> str | None:
        return self.response.media_type


@runtime_checkable
class ArtifactSink(Protocol):
    """Where acquired bytes go, one chunk at a time.

    The boundary the object-store task implements.  `commit` is the only step
    that makes an artifact durable, and `abort` must leave nothing behind, so an
    acquisition that fails partway cannot expose a partial object as a source
    artifact.

    Modelled on the release stage for the same reason: a caller that must
    distinguish "written" from "durable" needs two verbs, and one that must
    guarantee cleanup needs a third that cannot be forgotten.
    """

    def __enter__(self) -> ArtifactSink: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def write(self, chunk: bytes) -> None:
        """Append one bounded chunk.  Never handed the complete artifact."""
        ...

    def commit(self) -> str:
        """Make the artifact durable and return its immutable locator."""
        ...

    def abort(self) -> None:
        """Discard everything written.  Must be safe to call after a failure."""
        ...
