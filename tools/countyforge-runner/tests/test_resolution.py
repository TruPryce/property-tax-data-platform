"""Request, profile, provider, version, and budget contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from countyforge_runner.contracts import JsonObject, document_sha256
from countyforge_runner.errors import KernelError
from countyforge_runner.resolver import Kernel


def assert_error(kernel: Kernel, request: JsonObject, code: str) -> None:
    with pytest.raises(KernelError) as raised:
        kernel.resolve(request)
    assert raised.value.code == code


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_valid_review_resolves(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    resolved = kernel.resolve(request_factory("review"))
    assert resolved.execution_eligible is True
    assert resolved.profile["repository_access"] == "none"
    assert resolved.model is not None
    assert resolved.model["configured_model_id"] == "fugu-ultra"


def test_review_packet_outside_approved_root_fails(
    tmp_path: Path,
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
) -> None:
    outside_packet = tmp_path / "outside-packet.md"
    outside_packet.write_text("outside approved input root\n", encoding="utf-8")
    request = request_factory("review")
    request["input"]["packet_path"] = str(outside_packet)
    assert_error(kernel, request, "input_path_not_approved")


def test_review_packet_parent_traversal_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["input"]["packet_path"] = ".ai/reviews/../profiles/review.packet-only.v1.json"
    assert_error(kernel, request, "input_path_not_approved")


def test_review_packet_symlink_escape_fails(
    tmp_path: Path,
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("review")
    packet = Path(str(request["input"]["packet_path"]))
    outside_packet = tmp_path / "symlink-target.md"
    outside_packet.write_text("outside through symlink\n", encoding="utf-8")
    escaped_packet = packet.parent / "escaped-packet.md"
    escaped_packet.symlink_to(outside_packet)
    request["input"]["packet_path"] = str(escaped_packet)
    assert_error(kernel, request, "input_path_not_approved")


def test_review_packet_must_be_regular_file(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    packet = Path(str(request["input"]["packet_path"]))
    request["input"]["packet_path"] = str(packet.parent)
    assert_error(kernel, request, "input_not_regular")


def test_stale_head_sha_fails(kernel: Kernel, request_factory: Callable[[str], JsonObject]) -> None:
    request = request_factory("review")
    request["repository"]["head_sha"] = "0" * 40
    assert_error(kernel, request, "repository_head_mismatch")


def test_nonexistent_base_sha_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["repository"]["base_sha"] = "0" * 40
    assert_error(kernel, request, "repository_base_not_found")


def test_wrong_requested_repository_identity_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["repository"]["full_name"] = "example/other-repository"
    assert_error(kernel, request, "repository_identity_mismatch")


def test_wrong_origin_repository_identity_fails(
    monkeypatch: pytest.MonkeyPatch,
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("review")
    original_run_git = kernel._run_git

    def run_git(*arguments: str) -> subprocess.CompletedProcess[str]:
        if arguments == ("remote", "get-url", "origin"):
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout="git@github.com:example/other-repository.git\n",
                stderr="",
            )
        return original_run_git(*arguments)

    monkeypatch.setattr(kernel, "_run_git", run_git)
    assert_error(kernel, request, "repository_identity_mismatch")


def test_packet_content_hash_mismatch_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    packet = Path(str(request["input"]["packet_path"]))
    packet.write_text("changed after request creation\n", encoding="utf-8")
    assert_error(kernel, request, "packet_hash_mismatch")


def test_packet_provenance_must_agree_with_request(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    provenance_path = Path(str(request["input"]["packet_provenance_path"]))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["repository_full_name"] = "example/other-repository"
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    request["input"]["packet_provenance_sha256"] = file_sha256(provenance_path)
    assert_error(kernel, request, "packet_provenance_mismatch")


def test_embedded_packet_provenance_must_agree_with_request(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    packet = Path(str(request["input"]["packet_path"]))
    lines = packet.read_text(encoding="utf-8").splitlines()
    metadata = {
        "base_sha": request["repository"]["base_sha"],
        "builder_id": "repository-review-packet",
        "builder_version": 1,
        "contract_version": 1,
        "head_sha": request["repository"]["head_sha"],
        "repository_full_name": "example/other-repository",
    }
    lines[0] = (
        "<!-- countyforge-review-packet-metadata-v1 "
        + json.dumps(metadata, separators=(",", ":"), sort_keys=True)
        + " -->"
    )
    packet.write_text("\n".join(lines) + "\n", encoding="utf-8")
    request["input"]["packet_sha256"] = file_sha256(packet)
    provenance_path = Path(str(request["input"]["packet_provenance_path"]))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["packet_sha256"] = request["input"]["packet_sha256"]
    provenance["packet_bytes"] = packet.stat().st_size
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    request["input"]["packet_provenance_sha256"] = file_sha256(provenance_path)
    assert_error(kernel, request, "packet_provenance_mismatch")


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("packet_hash", "planning_packet_hash_mismatch"),
        ("manifest_hash", "context_manifest_hash_mismatch"),
        ("run_id", "planning_provenance_mismatch"),
        ("issue_number", "planning_provenance_mismatch"),
    ],
)
def test_planning_provenance_bindings_fail_closed(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
    mutation: str,
    code: str,
) -> None:
    request = request_factory("plan")
    if mutation == "packet_hash":
        request["input"]["planning_packet_sha256"] = "0" * 64
    elif mutation == "manifest_hash":
        request["input"]["context_manifest_sha256"] = "0" * 64
    elif mutation == "run_id":
        request["run_id"] = "fixture-plan-other"
    else:
        request["trigger"]["issue_number"] = 2
    assert_error(kernel, request, code)


def test_planning_manifest_packet_binding_fails_closed(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("plan")
    manifest_path = Path(str(request["input"]["context_manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["packet_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    request["input"]["context_manifest_sha256"] = file_sha256(manifest_path)
    assert_error(kernel, request, "planning_provenance_mismatch")


@pytest.mark.parametrize(
    ("mode", "schema"),
    [
        ("review", "codex-prepr-review.schema.json"),
        ("plan", "countyforge-plan-result.schema.json"),
        ("implement", "countyforge-implementation-result.schema.json"),
        ("fix", "countyforge-fix-result.schema.json"),
        ("validate", "countyforge-validation-result.schema.json"),
    ],
)
def test_each_mode_resolves_its_schema(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
    mode: str,
    schema: str,
) -> None:
    assert kernel.resolve(request_factory(mode)).profile["output_schema"] == schema


def test_mode_cannot_change_after_profile_selection(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["mode"] = "implement"
    assert_error(kernel, request, "mode_profile_mismatch")


@pytest.mark.parametrize("name", ["tool", "mount", "network_destination", "credential"])
def test_request_cannot_add_capability(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
    name: str,
) -> None:
    request = request_factory("review")
    request[name] = "undeclared"
    assert_error(kernel, request, "schema_validation_failed")


@pytest.mark.parametrize(
    ("budget", "value"),
    [
        ("wall_clock_seconds", 3601),
        ("attempts", 2),
        ("max_output_bytes", 1048577),
        ("max_input_bytes", 3000001),
        ("max_tokens", 1000001),
        ("max_cost_usd", 100.01),
    ],
)
def test_request_cannot_expand_budget(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
    budget: str,
    value: int | float,
) -> None:
    request = request_factory("review")
    request["budget_overrides"][budget] = value
    assert_error(kernel, request, "budget_ceiling_exceeded")


def test_request_can_tighten_budget(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["budget_overrides"] = {
        "wall_clock_seconds": 60,
        "max_output_bytes": 4096,
        "max_tokens": 1000,
        "max_cost_usd": 1.0,
    }
    budgets = kernel.resolve(request).effective_budgets
    assert budgets["wall_clock_seconds"] == 60
    assert budgets["max_output_bytes"] == 4096


@pytest.mark.parametrize(
    ("budget", "value"),
    [
        ("wall_clock_seconds", 1801),
        ("max_output_bytes", 262145),
    ],
)
def test_request_cannot_expand_profile_default(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
    budget: str,
    value: int | float,
) -> None:
    request = request_factory("review")
    request["budget_overrides"][budget] = value
    assert_error(kernel, request, "budget_expansion_not_permitted")


def test_concrete_token_and_cost_limits_tighten_unavailable_defaults(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["budget_overrides"].update({"max_tokens": 1000, "max_cost_usd": 1.0})
    budgets = kernel.resolve(request).effective_budgets
    assert budgets["max_tokens"] == 1000
    assert budgets["max_cost_usd"] == 1.0


def test_reasoning_effort_cannot_expand(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["reasoning_effort"] = "medium"
    assert_error(kernel, request, "reasoning_effort_not_permitted")


def test_reasoning_effort_can_tighten(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["reasoning_effort"] = "high"
    assert kernel.resolve(request).request["reasoning_effort"] == "high"


def test_run_id_and_idempotency_seed_are_mutually_exclusive(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["idempotency_seed"] = "duplicate-identity"
    assert_error(kernel, request, "schema_validation_failed")


@pytest.mark.parametrize(
    ("trigger_type", "number_field"),
    [("github_issue", "issue_number"), ("pull_request", "pull_request_number")],
)
def test_github_trigger_requires_its_number(
    kernel: Kernel,
    request_factory: Callable[[str], JsonObject],
    trigger_type: str,
    number_field: str,
) -> None:
    request = request_factory("review")
    request["trigger"]["type"] = trigger_type
    assert_error(kernel, request, "schema_validation_failed")
    request["trigger"][number_field] = 4
    kernel.resolve(request)


def test_undeclared_artifact_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["requested_artifacts"].append("git-push.json")
    assert_error(kernel, request, "artifact_not_declared")


def test_undeclared_output_schema_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("plan")
    request["expected_output_schema"] = "codex-prepr-review.schema.json"
    assert_error(kernel, request, "output_schema_not_declared")


def test_unknown_profile_version_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["profile"]["version"] = 99
    assert_error(kernel, request, "profile_not_found")


def test_unsupported_provider_model_pair_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["provider"] = {
        "id": "openai",
        "model_ref": "sakana.fugu-ultra",
        "codex_cli_version": "0.144.6",
    }
    assert_error(kernel, request, "provider_model_mismatch")


def test_below_minimum_codex_cli_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["provider"]["codex_cli_version"] = "0.143.9"
    assert_error(kernel, request, "codex_cli_too_old")


def test_unknown_json_property_fails(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    request = request_factory("review")
    request["unexpected"] = {"secret": "must-not-be-rendered"}  # pragma: allowlist secret
    assert_error(kernel, request, "schema_validation_failed")


def test_profile_hash_changes_with_posture(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    profile = kernel.resolve(request_factory("review")).profile
    changed = copy.deepcopy(profile)
    changed["expected_security_posture"]["repository_mounted"] = True
    assert document_sha256(changed) != document_sha256(profile)


def test_explain_contains_complete_resolution(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    document = kernel.resolve(request_factory("review")).as_document()
    assert document["provider"]["id"] == "sakana"
    assert document["model"]["logical_ref"] == "sakana.fugu-ultra"
    assert document["effective_budgets"]["attempts"] == 1
    assert document["reasoning_effort_policy"]["default"] == "xhigh"
    assert document["output_schema"] == "codex-prepr-review.schema.json"
    assert document["capabilities"]["repository_access"] == "none"
    assert document["execution_eligible"] is True


@pytest.fixture
def kernel() -> Kernel:
    return Kernel()
