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
    MAX_MARKED_COMMENT_BYTES,
    MAX_PART_BYTES,
    assert_unedited_since_trigger,
    collect_decision_input,
    decision_marker,
)
from countyforge_github.errors import ControlPlaneError
from countyforge_github.planning import validate_planning_result
from countyforge_github.planning_scope import POLICY_PATH, resolve_planning_scope
from countyforge_github.planning_semantics import (
    SEMANTIC_DISPOSITION,
    validate_planning_semantics,
)
from countyforge_test_support import controlled_contract_root

FIXTURE = Path("tools/countyforge-github/tests/fixtures/planning-result-collin-issue-18.json")


CONTRACT_ROOT = controlled_contract_root()
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


def _collect(comments: list[dict[str, Any]], **overrides: Any):
    """Collect with an authorized maintainer unless a test says otherwise.

    `authorized_author_ids` has no default in production: an empty allowlist
    authorizes nobody, so a test that omitted it would silently assert on an
    empty package rather than on the behaviour it names.
    """

    overrides.setdefault("authorized_author_ids", [AUTHOR_ID])
    return collect_decision_input(comments, **overrides)


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
    collected = _collect(_four_parts(), issue_number=18)
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
        _collect(parts, issue_number=18)
    assert raised.value.code == INCOMPLETE
    assert raised.value.details["reason"] == "missing_part"
    assert raised.value.details["missing"] == [3]


def test_3_a_duplicate_part_number_fails() -> None:
    parts = [*_four_parts(), _part(2, 4, "a second D2", comment_id=2000)]
    with pytest.raises(ControlPlaneError) as raised:
        _collect(parts, issue_number=18)
    assert raised.value.details["reason"] == "duplicate_part"


def test_4_a_part_edited_after_the_trigger_fails_closed() -> None:
    bound = _collect(_four_parts(), issue_number=18)
    provenance = [part.provenance() for part in bound.parts]
    edited = _four_parts()
    edited[2]["body"] = edited[2]["body"] + "\n\nreconsidered after the run started"
    edited[2]["updated_at"] = "2026-07-31T09:00:00Z"
    reread = _collect(edited, issue_number=18)
    with pytest.raises(ControlPlaneError) as raised:
        assert_unedited_since_trigger(reread, provenance)
    assert raised.value.details["reason"] == "part_edited_after_trigger"
    assert raised.value.details["observed_updated_at"] == "2026-07-31T09:00:00Z"


def test_5_an_oversized_part_is_excluded_with_a_reason_never_truncated() -> None:
    parts = _four_parts()
    parts[1] = _part(2, 4, "x" * 30_000, comment_id=1002)
    with pytest.raises(ControlPlaneError) as raised:
        _collect(parts, issue_number=18, max_part_bytes=24_000)
    # Excluded, so the package is incomplete; it is never half-included.
    assert raised.value.details["reason"] == "missing_part"
    partial = _collect([parts[1]], issue_number=18, max_part_bytes=24_000)
    assert partial.parts == []
    assert partial.excluded[0]["reason"] == EXCLUDED_TOO_LARGE
    assert partial.excluded[0]["byte_length"] == 30_000


def test_6_the_total_decision_budget_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    parts = [_part(index, 4, "y" * 5_000, comment_id=1000 + index) for index in range(1, 5)]
    with pytest.raises(ControlPlaneError) as raised:
        _collect(parts, issue_number=18, max_total_bytes=10_000)
    assert raised.value.details["reason"] == "total_budget_exceeded"
    assert raised.value.details["total_byte_length"] == 20_000


def test_7_bot_status_and_command_comments_are_never_decision_content() -> None:
    parts = _four_parts()
    bot = _part(1, 1, "status", comment_id=9001, input_id="bot", author_id=41898282)
    bot["user"]["type"] = "Bot"
    command = _part(1, 1, "/countyforge plan", comment_id=9002, input_id="cmd")
    collected = _collect([*parts, bot, command], issue_number=18, trusted_bot_id=41898282)
    assert collected.input_id == "collin-1"
    assert len(collected.parts) == 4
    reasons = {item["reason"] for item in collected.excluded}
    assert "command_comment_not_decision_content" in reasons
    assert 9001 not in {item.get("comment_id") for item in collected.excluded}


def test_an_unauthorized_author_and_a_foreign_issue_are_excluded() -> None:
    parts = _four_parts()
    stranger = _part(1, 1, "decision", comment_id=8001, input_id="other", author_id=999)
    foreign = _part(1, 1, "decision", comment_id=8002, input_id="foreign", issue=43)
    collected = _collect([*parts, stranger, foreign], issue_number=18)
    reasons = {item["reason"] for item in collected.excluded}
    assert reasons >= {"author_not_authorized", "issue_number_mismatch"}
    assert len(collected.parts) == 4


def test_an_older_decision_package_is_recorded_as_superseded_not_merged() -> None:
    older = [
        _part(index, 2, f"old D{index}", comment_id=500 + index, input_id="collin-0")
        for index in range(1, 3)
    ]
    collected = _collect([*older, *_four_parts()], issue_number=18)
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
    collected = _collect(parts, issue_number=18, comment_id_upper_bound=1004)
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
        for path in task["write_paths"]:
            # Task paths name files now, so containment is by prefix rather
            # than by set membership against the directory ceiling.
            assert any(path.startswith(prefix) for prefix in allowed), path
            assert not path.endswith("/"), path
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


# --------------------------------------------------------------------------
# Review 4840228618 — the ceiling and the boundary must be trusted, and must
# apply on the live call path, not only when a test passes them by hand.
# --------------------------------------------------------------------------


def test_the_live_path_refuses_a_narrow_but_unapproved_write_scope(tmp_path: Path) -> None:
    """Blocker 1: the model authored both sides of the subset check.

    A denylist stops `libs`; it cannot tell that `services/foo/` is the wrong
    narrow scope. The ceiling now comes from committed policy, so a plan that
    declares an unapproved scope is refused through `validate_planning_result`
    with no `declared_scope` argument -- the way every live caller invokes it.
    """

    for scope in (
        ["services/collin-api/"],
        ["libs/property-tax-domain/"],
        ["libs/property-tax-application/"],
        ["dags/collin/"],
    ):
        document = _result(declared_write_scope=scope)
        for task in document["task_slices"]:
            task["write_paths"] = list(scope)
        with pytest.raises(ControlPlaneError) as raised:
            # No declared_scope: exactly the live signature.
            validate_planning_result(document, contract_root=CONTRACT_ROOT)
        assert raised.value.code == SEMANTIC_DISPOSITION
        assert raised.value.details["reason"] == "declared_scope_exceeds_caller_ceiling"


def test_the_live_path_requires_the_issue_43_boundary(tmp_path: Path) -> None:
    """Blocker 2: `required_cross_issues` defaulted to empty in production."""

    document = _result(cross_issue_dependencies=[])
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert raised.value.details["reason"] == "cross_issue_boundary_absent"
    assert raised.value.details["issue"] == 43


def test_the_collin_plan_passes_the_live_path_with_no_hand_passed_scope() -> None:
    scope = validate_planning_result(_result(), contract_root=CONTRACT_ROOT)
    assert scope["resolved_from"] == "issue:18"
    assert scope["required_cross_issues"] == [43]
    assert "libs/property-tax-adapters/" in scope["write_roots"]
    # Bound into provenance, so the ceiling a run was judged against is auditable.
    assert scope["policy_path"] == POLICY_PATH


def test_the_trusted_ceiling_comes_from_committed_policy_not_from_the_plan() -> None:
    resolved = resolve_planning_scope(
        CONTRACT_ROOT, issue_number=18, capability="collin-cad-source-contract"
    )
    assert resolved.resolved_from == "issue:18"
    assert set(resolved.write_roots) == {
        "libs/property-tax-adapters/",
        "docs/engineering/",
        "docs/sources/",
    }
    assert resolved.required_cross_issues == (43,)
    # The issue a maintainer filed outranks the capability the model chose.
    conflicting = resolve_planning_scope(
        CONTRACT_ROOT, issue_number=18, capability="dallas-cad-source-contract"
    )
    assert conflicting.required_cross_issues == (43,)


def test_an_unknown_issue_and_capability_collapse_to_the_change_directory() -> None:
    """Fail closed: an unpoliced plan may write its own change and nothing else."""

    resolved = resolve_planning_scope(
        CONTRACT_ROOT, issue_number=9_999, capability="never-declared", change_name="add-thing"
    )
    assert resolved.resolved_from == "default"
    assert resolved.write_roots == ("openspec/changes/add-thing/",)
    assert resolved.required_cross_issues == ()


def test_a_missing_scope_policy_refuses_rather_than_defaulting_open(tmp_path: Path) -> None:
    with pytest.raises(ControlPlaneError) as raised:
        resolve_planning_scope(tmp_path, issue_number=18)
    assert raised.value.code == "planning_scope_policy_missing"


def test_the_materializer_binds_the_resolved_ceiling_into_its_manifest(tmp_path: Path) -> None:
    import shutil

    from countyforge_github.planning import materialize_plan

    shutil.copytree(CONTRACT_ROOT / ".ai", tmp_path / ".ai")
    document = _result()
    document["declared_write_scope"] = ["libs/property-tax-adapters/"]
    for task in document["task_slices"]:
        task["write_paths"] = ["libs/property-tax-adapters/src/collin.py"]
    manifest = materialize_plan(
        document,
        publication_root=tmp_path,
        issue_number=18,
        run_id="scope-provenance",
    )
    assert manifest["planning_scope"]["resolved_from"] == "issue:18"
    assert manifest["planning_scope"]["required_cross_issues"] == [43]
    assert manifest["implementation_eligibility"] is False


def test_a_four_part_decision_package_survives_packet_construction(tmp_path: Path) -> None:
    """The live path that clipped issue #18's decisions at 4,000 characters."""

    import subprocess

    from countyforge_github.planning import build_planning_packet

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    long_bodies = [f"## D{index} — " + ("decision detail. " * 500) for index in range(1, 5)]
    comments = [
        _part(index, 4, long_bodies[index - 1], comment_id=1000 + index) for index in range(1, 5)
    ]
    assert all(len(body.encode()) > 4_000 for body in long_bodies)

    info = build_planning_packet(
        trigger={
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
            # Decision content counts only from the actor the trigger authorized.
            "actor": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        },
        issue={
            "number": 18,
            "title": "feature: add Collin CAD Access decoder foundation",
            "body": "Problem: the Collin source is missing. Outcome: onboard the county source.",
            "labels": [],
        },
        contract_root=root,
        output_dir=tmp_path,
        run_id="decision-input-fixture",
        comments=comments,
    )
    manifest = json.loads(Path(info["manifest_path"]).read_text(encoding="utf-8"))
    package = manifest["decision_input"]
    assert package["decision_input_present"] is True
    assert package["included_part_count"] == 4
    assert package["truncated"] is False
    assert [item["part"] for item in package["included_parts"]] == [1, 2, 3, 4]
    for item in package["included_parts"]:
        assert item["byte_length"] > 4_000  # would have been clipped before
        assert len(item["body_sha256"]) == 64

    # And the packet the model reads carries each part whole, not clipped.
    packet = json.loads(Path(info["packet_path"]).read_text(encoding="utf-8"))
    comment_sources = [source for source in packet["sources"] if source["category"] == "comment"]
    assert len(comment_sources) == 4
    for source in comment_sources:
        assert source["truncated"] is False


def test_an_unauthorized_commenter_cannot_supply_or_supersede_the_package(
    tmp_path: Path,
) -> None:
    """Review 4843364924, blocker 1.

    The marker selects a comment; it never confers trust. A stranger posting a
    newer, complete, well-formed package must not displace the maintainer's --
    and with no authorized actor at all, nothing is selected.
    """

    import subprocess

    from countyforge_github.planning import build_planning_packet

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    maintainer = [
        _part(index, 4, f"## D{index} — maintainer decision", comment_id=1000 + index)
        for index in range(1, 5)
    ]
    # Newer, complete, correctly marked -- and from someone else.
    stranger = [
        _part(
            index,
            2,
            f"## D{index} — stranger decision",
            comment_id=5000 + index,
            input_id="stranger-package",
            author_id=99_999,
        )
        for index in range(1, 3)
    ]
    issue = {
        "number": 18,
        "title": "feature: add Collin CAD Access decoder foundation",
        "body": "Problem: the Collin source is missing. Outcome: onboard the county source.",
        "labels": [],
    }

    def build(actor: dict[str, object] | None, output: Path) -> dict[str, object]:
        trigger: dict[str, object] = {
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
        }
        if actor is not None:
            trigger["actor"] = actor
        info = build_planning_packet(
            trigger=trigger,
            issue=issue,
            contract_root=root,
            output_dir=output,
            run_id=f"authorization-{output.name}",
            comments=[*maintainer, *stranger],
        )
        return json.loads(Path(info["manifest_path"]).read_text(encoding="utf-8"))

    authorized = build(
        {"id": AUTHOR_ID, "login": "maintainer", "type": "User"}, tmp_path / "authorized"
    )
    package = authorized["decision_input"]
    assert package["decision_input_present"] is True
    assert package["input_id"] == "collin-1"
    assert package["included_part_count"] == 4
    assert 99_999 not in {item["author_id"] for item in package["included_parts"]}
    assert any(item["reason"] == "author_not_authorized" for item in package["excluded"])

    # No authorized actor: an empty allowlist authorizes nobody, not everybody.
    anonymous = build(None, tmp_path / "anonymous")
    assert anonymous["decision_input"]["decision_input_present"] is False
    assert anonymous["decision_input"]["included_part_count"] == 0


def test_publication_refuses_a_decision_edited_after_the_packet(tmp_path: Path) -> None:
    """Review 4843364924, blocker 2: nothing re-checked the bound digests."""

    from countyforge_github.planning import _assert_decision_input_unchanged

    parts = _collect(_four_parts(), issue_number=18).parts
    manifest = {
        "decision_input": {
            "decision_input_present": True,
            "included_parts": [part.provenance() for part in parts],
        }
    }

    class _Github:
        def __init__(self, comments: list[dict[str, Any]]) -> None:
            self._comments = comments

        def list_comments(self, repository: str, target_number: int) -> list[dict[str, Any]]:
            assert target_number == 18
            return self._comments

    # Unchanged: publication proceeds.
    _assert_decision_input_unchanged(
        _Github(_four_parts()),
        repository="TruPryce/property-tax-data-platform",
        issue_number=18,
        manifest=manifest,
    )

    edited = _four_parts()
    edited[2]["body"] += "\n\nreconsidered after the packet was built"
    edited[2]["updated_at"] = "2026-08-02T09:00:00Z"
    with pytest.raises(ControlPlaneError) as raised:
        _assert_decision_input_unchanged(
            _Github(edited),
            repository="TruPryce/property-tax-data-platform",
            issue_number=18,
            manifest=manifest,
        )
    assert raised.value.details["reason"] == "part_edited_after_trigger"

    # A deleted part is equally disqualifying.
    with pytest.raises(ControlPlaneError) as raised:
        _assert_decision_input_unchanged(
            _Github(_four_parts()[:3]),
            repository="TruPryce/property-tax-data-platform",
            issue_number=18,
            manifest=manifest,
        )
    assert raised.value.code == "incomplete_decision_input"


def test_an_unreadable_comment_list_refuses_rather_than_skipping_the_check() -> None:
    from countyforge_github.planning import _assert_decision_input_unchanged

    parts = _collect(_four_parts(), issue_number=18).parts

    class _Broken:
        def list_comments(self, repository: str, target_number: int) -> list[dict[str, Any]]:
            raise RuntimeError("transport failure")

    with pytest.raises(ControlPlaneError) as raised:
        _assert_decision_input_unchanged(
            _Broken(),
            repository="TruPryce/property-tax-data-platform",
            issue_number=18,
            manifest={
                "decision_input": {
                    "decision_input_present": True,
                    "included_parts": [part.provenance() for part in parts],
                }
            },
        )
    assert raised.value.code == "decision_input_unverifiable"


def test_publication_invokes_the_edit_check_before_the_first_git_object() -> None:
    """A tested helper nobody calls proves nothing; pin the call site.

    The behavioural proof is `test_publication_refuses_a_decision_edited_after_
    the_packet`; this asserts the live publisher reaches it, and reaches it
    before any Git object exists.
    """

    source = Path("tools/countyforge-github/src/countyforge_github/planning.py").read_text(
        encoding="utf-8"
    )
    body = source[source.index("\ndef publish_plan(") :]
    call = body.index("_assert_decision_input_unchanged(")
    for stage in ("create_blobs", "create_tree", "create_commit", "create_ref"):
        assert call < body.index(f'progress.enter("{stage}")'), stage
    # And after the packet/manifest have been validated, so it reads bound facts.
    assert body.index('progress.enter("validate_provenance")') < call


# --------------------------------------------------------------------------
# Review 4845338099 — the marker must open the comment, not appear inside it.
# --------------------------------------------------------------------------


_MARKER_LINE = "<!-- countyforge-plan-input:v1 issue=18 input=collin-1 part=1/1 -->"


def test_the_marker_must_open_the_comment() -> None:
    """First line only. Leading blank lines carry no content, so they are fine."""

    assert decision_marker(f"{_MARKER_LINE}\n\n## D1 — body") is not None
    assert decision_marker(f"\n\n{_MARKER_LINE}\n\n## D1 — body") is not None


def test_leading_prose_before_the_marker_is_not_a_decision_part() -> None:
    """The payload starts after the marker, so a mid-body marker would discard
    everything before it -- silently, which is the failure this contract exists
    to remove. Such a comment is ordinary evidence instead."""

    body = f"Some earlier thinking that must not be thrown away.\n\n{_MARKER_LINE}\n\n## D1 — body"
    assert decision_marker(body) is None
    collected = _collect(
        [
            {
                "id": 7001,
                "body": body,
                "updated_at": "2026-08-01T00:00:00Z",
                "user": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
            }
        ],
        issue_number=18,
    )
    assert collected.parts == []
    assert collected.excluded == []


def test_a_marker_quoted_inside_a_fenced_example_is_not_a_decision_part() -> None:
    """Documentation and review comments quote this marker routinely."""

    body = (
        "Here is how the convention works:\n\n"
        "```markdown\n"
        f"{_MARKER_LINE}\n"
        "```\n\n"
        "Please use it next time."
    )
    assert decision_marker(body) is None
    collected = _collect(
        [
            {
                "id": 7002,
                "body": body,
                "updated_at": "2026-08-01T00:00:00Z",
                "user": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
            }
        ],
        issue_number=18,
    )
    assert collected.parts == []


def test_every_path_uses_the_same_marker_predicate(tmp_path: Path) -> None:
    """Fingerprinting, collection, and packet construction must agree.

    If one path treated a quoted marker as a decision part, that comment would be
    bounded at 24,000 bytes in the fingerprint while being ordinary evidence in
    the packet -- two descriptions of one comment.
    """

    import subprocess

    from countyforge_github import planning
    from countyforge_github.planning import build_planning_packet

    # No path may reach for an unanchored search of its own.
    for module in (planning, __import__("countyforge_github.decision_input", fromlist=["x"])):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "MARKER.search" not in source, module.__name__

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    quoted = {
        "id": 7003,
        "body": f"As a reminder, the marker looks like:\n\n{_MARKER_LINE}\n",
        "updated_at": "2026-08-01T00:00:00Z",
        "user": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
    }
    real = _part(1, 1, "## D1 — the actual decision", comment_id=7004)

    info = build_planning_packet(
        trigger={
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
            "actor": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        },
        issue={
            "number": 18,
            "title": "feature: add Collin CAD Access decoder foundation",
            "body": "Problem: the Collin source is missing. Outcome: onboard the county source.",
            "labels": [],
        },
        contract_root=root,
        output_dir=tmp_path,
        run_id="marker-consistency",
        comments=[quoted, real],
    )
    package = json.loads(Path(info["manifest_path"]).read_text(encoding="utf-8"))["decision_input"]
    assert package["included_part_count"] == 1
    assert [item["comment_id"] for item in package["included_parts"]] == [7004]
    assert 7003 not in {item.get("comment_id") for item in package["excluded"]}


# --------------------------------------------------------------------------
# Review 4845xxxxx — one byte bound, one strict policy, one narrow issue scope.
# --------------------------------------------------------------------------


def _packet_with_payload(tmp_path: Path, payload: str, *, run: str) -> dict[str, Any]:
    import subprocess

    from countyforge_github.planning import build_planning_packet

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    comment = {
        "id": 1001,
        "body": f"{_MARKER_LINE}\n\n{payload}",
        "updated_at": "2026-08-01T00:00:00Z",
        "user": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
    }
    info = build_planning_packet(
        trigger={
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
            "actor": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        },
        issue={
            "number": 18,
            "title": "feature: add Collin CAD Access decoder foundation",
            "body": "Problem: the Collin source is missing. Outcome: onboard the county source.",
            "labels": [],
        },
        contract_root=root,
        output_dir=tmp_path / run,
        run_id=run,
        comments=[comment],
    )
    return {
        "manifest": json.loads(Path(info["manifest_path"]).read_text(encoding="utf-8")),
        "packet": json.loads(Path(info["packet_path"]).read_text(encoding="utf-8")),
    }


def test_a_part_at_the_exact_documented_bound_reaches_the_model_whole(
    tmp_path: Path,
) -> None:
    """The collector accepted 24,000 bytes and the packet schema capped content
    at 20,000 characters, so a part inside the documented limit died later under
    an unrelated schema error -- neither carried nor excluded. One bound now."""

    payload = "x" * MAX_PART_BYTES
    result = _packet_with_payload(tmp_path, payload, run="exact-bound")
    package = result["manifest"]["decision_input"]
    assert package["included_part_count"] == 1
    assert package["included_parts"][0]["byte_length"] == MAX_PART_BYTES
    assert package["truncated"] is False
    source = next(item for item in result["packet"]["sources"] if item["category"] == "comment")
    assert source["truncated"] is False
    assert payload in source["content"]


def test_a_part_one_byte_over_the_bound_is_excluded_with_the_stable_reason(
    tmp_path: Path,
) -> None:
    payload = "x" * (MAX_PART_BYTES + 1)
    result = _packet_with_payload(tmp_path, payload, run="one-over")
    package = result["manifest"]["decision_input"]
    assert package["decision_input_present"] is False
    assert package["excluded"][0]["reason"] == EXCLUDED_TOO_LARGE
    assert package["excluded"][0]["byte_length"] == MAX_PART_BYTES + 1


def test_a_multibyte_part_is_bounded_by_bytes_not_characters(tmp_path: Path) -> None:
    """`é` is two bytes: half as many characters fit, and the packet must still
    hold the whole part rather than failing on its character bound."""

    payload = "é" * (MAX_PART_BYTES // 2)
    assert len(payload.encode("utf-8")) == MAX_PART_BYTES
    result = _packet_with_payload(tmp_path, payload, run="multibyte")
    package = result["manifest"]["decision_input"]
    assert package["included_part_count"] == 1
    assert package["included_parts"][0]["byte_length"] == MAX_PART_BYTES
    source = next(item for item in result["packet"]["sources"] if item["category"] == "comment")
    assert source["truncated"] is False
    assert payload in source["content"]


def test_the_packet_source_bound_admits_a_maximum_decision_part() -> None:
    """Pin the relationship so the two bounds cannot drift apart again."""

    schema = json.loads(
        Path(".ai/schemas/countyforge-planning-packet.schema.json").read_text(encoding="utf-8")
    )
    content_max = schema["properties"]["sources"]["items"]["properties"]["content"]["maxLength"]
    # Marker, the `COMMENT (untrusted):\n` prefix, and separating newlines ride
    # along with the payload.  Bytes >= characters for UTF-8, so bounding the
    # payload in bytes bounds its character length too.
    overhead = len("COMMENT (untrusted):\n") + 8
    assert content_max >= MAX_MARKED_COMMENT_BYTES + overhead


# --- Strict trusted policy ------------------------------------------------


def _policy_root(tmp_path: Path, policy: dict[str, Any]) -> Path:
    import shutil

    root = tmp_path / "contract"
    (root / ".ai/policies").mkdir(parents=True, exist_ok=True)
    (root / ".ai/schemas").mkdir(parents=True, exist_ok=True)
    (root / POLICY_PATH).write_text(json.dumps(policy), encoding="utf-8")
    shutil.copy(
        Path(".ai/schemas/countyforge-planning-scope.schema.json"),
        root / ".ai/schemas/countyforge-planning-scope.schema.json",
    )
    return root


_VALID_POLICY: dict[str, Any] = {
    "contract_version": 1,
    "default_write_roots": [],
    "issues": {
        "18": {
            "write_roots": ["libs/property-tax-adapters/"],
            "required_cross_issues": [43],
        }
    },
}


def test_the_trusted_policy_is_validated_strictly(tmp_path: Path) -> None:
    scope = resolve_planning_scope(_policy_root(tmp_path / "ok", _VALID_POLICY), issue_number=18)
    assert scope.required_cross_issues == (43,)


@pytest.mark.parametrize(
    ("mutation", "label"),
    [
        ({"contract_version": 999}, "unsupported_version"),
        ({"unknown_field": True}, "unknown_field"),
        ({"issues": {"18": {"write_roots": ["/etc/passwd"]}}}, "absolute_root"),
        ({"issues": {"18": {"write_roots": ["libs/../../etc"]}}}, "escaping_root"),
        (
            {"issues": {"18": {"write_roots": ["libs/"], "required_cross_issues": ["43"]}}},
            "string_cross_issue",
        ),
        (
            {"issues": {"18": {"write_roots": ["libs/"], "unexpected": 1}}},
            "unknown_entry_field",
        ),
        ({"issues": {"18": {"required_cross_issues": [43]}}}, "missing_write_roots"),
    ],
)
def test_an_invalid_policy_fails_closed_rather_than_dropping_the_requirement(
    tmp_path: Path, mutation: dict[str, Any], label: str
) -> None:
    """`"43"` as a string was silently discarded, which *removed* the issue-43
    requirement. A policy that cannot be trusted must refuse, not degrade."""

    policy = {**copy.deepcopy(_VALID_POLICY), **copy.deepcopy(mutation)}
    with pytest.raises(ControlPlaneError) as raised:
        resolve_planning_scope(_policy_root(tmp_path / label, policy), issue_number=18)
    assert raised.value.code == "planning_scope_policy_invalid"


# --- Issue 18 scope -------------------------------------------------------


def test_issue_18_does_not_authorize_the_root_test_tree() -> None:
    """The adapter suite is at `libs/property-tax-adapters/tests/`, inside the
    adapter root. Root `tests/` holds repository architecture, infrastructure,
    and artifact tests a county decoder has no business rewriting."""

    policy = json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))
    for entry in (policy["issues"]["18"], policy["capabilities"]["collin-cad-source-contract"]):
        assert "tests/" not in entry["write_roots"]
    assert Path("libs/property-tax-adapters/tests").is_dir()

    document = _result()
    assert "tests/" not in document["declared_write_scope"]
    for task in document["task_slices"]:
        assert "tests/" not in task["write_paths"]
    # And the narrowed fixture still passes the live gate.
    scope = validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert "tests/" not in scope["write_roots"]


def test_a_task_reaching_the_root_test_tree_is_now_refused() -> None:
    document = _result()
    document["task_slices"][0]["write_paths"] = [
        "libs/property-tax-adapters/src/collin.py",
        "tests/test_root.py",
    ]
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert raised.value.details["reason"] == "task_path_outside_declared_scope"


# --------------------------------------------------------------------------
# Run 30836072011 — the plan lane spent its whole 1,800-second budget having
# emitted only `thread.started` and `turn.started`.
# --------------------------------------------------------------------------


def test_the_plan_lane_reasoning_effort_is_high_and_the_clock_is_unchanged() -> None:
    """Reduce the request, not the deadline: a longer clock hides the cause."""

    policy = json.loads(
        Path(".ai/policies/countyforge-github-execution.v1.json").read_text(encoding="utf-8")
    )
    assert policy["commands"]["plan"]["reasoning_effort"] == "high"
    profile = json.loads(Path(".ai/profiles/plan.read-only.v1.json").read_text(encoding="utf-8"))
    assert profile["default_reasoning_effort"] == "high"
    assert profile["budgets"]["defaults"]["wall_clock_seconds"] == 1800
    assert profile["budgets"]["defaults"]["attempts"] == 1


def test_the_planning_packet_aims_at_the_operational_target(tmp_path: Path) -> None:
    """Run 30836072011 sent 262,974 bytes; the ceiling stays the fail-safe."""

    import subprocess

    from countyforge_github.planning import ContextLimits, build_planning_packet

    limits = ContextLimits()
    assert limits.operational_target_bytes < limits.max_total_bytes

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    info = build_planning_packet(
        trigger={
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
            "actor": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        },
        issue={
            "number": 18,
            "title": "feature: add Collin CAD Access decoder foundation",
            "body": "Problem: the Collin source is missing. Outcome: onboard the county source.",
            "labels": [],
        },
        contract_root=root,
        output_dir=tmp_path,
        run_id="operational-target",
    )
    packet = json.loads(Path(info["packet_path"]).read_text(encoding="utf-8"))
    # The target bounds selected *content*; the serialized packet adds JSON
    # structure on top, so the two are asserted separately rather than conflated.
    content_bytes = sum(
        len(str(source.get("content", "")).encode("utf-8")) for source in packet["sources"]
    )
    assert content_bytes <= limits.operational_target_bytes
    size = Path(info["packet_path"]).stat().st_size
    assert size <= limits.max_total_bytes
    # Materially smaller than the run that timed out, not merely under a ceiling.
    assert size < 262_974


def test_repository_context_is_ordered_by_relevance_to_the_issue(tmp_path: Path) -> None:
    """Alphabetical order let an unrelated ADR crowd out the capability spec."""

    from countyforge_github.planning import ContextLimits, _select_files

    root = Path.cwd()
    selected, _ = _select_files(root, ContextLimits(), ("collin",))
    paths = [str(item["path"]) for item in selected]
    collin = [index for index, path in enumerate(paths) if "collin" in path.casefold()]
    if collin:
        unrelated = [
            index
            for index, path in enumerate(paths)
            if "collin" not in path.casefold() and path.startswith("docs/decisions/")
        ]
        if unrelated:
            assert min(collin) < min(unrelated)


def test_a_timeout_with_no_observed_output_is_reported_distinctly(tmp_path: Path) -> None:
    """`thread.started` + `turn.started` is an accepted turn, not progress.

    Reporting a stalled provider and a too-large request alike is what made run
    30836072011 read as a budget question.
    """

    from countyforge_github.results import (
        TIMED_OUT_AFTER_PROGRESS,
        TIMED_OUT_NO_PROGRESS,
        classify_implementation_lane,
    )

    document = {
        "ok": False,
        "mode": "implement",
        "disposition": "timed_out",
        "summary": {"disposition": "timed_out", "exit_code": 5},
    }
    result_path = tmp_path / "runner.json"
    result_path.write_text(json.dumps(document), encoding="utf-8")
    exit_path = tmp_path / "exit"
    exit_path.write_text("5\n", encoding="utf-8")

    def classify(observed: bool | None) -> str:
        return str(
            classify_implementation_lane(
                selected_provider="sakana",
                lane_results={"openai": "skipped", "sakana": "failure"},
                result_path=result_path,
                exit_code_path=exit_path,
                model_output_observed=observed,
            )["disposition"]
        )

    assert classify(False) == TIMED_OUT_NO_PROGRESS
    assert classify(True) == TIMED_OUT_AFTER_PROGRESS
    # Unknown must not assert a progress claim the evidence cannot support.
    assert classify(None) == TIMED_OUT_AFTER_PROGRESS


def test_turn_lifecycle_events_alone_do_not_count_as_model_output() -> None:
    """The exact stream run 30836072011 produced."""

    from countyforge_runner.model_events import summarize_model_events

    stream = Path("/tmp/countyforge-turn-only.ndjson")
    stream.write_text(
        json.dumps({"type": "thread.started", "thread_id": "019fc8a2"})
        + "\n"
        + json.dumps({"type": "turn.started"})
        + "\n",
        encoding="utf-8",
    )
    summary = summarize_model_events(stream)
    assert summary["event_count"] == 2
    assert summary["last_event_type"] == "turn.started"
    assert summary["output_event_observed"] is False
    assert summary["provider_error_observed"] is False
    stream.unlink()


def test_the_packet_ceiling_is_measured_on_the_serialized_packet(tmp_path: Path) -> None:
    """Bounding selected content left JSON framing unaccounted for.

    A maximum decision package plus ordinary comments serialized to 245,614
    bytes against a 240,000-byte ceiling. The ceiling is now measured on what is
    actually written, optional context is shed to fit, and the maintainer's
    decision parts are never shortened to make room.
    """

    import subprocess

    from countyforge_github.decision_input import MAX_TOTAL_DECISION_BYTES
    from countyforge_github.planning import ContextLimits, build_planning_packet

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    per_part = MAX_TOTAL_DECISION_BYTES // 7
    comments = [
        {
            "id": 2000 + index,
            "body": (
                f"<!-- countyforge-plan-input:v1 issue=18 input=big part={index}/7 -->\n\n"
                + "x" * per_part
            ),
            "updated_at": "2026-08-01T00:00:00Z",
            "user": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        }
        for index in range(1, 8)
    ]
    comments += [
        {
            "id": 3000 + index,
            "body": "z" * 4_000,
            "updated_at": "2026-08-01T00:00:00Z",
            "user": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        }
        for index in range(1, 10)
    ]
    info = build_planning_packet(
        trigger={
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
            "actor": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        },
        issue={
            "number": 18,
            "title": "feature: add Collin CAD Access decoder foundation",
            "body": "Problem: the Collin source is missing. Outcome: onboard it." + "y" * 19_500,
            "labels": [],
        },
        contract_root=root,
        output_dir=tmp_path,
        run_id="serialized-ceiling",
        comments=comments,
    )
    size = Path(info["packet_path"]).stat().st_size
    assert size <= ContextLimits().max_total_bytes

    package = json.loads(Path(info["manifest_path"]).read_text(encoding="utf-8"))["decision_input"]
    assert package["included_part_count"] == 7
    assert package["truncated"] is False

    packet = json.loads(Path(info["packet_path"]).read_text(encoding="utf-8"))
    shed = [
        item
        for item in packet["selection"]["excluded_candidates"]
        if item["reason_code"] == "packet_ceiling"
    ]
    assert shed, "the ceiling should have shed optional context, not passed by luck"
    # Every decision part still reached the packet whole.
    decision_sources = [
        source
        for source in packet["sources"]
        if source["category"] == "comment" and not source["truncated"]
    ]
    assert len(decision_sources) >= 7


def test_mandatory_content_over_the_ceiling_refuses_rather_than_truncating() -> None:
    """A plan built on half a decision is the failure this contract prevents."""

    from countyforge_github.planning import ContextLimits, _fit_packet_to_ceiling

    limits = ContextLimits()
    packet = {
        "sources": [
            {"source_id": "issue", "category": "issue", "content": "i" * 200_000, "bytes": 200_000},
            {
                "source_id": "part1",
                "category": "comment",
                "content": "d" * 200_000,
                "bytes": 200_000,
            },
        ],
        "selection": {"excluded_candidates": []},
    }
    with pytest.raises(ControlPlaneError) as raised:
        _fit_packet_to_ceiling(packet, limits, frozenset({"part1"}))
    assert raised.value.code == "planning_packet_ceiling_exceeded"
    assert raised.value.details["max_total_bytes"] == limits.max_total_bytes


def test_the_observed_output_fact_reaches_classification_from_the_workflow() -> None:
    """The parameter had no production caller, so the disposition was unreachable."""

    import yaml
    from countyforge_github.cli import main as cli_main

    del cli_main
    workflow = yaml.safe_load(
        Path(".github/workflows/countyforge-run.yml").read_text(encoding="utf-8")
    )
    prep = workflow["jobs"]["implementation-publication-prep"]["steps"]
    run = next(
        str(step["run"])
        for step in prep
        if "classify-implementation-lane" in str(step.get("run", ""))
    )
    assert "countyforge-implementation-model-events.summary.json" in run
    assert "--model-output-observed" in run
    # Only when the stream exists: absent evidence must stay unknown.
    assert ".model_events_present == true" in run
    assert ".output_event_observed" in run

    cli_source = Path("tools/countyforge-github/src/countyforge_github/cli.py").read_text(
        encoding="utf-8"
    )
    assert '"--model-output-observed"' in cli_source
    assert "model_output_observed=(" in cli_source


def _ceiling_packet(context_count: int, *, issue_bytes: int = 3_000) -> dict[str, Any]:
    """Long context paths make each exclusion record expensive to record."""

    long_path = "docs/engineering/" + ("deeply-nested-directory-name/" * 6) + "document.md"
    return {
        "sources": [
            {
                "source_id": "issue",
                "category": "issue",
                "content": "i" * issue_bytes,
                "bytes": issue_bytes,
                "path": "github://issue/18",
            },
            *[
                {
                    "source_id": f"ctx{index}",
                    "category": "adr",
                    "content": "c" * 120,
                    "bytes": 120,
                    "path": f"{long_path}?{index}",
                }
                for index in range(context_count)
            ],
        ],
        "selection": {"excluded_candidates": []},
    }


def test_the_returned_packet_is_measured_with_its_own_exclusion_evidence() -> None:
    """Shedding a source frees its content and then costs a `packet_ceiling`
    record. Measuring only the surviving sources declared a packet fitting and
    then returned it over the ceiling -- here by 4,164 bytes."""

    from countyforge_github.planning import (
        ContextLimits,
        _fit_packet_to_ceiling,
        _serialized_size,
    )

    packet = _ceiling_packet(24)
    limits = ContextLimits(max_total_bytes=6_000)
    assert _serialized_size(packet) > limits.max_total_bytes
    with pytest.raises(ControlPlaneError) as raised:
        _fit_packet_to_ceiling(packet, limits, frozenset())
    # Refused rather than returned oversized: the records cost more than the
    # content they freed, so no split of these sources fits.
    assert raised.value.code == "planning_packet_ceiling_exceeded"
    assert raised.value.details["shed_source_count"] == 24
    assert raised.value.details["serialized_bytes"] > limits.max_total_bytes


@pytest.mark.parametrize("ceiling", list(range(9_400, 12_800, 400)))
def test_no_ceiling_leaves_the_returned_packet_over_the_limit(ceiling: int) -> None:
    """Sweep the boundary rather than testing one value with comfortable headroom.

    Every ceiling either yields a packet within it -- exclusion evidence
    included -- or refuses. Neither may return an oversized document.
    """

    from countyforge_github.planning import (
        ContextLimits,
        _fit_packet_to_ceiling,
        _serialized_size,
    )

    packet = _ceiling_packet(24)
    limits = ContextLimits(max_total_bytes=ceiling)
    try:
        fitted = _fit_packet_to_ceiling(packet, limits, frozenset())
    except ControlPlaneError as error:
        assert error.code == "planning_packet_ceiling_exceeded"
        return
    assert _serialized_size(fitted) <= ceiling
    # The evidence of what was dropped is present and counted in the measurement.
    shed = [
        item
        for item in fitted["selection"]["excluded_candidates"]
        if item["reason_code"] == "packet_ceiling"
    ]
    assert len(fitted["sources"]) + len(shed) == len(packet["sources"])


def test_ordinary_comments_are_shed_before_trusted_repository_material() -> None:
    """`comment` was absent from the sheddable list, so it took the fallback rank
    and shed *last*: an unmarked 4 KB discussion comment could survive while the
    capability specification the issue is about was deleted."""

    from countyforge_github.planning import (
        _SHEDDABLE_CATEGORIES,
        ContextLimits,
        _fit_packet_to_ceiling,
    )

    assert "comment" in _SHEDDABLE_CATEGORIES
    order = list(_SHEDDABLE_CATEGORIES)
    assert order.index("comment") < order.index("openspec")
    assert order.index("comment") < order.index("source_contract")

    packet: dict[str, Any] = {
        "sources": [
            {
                "source_id": "issue",
                "category": "issue",
                "content": "i" * 2_000,
                "bytes": 2_000,
                "path": "github://issue/18",
            },
            {
                "source_id": "part1",
                "category": "comment",
                "content": "d" * 2_000,
                "bytes": 2_000,
                "path": "github://issue/18/comment/1",
            },
            {
                "source_id": "chatter",
                "category": "comment",
                "content": "z" * 4_000,
                "bytes": 4_000,
                "path": "github://issue/18/comment/2",
            },
            {
                "source_id": "spec",
                "category": "openspec",
                "content": "s" * 2_000,
                "bytes": 2_000,
                "path": "openspec/specs/collin-cad-source-contract/spec.md",
            },
            {
                "source_id": "contract",
                "category": "source_contract",
                "content": "c" * 2_000,
                "bytes": 2_000,
                "path": "docs/sources/collin.md",
            },
        ],
        "selection": {"excluded_candidates": []},
    }
    fitted = _fit_packet_to_ceiling(
        packet, ContextLimits(max_total_bytes=11_000), frozenset({"part1"})
    )
    kept = {str(source["source_id"]) for source in fitted["sources"]}
    # The chatter went; the capability specification and source contract stayed.
    assert "chatter" not in kept
    assert {"spec", "contract"} <= kept
    # And the decision part was never a candidate, because it is mandatory.
    assert "part1" in kept
    shed = [
        item["path"]
        for item in fitted["selection"]["excluded_candidates"]
        if item["reason_code"] == "packet_ceiling"
    ]
    assert shed == ["github://issue/18/comment/2"]


def test_retained_comments_do_not_count_toward_selected_files() -> None:
    """`selected_files` counts repository files, and comments are not files.

    Adding `comment` to the shedding-priority tuple silently changed what
    `selected_files` meant, because one tuple was answering two questions. A
    packet holding six comments and one specification reported six selected
    files against a declared `max_files` of two.
    """

    from countyforge_github.planning import (
        _REPOSITORY_FILE_CATEGORIES,
        _SHEDDABLE_CATEGORIES,
        ContextLimits,
        _fit_packet_to_ceiling,
    )

    # The two answer different questions and must not be the same tuple.
    assert "comment" in _SHEDDABLE_CATEGORIES
    assert "comment" not in _REPOSITORY_FILE_CATEGORIES
    assert "issue" not in _REPOSITORY_FILE_CATEGORIES
    assert set(_REPOSITORY_FILE_CATEGORIES) < set(_SHEDDABLE_CATEGORIES)

    packet: dict[str, Any] = {
        "sources": [
            {
                "source_id": "issue",
                "category": "issue",
                "content": "i" * 2_000,
                "bytes": 2_000,
                "path": "github://issue/18",
            },
            *[
                {
                    "source_id": f"c{index}",
                    "category": "comment",
                    "content": "z" * 1_000,
                    "bytes": 1_000,
                    "path": f"github://issue/18/comment/{index}",
                }
                for index in range(6)
            ],
            {
                "source_id": "spec",
                "category": "openspec",
                "content": "s" * 2_000,
                "bytes": 2_000,
                "path": "openspec/specs/collin-cad-source-contract/spec.md",
            },
        ],
        "selection": {"max_files": 2, "selected_files": 1, "excluded_candidates": []},
    }
    fitted = _fit_packet_to_ceiling(
        packet, ContextLimits(max_total_bytes=10_500), frozenset({"c0"})
    )
    retained_comments = [source for source in fitted["sources"] if source["category"] == "comment"]
    repository_files = [
        source
        for source in fitted["sources"]
        if str(source["category"]) in _REPOSITORY_FILE_CATEGORIES
    ]
    assert retained_comments, "the case is only meaningful with comments retained"
    assert fitted["selection"]["selected_files"] == len(repository_files)
    # And it never exceeds the limit repository selection was held to.
    assert fitted["selection"]["selected_files"] <= fitted["selection"]["max_files"]


# --------------------------------------------------------------------------
# The Sakana run that completed in 8m41s and failed schema validation: every
# scenario folded its outcome into `when` and left `then` empty.
# --------------------------------------------------------------------------


def _folded_scenario_result() -> dict[str, Any]:
    document = _result()
    scenario = document["requirements"][0]["scenarios"][0]
    scenario["when"] = (
        "When the adapter decodes the literal, then it returns the reviewed exact negative Decimal."
    )
    scenario["then"] = []
    return document


def test_a_schema_failure_reports_the_exact_json_path() -> None:
    """Twelve identical failures were reported as one opaque sentence."""

    # A different constraint on a different field, so the mapping is shown to
    # generalise rather than to hardcode the one failure that prompted it.
    document = _result()
    document["requirements"][0]["scenarios"][0]["given"] = []
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert raised.value.code == "invalid_plan_result"
    details = raised.value.details
    assert details["path"] == "requirements[0].scenarios[0].given"
    assert details["pointer"] == "/requirements/0/scenarios/0/given"
    assert details["validator"] == "minItems"
    assert details["detail"] == "requirements[0].scenarios[0].given: should be non-empty"


def test_an_outcome_folded_into_when_is_named_through_the_real_entry_point() -> None:
    """The previous version asserted `scenario_incomplete` while the PR claimed
    the folded pattern was named -- the check sat after a branch that always
    raised first, and after schema validation that rejects `then: []` anyway.

    This drives `validate_planning_result`, the way every caller does.
    """

    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(_folded_scenario_result(), contract_root=CONTRACT_ROOT)
    details = raised.value.details
    assert details["reason"] == "scenario_outcome_folded_into_when"
    assert details["path"] == "requirements[0].scenarios[0].then"
    assert "written inside requirements[0].scenarios[0].when" in details["detail"]
    assert details["scenario"]

    # The trigger is never rewritten to manufacture an outcome.
    document = _folded_scenario_result()
    assert "then it returns" in document["requirements"][0]["scenarios"][0]["when"]


def test_an_empty_then_without_a_folded_outcome_gets_the_plain_path_diagnostic() -> None:
    """The specific diagnosis must not swallow the general one."""

    document = _result()
    document["requirements"][0]["scenarios"][0]["then"] = []
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    details = raised.value.details
    assert details.get("reason") is None
    assert details["detail"] == "requirements[0].scenarios[0].then: should be non-empty"
    assert details["validator"] == "minItems"


def test_a_populated_then_beside_a_when_containing_the_word_is_not_flagged() -> None:
    """`then` appears legitimately in prose; only a *missing* outcome matters."""

    from countyforge_github.planning_semantics import folded_outcome_detail

    document = _result()
    document["requirements"][0]["scenarios"][0]["when"] = (
        "the adapter decodes the literal, then halts"
    )
    assert folded_outcome_detail(document) is None
    validate_planning_result(document, contract_root=CONTRACT_ROOT)


_FOLDED_WHEN = "When the adapter decodes the literal, then it returns the reviewed exact value."


@pytest.mark.parametrize(
    ("label", "value", "validator"),
    [
        ("missing", ..., "required"),
        ("null", None, "type"),
        ("empty string", "", "type"),
        ("empty object", {}, "type"),
        ("zero", 0, "type"),
    ],
)
def test_a_falsy_then_that_is_not_an_empty_list_keeps_its_real_validator(
    label: str, value: Any, validator: str
) -> None:
    """A falsy check caught `required` and `type` failures and relabelled them
    `minItems`. This diagnostic runs *before* schema validation, so nothing
    downstream would have corrected the substituted evidence."""

    document = _result()
    scenario = document["requirements"][0]["scenarios"][0]
    scenario["when"] = _FOLDED_WHEN
    if value is ...:
        scenario.pop("then", None)
    else:
        scenario["then"] = value

    from countyforge_github.planning_semantics import folded_outcome_detail

    # The specific diagnosis declines these outright.
    assert folded_outcome_detail(document) is None, label

    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    details = raised.value.details
    assert details["validator"] == validator, label
    assert details.get("reason") is None, label
    assert details["path"].endswith("then") or details["path"].endswith("scenarios[0]")


def test_only_a_present_empty_list_earns_the_folded_diagnosis() -> None:
    """The one shape actually observed, and only that shape."""

    from countyforge_github.planning_semantics import folded_outcome_detail

    document = _result()
    scenario = document["requirements"][0]["scenarios"][0]
    scenario["when"] = _FOLDED_WHEN
    scenario["then"] = []
    detail = folded_outcome_detail(document)
    assert detail is not None
    assert detail["reason"] == "scenario_outcome_folded_into_when"
    assert detail["validator"] == "minItems"


def test_the_folded_detector_tolerates_a_malformed_pre_schema_document() -> None:
    """It runs before schema validation, so it sees unvalidated shapes."""

    from countyforge_github.planning_semantics import folded_outcome_detail

    # Each scenario carries a folded `when` where it can, so the check under
    # test is the `then` branch rather than an early return on a missing
    # trigger -- which is how the previous version passed without exercising it.
    for document in (
        {},
        {"requirements": "not a list"},
        {"requirements": [None, 7, "text"]},
        {"requirements": [{"scenarios": "not a list"}]},
        {"requirements": [{"scenarios": [None, {"when": 42, "then": []}]}]},
        {"requirements": [{"scenarios": [{"when": _FOLDED_WHEN, "then": None}]}]},
        {"requirements": [{"scenarios": [{"when": _FOLDED_WHEN}]}]},
        {"requirements": [{"scenarios": [{"when": _FOLDED_WHEN, "then": "text"}]}]},
    ):
        assert folded_outcome_detail(document) is None


def test_the_prompt_shows_the_separated_scenario_shape() -> None:
    prompt = Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8")
    assert "nothing splits it for you" in prompt
    assert '"when": "the adapter decodes the literal",' in prompt
    assert '"the reviewed exact negative Decimal is returned",' in prompt
    # The instruction and the worked example must both be present: the example
    # alone reads as decoration, and the rule alone was already there.
    assert "is the trigger" in prompt
    assert prompt.index("is the trigger") < prompt.index('"when": "the adapter decodes')


def test_a_correctly_separated_scenario_still_passes() -> None:
    """The guard must not reject prose that legitimately contains the word."""

    document = _result()
    scenario = document["requirements"][0]["scenarios"][0]
    scenario["when"] = "the adapter decodes the literal"
    scenario["then"] = ["the reviewed exact negative Decimal is returned"]
    validate_planning_result(document, contract_root=CONTRACT_ROOT)


# --------------------------------------------------------------------------
# Run 31269239926 — Sakana completed in ~295s and the plan failed validation.
# 23 schema errors, all of them constraints the provider-compatible generation
# schema strips before the model ever sees it.
# --------------------------------------------------------------------------

RUN_31269239926 = Path("tools/countyforge-github/tests/fixtures/plan-result-run-31269239926.json")


def _schema_errors(document: dict[str, Any]) -> list[Any]:
    from jsonschema import Draft202012Validator

    schema = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    return sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: (list(item.absolute_path), item.validator or ""),
    )


def test_the_run_31269239926_plan_is_rejected_for_three_independent_reasons() -> None:
    """The reported `write_paths: []` was real but was one of three blockers,
    and not the first the validator reports."""

    document = json.loads(RUN_31269239926.read_text(encoding="utf-8"))
    failures = {
        (
            "/" + "/".join(str(part) for part in error.absolute_path),
            error.validator,
        )
        for error in _schema_errors(document)
    }
    # The validation-only task.
    assert ("/task_slices/5/write_paths", "minItems") in failures
    # Requirement ids emitted as `R1`..`R9`.
    assert ("/requirements/0/id", "pattern") in failures
    # Validation checks written as prose sentences.
    assert ("/task_slices/1/validation_checks/0", "maxLength") in failures
    assert len(failures) > 20


def test_a_validation_only_task_slice_remains_schema_invalid() -> None:
    """Strictness is not weakened to accommodate the model."""

    schema = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    write_paths = schema["$defs"]["task_slice"]["properties"]["write_paths"]
    assert write_paths["minItems"] == 1

    document = _result()
    document["task_slices"].append(
        {
            "task_id": "6.1",
            "title": "Run deterministic Collin foundation validation",
            "description": "Run strict OpenSpec validation and the repository gates.",
            "write_paths": [],
            "validation_checks": ["make check"],
            "prerequisites": ["1.1"],
            "risk": "low",
            "source_ids": ["aa11aa11aa11aa11aa11aa11"],
        }
    )
    assert any(
        error.validator == "minItems" and "write_paths" in str(list(error.absolute_path))
        for error in _schema_errors(document)
    )
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert raised.value.code == "invalid_plan_result"
    assert raised.value.details["path"] == "task_slices[4].write_paths"


def test_the_prompt_forbids_validation_only_task_slices() -> None:
    prompt = Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8")
    assert "mutating implementation work" in prompt
    assert "only to run validation" in prompt
    assert "belong in top-level `validation_commands`" in prompt
    # The negative example, in the shape the model actually emitted.
    assert '"task_id": "6.1"' in prompt
    assert '"write_paths": []' in prompt
    assert "Do not invent a write path" in prompt


def test_the_prompt_states_every_constraint_the_generation_schema_strips() -> None:
    """The root cause, as an invariant rather than three patched sentences.

    The generation schema is projected onto the provider-compatible keyword
    subset, which drops `pattern`, `minItems`, `maxLength`, and `minLength`.
    Every one of run 31269239926's 23 errors violated a dropped constraint, so
    the prompt is the only channel for them and must carry them.
    """

    prompt = " ".join(
        Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    generation = json.loads(
        Path(".ai/schemas/countyforge-plan-generation.schema.json").read_text(encoding="utf-8")
    )

    def keywords(node: object) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                found.add(key)
                found |= keywords(value)
        elif isinstance(node, list):
            for item in node:
                found |= keywords(item)
        return found

    stripped = {"pattern", "minItems", "maxLength", "minLength"} & keywords(generation)
    assert not stripped, f"generation schema unexpectedly carries {sorted(stripped)}"

    # So the prompt must say each of them in words.
    assert "lower-case letters, digits, and hyphens" in prompt  # pattern
    assert "64 characters at most" in prompt  # maxLength
    assert "at least one entry" in prompt  # minItems
    assert "never `R1`" in prompt
    assert "never a sentence" in prompt


def test_the_generated_requirement_id_and_check_shapes_are_named_in_the_prompt() -> None:
    """Both other blockers, pinned to the exact values the model produced."""

    document = json.loads(RUN_31269239926.read_text(encoding="utf-8"))
    assert document["requirements"][0]["id"] == "R1"
    assert len(document["task_slices"][1]["validation_checks"][0]) > 64

    # Whitespace-normalized: the guidance wraps, so a raw read would miss any
    # phrase that happens to straddle a line break.
    prompt = " ".join(
        Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    assert "`numeric-decoding-exactness`, never `R1`" in prompt
    # The wording moved from "a short command identifier" to a named closed set
    # (because the example it gave -- `make check` -- was the defect), and then
    # from a set written out in prose to the packet field that carries it.
    assert "one identifier copied from the packet's `implementation_check_ids`" in prompt


# --------------------------------------------------------------------------
# Run 31281189305 — zero schema errors, refused by the semantic gate for
# declaring MODIFIED against a capability inventory that is empty.
# --------------------------------------------------------------------------

RUN_31281189305 = Path("tools/countyforge-github/tests/fixtures/plan-result-run-31281189305.json")


def _run_31281189305(change_type: str) -> dict[str, Any]:
    document = json.loads(RUN_31281189305.read_text(encoding="utf-8"))
    document["affected_capabilities"][0]["change_type"] = change_type
    return document


#: Every plan the pipeline produced before this rule emitted shell commands in
#: `validation_checks` -- `make test`, `make lint`, `make docs`. It stayed
#: latent because each of those runs failed earlier, on capability resolution or
#: on blocked reasons. Implementation would have refused all of them.
_HISTORICAL_CHECK_DEFECT = ("make check", "make docs", "make lint", "make test", "make typecheck")


def _with_supported_checks(document: dict[str, Any]) -> dict[str, Any]:
    """Apply the check-vocabulary correction the artifact also needs."""

    for task in document["task_slices"]:
        assert any(check in _HISTORICAL_CHECK_DEFECT for check in task["validation_checks"])
        task["validation_checks"] = ["repo.check"]
    return document


def _with_file_paths(document: dict[str, Any]) -> dict[str, Any]:
    """Apply the third correction: every recorded plan wrote directories.

    Each task said "somewhere under this package" and named no artifact, so the
    plan authorized a whole subtree while describing none of it. Narrowed here
    to one representative file per declared directory, which is the shape the
    contract now requires.
    """

    for index, task in enumerate(document["task_slices"]):
        task["write_paths"] = [
            f"{path}artifact_{index}.py" if path.endswith("/") else path
            for path in task["write_paths"]
        ]
    return document


def test_the_run_31281189305_plan_has_no_schema_errors() -> None:
    """The prompt work in #50 held: this failure is purely semantic."""

    from jsonschema import Draft202012Validator

    schema = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    document = json.loads(RUN_31281189305.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(document)) == []
    assert document["affected_capabilities"][0]["change_type"] == "MODIFIED"


def test_modified_against_an_empty_inventory_is_refused_and_names_it(
    tmp_path: Path,
) -> None:
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(_run_31281189305("MODIFIED"), contract_root=CONTRACT_ROOT)
    details = raised.value.details
    assert details["reason"] == "affected_capability_not_declared"
    assert details["capability"] == "collin-cad-source-contract"
    assert details["change_type"] == "MODIFIED"
    # The inventory travels with the refusal; empty is the whole answer.
    assert details["declared_capabilities"] == []
    assert details["declared_capability_count"] == 0


def test_the_single_added_correction_passes_the_whole_semantic_validator() -> None:
    """Probed before implementing: `MODIFIED` -> `ADDED` is the only blocker.

    Asserting the full pass, not just the capability check, is what makes the
    next paid run predictable instead of revealing one constraint at a time.
    """

    # Two corrections, not one: the artifact also emitted `make ...` checks,
    # which the implementation lane cannot run. That defect was latent until
    # the capability failure ahead of it was fixed.
    scope = validate_planning_result(
        _with_file_paths(_with_supported_checks(_run_31281189305("ADDED"))),
        contract_root=CONTRACT_ROOT,
    )
    assert scope["resolved_from"] == "issue:18"
    assert scope["required_cross_issues"] == [43]


def test_the_corrected_plan_materializes_a_draft_change(tmp_path: Path) -> None:
    """One correction reaches a materialized change, not merely a passing gate."""

    import shutil

    from countyforge_github.planning import materialize_plan

    shutil.copytree(CONTRACT_ROOT / ".ai", tmp_path / ".ai")
    document = _with_file_paths(_with_supported_checks(_run_31281189305("ADDED")))
    manifest = materialize_plan(
        document, publication_root=tmp_path, issue_number=18, run_id="run-31281189305"
    )
    assert manifest["implementation_eligibility"] is False
    change = tmp_path / "openspec/changes" / document["proposed_change_name"]
    assert (change / "specs/collin-cad-source-contract/spec.md").is_file()
    assert (
        (change / "specs/collin-cad-source-contract/spec.md")
        .read_text(encoding="utf-8")
        .startswith("## ADDED Requirements")
    )


# --- The inventory itself -------------------------------------------------


def test_only_promoted_openspec_specs_count_as_declared(tmp_path: Path) -> None:
    """A capability proposed in a change is a draft awaiting human merge."""

    from countyforge_github.planning_semantics import declared_capabilities

    root = tmp_path
    promoted = root / "openspec/specs/promoted-capability"
    promoted.mkdir(parents=True)
    (promoted / "spec.md").write_text("## Requirements\n", encoding="utf-8")

    # Proposed only inside a change: not declared.
    proposed = root / "openspec/changes/add-thing/specs/proposed-capability"
    proposed.mkdir(parents=True)
    (proposed / "spec.md").write_text("## ADDED Requirements\n", encoding="utf-8")

    # A directory with no spec.md is not a capability either.
    (root / "openspec/specs/empty-directory").mkdir(parents=True)

    assert declared_capabilities(root) == frozenset({"promoted-capability"})


def test_the_inventory_is_deterministic_and_bounded(tmp_path: Path) -> None:
    from countyforge_github.planning_semantics import declared_capabilities

    for index in range(12):
        directory = tmp_path / "openspec/specs" / f"capability-{11 - index:02d}"
        directory.mkdir(parents=True)
        (directory / "spec.md").write_text("## Requirements\n", encoding="utf-8")

    first = sorted(declared_capabilities(tmp_path))
    second = sorted(declared_capabilities(tmp_path))
    assert first == second == [f"capability-{index:02d}" for index in range(12)]

    schema = json.loads(
        Path(".ai/schemas/countyforge-planning-packet.schema.json").read_text(encoding="utf-8")
    )
    bound = schema["properties"]["declared_capabilities"]
    assert bound["maxItems"] == 128
    assert bound["items"]["maxLength"] == 64


def test_the_packet_inventory_is_the_semantic_gate_inventory(tmp_path: Path) -> None:
    """One canonical definition, asserted against the real repository."""

    import subprocess

    from countyforge_github.planning import build_planning_packet
    from countyforge_github.planning_semantics import declared_capabilities

    root = Path.cwd()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    info = build_planning_packet(
        trigger={
            "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
            "target": {"type": "issue", "number": 18, "head_sha": sha, "base_sha": sha},
            "actor": {"id": AUTHOR_ID, "login": "maintainer", "type": "User"},
        },
        issue={
            "number": 18,
            "title": "feature: add Collin CAD Access decoder foundation",
            "body": "Problem: the Collin source is missing. Outcome: onboard the county source.",
            "labels": [],
        },
        contract_root=root,
        output_dir=tmp_path,
        run_id="declared-capabilities",
    )
    packet = json.loads(Path(info["packet_path"]).read_text(encoding="utf-8"))
    # The invariant is that the two agree, not that the repository happens to
    # declare nothing: asserting emptiness made this fail on any tree where a
    # spec had been promoted locally.
    assert packet["declared_capabilities"] == sorted(declared_capabilities(root))


def test_the_prompt_names_the_packet_field_authoritative() -> None:
    prompt = Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8")
    # Wrapping-independent: the prompt is prose and will be reflowed.
    flat = " ".join(prompt.split())
    assert "`declared_capabilities` list is the authoritative inventory" in flat
    assert "every capability must be `ADDED`" in flat
    assert "Do not infer that a capability exists from a proposal under" in flat
    assert "only `declared_capabilities` counts" in flat


def test_a_directory_that_cannot_be_a_capability_name_is_not_inventoried(
    tmp_path: Path,
) -> None:
    """Self-review: the inventory was unbounded into a bounded packet field.

    `affected_capability.name` caps at 64 characters, so a longer directory
    could never be declared against; carrying it would only have broken the
    packet that must transport it.
    """

    from countyforge_github.planning_semantics import declared_capabilities

    for name in ("c" * 70, "Capital-Letters", "under_score", "valid-capability"):
        directory = tmp_path / "openspec/specs" / name
        directory.mkdir(parents=True)
        (directory / "spec.md").write_text("## Requirements\\n", encoding="utf-8")

    assert declared_capabilities(tmp_path) == frozenset({"valid-capability"})


def test_an_inventory_too_large_to_carry_refuses_rather_than_truncating(
    tmp_path: Path,
) -> None:
    """An inventory the prompt calls authoritative must be complete.

    Truncating would let the model choose `ADDED` for a capability that already
    exists; overflowing would fail packet construction with an opaque schema
    error. Neither is acceptable, so this refuses by name.
    """

    from countyforge_github.planning import (
        MAX_DECLARED_CAPABILITIES,
        _bounded_capability_inventory,
    )

    def stage(count: int) -> Path:
        root = tmp_path / f"root{count}"
        for index in range(count):
            directory = root / "openspec/specs" / f"capability-{index:03d}"
            directory.mkdir(parents=True)
            (directory / "spec.md").write_text("## Requirements\\n", encoding="utf-8")
        return root

    assert len(_bounded_capability_inventory(stage(MAX_DECLARED_CAPABILITIES))) == (
        MAX_DECLARED_CAPABILITIES
    )
    with pytest.raises(ControlPlaneError) as raised:
        _bounded_capability_inventory(stage(MAX_DECLARED_CAPABILITIES + 1))
    assert raised.value.code == "declared_capability_inventory_too_large"
    assert raised.value.details["declared_capability_count"] == MAX_DECLARED_CAPABILITIES + 1


def test_the_producer_bound_matches_the_packet_schema_bound() -> None:
    """Pin the two together; a bound enforced only at the consumer is the defect."""

    from countyforge_github.planning import MAX_DECLARED_CAPABILITIES

    schema = json.loads(
        Path(".ai/schemas/countyforge-planning-packet.schema.json").read_text(encoding="utf-8")
    )
    bound = schema["properties"]["declared_capabilities"]
    assert bound["maxItems"] == MAX_DECLARED_CAPABILITIES

    from countyforge_github.planning_semantics import CAPABILITY_NAME

    assert CAPABILITY_NAME.pattern == "^[a-z0-9][a-z0-9-]{0,63}$"
    assert bound["items"]["maxLength"] == 64


# --------------------------------------------------------------------------
# Run 31293882847 — zero schema errors, capability correctly ADDED, refused
# because a `planned` result carried three standing conditions as blockers.
# --------------------------------------------------------------------------

RUN_31293882847 = Path("tools/countyforge-github/tests/fixtures/plan-result-run-31293882847.json")

#: The exact strings the model emitted. All true, none a blocker of this plan.
PRODUCTION_BLOCKED_REASONS = [
    "The generated OpenSpec change remains a draft until an authorized maintainer merges it; "
    "decisions D1 through D4 are resolved only for drafting and each requires human merge "
    "acceptance.",
    "Non-bootstrap implementation must not begin before the issue-linked OpenSpec change is "
    "accepted.",
    "Implementation must remain outside the production and shared abstraction boundaries owned "
    "by Issue 43.",
]


def test_the_run_31293882847_artifact_fails_only_the_blocked_reasons_invariant() -> None:
    """Everything earlier in the pipeline held: schema clean, capability ADDED."""

    from jsonschema import Draft202012Validator

    document = json.loads(RUN_31293882847.read_text(encoding="utf-8"))
    schema = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(document)) == []
    assert document["affected_capabilities"][0]["change_type"] == "ADDED"
    assert document["status"] == "planned"
    assert len(document["blocked_reasons"]) == 3

    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    details = raised.value.details
    assert raised.value.code == "invalid_plan_result"
    assert details["reason"] == "planned_result_has_blocked_reasons"
    assert details["status"] == "planned"
    assert details["blocked_reason_count"] == 3
    # The prose itself is never in the refusal.
    for reason in document["blocked_reasons"]:
        assert reason not in json.dumps(details)


def test_clearing_blocked_reasons_alone_passes_and_materializes(tmp_path: Path) -> None:
    """The one-field correction, proven before implementing."""

    import shutil

    from countyforge_github.planning import materialize_plan

    document = _with_file_paths(
        _with_supported_checks(json.loads(RUN_31293882847.read_text(encoding="utf-8")))
    )
    document["blocked_reasons"] = []
    scope = validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert scope["resolved_from"] == "issue:18"

    shutil.copytree(CONTRACT_ROOT / ".ai", tmp_path / ".ai")
    manifest = materialize_plan(
        document, publication_root=tmp_path, issue_number=18, run_id="run-31293882847"
    )
    assert len(manifest["files"]) == 5
    change = tmp_path / "openspec/changes" / document["proposed_change_name"]
    assert (change / "specs/collin-cad-source-contract/spec.md").is_file()


def test_a_blocked_result_may_carry_genuine_blocked_reasons() -> None:
    """The invariant is about `planned`, not about blockers existing."""

    document = _result()
    decisions = document["planning_decisions"]
    decisions[0]["status"] = "blocked"
    document["status"] = "blocked"
    document["blocked_reasons"] = ["D1 is not accepted yet."]
    scope = validate_planning_result(document, contract_root=CONTRACT_ROOT)
    assert scope["resolved_from"] == "issue:18"


def test_a_planned_result_with_empty_blocked_reasons_is_valid() -> None:
    document = _result()
    assert document["status"] == "planned"
    assert document["blocked_reasons"] == []
    validate_planning_result(document, contract_root=CONTRACT_ROOT)


@pytest.mark.parametrize(
    ("name", "validator"),
    [
        ("Not A Valid Name", "pattern"),
        ("-leading-hyphen", "pattern"),
        ("a" * 200, "maxLength"),
    ],
)
def test_an_invalid_change_name_is_reported_by_the_schema_path(name: str, validator: str) -> None:
    """The in-code guard for this is unreachable, so the schema reports it.

    `_CHANGE` and the schema pattern are identical and the schema is validated
    first, so no input reaches the guard. The real diagnostic is the pointer
    path, and it does not surface the offending name.
    """

    from countyforge_github.planning import _CHANGE

    schema = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["proposed_change_name"]["pattern"] == _CHANGE.pattern

    document = _result()
    document["proposed_change_name"] = name
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_result(document, contract_root=CONTRACT_ROOT)
    details = raised.value.details
    assert details["path"] == "proposed_change_name"
    assert details["validator"] == validator
    # Unvalidated model output stays out of the diagnostic.
    assert name not in json.dumps(details)


def test_the_prompt_separates_blockers_from_standing_conditions() -> None:
    prompt = " ".join(
        Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    assert "A `planned` result must emit `blocked_reasons: []`." in prompt
    assert "only for a result whose `status` is `blocked`" in prompt
    # Each standing condition is named with the field that actually represents it.
    assert "human maintainer merge is `implementation_eligibility: false`" in prompt
    assert "`planning_decisions[].requires_human_merge`" in prompt
    assert "lifecycle gate, not a blocker" in prompt
    assert "`cross_issue_dependencies` entry" in prompt
    # And all three production strings appear as negative examples.
    for reason in PRODUCTION_BLOCKED_REASONS:
        assert " ".join(reason.split()) in prompt


def test_the_capability_tests_do_not_read_the_working_tree() -> None:
    """`Path.cwd()` made these flip on any tree with a promoted spec.

    `collin-cad-source-contract` is now declared in the repository, so this is
    the difference between passing and failing rather than a hypothetical.
    """

    from countyforge_github.planning_semantics import declared_capabilities

    assert CONTRACT_ROOT != Path.cwd()
    assert declared_capabilities(CONTRACT_ROOT) == frozenset()
    # The real tree does declare one now; the tests are simply not coupled to it.
    assert "collin-cad-source-contract" in declared_capabilities(Path.cwd())
    # Schemas and policy still come from the real tree, so they stay authoritative.
    assert (CONTRACT_ROOT / ".ai/schemas/countyforge-plan-result.schema.json").is_file()
    assert (CONTRACT_ROOT / ".ai/policies/countyforge-planning-scope.v1.json").is_file()


# --------------------------------------------------------------------------
# PR #56 — the Tarrant plan passed planning and would have been refused by
# implementation, because two contracts disagreed about what a plan may say.
# --------------------------------------------------------------------------


def test_a_validation_check_implementation_cannot_run_is_refused() -> None:
    """`make check` is not a check identifier, and its space ends the task
    marker field -- so the whole marker failed to parse and every task fell back
    to the broad default write scope."""

    from countyforge_github.implementation import _IMPLEMENTATION_VALIDATION_CHECKS

    for unsupported in ("make check", "make docs", "pytest", "repo.checks"):
        document = _result()
        document["task_slices"][0]["validation_checks"] = [unsupported]
        with pytest.raises(ControlPlaneError) as raised:
            _validate(document, required_cross_issues=[43])
        details = raised.value.details
        assert details["reason"] == "task_validation_check_unsupported"
        assert details["unsupported"] == [unsupported]
        # The refusal names the vocabulary, so the correction is obvious.
        assert set(details["supported"]) == set(_IMPLEMENTATION_VALIDATION_CHECKS)


def test_every_supported_check_identifier_is_accepted() -> None:
    from countyforge_github.implementation import _IMPLEMENTATION_VALIDATION_CHECKS

    for supported in sorted(_IMPLEMENTATION_VALIDATION_CHECKS):
        document = _result()
        for task in document["task_slices"]:
            task["validation_checks"] = [supported]
        _validate(document, required_cross_issues=[43])


def test_no_supported_check_identifier_contains_a_space() -> None:
    """A space ends the marker field; the vocabulary must never contain one."""

    from countyforge_github.implementation import _IMPLEMENTATION_VALIDATION_CHECKS

    for check in _IMPLEMENTATION_VALIDATION_CHECKS:
        assert " " not in check, check


def test_a_trigger_that_repeats_its_own_outcome_is_refused() -> None:
    """All seven Tarrant scenarios set `when` and `then` to one sentence.

    It passed because `then` was non-empty and the duplicate check compared
    only *across* requirements, never within a scenario.
    """

    document = _result()
    scenario = document["requirements"][0]["scenarios"][0]
    repeated = "the adapter decodes the value and returns the exact reviewed Decimal"
    scenario["when"] = repeated
    scenario["then"] = [repeated]
    with pytest.raises(ControlPlaneError) as raised:
        _validate(document, required_cross_issues=[43])
    assert raised.value.details["reason"] == "scenario_trigger_repeats_outcome"
    assert raised.value.details["scenario"]


def test_a_trigger_echoed_among_several_outcomes_is_still_refused() -> None:
    document = _result()
    scenario = document["requirements"][0]["scenarios"][0]
    repeated = "the adapter decodes the value"
    scenario["when"] = repeated
    scenario["then"] = ["the exact reviewed Decimal is returned", repeated]
    with pytest.raises(ControlPlaneError) as raised:
        _validate(document, required_cross_issues=[43])
    assert raised.value.details["reason"] == "scenario_trigger_repeats_outcome"


def test_the_prompt_names_the_closed_check_vocabulary_and_the_trigger_rule() -> None:
    """The prompt offered `make check` as an example, which is what the planner
    copied into every task."""

    prompt = " ".join(
        Path(".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    # The identifiers themselves are no longer written into the prompt. Prose
    # restating a registry is prose that drifts from it; the packet carries the
    # registry, and the prompt points at the packet. That the packet really
    # carries them is asserted in
    # `test_the_packet_carries_the_implementation_check_registry`.
    assert "copied from the packet's `implementation_check_ids`" in prompt
    assert "it is authoritative over anything stated here" in prompt
    assert "never a value containing a space" in prompt
    assert "repeats a `then` is rejected" in prompt
    # `make check` is still correct for the top-level `validation_commands`;
    # the defect was offering it as a *validation_checks* example. The prompt
    # now contrasts the two similarly named fields explicitly.
    assert "are different fields with similar names" in prompt
    assert "A shell command in `validation_checks` is rejected" in prompt
    guidance = prompt[prompt.index("each `validation_checks` entry") :][:600]
    assert "make check" not in guidance.split("validation_commands` holds")[0]
