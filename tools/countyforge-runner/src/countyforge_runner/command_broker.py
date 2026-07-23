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


# Fixed system runtime roots mounted read-only at identical paths inside the sandbox. These
# are the only host roots (besides the trusted contract root and any explicitly declared
# toolchain root) permitted to provide a command executable.
_RUNTIME_ROOTS = ("/usr", "/usr/local", "/bin", "/lib", "/lib64", "/opt", "/etc")
# Deterministic system fallback search directories appended after the inherited PATH so a
# trusted system interpreter is preferred over a masked host-home installation.
_SYSTEM_BIN_DIRS = (
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/sbin",
    "/usr/bin",
    "/sbin",
    "/bin",
)
_CONTRACT_SANDBOX_ROOT = "/countyforge/contract"


def _sandbox_join(sandbox_root: str, relative: Path) -> str:
    """Map a host-relative path onto its sandbox-visible root without escaping it."""

    base = sandbox_root.rstrip("/")
    posix = relative.as_posix()
    return base if posix in ("", ".") else f"{base}/{posix}"


def _resolve_executable(
    executable: str,
    *,
    approved_roots: tuple[tuple[Path, str], ...],
    workspace_root: Path,
) -> str:
    """Resolve a registry executable to its sandbox-visible path in trusted host code.

    The executable is resolved (including its full symlink chain) before Bubblewrap runs,
    rather than relying on the sandbox ``PATH``. Only paths whose fully resolved target lives
    beneath an explicitly mounted approved root (fixed system runtime roots, the trusted
    contract root, or an explicitly declared toolchain root) are permitted; anything else --
    including a masked host-home installation, the candidate workspace, or a symlink whose
    target escapes those roots -- fails closed with a bounded error.
    """

    def classify(resolved: Path) -> str | None:
        for host_root, sandbox_root in approved_roots:
            if resolved == host_root or resolved.is_relative_to(host_root):
                return _sandbox_join(sandbox_root, resolved.relative_to(host_root))
        return None

    candidates: list[Path] = []
    if executable.startswith("/"):
        candidates.append(Path(executable))
    elif "/" in executable:
        # A relative path is interpreted against the candidate workspace, which v1 rejects
        # as an executable source. Resolve it so the workspace guard below can fail closed.
        candidates.append(workspace_root / executable)
    else:
        search_dirs: list[str] = []
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if entry and entry not in search_dirs:
                search_dirs.append(entry)
        for fixed in _SYSTEM_BIN_DIRS:
            if fixed not in search_dirs:
                search_dirs.append(fixed)
        candidates.extend(Path(directory) / executable for directory in search_dirs)

    found_outside = False
    for candidate in candidates:
        try:
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        try:
            if resolved.is_relative_to(workspace_root.resolve()):
                # Candidate-workspace executables are never permitted in v1.
                found_outside = True
                continue
        except OSError:
            pass
        mapped = classify(resolved)
        if mapped is not None:
            return mapped
        found_outside = True
    if found_outside:
        raise KernelError(
            "command_executable_outside_sandbox",
            "The registry executable resolves outside the mounted trusted roots.",
        )
    raise KernelError(
        "command_executable_unavailable",
        "The registry executable is unavailable under any mounted trusted root.",
    )


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
        toolchain_roots: tuple[Path, ...] = (),
    ) -> JsonObject:
        entry = self._commands.get(command_id)
        if entry is None:
            raise KernelError("command_not_declared", "Implementation command is not declared.")
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise KernelError("workspace_unavailable", "Implementation workspace is unavailable.")
        executable = str(entry["executable"])
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
        runtime_roots = _RUNTIME_ROOTS
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
        # Approved executable roots, mapped to their sandbox-visible equivalent. Fixed system
        # runtime roots are mounted identically; the contract root is remapped; explicitly
        # declared toolchain roots (if any) are mounted read-only at their identical path.
        approved_roots: list[tuple[Path, str]] = [
            (Path(runtime_root), runtime_root)
            for runtime_root in runtime_roots
            if Path(runtime_root).exists()
        ]
        contract: Path | None = None
        if contract_root is not None:
            contract = contract_root.resolve(strict=True)
            if not contract.is_dir():
                raise KernelError(
                    "contract_root_unavailable", "Trusted contract root is unavailable."
                )
            sandboxed_argv.extend(
                ("--dir", "/countyforge", "--ro-bind", str(contract), _CONTRACT_SANDBOX_ROOT)
            )
            approved_roots.append((contract, _CONTRACT_SANDBOX_ROOT))
        for declared in toolchain_roots:
            toolchain = declared.resolve(strict=True)
            if not toolchain.is_dir():
                raise KernelError(
                    "command_toolchain_root_invalid",
                    "A declared trusted toolchain root is unavailable.",
                )
            sandboxed_argv.extend(("--ro-bind", str(toolchain), str(toolchain)))
            approved_roots.append((toolchain, str(toolchain)))
        resolved_executable = _resolve_executable(
            executable,
            approved_roots=tuple(approved_roots),
            workspace_root=root,
        )
        argv = [resolved_executable, *(str(value) for value in entry["arguments"])]
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
                    contract_host_path, _CONTRACT_SANDBOX_ROOT
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
