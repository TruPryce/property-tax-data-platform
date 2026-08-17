"""One HTTP exchange, with nothing automatic about it.

`http.client` rather than `urllib.request`, because urllib follows redirects for
you.  A followed redirect is a request already sent to a destination no rule has
examined, and the whole point of this module is that no destination is contacted
before the policy admits it.

The standard library only.  No dependency is introduced here.
"""

from __future__ import annotations

import http.client
import ssl
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit, urlunsplit

from property_tax_application.acquisition import AcquisitionError, AcquisitionFailure

__all__ = ["HttpResponse", "HttpTransport", "StdlibHttpTransport", "resolve_location"]


@runtime_checkable
class HttpResponse(Protocol):
    """Just enough of a response to stream it and describe it."""

    @property
    def status(self) -> int: ...

    def headers_as_dict(self) -> Mapping[str, str]: ...

    def read_chunk(self, size: int) -> bytes:
        """At most `size` bytes; empty means the body ended."""
        ...

    def location(self) -> str | None:
        """The `Location` header, or `None` when the response carries none.

        On the protocol rather than fished out of the header mapping, because a
        redirect target is the one header this boundary acts on rather than
        merely records, and the sanitized mapping deliberately omits it.
        """
        ...


@runtime_checkable
class HttpTransport(Protocol):
    """Issues exactly one request and never follows anything."""

    def open(self, url: str, *, timeout: float) -> AbstractContextManager[HttpResponse]: ...


@dataclass(slots=True)
class _StdlibResponse:
    raw: http.client.HTTPResponse

    @property
    def status(self) -> int:
        return int(self.raw.status)

    def headers_as_dict(self) -> Mapping[str, str]:
        return {name: value for name, value in self.raw.getheaders()}

    def read_chunk(self, size: int) -> bytes:
        # `read(size)` on a chunked response returns at most `size` bytes and
        # never the whole body, which is what keeps memory flat regardless of
        # how large the artifact is.
        return self.raw.read(size)

    def location(self) -> str | None:
        return self.raw.getheader("Location")


class StdlibHttpTransport:
    """`http.client` with redirects disabled by construction.

    There is no redirect handler to disable: this issues one request and hands
    back the response, 3xx included, so the caller decides whether a hop is
    permitted before any further connection exists.
    """

    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self._context = context

    @contextmanager
    def open(self, url: str, *, timeout: float) -> Iterator[_StdlibResponse]:
        parts = urlsplit(url)
        connection: http.client.HTTPConnection
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                parts.netloc,
                timeout=timeout,
                context=self._context or ssl.create_default_context(),
            )
        else:
            connection = http.client.HTTPConnection(parts.netloc, timeout=timeout)
        try:
            target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            try:
                connection.request("GET", target, headers={"Accept-Encoding": "identity"})
                raw = connection.getresponse()
            except (OSError, http.client.HTTPException) as error:
                # The class only; a transport message may carry a host, a path,
                # or a system detail that does not belong in a manifest.
                raise AcquisitionError(
                    AcquisitionFailure.REQUEST_FAILED, type(error).__name__
                ) from error
            yield _StdlibResponse(raw)
        finally:
            connection.close()


def resolve_location(current_url: str, location: str) -> str:
    """Resolve a `Location` against the URL that produced it.

    Relative locations are legal and common, and a relative target resolved
    against the wrong base would be validated as one host and fetched as
    another.  Resolution happens here so validation and the request that follows
    it always see the identical absolute URL.
    """

    if not location or not location.strip():
        raise AcquisitionError(AcquisitionFailure.MISSING_REDIRECT_TARGET, "empty Location")
    resolved = urljoin(current_url, location.strip())
    parts = urlsplit(resolved)
    if not parts.scheme or not parts.hostname:
        raise AcquisitionError(
            AcquisitionFailure.MISSING_REDIRECT_TARGET, "Location resolved without scheme or host"
        )
    return resolved
