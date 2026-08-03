"""Trusted semantic validation and bounded multipart decision input.

PR #46 was syntactically valid and semantically useless. Every test here names
the defect it pins, so a regression reads as the original failure rather than as
an abstract assertion.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from countyforge_github.decision_input import (
    EXCLUDED_SUPERSEDED,
    EXCLUDED_TOO_LARGE,
    INCOMPLETE,
    MARKER,
    assert_unedited_since_trigger,
    collect_decision_input,
)
from countyforge_github.errors import ControlPlaneError
from countyforge_github.planning_semantics import (
    SEMANTIC_DISPOSITION,
    validate_planning_semantics,
)

FIXTURE = Path("tools/countyforge-github/tests/fixtures/planning-result-collin-issue-18.json")
CONTRACT_ROOT = Path.cwd()
AUTHOR_ID = 4242


def _result(**overrides: Any) -> dict[str, Any]:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document.update(copy.deepcopy(overrides))
    return document


def _validate(document: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return validate_planning_semantics(document, contract_root=CONTRACT_ROOT, **kwargs)


def _refusal(document: dict[str, Any], **kwargs: Any) -> str:
    with pytest.raises(ControlPlaneError) as raised:
        _validate(document, **kwargs)
    assert raised.value.code == SEMANTIC_DISPOSITION
    return str(raised.value.details["reason"])


# --------------------------------------------------------------------------
# Defect 1 — bounded multipart decision input
# --------------------------------------------------------------------------


def _part(
    part: int,
    total: int,
    body: str,
    *,
    comment_id: int,
    input_id: str = "collin-1",
    issue: int = 18,
    author_id: int = AUTHOR_ID,
    updated_at: str = "2026-07-30T00:00:00Z",
):
    marker = (
        f"<!-- countyforge-plan-input:v1 issue={issue} input={input_id} part={part}/{total} -->"
    )
    return {
        "id": comment_id,
        "body": f"{marker}\n\n{body}",
        "updated_at": updated_at,
        "user": {"id": author_id, "login": "maintainer", "type": "User"},
    }


def _four_parts() -> list[dict[str, Any]]:
    return [
        _part(index, 4, f"## D{index} — decision {index} body text", comment_id=1000 + index)
        for index in range(1, 5)
    ]


def test_1_a_four_part_decision_package_is_assembled_whole() -> None:
    collected = collect_decision_input(_four_parts(), issue_number=18)
    assert [part.part for part in collected.parts] == [1, 2, 3, 4]
    assert collected.input_id == "collin-1"
    text = collected.text()
    for index in range(1, 5):
        assert f"## D{index} —" in text
    entry = collected.manifest_entry()
    assert entry["truncated"] is False
    assert entry["included_part_count"] == 4
    assert [item["part"] for item in entry["included_parts"]] == [1, 2, 3, 4]
    # Every part is bound to the facts that identify it.
    for item in entry["included_parts"]:
        assert set(item) >= {"comment_id", "author_id", "body_sha256", "updated_at"}


def test_2_a_missing_part_fails_closed_rather_than_planning_from_a_fragment() -> None:
    parts = [comment for comment in _four_parts() if "part=3/4" not in comment["body"]]
    with pytest.raises(ControlPlaneError) as raised:
        collect_decision_input(parts, issue_number=18)
    assert raised.value.code == INCOMPLETE
    assert raised.value.details["reason"] == "missing_part"
    assert raised.value.details["missing"] == [3]


def test_3_a_duplicate_part_number_fails() -> None:
    parts = [*_four_parts(), _part(2, 4, "a second D2", comment_id=2000)]
    with pytest.raises(ControlPlaneError) as raised:
        collect_decision_input(parts, issue_number=18)
    assert raised.value.details["reason"] == "duplicate_part"


def test_4_a_part_edited_after_the_trigger_fails_closed() -> None:
    bound = collect_decision_input(_four_parts(), issue_number=18)
    provenance = [part.provenance() for part in bound.parts]
    edited = _four_parts()
    edited[2]["body"] = edited[2]["body"] + "\n\nreconsidered after the run started"
    edited[2]["updated_at"] = "2026-07-31T09:00:00Z"
    reread = collect_decision_input(edited, issue_number=18)
    with pytest.raises(ControlPlaneError) as raised:
        assert_unedited_since_trigger(reread, provenance)
    assert raised.value.details["reason"] == "part_edited_after_trigger"
    assert raised.value.details["observed_updated_at"] == "2026-07-31T09:00:00Z"


def test_5_an_oversized_part_is_excluded_with_a_reason_never_truncated() -> None:
    parts = _four_parts()
    parts[1] = _part(2, 4, "x" * 30_000, comment_id=1002)
    with pytest.raises(ControlPlaneError) as raised:
        collect_decision_input(parts, issue_number=18, max_part_bytes=24_000)
    # Excluded, so the package is incomplete; it is never half-included.
    assert raised.value.details["reason"] == "missing_part"
    partial = collect_decision_input([parts[1]], issue_number=18, max_part_bytes=24_000)
    assert partial.parts == []
    assert partial.excluded[0]["reason"] == EXCLUDED_TOO_LARGE
    assert partial.excluded[0]["byte_length"] == 30_000


def test_6_the_total_decision_budget_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = [_part(index, 4, "y" * 5_000, comment_id=1000 + index) for index in range(1, 5)]
    with pytest.raises(ControlPlaneError) as raised:
        collect_decision_input(parts, issue_number=18, max_total_bytes=10_000)
    assert raised.value.details["reason"] == "total_budget_exceeded"
    assert raised.value.details["total_byte_length"] == 20_000


def test_7_bot_status_and_command_comments_are_never_decision_content() -> None:
    parts = _four_parts()
    bot = _part(1, 1, "status", comment_id=9001, input_id="bot", author_id=41898282)
    bot["user"]["type"] = "Bot"
    command = _part(1, 1, "/countyforge plan", comment_id=9002, input_id="cmd")
    collected = collect_decision_input(
        [*parts, bot, command], issue_number=18, trusted_bot_id=41898282
    )
    assert collected.input_id == "collin-1"
    assert len(collected.parts) == 4
    reasons = {item["reason"] for item in collected.excluded}
    assert "command_comment_not_decision_content" in reasons
    assert 9001 not in {item.get("comment_id") for item in collected.excluded}


def test_an_unauthorized_author_and_a_foreign_issue_are_excluded() -> None:
    parts = _four_parts()
    stranger = _part(1, 1, "decision", comment_id=8001, input_id="other", author_id=999)
    foreign = _part(1, 1, "decision", comment_id=8002, input_id="foreign", issue=43)
    collected = collect_decision_input(
        [*parts, stranger, foreign], issue_number=18, authorized_author_ids=[AUTHOR_ID]
    )
    reasons = {item["reason"] for item in collected.excluded}
    assert reasons >= {"author_not_authorized", "issue_number_mismatch"}
    assert len(collected.parts) == 4


def test_an_older_decision_package_is_recorded_as_superseded_not_merged() -> None:
    older = [
        _part(index, 2, f"old D{index}", comment_id=500 + index, input_id="collin-0")
        for index in range(1, 3)
    ]
    collected = collect_decision_input([*older, *_four_parts()], issue_number=18)
    assert collected.input_id == "collin-1"
    superseded = [item for item in collected.excluded if item["reason"] == EXCLUDED_SUPERSEDED]
    assert {item["part"] for item in superseded} == {1, 2}


def test_only_the_exact_versioned_marker_selects_a_comment() -> None:
    for body in (
        "<!-- countyforge-plan-input:v2 issue=18 input=x part=1/1 -->",
        "<!-- countyforge-plan-input issue=18 input=x part=1/1 -->",
        "countyforge-plan-input:v1 issue=18 input=x part=1/1",
    ):
        assert MARKER.search(body) is None
    assert MARKER.search("<!-- countyforge-plan-input:v1 issue=18 input=x part=1/1 -->")


def test_a_comment_posted_after_the_trigger_is_not_part_of_the_package() -> None:
    parts = [*_four_parts(), _part(5, 5, "late", comment_id=99_999)]
    collected = collect_decision_input(parts, issue_number=18, comment_id_upper_bound=1004)
    assert [part.part for part in collected.parts] == [1, 2, 3, 4]
    assert any(item["reason"] == "posted_after_trigger" for item in collected.excluded)


# --------------------------------------------------------------------------
# Defects 2, 3 — capability resolution and decision approval
# --------------------------------------------------------------------------


def test_8_the_affected_capability_resolves_to_the_domain_capability() -> None:
    evidence = _validate(_result(), required_cross_issues=[43])
    assert evidence["affected_capability"] == "collin-cad-source-contract"
    assert evidence["implementation_eligibility"] is False


def test_9_the_planner_capability_is_never_a_fallback() -> None:
    """PR #46 filed a Collin change against `issue-to-openspec-planning`."""

    document = _result(affected_capabilities=[])
    assert _refusal(document, required_cross_issues=[43]) == "affected_capability_ambiguous"
    document = _result(
        affected_capabilities=[
            {"name": "collin-cad-source-contract", "change_type": "ADDED"},
            {"name": "issue-to-openspec-planning", "change_type": "MODIFIED"},
        ]
    )
    assert _refusal(document, required_cross_issues=[43]) == "affected_capability_ambiguous"


def test_a_modified_capability_must_already_be_declared(tmp_path: Path) -> None:
    document = _result(
        affected_capabilities=[{"name": "never-declared", "change_type": "MODIFIED"}]
    )
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_semantics(document, contract_root=tmp_path, required_cross_issues=[43])
    assert raised.value.details["reason"] == "affected_capability_not_declared"


def test_20_implementation_eligibility_remains_false() -> None:
    assert (
        _refusal(_result(implementation_eligibility=True), required_cross_issues=[43])
        == "implementation_eligibility_not_false"
    )
    decisions = _result()["planning_decisions"]
    decisions[0]["requires_human_merge"] = False
    assert (
        _refusal(_result(planning_decisions=decisions), required_cross_issues=[43])
        == "decision_bypasses_human_merge"
    )


def test_a_blocked_decision_must_be_reflected_in_the_plan_status() -> None:
    decisions = _result()["planning_decisions"]
    decisions[0]["status"] = "blocked"
    assert (
        _refusal(_result(planning_decisions=decisions), required_cross_issues=[43])
        == "blocked_decision_not_reflected_in_status"
    )


# --------------------------------------------------------------------------
# Defect 4 — concrete requirements
# --------------------------------------------------------------------------

_PLACEHOLDER = {
    "id": "generic",
    "title": "Generic acceptance",
    "normative_rule": "The implementation SHALL satisfy this criterion.",
    "scenarios": [
        {
            "name": "Acceptance",
            "given": ["a completed implementation"],
            "when": "the implementation is evaluated",
            "then": ["the criterion is demonstrably satisfied"],
        }
    ],
    "source_ids": ["aa11aa11aa11aa11aa11aa11"],
}


def test_10_generic_placeholder_requirements_fail() -> None:
    """Exactly what trusted materialization used to emit for every criterion."""

    assert (
        _refusal(_result(requirements=[_PLACEHOLDER]), required_cross_issues=[43])
        == "requirement_placeholder_text"
    )


def test_a_requirement_without_a_normative_verb_fails() -> None:
    requirement = copy.deepcopy(_PLACEHOLDER)
    requirement["normative_rule"] = "The adapter decodes values correctly and quickly."
    assert (
        _refusal(_result(requirements=[requirement]), required_cross_issues=[43])
        == "requirement_not_normative"
    )


def test_identical_scenarios_across_requirements_fail() -> None:
    first = copy.deepcopy(_result()["requirements"][0])
    second = copy.deepcopy(first)
    second["id"] = "second-requirement"
    second["title"] = "A different obligation entirely"
    assert (
        _refusal(_result(requirements=[first, second]), required_cross_issues=[43])
        == "scenario_duplicated_across_requirements"
    )


def test_11_concrete_normative_rules_and_scenarios_are_accepted() -> None:
    evidence = _validate(_result(), required_cross_issues=[43])
    assert evidence["requirement_count"] == 5
    rules = [item["normative_rule"] for item in _result()["requirements"]]
    assert all(any(word in rule for word in ("SHALL", "MUST")) for rule in rules)
    assert all("satisfy this criterion" not in rule for rule in rules)


# --------------------------------------------------------------------------
# Defect 5 — task write scope
# --------------------------------------------------------------------------


def _tasks_with_paths(paths: list[str]) -> list[dict[str, Any]]:
    tasks = _result()["task_slices"]
    tasks[0]["write_paths"] = paths
    return tasks


def test_12_the_broad_path_list_pr_46_emitted_fails() -> None:
    broad = ["libs", "services", "dags", "docs", "tools", "tests", "README.md", "CONTRIBUTING.md"]
    assert (
        _refusal(_result(task_slices=_tasks_with_paths(broad)), required_cross_issues=[43])
        == "task_path_too_broad"
    )


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/etc/passwd", "task_path_not_relative"),
        ("libs/../../etc", "task_path_escapes_repository"),
        ("libs/**", "task_path_wildcard"),
        (".github/workflows/", "task_path_forbidden"),
        (".ai/policies/", "task_path_forbidden"),
    ],
)
def test_13_paths_outside_the_declared_scope_or_the_trust_boundary_fail(
    path: str, reason: str
) -> None:
    assert (
        _refusal(_result(task_slices=_tasks_with_paths([path])), required_cross_issues=[43])
        == reason
    )


def test_a_task_path_outside_the_declared_scope_fails() -> None:
    assert (
        _refusal(
            _result(task_slices=_tasks_with_paths(["libs/property-tax-domain/"])),
            required_cross_issues=[43],
        )
        == "task_path_outside_declared_scope"
    )


def test_14_the_collin_task_paths_pass() -> None:
    evidence = _validate(_result(), required_cross_issues=[43])
    assert evidence["task_count"] == 4
    allowed = {
        "libs/property-tax-adapters/",
        "tests/",
        "docs/engineering/",
        "docs/sources/",
    }
    for task in _result()["task_slices"]:
        assert set(task["write_paths"]) <= allowed
    forbidden = {
        "services/",
        "dags/",
        "tools/",
        ".github/",
        ".ai/",
        "README.md",
        "CONTRIBUTING.md",
        "libs/property-tax-domain/",
        "libs/property-tax-application/",
    }
    for task in _result()["task_slices"]:
        assert not set(task["write_paths"]) & forbidden


# --------------------------------------------------------------------------
# Defect 6 — prerequisites
# --------------------------------------------------------------------------


def test_the_collin_prerequisite_ordering_is_exactly_as_specified() -> None:
    ordering = {task["task_id"]: task["prerequisites"] for task in _result()["task_slices"]}
    assert ordering == {
        "1.1": ["D1"],
        "1.2": ["D2", "D4"],
        "1.3": ["1.1", "1.2", "D3"],
        "1.4": ["1.1", "1.2", "1.3"],
    }
    _validate(_result(), required_cross_issues=[43])


def test_15_a_missing_prerequisite_reference_fails() -> None:
    tasks = _result()["task_slices"]
    tasks[0]["prerequisites"] = ["D9"]
    assert (
        _refusal(_result(task_slices=tasks), required_cross_issues=[43])
        == "prerequisite_decision_unknown"
    )
    tasks = _result()["task_slices"]
    tasks[3]["prerequisites"] = ["1.1", "1.2", "1.3", "9.9"]
    assert (
        _refusal(_result(task_slices=tasks), required_cross_issues=[43])
        == "prerequisite_task_unknown"
    )


def test_16_cyclic_prerequisites_fail() -> None:
    tasks = _result()["task_slices"]
    tasks[0]["prerequisites"] = ["1.4"]
    reason = _refusal(_result(task_slices=tasks), required_cross_issues=[43])
    # A forward reference is caught as ordering before it can close a cycle;
    # both are refusals, and neither is silently accepted.
    assert reason in {"prerequisite_not_earlier", "prerequisite_cycle"}


def test_a_true_cycle_is_rejected_by_the_graph_walk() -> None:
    from countyforge_github.planning_semantics import _reject_cycles

    with pytest.raises(ControlPlaneError) as raised:
        _reject_cycles({"1.1": ["1.2"], "1.2": ["1.3"], "1.3": ["1.1"]})
    assert raised.value.details["reason"] == "prerequisite_cycle"


def test_17_prose_naming_a_dependency_the_metadata_omits_fails() -> None:
    """PR #46 emitted `prerequisites=-` for tasks whose prose named D1."""

    tasks = _result()["task_slices"]
    tasks[2]["prerequisites"] = []
    reason = _refusal(_result(task_slices=tasks), required_cross_issues=[43])
    assert reason == "prerequisite_named_in_prose_only"

    tasks = _result()["task_slices"]
    tasks[0]["description"] = "After D1 and D2 are accepted, decode the packed value exactly."
    tasks[0]["prerequisites"] = ["D1"]
    assert (
        _refusal(_result(task_slices=tasks), required_cross_issues=[43])
        == "prerequisite_named_in_prose_only"
    )


# --------------------------------------------------------------------------
# Defect 7 — cross-issue boundary
# --------------------------------------------------------------------------


def test_18_the_issue_43_boundary_is_required() -> None:
    assert (
        _refusal(_result(cross_issue_dependencies=[]), required_cross_issues=[43])
        == "cross_issue_boundary_absent"
    )
    dependency = _result()["cross_issue_dependencies"]
    dependency[0]["boundary"] = []
    with pytest.raises(ControlPlaneError):
        _validate(_result(cross_issue_dependencies=dependency), required_cross_issues=[43])


def test_19_a_task_conflicting_with_the_boundary_fails() -> None:
    tasks = _result()["task_slices"]
    tasks[0]["description"] = (
        "Decode the packed value and wire the Collin DAG integration into the scheduler."
    )
    assert (
        _refusal(_result(task_slices=tasks), required_cross_issues=[43])
        == "task_conflicts_with_cross_issue_boundary"
    )

    tasks = _result()["task_slices"]
    tasks[1]["description"] = (
        "Add the structural fingerprint and a shared vendor-neutral source record for all counties."
    )
    assert (
        _refusal(_result(task_slices=tasks), required_cross_issues=[43])
        == "task_conflicts_with_cross_issue_boundary"
    )


def test_an_unresolved_decision_is_not_delegated_to_implementation() -> None:
    """A blocked plan may depend on a blocked decision; it may not hide it."""

    decisions = _result()["planning_decisions"]
    decisions[0]["status"] = "blocked"
    # Task 1.1 depends on D1, D1 is blocked, and nothing records it as a blocker.
    hidden = _result(planning_decisions=decisions, status="blocked", blocked_reasons=[])
    assert _refusal(hidden, required_cross_issues=[43]) == (
        "unresolved_decision_delegated_to_implementation"
    )
    # Naming the blocker is what makes the dependency honest.
    declared = _result(
        planning_decisions=decisions,
        status="blocked",
        blocked_reasons=["D1 is not accepted yet."],
    )
    assert _validate(declared, required_cross_issues=[43])["implementation_eligibility"] is False


# --------------------------------------------------------------------------
# Defect 8 — the gate itself
# --------------------------------------------------------------------------


def test_the_disposition_is_stable_and_publication_fails_closed() -> None:
    assert SEMANTIC_DISPOSITION == "planning_semantic_validation_failed"
    with pytest.raises(ControlPlaneError) as raised:
        _validate(_result(requirements=[_PLACEHOLDER]), required_cross_issues=[43])
    assert raised.value.code == "planning_semantic_validation_failed"
    assert raised.value.exit_code == 2


def test_a_v1_planning_result_is_readable_but_not_republishable() -> None:
    """Migration: old results are not silently upgraded into new ones."""

    assert _refusal(_result(contract_version=1)) == "contract_version_unsupported"
