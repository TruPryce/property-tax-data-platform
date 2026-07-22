"""Small registry-gated command broker for implementation validation.

The model container remains network-isolated. This broker is used by trusted tooling when a
task requests a repository-declared deterministic command; it never accepts a shell string or
additional executable arguments.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from countyforge_runner.contracts import JsonObject, load_json_object, validate_document
from countyforge_runner.errors import KernelError


def _hash_output(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


class CommandBroker:
    """Execute only an exact command entry from a trusted registry."""

    def __init__(self, registry_path: Path, schema_path: Path) -> None:
        self.registry = load_json_object(registry_path, kind="implementation command registry")
        schema = load_json_object(schema_path, kind="implementation command schema")
        validate_document(self.registry, schema, kind="implementation command registry")
        self._commands = {str(item["id"]): item for item in self.registry["commands"]}

    def run(self, command_id: str, *, workspace: Path) -> JsonObject:
        entry = self._commands.get(command_id)
        if entry is None:
            raise KernelError("command_not_declared", "Implementation command is not declared.")
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise KernelError("workspace_unavailable", "Implementation workspace is unavailable.")
        executable = str(entry["executable"])
        argv = [executable, *(str(value) for value in entry["arguments"])]
        environment = {
            name: os.environ[name]
            for name in entry["environment"]
            if name in os.environ and name not in {"OPENAI_API_KEY", "SAKANA_API_KEY"}
        }
        environment["PWD"] = str(root)
        try:
            completed = subprocess.run(  # noqa: S603 - executable and argv are registry-owned
                argv,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=int(entry["timeout_seconds"]),
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise KernelError(
                "command_timed_out", "Implementation command exceeded its limit."
            ) from error
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined = (stdout + stderr).encode("utf-8", errors="replace")
        limit = int(entry["max_output_bytes"])
        return {
            "contract_version": 1,
            "command_id": command_id,
            "phase": entry["phase"],
            "exit_code": int(completed.returncode),
            "stdout_sha256": _hash_output(stdout),
            "stderr_sha256": _hash_output(stderr),
            "output_bytes": len(combined),
            "truncated": len(combined) > limit,
            "network": entry["network"],
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
