"""Registry-gated implementation command fixtures."""

from __future__ import annotations

import hashlib
import json
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


def test_broker_fails_closed_when_bubblewrap_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = Path.cwd().resolve()
    broker = CommandBroker(
        repo_root / ".ai/policies/countyforge-implementation-commands.v1.json",
        repo_root / ".ai/schemas/countyforge-implementation-command-registry.schema.json",
    )
    monkeypatch.setattr("countyforge_runner.command_broker.shutil.which", lambda _: None)
    with pytest.raises(KernelError, match="sandbox is unavailable"):
        broker.run("inspect.list-files", workspace=tmp_path)


def test_command_evidence_rejects_registry_bypass() -> None:
    with pytest.raises(KernelError, match="not declared"):
        validate_command_event(
            {"command_id": "shell.arbitrary"}, command_ids={"inspect.list-files"}
        )


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


def test_non_mutating_command_cannot_change_candidate_workspace(tmp_path: Path) -> None:
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
                        "id": "test.mutates",
                        "executable": "python3",
                        "arguments": [
                            "-c",
                            "open('/workspace/model-mutated.py', 'w').write('unsafe\\n')",
                        ],
                        "phase": "validate",
                        "network": "disabled",
                        "workspace_mutating": False,
                        "timeout_seconds": 30,
                        "max_output_bytes": 1024,
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
    with pytest.raises(KernelError, match="workspace"):
        broker.run("test.mutates", workspace=tmp_path)


def test_prepr_generated_review_artifacts_are_allowed_for_non_mutating_gate(
    tmp_path: Path,
) -> None:
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
                        "id": "test.prepr-artifacts",
                        "executable": "python3",
                        "arguments": [
                            "-c",
                            (
                                "import os;os.makedirs('/workspace/.ai/reviews');"
                                "open('/workspace/.ai/reviews/review-packet.md','w').write('x')"
                            ),
                        ],
                        "phase": "validate",
                        "network": "disabled",
                        "workspace_mutating": False,
                        "timeout_seconds": 30,
                        "max_output_bytes": 1024,
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
    result = broker.run("test.prepr-artifacts", workspace=tmp_path)
    assert result["exit_code"] == 0


def test_broker_masks_host_temp_and_mounts_only_contract_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = Path.cwd().resolve()
    marker = tmp_path / "host-only-marker"
    marker.write_text("must remain hidden\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    monkeypatch.setenv("COUNTYFORGE_HOST_MARKER", str(marker))
    probe = "import os; print(os.path.exists(os.environ['COUNTYFORGE_HOST_MARKER']))"
    registry.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "policy_id": "countyforge-implementation-commands",
                "version": 1,
                "default_network": "disabled",
                "commands": [
                    {
                        "id": "test.sandbox",
                        "executable": "python3",
                        "arguments": ["-c", probe],
                        "phase": "validate",
                        "network": "disabled",
                        "workspace_mutating": False,
                        "timeout_seconds": 30,
                        "max_output_bytes": 1024,
                        "environment": ["COUNTYFORGE_HOST_MARKER", "PATH"],
                        "artifact_paths": [],
                    },
                    {
                        "id": "test.contract",
                        "executable": "test",
                        "arguments": [
                            "-f",
                            "/countyforge/contract/.ai/schemas/countyforge-run-request.schema.json",
                        ],
                        "phase": "validate",
                        "network": "disabled",
                        "workspace_mutating": False,
                        "timeout_seconds": 30,
                        "max_output_bytes": 1024,
                        "environment": ["PATH"],
                        "artifact_paths": [],
                    },
                    {
                        "id": "test.host-sockets",
                        "executable": "test",
                        "arguments": [
                            "!",
                            "-e",
                            "/var/run/docker.sock",
                            "-a",
                            "!",
                            "-e",
                            "/run/user",
                            "-a",
                            "!",
                            "-e",
                            "/home/runner",
                        ],
                        "phase": "validate",
                        "network": "disabled",
                        "workspace_mutating": False,
                        "timeout_seconds": 30,
                        "max_output_bytes": 1024,
                        "environment": ["PATH"],
                        "artifact_paths": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    broker = CommandBroker(
        registry,
        repo_root / ".ai/schemas/countyforge-implementation-command-registry.schema.json",
    )
    evidence = broker.run("test.sandbox", workspace=tmp_path, contract_root=repo_root)
    assert evidence["stdout_sha256"] == hashlib.sha256(b"False\n").hexdigest()
    contract_evidence = broker.run("test.contract", workspace=tmp_path, contract_root=repo_root)
    assert contract_evidence["exit_code"] == 0
    socket_evidence = broker.run("test.host-sockets", workspace=tmp_path, contract_root=repo_root)
    assert socket_evidence["exit_code"] == 0
