"""Request, profile, provider, version, and budget contracts."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from countyforge_runner.contracts import JsonObject, document_sha256
from countyforge_runner.errors import KernelError
from countyforge_runner.resolver import Kernel


def assert_error(kernel: Kernel, request: JsonObject, code: str) -> None:
    with pytest.raises(KernelError) as raised:
        kernel.resolve(request)
    assert raised.value.code == code


def test_valid_review_resolves(
    kernel: Kernel, request_factory: Callable[[str], JsonObject]
) -> None:
    resolved = kernel.resolve(request_factory("review"))
    assert resolved.execution_eligible is True
    assert resolved.profile["repository_access"] == "none"
    assert resolved.model is not None
    assert resolved.model["configured_model_id"] == "fugu-ultra"


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
