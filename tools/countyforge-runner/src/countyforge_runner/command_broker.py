"""Small registry-gated command broker for implementation validation.

The model container remains network-isolated. This broker is used by trusted tooling when a
task requests a repository-declared deterministic command; it never accepts a shell string or
additional executable arguments.
"""

from __future__ import annotations

import hashlib
import os
import selectors
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from countyforge_runner.contracts import JsonObject, load_json_object, validate_document
from countyforge_runner.errors import KernelError


def _hash_output(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class CommandBroker:
    """Execute only an exact command entry from a trusted registry."""

    def __init__(self, registry_path: Path, schema_path: Path) -> None:
        self.registry = load_json_object(registry_path, kind="implementation command registry")
        schema = load_json_object(schema_path, kind="implementation command schema")
        validate_document(self.registry, schema, kind="implementation command registry")
        self._commands = {str(item["id"]): item for item in self.registry["commands"]}

    def run(
        self,
        command_id: str,
        *,
        workspace: Path,
        run_id: str = "local",
        workspace_revision: str | None = None,
    ) -> JsonObject:
        entry = self._commands.get(command_id)
        if entry is None:
            raise KernelError("command_not_declared", "Implementation command is not declared.")
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise KernelError("workspace_unavailable", "Implementation workspace is unavailable.")
        executable = str(entry["executable"])
        argv = [executable, *(str(value) for value in entry["arguments"])]
        network = str(entry["network"])
        if network != "disabled":
            raise KernelError(
                "network_policy_unsupported",
                "Only default-deny command networking is executable in this profile.",
            )
        sandbox = shutil.which("bwrap")
        if sandbox is None:
            raise KernelError(
                "network_sandbox_unavailable",
                "The required no-network command sandbox is unavailable.",
            )
        sandboxed_argv = [
            sandbox,
            "--die-with-parent",
            "--unshare-net",
            "--new-session",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(root),
            str(root),
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--chdir",
            str(root),
            "--",
            *argv,
        ]
        environment = {
            name: os.environ[name]
            for name in entry["environment"]
            if name in os.environ and name not in {"OPENAI_API_KEY", "SAKANA_API_KEY"}
        }
        environment["PWD"] = str(root)
        started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        limit = int(entry["max_output_bytes"])
        try:
            process = subprocess.Popen(  # noqa: S603 - executable and argv are registry-owned
                sandboxed_argv,
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )
        except OSError as error:
            raise KernelError(
                "command_failed", "Implementation command could not start."
            ) from error
        selector = selectors.DefaultSelector()
        assert process.stdout is not None
        assert process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        output_bytes = 0
        deadline = time.monotonic() + int(entry["timeout_seconds"])
        output_exceeded = False
        timed_out = False
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    break
                ready = selector.select(min(0.25, remaining))
                if not ready and process.poll() is not None:
                    continue
                for key, _ in ready:
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        try:
                            os.close(key.fd)
                        except OSError:
                            pass
                        continue
                    room = limit - output_bytes
                    if len(chunk) > room:
                        first_excess = not output_exceeded
                        output_exceeded = True
                        if room > 0:
                            buffers[key.data].extend(chunk[:room])
                            output_bytes += room
                        if first_excess:
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                    elif not output_exceeded:
                        buffers[key.data].extend(chunk)
                        output_bytes += len(chunk)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                process.wait()
        finally:
            selector.close()
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                process.wait()
        if timed_out:
            raise KernelError("command_timed_out", "Implementation command exceeded its limit.")
        if output_exceeded:
            raise KernelError(
                "command_output_limit_exceeded",
                "Implementation command exceeded its output limit.",
            )
        stdout = bytes(buffers["stdout"])
        stderr = bytes(buffers["stderr"])
        finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        revision = workspace_revision or _workspace_revision(root)
        raw_exit_code = int(process.returncode or 0)
        exit_code = 128 + abs(raw_exit_code) if raw_exit_code < 0 else raw_exit_code
        return {
            "contract_version": 1,
            "run_id": run_id,
            "command_id": command_id,
            "phase": entry["phase"],
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "stdout_sha256": _hash_output(stdout),
            "stderr_sha256": _hash_output(stderr),
            "output_bytes": len(stdout) + len(stderr),
            "truncated": False,
            "network_policy": network,
            "workspace_revision": revision,
            "workspace_mutating": entry["workspace_mutating"],
        }


def validate_command_event(event: JsonObject, *, command_ids: set[str]) -> None:
    """Validate optional model command evidence without trusting free-form output."""

    command_id: Any = event.get("command_id")
    if command_id is not None and (
        not isinstance(command_id, str) or command_id not in command_ids
    ):
        raise KernelError(
            "command_not_declared", "Implementation command evidence is not declared."
        )


__all__ = ["CommandBroker", "validate_command_event"]


def _workspace_revision(root: Path) -> str:
    """Return a bounded content-independent revision for command evidence."""

    try:
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        status = str(root)
    return hashlib.sha256(status.encode("utf-8", errors="replace")).hexdigest()
