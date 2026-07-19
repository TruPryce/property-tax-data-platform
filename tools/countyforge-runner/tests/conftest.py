"""CountyForge runner contract fixtures."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from countyforge_runner.contracts import JsonObject

MODE_FACTS: dict[str, dict[str, Any]] = {
    "review": {
        "profile": "review.packet-only.v1",
        "prompt": "codex-prepr-review",
        "provider": {
            "id": "sakana",
            "model_ref": "sakana.fugu-ultra",
            "codex_cli_version": "0.144.6",
        },
        "effort": "xhigh",
        "schema": "codex-prepr-review.schema.json",
    },
    "plan": {
        "profile": "plan.read-only.v1",
        "prompt": "countyforge-plan",
        "provider": {"id": "openai", "model_ref": "openai.gpt-5.6", "codex_cli_version": "0.144.6"},
        "effort": "medium",
        "schema": "countyforge-plan-result.schema.json",
    },
    "implement": {
        "profile": "implement.workspace-write.v1",
        "prompt": "countyforge-implement",
        "provider": {"id": "openai", "model_ref": "openai.gpt-5.6", "codex_cli_version": "0.144.6"},
        "effort": "high",
        "schema": "countyforge-implementation-result.schema.json",
    },
    "fix": {
        "profile": "fix.targeted-write.v1",
        "prompt": "countyforge-fix",
        "provider": {"id": "openai", "model_ref": "openai.gpt-5.6", "codex_cli_version": "0.144.6"},
        "effort": "high",
        "schema": "countyforge-fix-result.schema.json",
    },
    "validate": {
        "profile": "validate.deterministic.v1",
        "prompt": "countyforge-validate",
        "provider": None,
        "effort": "none",
        "schema": "countyforge-validation-result.schema.json",
    },
}


@pytest.fixture
def request_factory(tmp_path: Path) -> Callable[[str], JsonObject]:
    packet = tmp_path / "packet.md"
    packet.write_text("# deterministic packet\n", encoding="utf-8")

    def build(mode: str = "review") -> JsonObject:
        facts = MODE_FACTS[mode]
        input_facts: JsonObject = {}
        if mode == "review":
            input_facts["packet_path"] = str(packet)
        if mode == "fix":
            input_facts = {"selected_finding_ids": ["finding-1"], "expected_head_sha": "b" * 40}
        return {
            "contract_version": 1,
            "run_id": f"fixture-{mode}",
            "trigger": {"type": "manual", "actor": {"id": "fixture-actor"}},
            "repository": {
                "full_name": "TruPryce/property-tax-data-platform",
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
            },
            "display_metadata": {"branch": "feature/kernel"},
            "openspec_change": "build-mode-aware-runner-kernel",
            "mode": mode,
            "profile": {"id": facts["profile"], "version": 1},
            "prompt": {"id": facts["prompt"], "version": 1},
            "provider": copy.deepcopy(facts["provider"]),
            "reasoning_effort": facts["effort"],
            "budget_overrides": {},
            "input": input_facts,
            "expected_output_schema": facts["schema"],
            "requested_artifacts": ["countyforge-run-summary.json"],
        }

    return build
