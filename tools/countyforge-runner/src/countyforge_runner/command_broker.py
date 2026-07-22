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

from countyforge_runner.contracts import (
    JsonObject,
    load_json_object,
    validate_document,
    workspace_sha256,
)
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
        contract_root: Path | None = None,
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
        runtime_roots = ("/usr", "/usr/local", "/bin", "/lib", "/lib64", "/opt", "/etc")
        sandboxed_argv = [
            sandbox,
            "--die-with-parent",
            "--unshare-net",
            "--new-session",
            "--clearenv",
        ]
        for runtime_root in runtime_roots:
            if Path(runtime_root).exists():
                sandboxed_argv.extend(("--ro-bind", runtime_root, runtime_root))
        sandboxed_argv.extend(
            [
                "--tmpfs",
                "/home",
                "--tmpfs",
                "/root",
                "--tmpfs",
                "/run",
                "--tmpfs",
                "/var",
                "--tmpfs",
                "/var/run",
                "--tmpfs",
                "/sys",
                "--tmpfs",
                "/boot",
                "--tmpfs",
                "/mnt",
                "--tmpfs",
                "/media",
                "--tmpfs",
                "/srv",
                "--tmpfs",
                "/tmp",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--dir",
                "/workspace",
                "--bind",
                str(root),
                "/workspace",
            ]
        )
        if contract_root is not None:
            contract = contract_root.resolve(strict=True)
            if not contract.is_dir():
                raise KernelError(
                    "contract_root_unavailable", "Trusted contract root is unavailable."
                )
            sandboxed_argv.extend(
                ("--dir", "/countyforge", "--ro-bind", str(contract), "/countyforge/contract")
            )
        environment = {
            name: os.environ[name]
            for name in entry["environment"]
            if name in os.environ and name not in {"OPENAI_API_KEY", "SAKANA_API_KEY"}
        }
        environment["PWD"] = "/workspace"
        environment["HOME"] = "/workspace/.home"
        environment["TMPDIR"] = "/tmp"
        if contract_root is not None:
            contract_host_path = str(contract)
            if "PATH" in environment:
                environment["PATH"] = environment["PATH"].replace(
                    contract_host_path, "/countyforge/contract"
                )
            environment["PYTHONPATH"] = (
                "/countyforge/contract/tools/countyforge-github/src:"
                "/countyforge/contract/tools/countyforge-runner/src"
            )
        for name, value in environment.items():
            sandboxed_argv.extend(("--setenv", name, value))
        sandboxed_argv.extend(
            [
                "--chdir",
                "/workspace",
                "--",
                *argv,
            ]
        )
        started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        limit = int(entry["max_output_bytes"])
        workspace_before = workspace_sha256(root) if not bool(entry["workspace_mutating"]) else None
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
        if workspace_before is not None and workspace_sha256(root) != workspace_before:
            raise KernelError(
                "command_workspace_mutated",
                "A non-mutating implementation command changed the candidate workspace.",
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
