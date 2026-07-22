"""Registry-gated implementation command fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from countyforge_runner.command_broker import CommandBroker, validate_command_event
from countyforge_runner.contracts import load_json_object, validate_document
from countyforge_runner.errors import KernelError


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
