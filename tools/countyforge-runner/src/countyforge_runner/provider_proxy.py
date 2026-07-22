"""Minimal allowlist CONNECT proxy for provider-only model egress.

The proxy carries no credentials. It permits only the selected provider host and is intended
to run on the trusted workflow host while the model container uses it for HTTPS CONNECT.
"""

from __future__ import annotations

import argparse
import select
import socket
import threading


def _tunnel(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 30)
            if not readable:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (right if source is left else left).sendall(data)
    finally:
        left.close()
        right.close()


def serve(host: str, port: int, allowed_host: str) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen(16)
    print(listener.getsockname()[1], flush=True)
    while True:
        client, _ = listener.accept()
        thread = threading.Thread(target=_handle, args=(client, allowed_host), daemon=True)
        thread.start()


def _handle(client: socket.socket, allowed_host: str) -> None:
    try:
        request = client.recv(8192)
        first = request.split(b"\r\n", 1)[0].decode("ascii", errors="ignore")
        method, target, _ = first.split(" ", 2)
        host, separator, raw_port = target.partition(":")
        if method != "CONNECT" or not separator or host != allowed_host or raw_port != "443":
            client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        upstream = socket.create_connection((allowed_host, 443), timeout=15)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        _tunnel(client, upstream)
    except (OSError, ValueError):
        try:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except OSError:
            pass
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--allowed-host", required=True)
    args = parser.parse_args()
    serve(args.host, args.port, args.allowed_host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
