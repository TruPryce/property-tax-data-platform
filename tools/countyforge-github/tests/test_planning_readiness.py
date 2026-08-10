"""The gates that stand between a valid-looking plan and an executable one.

PR #56 is the whole motivation. It satisfied every planning contract and would
have been refused by the implementation lane, because planning validated the
result *document* while implementation parses the materialized *markdown*, and
nothing read the second with the tool that would actually read it.

Each test here drives the real artifact, not a hand-built stand-in shaped like
what the code expects. That distinction is the reason the defect survived four
reviews: a mechanism tested against a shape the production path never produces
proves nothing about the production path.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from countyforge_github.errors import ControlPlaneError
from countyforge_github.implementation import _IMPLEMENTATION_VALIDATION_CHECKS, _tasks_from_text
from countyforge_github.implementation_readiness import (
    READINESS_DISPOSITION,
    assert_implementation_readable,
    implementation_check_ids,
)
from countyforge_github.planning import materialize_plan
from countyforge_github.planning_context import (
    STALE_DISPOSITION,
    TRUSTED_CONTEXT_PATHS,
    assert_base_context_unmoved,
    assert_context_fresh,
    trusted_context_digest,
)
from countyforge_github.planning_semantics import validate_planning_semantics
from countyforge_test_support import controlled_contract_root

CONTRACT_ROOT = controlled_contract_root()
FIXTURE = Path("tools/countyforge-github/tests/fixtures/planning-result-collin-issue-18.json")


def _result(**overrides: Any) -> dict[str, Any]:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document.update(copy.deepcopy(overrides))
    return document


def _refusal(document: dict[str, Any]) -> str:
    with pytest.raises(ControlPlaneError) as raised:
        validate_planning_semantics(document, contract_root=CONTRACT_ROOT)
    return str(raised.value.details["reason"])


# --------------------------------------------------------------------------
# The readiness gate: rendered markdown, read by the implementation parser
# --------------------------------------------------------------------------

#: Verbatim from the PR #56 branch. `checks=make check` is valid JSON and
#: unreadable markup: the marker parser captures `checks=([^\s]+)`, so the space
#: ends the field and the rest of the marker -- paths, risk, prerequisites --
#: is silently discarded.
PR_56_TASKS = (
    "## Tasks\n\n"
    "<!-- countyforge-task: 1.1 paths=libs/property-tax-adapters/src/texas/"
    " checks=make check risk=high prerequisites=D1,D2 -->\n"
    "- [ ] 1.1 Implement the certified roll parser\n\n"
    "<!-- countyforge-task: 1.2 paths=docs/sources/"
    " checks=make docs risk=high prerequisites=1.1 -->\n"
    "- [ ] 1.2 Document the parser\n"
)


def test_the_pr_56_tasks_are_unreadable_to_the_implementation_parser() -> None:
    """The premise, proved against the real markdown before anything is gated.

    Nothing raises here -- that is the point. The parser is content with this
    input; it simply understands something other than what the plan said.
    """

    tasks = _tasks_from_text(PR_56_TASKS)
    assert [task["task_id"] for task in tasks] == ["1.1", "1.2"]
    for task in tasks:
        assert task["metadata_complete"] is False
        # The declared scope is gone, replaced by the broad repository default.
        assert task["allowed_paths"] == ["libs", "services", "dags", "docs", "openspec"]
        assert task["required_checks"] == ["repo.check"]
        assert task["prerequisites"] == []
        # `risk=high` was declared; the parser never saw it.
        assert task["risk"] == "normal"


def test_the_readiness_gate_refuses_the_pr_56_tasks() -> None:
    with pytest.raises(ControlPlaneError) as raised:
        assert_implementation_readable(
            PR_56_TASKS, contract_root=CONTRACT_ROOT, declared_task_ids=["1.1", "1.2"]
        )
    assert raised.value.code == READINESS_DISPOSITION
    details = raised.value.details
    assert details["reason"] == "task_metadata_unreadable"
    assert details["task"] == "1.1"
    # The refusal carries the vocabulary, so the correction is mechanical.
    assert details["supported_checks"] == sorted(_IMPLEMENTATION_VALIDATION_CHECKS)


def test_a_dropped_task_is_caught_by_the_round_trip_and_not_by_the_schema() -> None:
    """A marker that fails to match is not a parse error -- it is a task with
    default metadata. Only comparing declared against recovered reveals it."""

    with pytest.raises(ControlPlaneError) as raised:
        assert_implementation_readable(
            PR_56_TASKS, contract_root=CONTRACT_ROOT, declared_task_ids=["1.1", "1.2", "1.3"]
        )
    details = raised.value.details
    assert details["reason"] == "task_round_trip_mismatch"
    assert details["declared"] == ["1.1", "1.2", "1.3"]
    assert details["recovered"] == ["1.1", "1.2"]


def test_a_readable_plan_passes_and_reports_what_it_checked() -> None:
    readable = PR_56_TASKS.replace("checks=make check", "checks=repo.check").replace(
        "checks=make docs", "checks=docs.links"
    )
    evidence = assert_implementation_readable(
        readable, contract_root=CONTRACT_ROOT, declared_task_ids=["1.1", "1.2"]
    )
    assert evidence["implementation_readable"] is True
    assert evidence["task_count"] == 2
    assert evidence["checks_used"] == ["docs.links", "repo.check"]


def test_materialization_runs_the_readiness_gate_before_publication(tmp_path: Path) -> None:
    """The gate is only worth anything at the seam the publisher passes through."""

    import shutil

    shutil.copytree(CONTRACT_ROOT / ".ai", tmp_path / ".ai")
    manifest = materialize_plan(
        _result(), publication_root=tmp_path, issue_number=18, run_id="readiness"
    )
    readiness = manifest["implementation_readiness"]
    assert readiness["implementation_readable"] is True
    assert readiness["task_ids"] == ["1.1", "1.2", "1.3", "1.4"]
    # And the evidence describes the file the implementation lane will read,
    # not the result document the planner produced.
    rendered = (tmp_path / "openspec/changes" / manifest["change_name"] / "tasks.md").read_text(
        encoding="utf-8"
    )
    assert [task["task_id"] for task in _tasks_from_text(rendered)] == readiness["task_ids"]


def test_the_gate_reads_the_marker_and_not_the_document_it_came_from() -> None:
    """Why this exists even though the semantic gate catches today's defects.

    Every route into PR #56 is now refused earlier, so this gate is currently
    the second line. It is the only check that reads the rendered artifact with
    the parser that will consume it, which is what keeps it correct when either
    side moves: here a task carries a risk value the marker parser has no entry
    for, and the plan document it was rendered from looks entirely well-formed.
    """

    markup = PR_56_TASKS.replace("checks=make check", "checks=repo.check").replace(
        "checks=make docs", "checks=docs.links"
    )
    drifted = markup.replace("risk=high", "risk=critical", 1)
    with pytest.raises(ControlPlaneError) as raised:
        assert_implementation_readable(
            drifted, contract_root=CONTRACT_ROOT, declared_task_ids=["1.1", "1.2"]
        )
    assert raised.value.details["reason"] == "task_metadata_unreadable"


def test_the_planning_and_implementation_vocabularies_are_still_aligned() -> None:
    """The drift above is hypothetical only while these agree. Pin them.

    Two contracts describing one artifact is the shape of the original defect,
    so the agreement is asserted rather than assumed.
    """

    from countyforge_github.implementation import _PLANNING_RISK

    schema = json.loads(
        (CONTRACT_ROOT / ".ai/schemas/countyforge-plan-result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    task = schema["$defs"]["task_slice"]["properties"]
    assert set(task["risk"]["enum"]) <= set(_PLANNING_RISK)
    # Every task_id the plan schema admits must match the marker the
    # implementation lane greps for, or the task silently disappears.
    import re as _re

    from countyforge_github.implementation import _TASK_META

    assert task["task_id"]["pattern"] == r"^[0-9]{1,3}\.[0-9]{1,3}$"
    for candidate in ("1.1", "10.20", "999.999"):
        assert _re.fullmatch(task["task_id"]["pattern"], candidate)
        marker = (
            f"<!-- countyforge-task: {candidate} paths=docs/a.md checks=repo.check risk=low -->"
        )
        assert _TASK_META.match(marker), candidate


# --------------------------------------------------------------------------
# The registry: the vocabulary reaches the model as data, not as prose
# --------------------------------------------------------------------------


def test_the_packet_carries_the_implementation_check_registry() -> None:
    """The prompt no longer lists the identifiers, so this is where they live."""

    assert implementation_check_ids() == sorted(_IMPLEMENTATION_VALIDATION_CHECKS)
    schema = json.loads(
        (CONTRACT_ROOT / ".ai/schemas/countyforge-planning-packet.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert "implementation_check_ids" in schema["required"]


def test_no_check_identifier_can_survive_the_task_marker_unread() -> None:
    """The registry is only safe to hand over if every entry round-trips.

    A space in any identifier would reintroduce the exact PR #56 failure at the
    moment the planner did what it was told.
    """

    for check in implementation_check_ids():
        assert " " not in check
        # `prerequisites` is optional in the marker and takes no empty value,
        # so a task with none omits the field entirely.
        markup = (
            f"## Tasks\n\n<!-- countyforge-task: 1.1 paths=docs/a.md checks={check} "
            "risk=low -->\n- [ ] 1.1 A task\n"
        )
        parsed = _tasks_from_text(markup)
        assert parsed[0]["required_checks"] == [check], check
        assert parsed[0]["metadata_complete"] is True, check


# --------------------------------------------------------------------------
# Narrow execution paths
# --------------------------------------------------------------------------


def test_a_task_naming_a_directory_is_refused() -> None:
    document = _result()
    document["task_slices"][0]["write_paths"] = ["libs/property-tax-adapters/"]
    assert _refusal(document) == "task_path_not_a_file"


def test_a_path_without_an_extension_is_refused() -> None:
    """`libs/adapters/collin` is a directory wearing a file's clothes."""

    document = _result()
    document["task_slices"][0]["write_paths"] = [
        "libs/property-tax-adapters/src/property_tax_adapters/collin"
    ]
    assert _refusal(document) == "task_path_not_a_file"


def test_the_declared_scope_may_still_be_a_directory() -> None:
    """The plan-level ceiling stays a directory; only tasks name files."""

    document = _result()
    assert all(path.endswith("/") for path in document["declared_write_scope"])
    evidence = validate_planning_semantics(document, contract_root=CONTRACT_ROOT)
    assert evidence["task_count"] == 4


# --------------------------------------------------------------------------
# Typed dependency relationships
# --------------------------------------------------------------------------


def test_a_blocking_relationship_on_an_unblocked_plan_is_refused() -> None:
    """The Collin plan really did declare `blocked_by` while calling itself
    `planned` with no blocked reasons. `related_to` and `blocked_by` were
    interchangeable prose; now only one of them obliges anything."""

    document = _result()
    document["cross_issue_dependencies"][0]["relationship"] = "blocked_by"
    assert _refusal(document) == "blocking_dependency_not_reflected_in_status"


def test_requires_contract_from_blocks_exactly_as_blocked_by_does() -> None:
    document = _result()
    document["cross_issue_dependencies"][0]["relationship"] = "requires_contract_from"
    assert _refusal(document) == "blocking_dependency_not_reflected_in_status"


def test_a_blocked_plan_must_still_name_the_issue_in_its_reasons() -> None:
    """Status alone is not enough: eligibility reads `blocked_reasons`."""

    document = _result()
    document["cross_issue_dependencies"][0]["relationship"] = "blocked_by"
    document["status"] = "blocked"
    document["blocked_reasons"] = ["Waiting on an unrelated matter."]
    assert _refusal(document) == "blocking_dependency_absent_from_blocked_reasons"

    document["blocked_reasons"] = ["The shared source record contract in #43 is not defined yet."]
    assert validate_planning_semantics(document, contract_root=CONTRACT_ROOT)["task_count"] == 4


def test_the_context_only_relationships_oblige_nothing() -> None:
    document = _result()
    for relationship in ("related_to", "depends_on", "supersedes"):
        document["cross_issue_dependencies"][0]["relationship"] = relationship
        assert validate_planning_semantics(document, contract_root=CONTRACT_ROOT)["task_count"] == 4


def test_both_schemas_offer_the_same_relationships() -> None:
    """The generation schema is a projection; a drift here silently narrows
    what the model may emit relative to what the validator accepts."""

    result = json.loads(
        (CONTRACT_ROOT / ".ai/schemas/countyforge-plan-result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    generation = json.loads(
        (CONTRACT_ROOT / ".ai/schemas/countyforge-plan-generation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    declared = result["$defs"]["cross_issue_dependency"]["properties"]["relationship"]["enum"]
    mirrored = generation["properties"]["cross_issue_dependencies"]["items"]["properties"][
        "relationship"
    ]["enum"]
    assert declared == mirrored
    assert {"requires_contract_from", "supersedes"} <= set(declared)


# --------------------------------------------------------------------------
# Trusted-context freshness
# --------------------------------------------------------------------------


def test_the_digest_changes_when_any_trusted_contract_changes(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(CONTRACT_ROOT / ".ai", tmp_path / ".ai")
    baseline = trusted_context_digest(tmp_path)
    assert trusted_context_digest(tmp_path) == baseline

    for relative in TRUSTED_CONTEXT_PATHS:
        path = tmp_path / relative
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        assert trusted_context_digest(tmp_path) != baseline, relative
        path.write_bytes(original)
    assert trusted_context_digest(tmp_path) == baseline


def test_the_derived_inventory_moves_the_digest_without_any_file_changing(
    tmp_path: Path,
) -> None:
    """A capability archived between packet and publication changes no contract
    file at all, which is exactly why the inventory is bound in too."""

    import shutil

    shutil.copytree(CONTRACT_ROOT / ".ai", tmp_path / ".ai")
    before = trusted_context_digest(tmp_path, extra={"capabilities": []})
    after = trusted_context_digest(tmp_path, extra={"capabilities": ["collin-cad-source-contract"]})
    assert before != after


def test_a_packet_built_under_different_contracts_is_refused() -> None:
    with pytest.raises(ControlPlaneError) as raised:
        assert_context_fresh(expected="a" * 64, observed="b" * 64, stage="provider_invocation")
    assert raised.value.code == STALE_DISPOSITION
    assert raised.value.details["stage"] == "provider_invocation"


class _ComparingGitHub:
    """Stands in for the compare API and records what was asked."""

    def __init__(self, files: list[str]) -> None:
        self.files = files
        self.calls: list[tuple[str, str]] = []

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> dict[str, Any]:
        del repository
        self.calls.append((base_sha, head_sha))
        return {"files": [{"filename": name} for name in self.files]}


def test_an_unmoved_base_is_not_compared_at_all() -> None:
    github = _ComparingGitHub([])
    evidence = assert_base_context_unmoved(
        github, repository="o/r", target_sha="a" * 40, default_branch_sha="a" * 40
    )
    assert evidence == {"compared": False, "reason": "base_unmoved"}
    assert github.calls == []


def test_a_base_that_moved_without_touching_the_context_still_publishes() -> None:
    github = _ComparingGitHub(["libs/property-tax-adapters/src/collin.py", "README.md"])
    evidence = assert_base_context_unmoved(
        github, repository="o/r", target_sha="a" * 40, default_branch_sha="b" * 40
    )
    assert evidence["compared"] is True
    assert github.calls == [("a" * 40, "b" * 40)]


@pytest.mark.parametrize(
    "changed",
    [
        ".ai/prompts/countyforge-plan.v1.md",
        ".ai/schemas/countyforge-plan-result.schema.json",
        ".ai/policies/countyforge-github-execution.v1.json",
        # Not a contract file, but it is what the declared capability inventory
        # is derived from, so it changes what a correct plan says.
        "openspec/specs/collin-cad-source-contract/spec.md",
    ],
)
def test_a_moved_trusted_context_refuses_publication(changed: str) -> None:
    github = _ComparingGitHub(["README.md", changed])
    with pytest.raises(ControlPlaneError) as raised:
        assert_base_context_unmoved(
            github, repository="o/r", target_sha="a" * 40, default_branch_sha="b" * 40
        )
    assert raised.value.code == STALE_DISPOSITION
    details = raised.value.details
    assert details["stage"] == "publication"
    assert details["changed"] == [changed]
    # Repository-relative contract paths only: no model output, no issue text.
    assert "README.md" not in details["changed"]


def test_the_publication_manifest_records_the_freshness_check() -> None:
    """A gate that can be skipped must say when it was skipped."""

    schema = json.loads(
        (
            CONTRACT_ROOT / ".ai/schemas/countyforge-planning-publication-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert "trusted_context_freshness" in schema["required"]
    assert "implementation_readiness" in schema["required"]
