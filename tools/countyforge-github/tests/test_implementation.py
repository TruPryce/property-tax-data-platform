"""Free implementation eligibility, packet, and artifact policy fixtures."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from countyforge_github.errors import ControlPlaneError
from countyforge_github.implementation import (
    build_implementation_packet,
    evaluate_implementation_eligibility,
    implementation_branch,
    validate_implementation_result,
)
from countyforge_runner.contracts import load_json_object, validate_document


def _facts() -> tuple[dict[str, object], dict[str, object], str]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    trigger = {
        "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
        "target": {"type": "issue", "number": 7, "base_sha": sha, "head_sha": sha},
    }
    issue = {"number": 7, "title": "Feature implementation", "body": "Feature acceptance criteria"}
    return trigger, issue, sha


def test_unmerged_plan_is_not_eligible(repo_root: Path) -> None:
    _, _, sha = _facts()
    decision = evaluate_implementation_eligibility(
        contract_root=repo_root,
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="add-isolated-openspec-to-code-agents",
        trusted_base_sha=sha,
        planning_pr_merged=False,
    )
    assert decision["eligible"] is False
    assert "planning_pr_not_merged" in decision["blocking_reasons"]


def test_packet_is_bounded_and_hash_bound(tmp_path: Path, repo_root: Path) -> None:
    trigger, issue, _ = _facts()
    result = build_implementation_packet(
        trigger=trigger,
        issue=issue,
        contract_root=repo_root,
        output_dir=tmp_path,
        run_id="fixture-implementation",
        change_name="add-isolated-openspec-to-code-agents",
        planning_pr_merged=True,
        approval_actor_id=42,
    )
    packet = load_json_object(Path(str(result["packet_path"])), kind="implementation packet")
    schema = load_json_object(
        repo_root / ".ai/schemas/countyforge-implementation-packet.schema.json", kind="schema"
    )
    validate_document(packet, schema, kind="implementation packet")
    assert packet["eligibility"]["eligible"] is True
    assert packet["implementation_revision"] >= 1
    assert packet["sources"][-1]["trust_class"] == "untrusted_evidence"
    assert (
        hashlib.sha256(Path(str(result["packet_path"])).read_bytes()).hexdigest()
        == result["packet_sha256"]
    )


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../outside.py", ".github/workflows/evil.yml", ".env"]
)
def test_model_paths_fail_closed(path: str) -> None:
    result = {
        "files_created": [path],
        "files_modified": [],
        "files_deleted": [],
        "publication_eligibility": "not_evaluated",
    }
    with pytest.raises(ControlPlaneError):
        validate_implementation_result(result)


def test_higher_risk_claims_fail_without_explicit_approval() -> None:
    with pytest.raises(ControlPlaneError, match="higher-risk"):
        validate_implementation_result(
            {
                "files_created": [],
                "files_modified": [],
                "files_deleted": [],
                "security_sensitive_changes": ["authentication"],
                "publication_eligibility": "not_evaluated",
            }
        )


def test_branch_identity_is_deterministic() -> None:
    assert (
        implementation_branch(7, "safe-change", 2) == "countyforge/implement/issue-7-safe-change-r2"
    )
