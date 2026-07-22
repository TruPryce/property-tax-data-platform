"""Registry-gated implementation command fixtures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from countyforge_runner.command_broker import CommandBroker, validate_command_event
from countyforge_runner.contracts import load_json_object, validate_document
from countyforge_runner.errors import KernelError


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is not installed")
def test_broker_runs_only_declared_command(tmp_path: Path) -> None:
    repo_root = Path.cwd().resolve()
    broker = CommandBroker(
        repo_root / ".ai/policies/countyforge-implementation-commands.v1.json",
        repo_root / ".ai/schemas/countyforge-implementation-command-registry.schema.json",
    )
    result = broker.run("inspect.list-files", workspace=tmp_path)
    assert result["command_id"] == "inspect.list-files"
    assert result["network_policy"] == "disabled"
    schema = load_json_object(
        repo_root / ".ai/schemas/countyforge-implementation-command-event.schema.json",
        kind="command event schema",
    )
    validate_document(result, schema, kind="command event")
    with pytest.raises(KernelError, match="not declared"):
        broker.run("shell.arbitrary", workspace=tmp_path)


def test_command_evidence_rejects_registry_bypass() -> None:
    with pytest.raises(KernelError, match="not declared"):
        validate_command_event(
            {"command_id": "shell.arbitrary"}, command_ids={"inspect.list-files"}
        )


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is not installed")
def test_broker_fails_closed_at_output_limit(tmp_path: Path) -> None:
    repo_root = Path.cwd().resolve()
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "policy_id": "countyforge-implementation-commands",
                "version": 1,
                "default_network": "disabled",
                "commands": [
                    {
                        "id": "test.output",
                        "executable": "python3",
                        "arguments": ["-c", 'print("x" * 128)'],
                        "phase": "validate",
                        "network": "disabled",
                        "workspace_mutating": False,
                        "timeout_seconds": 30,
                        "max_output_bytes": 8,
                        "environment": ["PATH"],
                        "artifact_paths": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    broker = CommandBroker(
        registry,
        repo_root / ".ai/schemas/countyforge-implementation-command-registry.schema.json",
    )
    with pytest.raises(KernelError, match="output limit"):
        broker.run("test.output", workspace=tmp_path)
