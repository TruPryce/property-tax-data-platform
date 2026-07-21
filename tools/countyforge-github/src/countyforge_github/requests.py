"""Strict CountyForge runner-request construction from an authorized trigger."""

from __future__ import annotations

from pathlib import Path

from countyforge_runner.contracts import file_sha256
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
        "run_id": execution_run_id(trigger, contracts.execution_policy),
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
