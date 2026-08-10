"""Trusted semantic validation of a generated planning result.

PR #46 was syntactically valid and semantically useless: it declared the
CountyForge planner capability instead of the domain capability it changed,
rendered every requirement as "The implementation SHALL satisfy this criterion",
authorised every task to write `libs,services,dags,docs,tools,tests,README.md,
CONTRIBUTING.md`, and emitted `prerequisites=-` for tasks whose own prose named
their dependencies.  A schema can require the fields; only this module can say
whether what they contain means anything.

Every check here is a refusal, never a repair.  A planning result that cannot be
validated is not rewritten into one that can be: it fails closed with
`planning_semantic_validation_failed` before any Git object is created.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NoReturn

from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.implementation import _IMPLEMENTATION_VALIDATION_CHECKS

SEMANTIC_DISPOSITION = "planning_semantic_validation_failed"

#: Language that passes a schema while asserting nothing.  Drawn from the
#: materialization PR #46 actually produced.
PLACEHOLDER_PHRASES = (
    "satisfy this criterion",
    "satisfies this criterion",
    "implementation is evaluated",
    "demonstrably satisfied",
    "as described above",
    "see the description",
    "to be determined",
    "tbd",
)

#: Write scopes no planning change may authorise for itself.  These are the
#: control plane's own trust boundaries: a task that can edit them can rewrite
#: the rules that bound it.
FORBIDDEN_WRITE_PREFIXES = (
    ".github/",
    ".ai/",
    ".git/",
    "openspec/specs/",
)

#: Top-level aliases broad enough to be meaningless as a write scope.  A task
#: that may write all of `libs` has not declared a scope, it has declined to.
#:
#: `tests` is deliberately absent: a task that adds tests for the package it
#: changes writes there legitimately, and the declared-scope ceiling below is
#: what actually bounds it.  This set exists for the aliases that *are* the
#: ceiling -- the ones PR #46 listed to avoid choosing.
BROAD_WRITE_PATHS = frozenset(
    {
        "libs",
        "services",
        "dags",
        "docs",
        "tools",
        "src",
        "openspec",
        ".",
        "/",
        "*",
        "**",
        "README.md",
        "CONTRIBUTING.md",
        "AGENTS.md",
    }
)

_NORMATIVE = re.compile(r"\b(?:SHALL NOT|MUST NOT|SHALL|MUST)\b")
_DECISION_ID = re.compile(r"^D[0-9]{1,3}$")
_TASK_ID = re.compile(r"^[0-9]{1,3}\.[0-9]{1,3}$")
#: Mirrors `affected_capability.name` in the plan schema.
CAPABILITY_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
#: An outcome written inside the trigger.  Detected and reported, never
#: split: guessing where the trigger ends would mutate model output on a
#: heuristic, and "then" appears legitimately inside prose.
_FOLDED_OUTCOME = re.compile(r",\s*then\b|\bthen\s+it\b", re.IGNORECASE)


def _fail(reason: str, **details: object) -> NoReturn:
    raise ControlPlaneError(
        SEMANTIC_DISPOSITION,
        "The generated planning change failed trusted semantic validation.",
        {"reason": reason, **details},
    )


def _contains_placeholder(text: str) -> str | None:
    lowered = text.casefold()
    for phrase in PLACEHOLDER_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def declared_capabilities(root: Path) -> frozenset[str]:
    """The canonical capability inventory: promoted OpenSpec specs, nothing else.

    `openspec/specs/<name>/spec.md` is the only source.  A capability proposed
    inside `openspec/changes/**/specs/` is a draft awaiting human merge, not a
    declared capability, and neither documentation, policy keys, nor selected
    packet context may stand in for this.  Packet construction and the semantic
    gate both call this, so the model is told exactly what the gate enforces.
    """

    specs = root / "openspec" / "specs"
    if not specs.is_dir():
        return frozenset()
    return frozenset(
        child.name
        for child in sorted(specs.iterdir())
        if child.is_dir()
        and (child / "spec.md").is_file()
        # A directory whose name cannot be a capability name is not a
        # capability: `affected_capabilities[].name` is bound by this same
        # pattern, so such a name could never be declared against, and carrying
        # it would only risk breaking the packet that must transport it.
        and CAPABILITY_NAME.fullmatch(child.name) is not None
    )


def _validate_capability(result: JsonObject, root: Path) -> str:
    """Defect 3: the affected capability is the domain's, never the planner's."""

    capabilities = result.get("affected_capabilities")
    if not isinstance(capabilities, list) or len(capabilities) != 1:
        _fail("affected_capability_ambiguous", count=len(capabilities or []))
    entry = capabilities[0]
    if not isinstance(entry, dict):
        _fail("affected_capability_malformed")
    name = str(entry.get("name", ""))
    change_type = str(entry.get("change_type", ""))
    if change_type not in {"ADDED", "MODIFIED", "REMOVED"}:
        _fail("affected_capability_change_type_invalid", change_type=change_type)
    existing = declared_capabilities(root)
    if change_type in {"MODIFIED", "REMOVED"} and name not in existing:
        # Modifying something that does not exist means the planner guessed.
        # Report the inventory: an empty list is the whole answer -- nothing is
        # declared yet, so every capability must be ADDED.
        _fail(
            "affected_capability_not_declared",
            capability=name,
            change_type=change_type,
            declared_capabilities=sorted(existing)[:64],
            declared_capability_count=len(existing),
        )
    if change_type == "ADDED" and name in existing:
        _fail("affected_capability_already_exists", capability=name)
    return name


def _validate_requirements(result: JsonObject) -> None:
    """Defect 4: a requirement states an obligation and shows how to observe it."""

    requirements = result.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        _fail("requirements_missing")
    seen_ids: set[str] = set()
    scenario_signatures: dict[tuple[str, ...], str] = {}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            _fail("requirement_malformed")
        identifier = str(requirement.get("id", ""))
        if identifier in seen_ids:
            _fail("requirement_id_duplicated", requirement=identifier)
        seen_ids.add(identifier)
        rule = str(requirement.get("normative_rule", ""))
        if not _NORMATIVE.search(rule):
            _fail("requirement_not_normative", requirement=identifier)
        for field, text in (("normative_rule", rule), ("title", str(requirement.get("title", "")))):
            phrase = _contains_placeholder(text)
            if phrase is not None:
                _fail(
                    "requirement_placeholder_text",
                    requirement=identifier,
                    field=field,
                    phrase=phrase,
                )
        scenarios = requirement.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            _fail("requirement_without_scenario", requirement=identifier)
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                _fail("scenario_malformed", requirement=identifier)
            given = [str(item) for item in scenario.get("given") or []]
            then = [str(item) for item in scenario.get("then") or []]
            when = str(scenario.get("when", ""))
            if not given or not when or not then:
                # Name which half is missing.  Sakana folded every outcome into
                # `when` and left `then` empty across all 12 scenarios, and
                # "scenario_incomplete" alone did not say which field to fix.
                _fail(
                    "scenario_incomplete",
                    requirement=identifier,
                    scenario=str(scenario.get("name", "")),
                    missing=[
                        field
                        for field, value in (("given", given), ("when", when), ("then", then))
                        if not value
                    ],
                )
            for text in (*given, when, *then, str(scenario.get("name", ""))):
                phrase = _contains_placeholder(text)
                if phrase is not None:
                    _fail("scenario_placeholder_text", requirement=identifier, phrase=phrase)
            # A trigger that states its own outcome describes nothing to
            # observe.  Every scenario in the Tarrant plan set `when` and `then`
            # to the same sentence, which passed because `then` was non-empty
            # and the duplicate check only compared *across* requirements.
            if when in then:
                _fail(
                    "scenario_trigger_repeats_outcome",
                    requirement=identifier,
                    scenario=str(scenario.get("name", "")),
                )
            # Two requirements sharing a scenario verbatim describe one
            # observation, so at most one of them is actually observable.
            signature = (*sorted(given), when, *sorted(then))
            previous = scenario_signatures.get(signature)
            if previous is not None and previous != identifier:
                _fail(
                    "scenario_duplicated_across_requirements",
                    requirement=identifier,
                    duplicate_of=previous,
                )
            scenario_signatures[signature] = identifier


def folded_outcome_detail(result: JsonObject) -> JsonObject | None:
    """Name the mistake before the schema reports only its symptom.

    Runs *before* schema validation, which is the only place it can run: a
    scenario with `then: []` is rejected by `minItems` first, so a check placed
    after it could never fire.  `then: should be non-empty` is true but does not
    say why the array is empty; when the outcome is sitting inside `when`, that
    is worth saying, because it is the whole correction.

    Returns bounded evidence for the first such scenario, or `None`.  It never
    rewrites the trigger: guessing where one ends would mutate model output on a
    heuristic, and "then" appears legitimately inside prose.
    """

    requirements = result.get("requirements")
    if not isinstance(requirements, list):
        return None
    for requirement_index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            continue
        scenarios = requirement.get("scenarios")
        if not isinstance(scenarios, list):
            continue
        for scenario_index, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                continue
            # Exactly the observed shape: `then` present, a list, and empty.
            # A falsy check also caught a missing key, `null`, `""`, and `{}` --
            # which are `required` and `type` failures, not `minItems`. Claiming
            # `minItems` for those would substitute fabricated evidence for the
            # validator that actually failed, and this runs *before* schema
            # validation, so nothing downstream would correct it. They fall
            # through to the schema, which names them accurately.
            then = scenario.get("then")
            if not (isinstance(then, list) and not then):
                continue
            when = scenario.get("when")
            if not isinstance(when, str) or not _FOLDED_OUTCOME.search(when):
                continue
            path = f"requirements[{requirement_index}].scenarios[{scenario_index}]"
            return {
                "path": f"{path}.then",
                "pointer": f"/requirements/{requirement_index}/scenarios/{scenario_index}/then",
                "validator": "minItems",
                "reason": "scenario_outcome_folded_into_when",
                "scenario": str(scenario.get("name", ""))[:200],
                "detail": (
                    f"{path}.then: should be non-empty; the expected outcome appears to be "
                    f"written inside {path}.when, which must contain the trigger only"
                ),
            }
    return None


def normalize_write_path(candidate: str) -> str:
    """Return a repository-relative directory prefix, or refuse it."""

    value = str(candidate).strip()
    if not value or value.startswith("/") or value.startswith("~"):
        _fail("task_path_not_relative", path=value)
    if "\\" in value or "*" in value or "?" in value:
        _fail("task_path_wildcard", path=value)
    parts = [part for part in value.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        _fail("task_path_escapes_repository", path=value)
    normalized = "/".join(parts)
    if value.endswith("/"):
        normalized += "/"
    return normalized


def _validate_task_scope(result: JsonObject, declared_scope: Sequence[str]) -> None:
    """Defect 5: an enforceable write scope, narrowed to the declared plan.

    The ceiling is `declared_write_scope` on the plan itself, so the subset
    check tests the plan against its own stated limit rather than against an
    inference.  A caller may pass a narrower ceiling, never a wider one.
    """

    tasks = result.get("task_slices")
    if not isinstance(tasks, list) or not tasks:
        _fail("task_slices_missing")
    plan_scope = [normalize_write_path(item) for item in result.get("declared_write_scope") or []]
    if not plan_scope:
        _fail("declared_write_scope_missing")
    for path in plan_scope:
        bare = path.rstrip("/")
        if bare in BROAD_WRITE_PATHS or path in BROAD_WRITE_PATHS:
            _fail("declared_scope_too_broad", path=path)
        for forbidden in FORBIDDEN_WRITE_PREFIXES:
            if bare == forbidden.rstrip("/") or path.startswith(forbidden):
                _fail("declared_scope_forbidden", path=path)
    caller_scope = [normalize_write_path(item) for item in declared_scope]
    if caller_scope:
        for path in plan_scope:
            if not any(_within(path, allowed) for allowed in caller_scope):
                _fail("declared_scope_exceeds_caller_ceiling", path=path)
    scope = plan_scope
    for task in tasks:
        if not isinstance(task, dict):
            _fail("task_malformed")
        task_id = str(task.get("task_id", ""))
        paths = task.get("write_paths")
        if not isinstance(paths, list) or not paths:
            _fail("task_without_write_paths", task=task_id)
        checks = [str(item) for item in task.get("validation_checks") or []]
        unsupported = sorted(
            check for check in checks if check not in _IMPLEMENTATION_VALIDATION_CHECKS
        )
        if unsupported:
            # A check the implementation lane cannot run is not a check.  The
            # Tarrant plan emitted `make check`, which is not in the vocabulary
            # and contains a space, so its whole task marker failed to parse and
            # every task silently fell back to the broad default write scope.
            _fail(
                "task_validation_check_unsupported",
                task=task_id,
                unsupported=unsupported[:8],
                supported=sorted(_IMPLEMENTATION_VALIDATION_CHECKS),
            )
        for raw in paths:
            path = normalize_write_path(str(raw))
            bare = path.rstrip("/")
            if bare in BROAD_WRITE_PATHS or path in BROAD_WRITE_PATHS:
                _fail("task_path_too_broad", task=task_id, path=path)
            for forbidden in FORBIDDEN_WRITE_PREFIXES:
                if path == forbidden.rstrip("/") or path.startswith(forbidden):
                    _fail("task_path_forbidden", task=task_id, path=path)
            if scope and not any(_within(path, allowed) for allowed in scope):
                _fail("task_path_outside_declared_scope", task=task_id, path=path)


def _within(path: str, allowed: str) -> bool:
    candidate = path.rstrip("/")
    root = allowed.rstrip("/")
    return candidate == root or candidate.startswith(root + "/")


def _validate_prerequisites(result: JsonObject) -> None:
    """Defect 6: declared ordering that exists, terminates, and matches the prose."""

    tasks = [task for task in result.get("task_slices") or [] if isinstance(task, dict)]
    decisions = {
        str(entry.get("decision_id"))
        for entry in result.get("planning_decisions") or []
        if isinstance(entry, dict)
    }
    task_ids = [str(task.get("task_id", "")) for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        _fail("task_id_duplicated")
    graph: dict[str, list[str]] = {}
    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id", ""))
        prerequisites = [str(item) for item in task.get("prerequisites") or []]
        if len(set(prerequisites)) != len(prerequisites):
            _fail("prerequisite_duplicated", task=task_id)
        graph[task_id] = []
        for reference in prerequisites:
            if _DECISION_ID.fullmatch(reference):
                if reference not in decisions:
                    _fail("prerequisite_decision_unknown", task=task_id, prerequisite=reference)
                continue
            if not _TASK_ID.fullmatch(reference):
                _fail("prerequisite_malformed", task=task_id, prerequisite=reference)
            if reference not in task_ids:
                _fail("prerequisite_task_unknown", task=task_id, prerequisite=reference)
            if task_ids.index(reference) >= index:
                # Tasks are rendered in declared order, so a dependency must
                # already have been rendered when its dependent is reached.
                _fail("prerequisite_not_earlier", task=task_id, prerequisite=reference)
            graph[task_id].append(reference)
        _validate_prose_agreement(task, prerequisites)
    _reject_cycles(graph)


_PROSE_TASK = re.compile(r"\btasks?\s+((?:[0-9]{1,3}\.[0-9]{1,3}(?:\s*(?:,|and|&)\s*)?)+)", re.I)
_PROSE_DECISION = re.compile(r"\b(D[0-9]{1,3})\b")


def _validate_prose_agreement(task: JsonObject, prerequisites: Sequence[str]) -> None:
    """Refuse a task whose description names a dependency its metadata omits.

    PR #46 emitted `prerequisites=-` for tasks whose own text began "After D1 is
    accepted" and "After tasks 1.1 and 1.2".  The prose was right and the
    enforceable metadata was empty, which is the dangerous direction: the
    implementation lane reads the metadata.
    """

    task_id = str(task.get("task_id", ""))
    text = f"{task.get('title', '')}\n{task.get('description', '')}"
    declared = set(prerequisites)
    named: set[str] = set(_PROSE_DECISION.findall(text))
    for group in _PROSE_TASK.findall(text):
        named.update(re.findall(r"[0-9]{1,3}\.[0-9]{1,3}", group))
    named.discard(task_id)
    missing = sorted(named - declared)
    if missing:
        _fail("prerequisite_named_in_prose_only", task=task_id, missing=missing)


def _reject_cycles(graph: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str, trail: tuple[str, ...]) -> None:
        if node in done:
            return
        if node in visiting:
            _fail("prerequisite_cycle", cycle=list((*trail, node)))
        visiting.add(node)
        for dependency in graph.get(node, []):
            visit(dependency, (*trail, node))
        visiting.discard(node)
        done.add(node)

    for node in sorted(graph):
        visit(node, ())


def _validate_cross_issue_boundary(result: JsonObject, required_issues: Iterable[int] = ()) -> None:
    """Defect 7: a boundary owned elsewhere is stated and not contradicted."""

    dependencies = result.get("cross_issue_dependencies")
    if not isinstance(dependencies, list):
        _fail("cross_issue_dependencies_missing")
    declared = {
        int(entry["issue_number"]): entry
        for entry in dependencies
        if isinstance(entry, dict) and isinstance(entry.get("issue_number"), int)
    }
    for issue_number in required_issues:
        entry = declared.get(int(issue_number))
        if entry is None:
            _fail("cross_issue_boundary_absent", issue=int(issue_number))
        boundary = [str(item) for item in entry.get("boundary") or []]
        if not boundary:
            _fail("cross_issue_boundary_empty", issue=int(issue_number))
        _reject_boundary_conflicts(result, boundary, int(issue_number))


_BOUNDARY_TERMS = {
    "production release api": ("release api", "production release", "release-processing api"),
    "shared vendor-neutral source records": (
        "vendor-neutral source record",
        "vendor neutral source record",
        "shared source record",
    ),
    "dag integration": ("dag integration", "airflow dag", "dags/"),
    "persistence": ("persist", "publication pipeline", "write to the warehouse"),
}


def _reject_boundary_conflicts(result: JsonObject, boundary: Sequence[str], issue: int) -> None:
    """A task may not authorise work the declared boundary reserves elsewhere."""

    terms: list[str] = []
    for item in boundary:
        lowered = item.casefold()
        terms.extend(_BOUNDARY_TERMS.get(lowered, (lowered,)))
    for task in result.get("task_slices") or []:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id", ""))
        haystack = f"{task.get('title', '')} {task.get('description', '')}".casefold()
        paths = " ".join(str(item).casefold() for item in task.get("write_paths") or [])
        for term in terms:
            if term and (term in haystack or (term.endswith("/") and term in paths)):
                _fail(
                    "task_conflicts_with_cross_issue_boundary",
                    task=task_id,
                    issue=issue,
                    boundary_term=term,
                )


def _validate_eligibility(result: JsonObject) -> None:
    """Defect 2 and 8: a plan never authorises its own implementation."""

    if result.get("implementation_eligibility") is not False:
        _fail("implementation_eligibility_not_false")
    decisions = [
        entry for entry in result.get("planning_decisions") or [] if isinstance(entry, dict)
    ]
    for entry in decisions:
        if entry.get("requires_human_merge") is not True:
            _fail("decision_bypasses_human_merge", decision=str(entry.get("decision_id", "")))
        if str(entry.get("status")) not in {"proposed", "resolved_for_draft", "blocked"}:
            _fail("decision_status_invalid", decision=str(entry.get("decision_id", "")))
    blocked = [entry for entry in decisions if str(entry.get("status")) == "blocked"]
    if blocked and str(result.get("status")) != "blocked":
        _fail(
            "blocked_decision_not_reflected_in_status",
            decisions=[str(entry.get("decision_id", "")) for entry in blocked],
        )
    # An unresolved decision may not be handed to the implementation lane
    # silently.  A blocked plan may depend on one, but the blocker must be
    # named in `blocked_reasons`, which is what downstream eligibility reads.
    unresolved = {str(entry.get("decision_id")) for entry in blocked}
    reasons = " ".join(str(item) for item in result.get("blocked_reasons") or [])
    for task in result.get("task_slices") or []:
        if not isinstance(task, dict):
            continue
        overlap = unresolved.intersection(str(item) for item in task.get("prerequisites") or [])
        undeclared = sorted(item for item in overlap if item not in reasons)
        if undeclared:
            _fail(
                "unresolved_decision_delegated_to_implementation",
                task=str(task.get("task_id", "")),
                decisions=undeclared,
            )


def validate_planning_semantics(
    result: JsonObject,
    *,
    contract_root: Path,
    declared_scope: Sequence[str] = (),
    required_cross_issues: Iterable[int] = (),
) -> JsonObject:
    """Refuse a planning result that is syntactically valid but means nothing.

    Returns bounded evidence of what was checked.  Raises `ControlPlaneError`
    with `planning_semantic_validation_failed` on the first refusal, so the
    reported reason is the specific defect rather than a summary.
    """

    if not isinstance(result, dict):
        _fail("result_malformed")
    if result.get("contract_version") != 2:
        _fail("contract_version_unsupported", contract_version=result.get("contract_version"))
    capability = _validate_capability(result, contract_root)
    _validate_requirements(result)
    _validate_task_scope(result, declared_scope)
    _validate_prerequisites(result)
    _validate_cross_issue_boundary(result, required_cross_issues)
    _validate_eligibility(result)
    return {
        "contract_version": 1,
        "semantic_validation": "passed",
        "affected_capability": capability,
        "requirement_count": len(result.get("requirements") or []),
        "task_count": len(result.get("task_slices") or []),
        "decision_count": len(result.get("planning_decisions") or []),
        "cross_issue_dependency_count": len(result.get("cross_issue_dependencies") or []),
        "implementation_eligibility": False,
    }
