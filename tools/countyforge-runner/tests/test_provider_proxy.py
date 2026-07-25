"""Deterministic fixtures for the provider-only CONNECT proxy."""

from __future__ import annotations

from countyforge_runner import provider_proxy


class _FakeSocket:
    def __init__(self, request: bytes) -> None:
        self.request = request
        self.sent: list[bytes] = []
        self.closed = False

    def recv(self, _size: int) -> bytes:
        return self.request

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


def test_rejected_connect_closes_client() -> None:
    client = _FakeSocket(b"CONNECT example.invalid:443 HTTP/1.1\r\n\r\n")
    provider_proxy._handle(client, "api.openai.com")  # noqa: SLF001 - boundary fixture
    assert client.closed is True
    assert client.sent == [b"HTTP/1.1 403 Forbidden\r\n\r\n"]


def test_tunnel_waits_for_socket_activity_without_idle_timeout(monkeypatch) -> None:
    left, right = _FakeSocket(b""), _FakeSocket(b"")
    calls: list[tuple[object, ...]] = []

    def select_without_timeout(*args: object):
        calls.append(args)
        raise RuntimeError("stop fixture")

    monkeypatch.setattr(provider_proxy.select, "select", select_without_timeout)
    try:
        provider_proxy._tunnel(left, right)  # noqa: SLF001 - boundary fixture
    except RuntimeError:
        pass
    assert calls
    assert len(calls[0]) == 3
    assert calls[0][2] == []
