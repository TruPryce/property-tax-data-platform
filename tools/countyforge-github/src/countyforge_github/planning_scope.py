"""Trusted planning scope: the ceiling the generated plan is measured against.

The first version of the semantic gate treated the generated result's own
`declared_write_scope` as the ceiling whenever a caller supplied none, and every
live call supplied none.  The provider therefore authored both sides of the
subset check: it could declare `services/foo/` as its scope and then stay inside
it.  The broad-alias denylist stops `libs`, but it cannot tell that a narrow
scope is the *wrong* narrow scope.

The ceiling now comes from committed policy keyed by originating issue and
affected capability.  A plan may narrow it; nothing a model emits can widen it.
Required cross-issue boundaries resolve from the same policy, so a plan cannot
pass the live gate by simply omitting the boundary it is bound by.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from countyforge_runner.contracts import validate_document
from countyforge_runner.errors import KernelError

from countyforge_github.contracts import JsonObject, load_json_object
from countyforge_github.errors import ControlPlaneError

POLICY_PATH = ".ai/policies/countyforge-planning-scope.v1.json"


@dataclass(frozen=True, slots=True)
class PlanningScope:
    """The trusted ceiling, plus how it was resolved."""

    write_roots: tuple[str, ...]
    required_cross_issues: tuple[int, ...]
    resolved_from: str

    def provenance(self) -> JsonObject:
        """Bound into planning provenance so the ceiling is auditable."""

        return {
            "contract_version": 1,
            "policy_path": POLICY_PATH,
            "resolved_from": self.resolved_from,
            "write_roots": list(self.write_roots),
            "required_cross_issues": list(self.required_cross_issues),
        }


def _roots(entry: JsonObject) -> tuple[str, ...]:
    return tuple(
        str(item) for item in entry.get("write_roots") or [] if isinstance(item, (str, int))
    )


def _issues(entry: JsonObject) -> tuple[int, ...]:
    return tuple(
        int(item)
        for item in entry.get("required_cross_issues") or []
        if isinstance(item, int) and not isinstance(item, bool)
    )


def resolve_planning_scope(
    contract_root: Path,
    *,
    issue_number: int,
    capability: str = "",
    change_name: str = "",
) -> PlanningScope:
    """Resolve the trusted ceiling for one planning run.

    The originating issue wins over the affected capability, because the issue is
    what a maintainer filed and the capability is what the model chose.  When
    neither is declared the ceiling collapses to the change's own OpenSpec
    directory: a plan can always write its own change, and nothing else, until
    policy says otherwise.
    """

    policy_file = contract_root / POLICY_PATH
    if not policy_file.is_file():
        raise ControlPlaneError(
            "planning_scope_policy_missing",
            "The trusted planning scope policy is unavailable.",
            {"policy_path": POLICY_PATH},
        )
    policy = load_json_object(policy_file, kind="planning scope policy")
    # Strict, like every other versioned trusted-root document.  Parsing alone
    # let `"required_cross_issues": ["43"]` through: the string was dropped by
    # the integer filter below, so a typo silently *removed* the issue-43
    # requirement instead of failing closed -- the worst possible direction for
    # a policy whose whole job is to bound a generated plan.
    try:
        validate_document(
            policy,
            load_json_object(
                contract_root / ".ai/schemas/countyforge-planning-scope.schema.json",
                kind="planning scope schema",
            ),
            kind="planning scope policy",
        )
    except KernelError as error:
        raise ControlPlaneError(
            "planning_scope_policy_invalid",
            "The trusted planning scope policy does not satisfy its strict contract.",
            {"policy_path": POLICY_PATH, "detail": error.details.get("path", "")},
        ) from None
    issues = policy.get("issues")
    capabilities = policy.get("capabilities")
    entry: JsonObject | None = None
    resolved_from = "default"
    if isinstance(issues, dict):
        candidate = issues.get(str(int(issue_number)))
        if isinstance(candidate, dict):
            entry, resolved_from = candidate, f"issue:{int(issue_number)}"
    if entry is None and capability and isinstance(capabilities, dict):
        candidate = capabilities.get(str(capability))
        if isinstance(candidate, dict):
            entry, resolved_from = candidate, f"capability:{capability}"
    if entry is None:
        entry = {
            "write_roots": policy.get("default_write_roots") or [],
            "required_cross_issues": [],
        }

    roots = list(_roots(entry))
    if change_name:
        # Every plan materializes its own change directory; that is trusted
        # because the trusted materializer, not the model, chooses the path.
        own_change = f"openspec/changes/{change_name}/"
        if own_change not in roots:
            roots.append(own_change)
    return PlanningScope(
        write_roots=tuple(roots),
        required_cross_issues=_issues(entry),
        resolved_from=resolved_from,
    )
