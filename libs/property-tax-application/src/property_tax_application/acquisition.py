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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType, TracebackType
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

__all__ = [
    "ACQUISITION_CONTRACT_VERSION",
    "AcquiredArtifact",
    "AcquisitionError",
    "AcquisitionFailure",
    "AcquisitionPolicy",
    "ArtifactSink",
    "RedirectHop",
    "ResponseMetadata",
    "MAX_LOCATOR_CHARS",
    "SANITIZED_HEADERS",
    "TRANSIENT_STATUSES",
    "sanitize_headers",
    "sanitize_url",
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

#: A locator is bounded for the same reason, against a different party: the sink
#: rather than the server.  S3 keys stop at 1,024 bytes and a scheme and bucket
#: fit comfortably inside the remainder.
MAX_LOCATOR_CHARS: int = 2_048

#: Statuses a later attempt may resolve.  Everything else is a rule or a
#: representation problem, which retrying only repeats.
TRANSIENT_STATUSES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})

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
    TRANSIENT_STATUS = "transient_status"
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
            AcquisitionFailure.TRANSIENT_STATUS,
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
        #: Set when cleanup after this failure itself failed, which means a
        #: partial artifact may survive.  A separate fact from `failure`: one
        #: says why the acquisition stopped, the other whether anything was
        #: left behind, and a caller that cannot tell them apart will assume
        #: the sink is clean.
        self.cleanup_failed = False
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
        # Copied and frozen, not merely annotated as frozen.  A caller passing a
        # mutable set keeps a handle to it, and adding a host afterwards would
        # widen a security rule on a value the type calls immutable.
        for name in ("allowed_hosts", "allowed_schemes"):
            supplied = getattr(self, name)
            if isinstance(supplied, str) or not isinstance(supplied, Iterable):
                raise ValueError(f"{name} must be a collection of strings")
            object.__setattr__(self, name, frozenset(supplied))

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


def sanitize_url(url: str) -> str:
    """Reduce a URL to the part that is safe to keep as provenance.

    A request URL and a provenance URL are different things, and conflating
    them is how a credential reaches a manifest.  The userinfo component — the
    name and password an authority may carry before its `@` — is a credential
    outright, and a query string carries signed tokens, session identifiers, and
    expiring keys for most file-distribution hosts.
    Neither is needed to say where an artifact came from; the scheme, host,
    port, and path are.

    The fragment goes too: it is never sent to a server, so preserving it would
    record something the exchange never involved.
    """

    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        raise ValueError("a provenance URL needs a scheme and a host")
    authority = parts.hostname.casefold()
    if parts.port is not None:
        authority = f"{authority}:{parts.port}"
    return urlunsplit((parts.scheme.casefold(), authority, parts.path, "", ""))


def _require_sanitized_header_value(name: str, value: str) -> None:
    """Refuse a header value that `sanitize_headers` would have changed.

    The allowlist bounds which headers survive; it did not bound what they may
    contain, so a value built by hand rather than passed through the sanitizer
    could carry five kilobytes or a `\r\n` that splits a log line into a
    forged second record.  Checked here because this type is what task 3.2
    persists, and a rule only the adapter applies is a rule a second caller
    does not.
    """

    if len(value) > MAX_HEADER_VALUE_CHARS:
        raise ValueError(
            f"the {name} header exceeds {MAX_HEADER_VALUE_CHARS} characters; "
            "a bounded manifest cannot hold an unbounded value"
        )
    if _CONTROL_CHARACTERS.search(value) is not None:
        raise ValueError(f"the {name} header carries a control character")
    if value != value.strip():
        raise ValueError(f"the {name} header carries surrounding whitespace")


def _require_sanitized_locator(locator: str) -> None:
    """A locator says where bytes landed; it may not say who may fetch them.

    Not passed through `sanitize_url`, which lowercases an authority: an object
    key is case-sensitive and rewriting one would name a different object. The
    dangerous components are refused instead of removed, so a caller learns the
    locator was wrong rather than silently receiving a different one.
    """

    if not isinstance(locator, str) or not locator.strip():
        raise ValueError("locator must be the non-blank URI the sink's commit returned")
    # Bounded and clean for the same reasons a header value is, against a
    # different party.  The sink is trusted code, but a manifest field is a
    # manifest field: an unbounded one makes the record unbounded, and a control
    # character in it forges a line break wherever the record is later rendered.
    if len(locator) > MAX_LOCATOR_CHARS:
        raise ValueError(
            f"locator exceeds {MAX_LOCATOR_CHARS} characters; a bounded manifest "
            "cannot hold an unbounded locator"
        )
    if _CONTROL_CHARACTERS.search(locator) is not None:
        raise ValueError("locator carries a control character")
    if locator != locator.strip():
        raise ValueError("locator carries surrounding whitespace")
    parts = urlsplit(locator)
    if not parts.scheme:
        raise ValueError("locator must name a scheme, so a consumer knows how to fetch it")
    if parts.username or parts.password:
        raise ValueError("locator must not carry userinfo, which is a credential")
    if parts.query:
        raise ValueError(
            "locator must not carry a query string, which is where signed and expiring "
            "access tokens live on object stores"
        )
    if parts.fragment:
        raise ValueError("locator must not carry a fragment, which is never sent to a server")


def _require_sanitized_url(url: str, field_name: str) -> None:
    """Refuse a URL that still carries what `sanitize_url` removes.

    Checked on the carrier rather than trusted from the caller: the type is
    what task 3.2 persists, so the rule belongs where it cannot be bypassed by
    constructing the value some other way.
    """

    if not isinstance(url, str) or not url:
        raise ValueError(f"{field_name} must be a non-empty str")
    if url != sanitize_url(url):
        raise ValueError(
            f"{field_name} must be sanitized: userinfo, query, and fragment are removed, "
            "because a request URL may carry a credential and a provenance URL may not"
        )


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
        if not isinstance(self.headers, Mapping):
            raise ValueError("headers must be a mapping")
        unknown = set(self.headers) - SANITIZED_HEADERS
        if unknown:
            raise ValueError(f"headers outside the allowlist: {sorted(unknown)}")
        for name, value in self.headers.items():
            if not isinstance(value, str):
                raise ValueError(f"the {name} header must be a str")
            _require_sanitized_header_value(name, value)
        # Snapshotted behind a read-only view.  Without the copy a caller could
        # inject `set-cookie` after the allowlist check, or change
        # `content-length` and break an agreement an artifact already verified.
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

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
        _require_sanitized_url(self.from_url, "from_url")
        _require_sanitized_url(self.to_url, "to_url")
        if not 300 <= self.status <= 399:
            raise ValueError(f"a redirect hop must carry a 3xx status, got {self.status}")


@dataclass(frozen=True, slots=True)
class AcquiredArtifact:
    """What one complete, verified acquisition established.

    There is no partial form of this value: it is constructed after the byte
    count and checksum are final and after the sink committed, so holding one is
    the evidence that the artifact completed and is durable.

    `final_url` is provenance and is sanitized; `locator` is where the bytes
    landed, as the sink reported it.  They are different facts and neither
    substitutes for the other.
    """

    sha256: str
    byte_count: int
    final_url: str
    locator: str
    response: ResponseMetadata
    redirects: tuple[RedirectHop, ...] = ()
    acquisition_contract_version: int = ACQUISITION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        # Required, not optional: the manifest task consumes this value, and an
        # artifact that completed but cannot say where it landed would make the
        # commit unfindable through the only port that performed it.
        _require_sanitized_locator(self.locator)
        _require_sanitized_url(self.final_url, "final_url")
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
    ) -> None:
        """Release the sink's own resources, and raise nothing.

        Two obligations, and both are the caller's protection rather than the
        implementation's convenience.

        It SHALL NOT raise after a `commit` or an `abort` has run.  Exit is the
        last thing the acquisition does, so an exception here arrives after the
        artifact is already durable — the caller would receive a failure for an
        acquisition that succeeded, and could not tell that from one that did
        not.  A sink that raises there is a defect in trusted code, not a
        condition to report, exactly as the release stage treats the same case.

        It SHALL NOT suppress: annotated `-> None` rather than `-> bool`, so a
        failure that rejected the acquisition cannot be swallowed on the way out
        and reported as success.
        """
        ...

    def write(self, chunk: bytes) -> None:
        """Append one bounded chunk.  Never handed the complete artifact."""
        ...

    def commit(self) -> str:
        """Make the artifact durable and return its immutable locator."""
        ...

    def abort(self) -> None:
        """Discard everything written.  Must be safe to call after a failure."""
        ...
