"""A synthetic local HTTP server and a file-backed sink.

Every byte served here is generated in this process. No county endpoint is
contacted, and no county bytes exist in the repository.

The server binds 127.0.0.1 on an ephemeral port and is scripted per path, so a
test states the exact response shape it needs — a redirect chain, a lying
`Content-Length`, a body that stops early — rather than depending on how some
real server happens to behave.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType


@dataclass(slots=True)
class Route:
    """One scripted response.

    `declared_length` overrides the real body length, which is how a truncated
    transfer and an over-declaring server are simulated without a real network
    failure.
    """

    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    location: str | None = None
    declared_length: int | None = None
    send_bytes: int | None = None
    omit_length: bool = False


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
        routes: dict[str, Route] = self.server.routes  # type: ignore[attr-defined]
        self.server.requested.append(self.path)  # type: ignore[attr-defined]
        # Routed on the path alone, as a real server does: the query string
        # selects nothing here, and matching on it would make a signed URL
        # unreachable in exactly the test that checks signatures are dropped.
        route = routes.get(self.path.split("?", 1)[0])
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.send_response(route.status)
        if route.location is not None:
            self.send_header("Location", route.location)
        for name, value in route.headers.items():
            self.send_header(name, value)
        declared = route.declared_length
        if declared is None and route.location is None and not route.omit_length:
            declared = len(route.body)
        # Omitting Content-Length leaves the body framed by connection close,
        # which is the only shape in which more bytes can arrive than any
        # declaration promised.
        if declared is not None and not route.omit_length:
            self.send_header("Content-Length", str(declared))
        self.end_headers()

        payload = route.body if route.send_bytes is None else route.body[: route.send_bytes]
        if payload:
            self.wfile.write(payload)

    def log_message(self, *_: object) -> None:
        """Silent: a test suite is not a place for request logs."""


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, routes: dict[str, Route]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes = routes
        self.requested: list[str] = []


@contextmanager
def serving(routes: dict[str, Route]) -> Iterator[_Server]:
    """Run the scripted server for the duration of one test."""

    server = _Server(routes)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def base_url(server: _Server) -> str:
    host, port = server.server_address[0], server.server_address[1]
    return f"http://{host}:{port}"


class FileSink:
    """A sink writing to a temporary path, promoted only on commit.

    The local stand-in for the object store task 3.2 will supply. It writes to a
    `.partial` neighbour and renames on commit, so "durable" and "written" are
    different states here exactly as they are in S3.
    """

    def __init__(
        self, destination: Path, *, fail_on_write: bool = False, fail_on_commit: bool = False
    ) -> None:
        self.destination = destination
        self.partial = destination.with_suffix(destination.suffix + ".partial")
        self.committed = False
        self.aborted = False
        self._handle = None  # type: ignore[var-annotated]
        self._fail_on_write = fail_on_write
        self._fail_on_commit = fail_on_commit

    def __enter__(self) -> FileSink:
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.partial.open("wb")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def write(self, chunk: bytes) -> None:
        if self._fail_on_write:
            raise OSError("SECRET-SINK-WRITE")
        assert self._handle is not None, "written outside the context manager"
        self._handle.write(chunk)

    def commit(self) -> str:
        if self._fail_on_commit:
            raise OSError("SECRET-SINK-COMMIT")
        assert self._handle is not None
        self._handle.close()
        self._handle = None
        self.partial.rename(self.destination)
        self.committed = True
        return self.destination.as_uri()

    def abort(self) -> None:
        self.aborted = True
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self.partial.unlink(missing_ok=True)
        self.destination.unlink(missing_ok=True)
