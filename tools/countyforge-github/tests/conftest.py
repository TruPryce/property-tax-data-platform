"""Deterministic CountyForge GitHub control-plane fixtures."""

from __future__ import annotations

import copy
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.identity import semantic_idempotency_key
from countyforge_github.state import initial_state, transition_state


@pytest.fixture
def contracts() -> ControlContracts:
    return ControlContracts()


@pytest.fixture
def event_factory() -> Callable[[str, str, str], JsonObject]:
    def build(
        body: str = "/countyforge review", actor_type: str = "User", action: str = "created"
    ) -> JsonObject:
        return {
            "action": action,
            "repository": {
                "id": 987654,
                "full_name": "TruPryce/property-tax-data-platform",
                "default_branch": "main",
            },
            "issue": {
                "number": 11,
                "title": "Synthetic safe pull request",
                "html_url": "https://github.com/TruPryce/property-tax-data-platform/pull/11",
                "pull_request": {"url": "https://api.github.com/repos/example/pulls/11"},
            },
            "comment": {
                "id": 123456,
                "body": body,
                "user": {"login": "maintainer", "id": 42, "type": actor_type},
            },
            "sender": {"login": "maintainer", "id": 42, "type": actor_type},
        }

    return build


@pytest.fixture
def trigger_factory(
    contracts: ControlContracts,
    event_factory: Callable[[str, str, str], JsonObject],
) -> Callable[[str], JsonObject]:
    head_sha = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def build(command: str = "review") -> JsonObject:
        trigger: JsonObject = {
            "contract_version": 1,
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {
                "type": "pull_request",
                "number": 11,
                "source_repository": {
                    "id": 987654,
                    "full_name": "TruPryce/property-tax-data-platform",
                },
                "base_sha": head_sha,
                "head_sha": head_sha,
            },
            "comment": {"id": 123456, "event_action": "created", "delivery_id": "delivery-1"},
            "actor": {"login": "maintainer", "id": 42, "type": "User"},
            "authorization": {
                "permission": "write",
                "policy_version": 1,
                "outcome": "allowed",
                "reason_code": "repository_permission_allowed",
            },
            "command": {"contract_version": 1, "command": command, "arguments": {}},
            "trusted_tool_sha": head_sha,
            "workflow": {"run_id": 555, "run_attempt": 1},
            "timestamp": "2026-07-19T12:00:00Z",
            "display_metadata": {
                "title": "Synthetic safe pull request",
                "url": "https://github.com/TruPryce/property-tax-data-platform/pull/11",
            },
        }
        contracts.validate("trigger", trigger)
        return trigger

    return build


@pytest.fixture
def queued_state_factory(
    contracts: ControlContracts,
    trigger_factory: Callable[[str], JsonObject],
) -> Callable[[str], JsonObject]:
    def build(command: str = "review") -> JsonObject:
        trigger = trigger_factory(command)
        key = semantic_idempotency_key(trigger, contracts.execution_policy)
        state = initial_state(trigger, contracts.execution_policy, key)
        contracts.validate("state", state)
        state = transition_state(
            state,
            {
                "contract_version": 1,
                "from": "received",
                "to": "authorized",
                "at": "2026-07-19T12:00:01Z",
                "reason_code": "authorization_allowed",
            },
            contracts=contracts,
        )
        return transition_state(
            state,
            {
                "contract_version": 1,
                "from": "authorized",
                "to": "queued",
                "at": "2026-07-19T12:00:02Z",
                "reason_code": "workflow_queued",
            },
            contracts=contracts,
        )

    return build


@pytest.fixture
def copy_document() -> Callable[[JsonObject], JsonObject]:
    return copy.deepcopy


@pytest.fixture
def repo_root() -> Path:
    return Path.cwd().resolve(strict=True)
