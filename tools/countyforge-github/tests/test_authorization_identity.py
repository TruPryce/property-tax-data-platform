"""Authorization, trigger, semantic identity, and strict contract tests."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from countyforge_github.authorization import authorize
from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.identity import (
    build_trigger,
    effective_idempotency_key,
    execution_run_id,
    retry_idempotency_key,
    semantic_idempotency_key,
)
from countyforge_runner.errors import KernelError


@pytest.mark.parametrize(
    ("permission", "role", "expected"),
    [
        ("admin", "admin", "allowed"),
        ("write", "maintain", "allowed"),
        ("write", "write", "allowed"),
        ("read", "triage", "denied"),
        ("read", "read", "denied"),
        ("none", "none", "denied"),
    ],
)
def test_repository_permission_matrix(
    contracts: ControlContracts, permission: str, role: str, expected: str
) -> None:
    decision = authorize(
        actor_login="maintainer",
        actor_id=42,
        actor_type="User",
        permission={"permission": permission, "role_name": role},
        contracts=contracts,
    )
    assert decision["outcome"] == expected


def test_unlisted_bot_is_denied(contracts: ControlContracts) -> None:
    decision = authorize(
        actor_login="forged[bot]",
        actor_id=99,
        actor_type="Bot",
        permission={"permission": "admin", "role_name": "admin"},
        contracts=contracts,
    )
    assert decision["outcome"] == "denied"
    assert decision["reason_code"] == "bot_not_allowed"


def test_comment_and_delivery_ids_do_not_change_semantic_identity(
    contracts: ControlContracts, trigger_factory: Callable[[str], JsonObject]
) -> None:
    first = trigger_factory("review")
    second = copy.deepcopy(first)
    second["comment"] = {"id": 999, "event_action": "created", "delivery_id": "other"}
    assert semantic_idempotency_key(first, contracts.execution_policy) == semantic_idempotency_key(
        second, contracts.execution_policy
    )


def test_changed_head_changes_semantic_identity(
    contracts: ControlContracts, trigger_factory: Callable[[str], JsonObject]
) -> None:
    first = trigger_factory("review")
    second = copy.deepcopy(first)
    second["target"]["head_sha"] = "a" * 40
    assert semantic_idempotency_key(first, contracts.execution_policy) != semantic_idempotency_key(
        second, contracts.execution_policy
    )


def test_retry_identity_is_bound_to_original_command_and_attempt(
    contracts: ControlContracts, trigger_factory: Callable[[str], JsonObject]
) -> None:
    trigger = trigger_factory("review")
    original = semantic_idempotency_key(trigger, contracts.execution_policy)
    trigger["retry"] = {
        "original_idempotency_key": original,
        "original_run_id": f"gh-{original[:24]}-a1",
        "attempt": 2,
    }
    contracts.validate("trigger", trigger)
    expected = retry_idempotency_key(original, 2)
    assert effective_idempotency_key(trigger, contracts.execution_policy) == expected
    assert execution_run_id(trigger, contracts.execution_policy) == f"gh-{expected[:24]}-a2"

    trigger["retry"]["original_idempotency_key"] = "a" * 64
    with pytest.raises(ControlPlaneError) as raised:
        effective_idempotency_key(trigger, contracts.execution_policy)
    assert raised.value.code == "retry_identity_mismatch"


def test_unknown_contract_properties_fail(
    contracts: ControlContracts, trigger_factory: Callable[[str], JsonObject]
) -> None:
    trigger = trigger_factory("review")
    trigger["token"] = "must-not-exist"
    with pytest.raises(KernelError) as raised:
        contracts.validate("trigger", trigger)
    assert raised.value.code == "schema_validation_failed"


def test_invalid_date_time_format_fails_contract_validation(
    contracts: ControlContracts, trigger_factory: Callable[[str], JsonObject]
) -> None:
    trigger = trigger_factory("review")
    trigger["timestamp"] = "not-a-date"
    with pytest.raises(KernelError) as raised:
        contracts.validate("trigger", trigger)
    assert raised.value.code == "schema_validation_failed"


def test_trigger_builder_rejects_non_created_event(
    contracts: ControlContracts,
    event_factory: Callable[[str, str, str], JsonObject],
    trigger_factory: Callable[[str], JsonObject],
) -> None:
    reference = trigger_factory("review")
    event = event_factory("/countyforge review", action="edited")
    with pytest.raises(ControlPlaneError) as raised:
        build_trigger(
            event=event,
            command=reference["command"],
            authorization={
                "actor": reference["actor"],
                **reference["authorization"],
            },
            target=reference["target"],
            trusted_tool_sha=reference["trusted_tool_sha"],
            workflow_run_id=555,
            workflow_run_attempt=1,
            contracts=contracts,
        )
    assert raised.value.code == "invalid_event_action"


def test_policies_are_strict_and_deny_by_default(contracts: ControlContracts) -> None:
    assert contracts.authorization_policy["allowed_permissions"] == ["admin", "maintain", "write"]
    assert contracts.authorization_policy["allowed_bots"] == []
    assert contracts.authorization_policy["allowed_teams"] == []
    assert set(contracts.execution_policy["commands"]) == {
        "review",
        "plan",
        "implement",
        "fix",
        "validate",
    }
