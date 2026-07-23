"""Registry-gated implementation command fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from countyforge_runner.command_broker import CommandBroker, validate_command_event
from countyforge_runner.contracts import load_json_object, validate_document
from countyforge_runner.errors import KernelError

# Real runners always expose the system bin directories (where ``bwrap`` itself lives). Tests
# that pin PATH must retain them so sandbox discovery is unaffected while the fixture controls
# only where a candidate command executable is found.
_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _single_command_registry(tmp_path: Path, entry: dict[str, object]) -> Path:
    """Write a strict single-command registry fixture and return its path."""

    registry = tmp_path / f"registry-{entry['id']}.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "policy_id": "countyforge-implementation-commands",
                "version": 1,
                "default_network": "disabled",
                "commands": [entry],
            }
        ),
        encoding="utf-8",
    )
    return registry


def _broker(tmp_path: Path, entry: dict[str, object]) -> CommandBroker:
    repo_root = Path.cwd().resolve()
    return CommandBroker(
        _single_command_registry(tmp_path, entry),
        repo_root / ".ai/schemas/countyforge-implementation-command-registry.schema.json",
    )


def _entry(
    command_id: str,
    executable: str,
    arguments: list[str],
    *,
    environment: list[str] | None = None,
    workspace_mutating: bool = False,
) -> dict[str, object]:
    return {
        "id": command_id,
        "executable": executable,
        "arguments": arguments,
        "phase": "validate",
        "network": "disabled",
        "workspace_mutating": workspace_mutating,
        "timeout_seconds": 30,
        "max_output_bytes": 4096,
        "environment": environment if environment is not None else ["PATH"],
        "artifact_paths": [],
    }


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


def test_system_executable_under_usr_succeeds(tmp_path: Path) -> None:
    """A registry executable resolvable under a mounted /usr runtime root succeeds."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = _broker(tmp_path, _entry("test.usr", "python3", ["-c", "print('ok')"]))
    evidence = broker.run("test.usr", workspace=workspace)
    assert evidence["exit_code"] == 0
    assert evidence["stdout_sha256"] == hashlib.sha256(b"ok\n").hexdigest()


def test_interpreter_with_hidden_initial_path_entry_resolves_to_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A masked venv PATH entry must not hide a trusted system interpreter.

    This is the exact CI defect: under ``uv run`` the first PATH entry is a virtualenv whose
    ``python3`` resolves to a host-home toolchain masked by ``--tmpfs /home``. Trusted host
    resolution must prefer the system interpreter under an approved runtime root instead of
    relying on the sandbox PATH lookup.
    """

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    hidden = tmp_path / "hidden-venv-bin"
    hidden.mkdir()
    home_toolchain = tmp_path / "home-toolchain"
    home_toolchain.mkdir()
    real_target = home_toolchain / "python3-real"
    real_target.write_text("#!/bin/sh\necho masked\n", encoding="utf-8")
    real_target.chmod(0o755)
    # The venv python3 is a symlink whose target lives outside every approved root.
    (hidden / "python3").symlink_to(real_target)
    monkeypatch.setenv("PATH", f"{hidden}:/usr/local/bin:/usr/bin:/bin")
    broker = _broker(tmp_path, _entry("test.hidden-path", "python3", ["-c", "print('ok')"]))
    evidence = broker.run("test.hidden-path", workspace=workspace)
    assert evidence["exit_code"] == 0
    # The masked interpreter never ran; the trusted system interpreter produced the output.
    assert evidence["stdout_sha256"] == hashlib.sha256(b"ok\n").hexdigest()


def test_contract_root_executable_is_rewritten_to_sandbox_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A contract-root executable is mapped to /countyforge/contract and runs there."""

    contract_root = tmp_path / "contract"
    tool_dir = contract_root / "bin"
    tool_dir.mkdir(parents=True)
    tool = tool_dir / "cf-contract-tool"
    tool.write_text("#!/bin/sh\necho contract-ok\n", encoding="utf-8")
    tool.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("PATH", f"{tool_dir}:/usr/bin:/bin")
    broker = _broker(tmp_path, _entry("test.contract-exe", "cf-contract-tool", []))
    evidence = broker.run("test.contract-exe", workspace=workspace, contract_root=contract_root)
    assert evidence["exit_code"] == 0
    assert evidence["stdout_sha256"] == hashlib.sha256(b"contract-ok\n").hexdigest()


def test_symlink_target_outside_approved_roots_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An executable whose only resolution escapes approved roots fails closed."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stray_dir = tmp_path / "stray"
    stray_dir.mkdir()
    target = stray_dir / "cf-stray-target"
    target.write_text("#!/bin/sh\necho stray\n", encoding="utf-8")
    target.chmod(0o755)
    link_dir = tmp_path / "link-bin"
    link_dir.mkdir()
    (link_dir / "cf-stray-tool").symlink_to(target)
    monkeypatch.setenv("PATH", f"{link_dir}:{_SYSTEM_PATH}")
    broker = _broker(tmp_path, _entry("test.stray", "cf-stray-tool", []))
    with pytest.raises(KernelError) as raised:
        broker.run("test.stray", workspace=workspace)
    assert raised.value.code == "command_executable_outside_sandbox"


def test_executable_only_under_masked_host_home_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unique executable available only under a host home fails closed."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home_bin = tmp_path / "fake-home" / ".local" / "bin"
    home_bin.mkdir(parents=True)
    tool = home_bin / "cf-home-only-tool"
    tool.write_text("#!/bin/sh\necho home\n", encoding="utf-8")
    tool.chmod(0o755)
    # Only the host-home directory is on PATH; there is no approved-root equivalent.
    monkeypatch.setenv("PATH", f"{home_bin}:{_SYSTEM_PATH}")
    broker = _broker(tmp_path, _entry("test.home-only", "cf-home-only-tool", []))
    with pytest.raises(KernelError) as raised:
        broker.run("test.home-only", workspace=workspace)
    assert raised.value.code == "command_executable_outside_sandbox"


def test_candidate_workspace_executable_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workspace-resident executable is never permitted in v1."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = workspace / "cf-workspace-tool"
    tool.write_text("#!/bin/sh\necho workspace\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{workspace}:{_SYSTEM_PATH}")
    broker = _broker(tmp_path, _entry("test.workspace-exe", "cf-workspace-tool", []))
    with pytest.raises(KernelError) as raised:
        broker.run("test.workspace-exe", workspace=workspace)
    assert raised.value.code == "command_executable_outside_sandbox"


def test_python_command_can_write_inside_workspace(tmp_path: Path) -> None:
    """A mutating Python command may write within the bound workspace."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = _broker(
        tmp_path,
        _entry(
            "test.workspace-write",
            "python3",
            ["-c", "open('/workspace/generated.txt','w').write('ok')"],
            workspace_mutating=True,
        ),
    )
    evidence = broker.run("test.workspace-write", workspace=workspace)
    assert evidence["exit_code"] == 0
    assert (workspace / "generated.txt").read_text(encoding="utf-8") == "ok"


def test_host_temp_home_sockets_and_network_remain_inaccessible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host temp, home, sockets, and network must stay inaccessible after resolution."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = tmp_path / "host-secret-marker"
    marker.write_text("hidden\n", encoding="utf-8")
    monkeypatch.setenv("COUNTYFORGE_HOST_MARKER", str(marker))
    # The probe is written into the bound workspace so each registry argument stays within the
    # strict 128-byte contract limit; it reports True if any host surface is reachable.
    probe = workspace / "isolation_probe.py"
    probe.write_text(
        "import os, socket, sys\n"
        "hidden = os.path.exists(os.environ['COUNTYFORGE_HOST_MARKER'])\n"
        "home = os.path.exists('/home/runner') or os.path.exists('/root/.ssh')\n"
        "sock = os.path.exists('/var/run/docker.sock') or os.path.exists('/run/user')\n"
        "net = False\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "    net = True\n"
        "except OSError:\n"
        "    net = False\n"
        "sys.stdout.write(str(hidden or home or sock or net))\n",
        encoding="utf-8",
    )
    broker = _broker(
        tmp_path,
        _entry(
            "test.isolation",
            "python3",
            ["/workspace/isolation_probe.py"],
            environment=["COUNTYFORGE_HOST_MARKER", "PATH"],
        ),
    )
    evidence = broker.run("test.isolation", workspace=workspace)
    assert evidence["exit_code"] == 0
    assert evidence["stdout_sha256"] == hashlib.sha256(b"False").hexdigest()


def test_required_command_nonzero_exit_fails_validation_but_keeps_evidence(
    tmp_path: Path,
) -> None:
    """A nonzero child exit yields hashed evidence that is not a successful gate."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = _broker(
        tmp_path,
        _entry("test.nonzero", "python3", ["-c", "import sys; sys.exit(3)"]),
    )
    evidence = broker.run("test.nonzero", workspace=workspace)
    # Evidence is preserved (hashed streams present) ...
    assert evidence["exit_code"] == 3
    assert "stdout_sha256" in evidence and "stderr_sha256" in evidence
    # ... but the explicit success predicate the trusted validation gate uses is false.
    assert int(evidence["exit_code"]) != 0


def test_sandbox_bootstrap_failure_raises_bounded_kernel_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing sandbox binary raises a bounded KernelError rather than producing evidence."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    broker = _broker(tmp_path, _entry("test.bootstrap", "python3", ["-c", "print('x')"]))
    monkeypatch.setattr("countyforge_runner.command_broker.shutil.which", lambda _: None)
    with pytest.raises(KernelError) as raised:
        broker.run("test.bootstrap", workspace=workspace)
    assert raised.value.code == "network_sandbox_unavailable"
