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
from collections.abc import Iterator
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


# --------------------------------------------------------------------------
# Review fixes: each of these was reported as present and was not
# --------------------------------------------------------------------------


@pytest.fixture
def planning_inputs(
    tmp_path: Path, repo_root: Path, trigger_factory: Any
) -> Iterator[tuple[dict[str, Any], Path, Path]]:
    """A planning packet where the trusted profile actually admits one.

    Plan inputs are bounded to `.ai/contexts/<run>/`, and the workflow copies
    the packet there before invoking the provider. Building it anywhere else
    would exercise a path production never takes -- which is the failure mode
    this whole PR is about.
    """

    import shutil

    from countyforge_github.contracts import ControlContracts
    from countyforge_github.identity import execution_run_id
    from countyforge_github.planning import build_planning_packet

    trigger = trigger_factory("plan")
    # The kernel binds the packet to the run the trigger resolves to, so the
    # packet has to be built under that same identity rather than a literal.
    run_id = execution_run_id(trigger, ControlContracts(repo_root).execution_policy)
    context_root = repo_root / ".ai" / "contexts" / tmp_path.name
    info = build_planning_packet(
        trigger=trigger,
        issue={
            "number": 6,
            "title": "Feature work",
            "body": "Problem: bounded planning is needed. Outcome: create an OpenSpec draft.",
            "labels": [],
        },
        contract_root=repo_root,
        output_dir=context_root,
        run_id=run_id,
    )
    try:
        yield trigger, Path(info["packet_path"]), Path(info["manifest_path"])
    finally:
        shutil.rmtree(context_root, ignore_errors=True)


def test_the_pre_provider_check_runs_where_the_packet_is_actually_consumed(
    repo_root: Path,
    planning_inputs: tuple[dict[str, Any], Path, Path],
) -> None:
    """It was described, tested directly, and called by nothing.

    `build_run_request` is the last trusted step before the provider, so the
    check belongs there or nowhere. Driving the real entry point is the whole
    point: asserting on `assert_context_fresh` in isolation is what let the
    wiring go missing.
    """

    from countyforge_github.planning import planning_trusted_digest
    from countyforge_github.requests import build_run_request

    root = repo_root
    trigger, packet_path, manifest_path = planning_inputs
    packet = json.loads(packet_path.read_text(encoding="utf-8"))

    # The packet this checkout would build today: the request builds.
    assert packet["trusted_context_sha256"] == planning_trusted_digest(root)
    request = build_run_request(
        trigger,
        contract_root=root,
        target_root=root,
        planning_packet_path=packet_path,
        context_manifest_path=manifest_path,
    )
    assert request["input"]["planning_packet_path"] == str(packet_path)

    # A packet recorded under other contracts, which is what a retry replays:
    # the recorded planning context is reused while the tooling has moved on.
    # The checkout is the real one -- only the packet's own binding differs.
    replayed = packet_path.with_name("replayed-packet.json")
    replayed.write_text(
        json.dumps({**packet, "trusted_context_sha256": "1" * 64}), encoding="utf-8"
    )
    with pytest.raises(ControlPlaneError) as raised:
        build_run_request(
            trigger,
            contract_root=root,
            target_root=root,
            planning_packet_path=replayed,
            context_manifest_path=manifest_path,
        )
    assert raised.value.code == STALE_DISPOSITION
    assert raised.value.details["stage"] == "provider_invocation"
    assert raised.value.details["expected"] == "1" * 64
    assert raised.value.details["observed"] == packet["trusted_context_sha256"]


def test_the_pre_provider_digest_tracks_a_real_contract_edit(tmp_path: Path) -> None:
    """And the digest it compares is not inert: editing any bound contract
    moves it, so the comparison above can actually fail."""

    import shutil

    from countyforge_github.planning import planning_trusted_digest

    root = Path.cwd()
    mirror = tmp_path / "mirror"
    shutil.copytree(root / ".ai", mirror / ".ai")
    shutil.copytree(root / "openspec", mirror / "openspec")
    baseline = planning_trusted_digest(mirror)
    prompt = mirror / ".ai/prompts/countyforge-plan.v1.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "\nAn added rule.\n", encoding="utf-8")
    assert planning_trusted_digest(mirror) != baseline


def test_a_packet_without_the_digest_never_reaches_the_provider(
    repo_root: Path, planning_inputs: tuple[dict[str, Any], Path, Path]
) -> None:
    """Absent evidence is not evidence of freshness."""

    from countyforge_github.requests import build_run_request

    trigger, source_path, manifest_path = planning_inputs
    packet = json.loads(source_path.read_text(encoding="utf-8"))
    packet.pop("trusted_context_sha256")
    stripped = source_path.with_name("stripped-packet.json")
    stripped.write_text(json.dumps(packet), encoding="utf-8")

    with pytest.raises(ControlPlaneError) as raised:
        build_run_request(
            trigger,
            contract_root=repo_root,
            target_root=repo_root,
            planning_packet_path=stripped,
            context_manifest_path=manifest_path,
        )
    assert raised.value.code == "planning_context_required"


def test_the_already_materialized_path_proves_readiness_rather_than_claiming_it(
    tmp_path: Path,
) -> None:
    """Production publishes with `--already-materialized`.

    That branch rebuilt the manifest by hand, so the readiness evidence in every
    real publication came from a default rather than from a check -- an
    attestation of readability that nothing had read. It now runs the gate on
    the copied bytes that are about to become blobs.
    """

    import sys

    sys.path.insert(0, "tools/countyforge-github/tests")
    from countyforge_github.planning import materialize_plan, publication_progress, publish_plan
    from test_planning import _publication_case, _PublicationGitHub

    case = _publication_case(tmp_path, "already")
    root = case["publication_root"]
    assert isinstance(root, Path)
    materialize_plan(
        dict(case["result"]),  # type: ignore[arg-type]
        publication_root=root,
        issue_number=6,
        run_id=str(case["run_id"]),
    )
    case["already_materialized"] = True
    with publication_progress() as progress:
        published = publish_plan(_PublicationGitHub(), progress=progress, **case)  # type: ignore[arg-type]
    readiness = published["publication_manifest"]["implementation_readiness"]
    assert readiness["implementation_readable"] is True
    # The defect was `task_count: 0` on a plan that has tasks.
    assert readiness["task_count"] == len(case["result"]["task_slices"])  # type: ignore[index]
    assert readiness["task_ids"] == [
        str(task["task_id"])
        for task in case["result"]["task_slices"]  # type: ignore[index]
    ]


def test_the_already_materialized_path_refuses_tasks_it_cannot_read(tmp_path: Path) -> None:
    """The copied artifact is what gets published, so that is what is checked."""

    import sys

    sys.path.insert(0, "tools/countyforge-github/tests")
    from countyforge_github.planning import materialize_plan, publication_progress, publish_plan
    from test_planning import _publication_case, _PublicationGitHub

    case = _publication_case(tmp_path, "tampered")
    root = case["publication_root"]
    assert isinstance(root, Path)
    manifest = materialize_plan(
        dict(case["result"]),  # type: ignore[arg-type]
        publication_root=root,
        issue_number=6,
        run_id=str(case["run_id"]),
    )
    change = str(manifest["change_name"])
    tasks = root / f"openspec/changes/{change}/tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace("checks=repo.check", "checks=make check"),
        encoding="utf-8",
    )
    case["already_materialized"] = True
    github = _PublicationGitHub()
    with pytest.raises(ControlPlaneError) as raised:  # noqa: PT012 - the boundary is under test
        with publication_progress() as progress:
            publish_plan(github, progress=progress, **case)  # type: ignore[arg-type]
    assert raised.value.code == READINESS_DISPOSITION
    # Before the first Git object, which is the promise the stage order makes.
    assert github.created_refs == []


def test_a_longer_issue_number_does_not_satisfy_a_blocking_dependency() -> None:
    """`"#43" in reasons` was true for a plan that only ever named #430."""

    document = _result()
    document["cross_issue_dependencies"][0]["relationship"] = "blocked_by"
    document["status"] = "blocked"
    document["blocked_reasons"] = ["Waiting on the shared record contract in #430."]
    assert _refusal(document) == "blocking_dependency_absent_from_blocked_reasons"

    document["blocked_reasons"] = ["Waiting on the shared record contract in #43."]
    assert validate_planning_semantics(document, contract_root=CONTRACT_ROOT)["task_count"] == 4


@pytest.mark.parametrize(
    "outcome",
    [
        "the parser works correctly",
        "The parser works correctly",
        "the behaviour is verified",
        "the requirement is met",
        "the decoder functions as expected",
    ],
)
def test_an_unobservable_outcome_is_refused_as_the_prompt_says(outcome: str) -> None:
    """The prompt called these rejected; the validator had no such phrase.

    Guidance the validator does not enforce is guidance the next plan ignores,
    which is the same failure mode as `make check` being offered as an example.
    """

    document = _result()
    document["requirements"][0]["scenarios"][0]["then"] = [outcome]
    assert _refusal(document) == "scenario_placeholder_text"


def test_the_prompt_examples_are_exactly_the_phrases_the_validator_rejects() -> None:
    """Pin the two together so they cannot drift apart again."""

    from countyforge_github.planning_semantics import PLACEHOLDER_PHRASES

    prompt = " ".join(
        (CONTRACT_ROOT / ".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    quoted = prompt[
        prompt.index("are not observations") - 400 : prompt.index("are not observations")
    ]
    for phrase in ("works correctly", "behaviour is verified", "the requirement is met"):
        assert phrase in quoted.casefold(), phrase
        assert phrase in PLACEHOLDER_PHRASES, phrase


# --------------------------------------------------------------------------
# Re-review 4905830243: four findings, all in the freshness feature
# --------------------------------------------------------------------------


def test_the_stage_vocabulary_is_what_the_publisher_enters(
    tmp_path: Path, planning_inputs: tuple[dict[str, Any], Path, Path]
) -> None:
    """The vocabulary was declared twice and the copies drifted.

    Collapsing them to one definition removes the drift but proves nothing on
    its own -- a single wrong list is still wrong. So this drives a real
    publication and asserts that what the publisher actually recorded is what
    the normalizer accepts. A stage added to the publisher and to nothing else
    fails here.
    """

    import sys

    sys.path.insert(0, "tools/countyforge-github/tests")
    from countyforge_github.planning import publication_progress, publish_plan
    from countyforge_github.results import PUBLICATION_STAGES, normalize_publication_result
    from test_planning import _publication_case, _PublicationGitHub

    case = _publication_case(tmp_path, "vocabulary")
    progress_path = tmp_path / "vocabulary-progress.json"
    with publication_progress(progress_path) as progress:
        published = publish_plan(_PublicationGitHub(), progress=progress, **case)  # type: ignore[arg-type]

    recorded = json.loads(progress_path.read_text(encoding="utf-8"))
    assert recorded["stage"] == "complete"
    assert recorded["completed"] == list(PUBLICATION_STAGES[:-1])
    # `verify_trusted_context` is genuinely one of them, not merely consistent.
    assert "verify_trusted_context" in recorded["completed"]

    # And the normalizer agrees, which is what drift broke: a successful
    # publication was reported as incomplete. Driven through the files the
    # workflow actually hands it, not through a dict shaped like them.
    result_path = tmp_path / "vocabulary-result.json"
    result_path.write_text(json.dumps(published), encoding="utf-8")
    normalized = normalize_publication_result(
        result_path=result_path, progress_path=progress_path, exit_code=0
    )
    # `publication_result_incomplete` is what drift produced: a publication
    # that did everything, reported as having not finished.
    assert normalized["disposition"] == "planning_publication_completed"
    assert normalized["ok"] is True
    assert normalized["exit_code"] == 0
    assert normalized["details"]["stage"] == "complete"
    assert normalized["details"]["completed"] == list(PUBLICATION_STAGES[:-1])


def test_publication_fails_closed_when_the_default_branch_cannot_be_resolved(
    tmp_path: Path,
) -> None:
    """It recorded the skip and published anyway.

    Recording that freshness could not be established, and then publishing as
    though it had been, is the fail-open this stage exists to prevent.
    """

    import sys

    sys.path.insert(0, "tools/countyforge-github/tests")
    from countyforge_github.planning import publication_progress, publish_plan
    from countyforge_github.planning_context import UNVERIFIABLE_DISPOSITION
    from test_planning import _publication_case, _PublicationGitHub

    case = _publication_case(tmp_path, "unresolvable")
    github = _PublicationGitHub()

    def _no_profile(repository: str) -> dict[str, Any]:
        raise ControlPlaneError("github_api_error", "GitHub API request failed.", {"status": 503})

    github.repository_profile = _no_profile  # type: ignore[method-assign]
    with pytest.raises(ControlPlaneError) as raised:  # noqa: PT012 - the boundary is under test
        with publication_progress() as progress:
            publish_plan(github, progress=progress, **case)  # type: ignore[arg-type]
    assert raised.value.code == UNVERIFIABLE_DISPOSITION
    assert raised.value.details["reason"] == "default_branch_unavailable"
    # Before the first Git object, which is what "fails closed" has to mean.
    assert github.created_refs == []
    assert github.pull_requests == []


@pytest.mark.parametrize(
    ("comparison", "reason"),
    [
        ({"total_commits": 1}, "compare_files_unavailable"),
        ({"files": None, "total_commits": 1}, "compare_files_unavailable"),
        (
            {"files": [{"filename": "a.py"}], "files_complete": False, "total_commits": 1},
            "compare_files_incomplete",
        ),
        (
            {
                "files": [{"filename": f"file-{index}.py"} for index in range(300)],
                "total_commits": 4,
            },
            "compare_files_incomplete",
        ),
        (
            {"files": [{"filename": "a.py"}], "total_commits": "many"},
            "compare_metadata_malformed",
        ),
        ({"files": [], "total_commits": 3}, "compare_files_empty_for_commit_range"),
    ],
)
def test_incomplete_compare_evidence_never_establishes_freshness(
    comparison: dict[str, Any], reason: str
) -> None:
    """A capped file list is a sample, not a report that nothing else changed.

    GitHub caps compare responses at 300 files. A changed `.ai/schemas/...`
    sitting outside the returned page would otherwise read as proof that the
    trusted context held. Implementation approval already refuses on exactly
    this limitation; publication now does too.
    """

    from countyforge_github.planning_context import UNVERIFIABLE_DISPOSITION

    class _Capped:
        def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> dict[str, Any]:
            del repository, base_sha, head_sha
            return comparison

    with pytest.raises(ControlPlaneError) as raised:
        assert_base_context_unmoved(
            _Capped(), repository="o/r", target_sha="a" * 40, default_branch_sha="b" * 40
        )
    assert raised.value.code == UNVERIFIABLE_DISPOSITION
    assert raised.value.details["reason"] == reason


def test_complete_compare_evidence_still_publishes() -> None:
    """The fail-closed posture must not swallow the ordinary case."""

    class _Complete:
        def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> dict[str, Any]:
            del repository, base_sha, head_sha
            return {
                "files": [{"filename": "libs/property-tax-adapters/src/collin.py"}],
                "files_complete": True,
                "total_commits": 2,
            }

    evidence = assert_base_context_unmoved(
        _Complete(), repository="o/r", target_sha="a" * 40, default_branch_sha="b" * 40
    )
    assert evidence["compared"] is True
    assert evidence["reason"] == "base_moved_without_touching_context"


def test_no_surviving_prompt_guidance_offers_a_shell_command_as_a_task_check() -> None:
    """The corrected guidance was contradicted seventy lines later.

    A later bullet still said "include only checks supported by the packet and
    repository, such as `make check`, `make runner-contract-tests`" -- which is
    the #56 defect restated in the same file that forbids it. The model reads
    the whole prompt, so a single surviving example is enough to reproduce it.
    """

    prompt = " ".join(
        (CONTRACT_ROOT / ".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    occurrences = [index for index in range(len(prompt)) if prompt.startswith("`make ", index)]
    # Exactly one, and it is the sentence naming what `validation_commands`
    # holds -- the one place a shell command is the correct answer.
    assert len(occurrences) == 1, [prompt[index : index + 40] for index in occurrences]
    sentence = prompt[max(occurrences[0] - 200, 0) : occurrences[0] + 40]
    assert "`validation_commands` holds shell commands such as `make check`" in sentence
    # And no bullet anywhere offers a `make` target as a *task* check.
    assert "`make runner-contract-tests`" not in prompt
    assert "`make docs`" not in prompt


def test_the_task_ordering_bullet_points_at_the_registry() -> None:
    """And the bullet that carried the contradiction now names the registry."""

    prompt = " ".join(
        (CONTRACT_ROOT / ".ai/prompts/countyforge-plan.v1.md").read_text(encoding="utf-8").split()
    )
    bullet = prompt[prompt.index("Order task slices by dependency") :][:400]
    assert "implementation_check_ids" in bullet
    assert "no shell command" in bullet
    assert "make " not in bullet
