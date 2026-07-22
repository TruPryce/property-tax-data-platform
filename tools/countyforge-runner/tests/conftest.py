"""CountyForge runner contract fixtures."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from countyforge_runner.contracts import JsonObject, workspace_sha256

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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def request_factory(tmp_path: Path) -> Iterator[Callable[[str], JsonObject]]:
    repo_root = Path.cwd().resolve(strict=True)
    fixture_root = repo_root / ".ai" / "reviews" / "test-fixtures" / tmp_path.name
    plan_fixture_root = repo_root / ".ai" / "contexts" / "test-fixtures" / tmp_path.name
    fixture_root.mkdir(parents=True)
    plan_fixture_root.mkdir(parents=True)
    packet = fixture_root / "packet.md"
    head_sha = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    packet.write_text(
        "<!-- countyforge-review-packet-metadata-v1 "
        + json.dumps(
            {
                "base_sha": head_sha,
                "builder_id": "repository-review-packet",
                "builder_version": 1,
                "contract_version": 1,
                "head_sha": head_sha,
                "repository_full_name": "TruPryce/property-tax-data-platform",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + " -->\n# deterministic packet\n",
        encoding="utf-8",
    )
    provenance = fixture_root / "packet.provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "builder_id": "repository-review-packet",
                "builder_version": 1,
                "repository_full_name": "TruPryce/property-tax-data-platform",
                "base_sha": head_sha,
                "head_sha": head_sha,
                "packet_sha256": _sha256(packet),
                "packet_bytes": packet.stat().st_size,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    planning_packet = plan_fixture_root / "countyforge-planning-packet.json"
    planning_packet.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "packet_id": "fixture-planning-packet",
                "run_id": "fixture-plan",
                "repository": {
                    "id": 987654,
                    "full_name": "TruPryce/property-tax-data-platform",
                    "target_sha": head_sha,
                },
                "issue": {
                    "number": 1,
                    "title": "Feature planning",
                    "body": "Feature acceptance criteria",
                    "classification": "feature_work",
                    "untrusted": True,
                },
                "sources": [],
                "selection": {
                    "max_files": 1,
                    "max_bytes": 1,
                    "selected_files": 0,
                    "excluded_candidates": [],
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    planning_manifest = plan_fixture_root / "countyforge-context-manifest.json"
    planning_manifest.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "run_id": "fixture-plan",
                "repository_full_name": "TruPryce/property-tax-data-platform",
                "issue_number": 1,
                "target_sha": head_sha,
                "packet_sha256": _sha256(planning_packet),
                "sources": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    implementation_packet = plan_fixture_root / "countyforge-implementation-packet.json"
    implementation_packet.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
                "issue": {"number": 1, "title": "Implementation", "body": "Bounded task"},
                "change": {
                    "name": "build-mode-aware-runner-kernel",
                    "sha256": "a" * 64,
                    "files": [
                        "openspec/changes/build-mode-aware-runner-kernel/.openspec.yaml",
                        "openspec/changes/build-mode-aware-runner-kernel/proposal.md",
                        "openspec/changes/build-mode-aware-runner-kernel/design.md",
                        "openspec/changes/build-mode-aware-runner-kernel/tasks.md",
                    ],
                },
                "trusted_base_sha": head_sha,
                "run_id": "fixture-implement",
                "implementation_revision": 1,
                "eligibility": {
                    "contract_version": 1,
                    "eligible": True,
                    "repository": "TruPryce/property-tax-data-platform",
                    "issue_number": 1,
                    "change_name": "build-mode-aware-runner-kernel",
                    "change_sha256": "a" * 64,
                    "trusted_base_sha": head_sha,
                    "planning_pr_merged": True,
                    "approval_actor_id": 42,
                    "approval_actor_type": "User",
                    "blocking_reasons": [],
                },
                "sources": [],
                "tasks": [
                    {
                        "task_id": "1.1",
                        "description": "Implement the fixture task",
                        "status": "incomplete",
                        "allowed_paths": ["tools"],
                        "required_checks": ["make check"],
                        "risk": "normal",
                    }
                ],
                "policies": {
                    "path_policy": "countyforge-implementation-paths.v1",
                    "network": "disabled",
                    "command_registry": "countyforge-implementation-commands.v1",
                },
                "non_goals": ["merge"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    implementation_manifest = plan_fixture_root / "countyforge-implementation-context-manifest.json"
    implementation_manifest.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "repository": "TruPryce/property-tax-data-platform",
                "issue_number": 1,
                "change_name": "build-mode-aware-runner-kernel",
                "trusted_base_sha": head_sha,
                "run_id": "fixture-implement",
                "implementation_revision": 1,
                "packet_sha256": _sha256(implementation_packet),
                "sources": [],
                "excluded_candidates": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    implementation_tasks = plan_fixture_root / "countyforge-implementation-task-plan.json"
    implementation_tasks.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "run_id": "fixture-implement",
                "change_name": "build-mode-aware-runner-kernel",
                "tasks": [
                    {
                        "task_id": "1.1",
                        "description": "Implement the fixture task",
                        "allowed_paths": ["tools"],
                        "required_checks": ["make check"],
                        "prerequisites": [],
                        "risk": "normal",
                        "status": "incomplete",
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    workspace = plan_fixture_root / "workspace"
    subprocess.run(
        ["git", "clone", "--quiet", "--no-local", str(repo_root), str(workspace)],
        check=True,
        capture_output=True,
    )
    workspace_binding = plan_fixture_root / "countyforge-implementation-workspace-binding.json"
    workspace_binding.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "repository": "TruPryce/property-tax-data-platform",
                "issue_number": 1,
                "change_name": "build-mode-aware-runner-kernel",
                "run_id": "fixture-implement",
                "implementation_revision": 1,
                "base_sha": head_sha,
                "workspace_path": str(workspace.resolve()),
                "workspace_sha256": workspace_sha256(workspace),
                "git_head_sha": head_sha,
                "git_metadata_present": True,
                "hooks_path": "/dev/null",
                "credential_helper": "",
                "fsmonitor_enabled": False,
                "model_mount_excludes": [
                    ".git",
                    ".github/workflows",
                    ".ai/policies",
                    ".env",
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    def build(mode: str = "review") -> JsonObject:
        facts = MODE_FACTS[mode]
        input_facts: JsonObject = {}
        if mode == "review":
            input_facts = {
                "packet_path": str(packet),
                "packet_sha256": _sha256(packet),
                "packet_provenance_path": str(provenance),
                "packet_provenance_sha256": _sha256(provenance),
            }
        if mode == "plan":
            input_facts = {
                "planning_packet_path": str(planning_packet),
                "planning_packet_sha256": _sha256(planning_packet),
                "context_manifest_path": str(planning_manifest),
                "context_manifest_sha256": _sha256(planning_manifest),
            }
        if mode == "fix":
            input_facts = {
                "selected_finding_ids": ["finding-1"],
                "expected_head_sha": head_sha,
            }
        if mode == "implement":
            input_facts = {
                "implementation_packet_path": str(implementation_packet),
                "implementation_packet_sha256": _sha256(implementation_packet),
                "implementation_manifest_path": str(implementation_manifest),
                "implementation_manifest_sha256": _sha256(implementation_manifest),
                "implementation_task_plan_path": str(implementation_tasks),
                "implementation_task_plan_sha256": _sha256(implementation_tasks),
                "workspace_path": str(workspace),
                "workspace_binding_path": str(workspace_binding),
                "workspace_binding_sha256": _sha256(workspace_binding),
            }
        return {
            "contract_version": 1,
            "run_id": f"fixture-{mode}",
            "trigger": {"type": "manual", "actor": {"id": "fixture-actor"}},
            "repository": {
                "full_name": "TruPryce/property-tax-data-platform",
                "base_sha": head_sha,
                "head_sha": head_sha,
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

    yield build
    shutil.rmtree(fixture_root)
    shutil.rmtree(plan_fixture_root)
