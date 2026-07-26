"""Strict CountyForge runner-request construction from an authorized trigger."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from countyforge_runner.contracts import (
    canonical_bytes,
    file_sha256,
    load_json_object,
    validate_document,
    workspace_sha256,
)
from countyforge_runner.resolver import Kernel

from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.identity import execution_run_id


def build_run_request(
    trigger: JsonObject,
    *,
    contract_root: Path,
    target_root: Path,
    packet_path: Path | None = None,
    packet_provenance_path: Path | None = None,
    planning_packet_path: Path | None = None,
    context_manifest_path: Path | None = None,
    implementation_packet_path: Path | None = None,
    implementation_manifest_path: Path | None = None,
    implementation_task_plan_path: Path | None = None,
    workspace_path: Path | None = None,
    workspace_binding_path: Path | None = None,
) -> JsonObject:
    """Build and resolve one profile-specific request without loading credentials."""

    contracts = ControlContracts(contract_root)
    contracts.validate("trigger", trigger)
    if trigger["authorization"]["outcome"] != "allowed":
        raise ControlPlaneError(
            "authorization_denied", "CountyForge command authorization was denied.", exit_code=3
        )
    mode = str(trigger["command"]["command"])
    if mode not in contracts.execution_policy["commands"]:
        raise ControlPlaneError(
            "not_execution_command", "The selected command is a control-plane operation."
        )
    selection = contracts.execution_policy["commands"][mode]
    kernel = Kernel(contract_root=contract_root, target_root=target_root)
    profile_key = (str(selection["profile_id"]), int(selection["profile_version"]))
    profile = kernel.profiles.get(profile_key)
    if profile is None or profile["mode"] != mode:
        raise ControlPlaneError(
            "execution_policy_mismatch", "Execution selection does not match a trusted profile."
        )
    provider_id = selection["provider"]
    provider: JsonObject | None
    if provider_id is None:
        provider = None
    else:
        provider = {
            "id": provider_id,
            "model_ref": selection["model_ref"],
            "codex_cli_version": profile["container"]["codex_cli_version"],
        }
    request_input: JsonObject = {}
    run_id = execution_run_id(trigger, contracts.execution_policy)
    if mode == "review":
        if packet_path is None or packet_provenance_path is None:
            raise ControlPlaneError(
                "review_packet_required", "Review requires a frozen packet and provenance."
            )
        request_input = {
            "packet_path": str(packet_path),
            "packet_sha256": file_sha256(packet_path),
            "packet_provenance_path": str(packet_provenance_path),
            "packet_provenance_sha256": file_sha256(packet_provenance_path),
        }
    elif mode == "fix":
        request_input = {
            "selected_finding_ids": ["profile-not-implemented"],
            "expected_head_sha": trigger["target"]["head_sha"],
        }
    elif mode == "plan":
        if planning_packet_path is None or context_manifest_path is None:
            raise ControlPlaneError(
                "planning_context_required",
                "Planning requires a frozen planning packet and context manifest.",
            )
        request_input = {
            "planning_packet_path": str(planning_packet_path),
            "planning_packet_sha256": file_sha256(planning_packet_path),
            "context_manifest_path": str(context_manifest_path),
            "context_manifest_sha256": file_sha256(context_manifest_path),
        }
    elif mode == "implement":
        if trigger["target"]["type"] != "issue":
            raise ControlPlaneError(
                "implementation_issue_required",
                "Implementation commands are supported only on originating issues.",
            )
        if (
            implementation_packet_path is None
            or implementation_manifest_path is None
            or implementation_task_plan_path is None
            or workspace_path is None
        ):
            raise ControlPlaneError(
                "implementation_context_required",
                "Implementation requires a frozen packet, manifest, task plan, and workspace.",
            )
        else:
            workspace = workspace_path.resolve(strict=True)
            if not workspace.is_dir():
                raise ControlPlaneError(
                    "workspace_unavailable", "Implementation workspace is unavailable."
                )
            binding_path = (
                workspace_binding_path
                or workspace.parent / "countyforge-implementation-workspace-binding.json"
            ).resolve()
            try:
                head = subprocess.run(
                    ["git", "-C", str(workspace), "rev-parse", "--verify", "HEAD^{commit}"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env={"PATH": os.environ.get("PATH", ""), "GIT_OPTIONAL_LOCKS": "0"},
                )
            except (OSError, subprocess.SubprocessError):
                raise ControlPlaneError(
                    "workspace_binding_invalid",
                    "Implementation workspace Git metadata is unavailable.",
                ) from None
            git_head_sha = head.stdout.strip() if head.returncode == 0 else ""
            if len(git_head_sha) != 40:
                raise ControlPlaneError(
                    "workspace_binding_invalid", "Implementation workspace Git metadata is invalid."
                )
            target = trigger["target"]
            issue_number = int(target.get("number", 0))
            repository_name = str(trigger["repository"]["full_name"])
            binding: JsonObject = {
                "contract_version": 1,
                "repository": repository_name,
                "issue_number": issue_number,
                "change_name": str(trigger["command"]["arguments"].get("openspec_change", "")),
                "run_id": run_id,
                "implementation_revision": int(
                    load_json_object(implementation_packet_path, kind="implementation packet")[
                        "implementation_revision"
                    ]
                ),
                "base_sha": str(target["base_sha"]),
                "workspace_path": str(workspace),
                "workspace_sha256": workspace_sha256(workspace),
                "git_head_sha": git_head_sha,
                "git_metadata_present": True,
                "hooks_path": "/dev/null",
                "credential_helper": "",
                "fsmonitor_enabled": False,
                "model_mount_excludes": [".git", ".github/workflows", ".ai/policies", ".env"],
            }
            schema = (
                contracts.contract_root
                / ".ai"
                / "schemas"
                / "countyforge-implementation-workspace-binding.schema.json"
            )
            validate_document(
                binding,
                load_json_object(schema, kind="implementation workspace binding schema"),
                kind="implementation workspace binding",
            )
            binding_path.parent.mkdir(parents=True, exist_ok=True)
            binding_path.write_bytes(canonical_bytes(binding) + b"\n")
            request_input = {
                "implementation_packet_path": str(implementation_packet_path),
                "implementation_packet_sha256": file_sha256(implementation_packet_path),
                "implementation_manifest_path": str(implementation_manifest_path),
                "implementation_manifest_sha256": file_sha256(implementation_manifest_path),
                "implementation_task_plan_path": str(implementation_task_plan_path),
                "implementation_task_plan_sha256": file_sha256(implementation_task_plan_path),
                "workspace_path": str(workspace),
                "workspace_binding_path": str(binding_path),
                "workspace_binding_sha256": file_sha256(binding_path),
            }
    runner_trigger: JsonObject = {
        "type": "pull_request" if trigger["target"]["type"] == "pull_request" else "github_issue",
        "actor": {"id": str(trigger["actor"]["id"])},
    }
    number_field = (
        "pull_request_number" if trigger["target"]["type"] == "pull_request" else "issue_number"
    )
    runner_trigger[number_field] = trigger["target"]["number"]
    request: JsonObject = {
        "contract_version": 1,
        "run_id": run_id,
        "trigger": runner_trigger,
        "repository": {
            "full_name": trigger["repository"]["full_name"],
            "base_sha": trigger["target"]["base_sha"],
            "head_sha": trigger["target"]["head_sha"],
        },
        "display_metadata": {
            "branch": f"github/{trigger['target']['type']}-{trigger['target']['number']}",
            "title": trigger.get("display_metadata", {}).get("title", "CountyForge GitHub run"),
        },
        "openspec_change": trigger["command"]["arguments"].get("openspec_change"),
        "mode": mode,
        "profile": {"id": profile["profile_id"], "version": profile["profile_version"]},
        "prompt": {"id": profile["prompt"]["id"], "version": profile["prompt"]["version"]},
        "provider": provider,
        "reasoning_effort": selection["reasoning_effort"],
        "budget_overrides": {},
        "input": request_input,
        "expected_output_schema": profile["output_schema"],
        "requested_artifacts": profile["allowed_artifacts"],
    }
    kernel.resolve(request)
    return request
