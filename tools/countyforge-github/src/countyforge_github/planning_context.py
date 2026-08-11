"""Bind a plan to the trusted contracts it was actually planned against.

`planning_context_fingerprint` already covers the *untrusted* half of the input
— the issue and its comments — and refuses a run whose discussion moved between
intake and packet preparation.  Nothing covered the *trusted* half.

That half moves too, and on this repository it moves often: capabilities get
archived, the check vocabulary changes, the prompt is rewritten, schemas gain
constraints.  A planning run reads those at packet time and publishes minutes to
hours later against a base that may have moved underneath it.  The plan then
looks valid — it satisfies whatever the contracts say *now* — while having been
reasoned about under contracts that no longer exist.  A capability the model was
told is undeclared may have been declared in between, and the refusal it wrote
into `blocked_reasons` is now simply wrong.

So the digest is taken over the trusted inputs that shape a plan, recorded in
the packet, and checked again before publication.  Divergence is
`planning_context_stale`: not a rejection of the plan's content, but a statement
that it was planned against a base that no longer holds.  The run is re-planned,
never repaired in place.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NoReturn

from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort

STALE_DISPOSITION = "planning_context_stale"

#: The trusted inputs a plan is a function of.  A change to any of them can
#: change what a correct plan says, so each is bound into the digest.  Paths
#: that do not exist contribute their absence, which is itself a fact worth
#: detecting: a deleted schema must not silently widen what a plan may claim.
TRUSTED_CONTEXT_PATHS: tuple[str, ...] = (
    ".ai/prompts/countyforge-plan.v1.md",
    ".ai/schemas/countyforge-plan-generation.schema.json",
    ".ai/schemas/countyforge-plan-result.schema.json",
    ".ai/schemas/countyforge-planning-packet.schema.json",
    ".ai/schemas/countyforge-planning-context-manifest.schema.json",
    ".ai/schemas/countyforge-implementation-packet.schema.json",
    ".ai/schemas/countyforge-implementation-task-plan.schema.json",
    ".ai/policies/countyforge-github-execution.v1.json",
)


def trusted_context_digest(contract_root: Path, *, extra: JsonObject | None = None) -> str:
    """Digest the trusted contracts, plus any derived inventory handed to the model.

    `extra` carries state that is not a file — the declared capability
    inventory and the implementation check registry — so that a capability
    archived between packet and publication is caught even though no contract
    file changed.
    """

    digest = hashlib.sha256()
    for relative in TRUSTED_CONTEXT_PATHS:
        path = contract_root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        except OSError:
            digest.update(b"absent")
        digest.update(b"\n")
    derived = extra or {}
    for key in sorted(derived):
        digest.update(f"{key}=".encode())
        entry = derived[key]
        values = entry if isinstance(entry, list) else [entry]
        digest.update(",".join(str(item) for item in values).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def assert_context_fresh(*, expected: str, observed: str, stage: str) -> None:
    """Refuse a packet built against contracts the current checkout no longer has.

    This is the *before the provider runs* half.  Within one run both jobs check
    out the same pinned tooling SHA, so it holds trivially; it is not trivial on
    a retry, which reuses the recorded planning context and can therefore hand a
    packet built under one set of contracts to a job running under another.
    """

    if expected == observed:
        return
    raise ControlPlaneError(
        STALE_DISPOSITION,
        "The trusted planning context changed after this run read it.",
        # The digests are of trusted repository contracts, not model output or
        # issue text, so they are safe to surface and are what a maintainer
        # needs in order to tell staleness from corruption.
        {"stage": stage, "expected": expected, "observed": observed},
    )


#: Changes under these prefixes change what a correct plan says.  `openspec/specs/`
#: is included because the declared capability inventory is derived from it, and
#: that inventory is what tells a plan whether a capability already exists.
_STALENESS_PREFIXES: tuple[str, ...] = (
    ".ai/prompts/",
    ".ai/schemas/",
    ".ai/policies/",
    "openspec/specs/",
)

#: GitHub caps a compare response at 300 files.  At the cap the list is a sample.
_COMPARE_FILE_CAP = 300

UNVERIFIABLE_DISPOSITION = "planning_context_unverifiable"


def _unverifiable(reason: str, **details: object) -> NoReturn:
    """Refuse when freshness cannot be established, rather than assuming it.

    Not knowing whether the trusted context moved is not the same as knowing it
    did not.  Everything in this module exists to make that distinction, so
    treating an absent or capped answer as "unmoved" would defeat all of it.
    """

    raise ControlPlaneError(
        UNVERIFIABLE_DISPOSITION,
        "The trusted planning context could not be verified before publication.",
        {"stage": "publication", "reason": reason, **details},
    )


def assert_base_context_unmoved(
    github: GitHubPort, *, repository: str, target_sha: str, default_branch_sha: str
) -> JsonObject:
    """Refuse to publish a plan whose trusted base moved since the run read it.

    A draft is always committed onto the immutable `target_sha` the run claimed,
    so the branch itself is reproducible.  What is not reproducible is the
    reasoning: if the prompt, a schema, the execution policy, or the declared
    capability set changed on the default branch in between, the plan answers a
    question the repository no longer asks.  Such a plan is re-planned against
    the current base rather than merged as though nothing moved.

    Compare evidence must be *complete* to prove anything.  A capped or partial
    response would let a changed `.ai/...` file sit outside the returned list
    and read as proof that nothing changed, so incomplete evidence refuses.
    This mirrors the posture implementation approval already takes on the same
    GitHub limitation.

    Returns bounded evidence when the base is unmoved or moved harmlessly.
    """

    if target_sha == default_branch_sha:
        return {"compared": False, "reason": "base_unmoved"}
    comparison = github.compare_commits(repository, target_sha, default_branch_sha)
    files = comparison.get("files")
    if not isinstance(files, list):
        # The compare API omits file evidence when it cannot provide a complete
        # response.  Commit metadata alone never establishes freshness.
        _unverifiable("compare_files_unavailable")
    if comparison.get("files_complete") is False or len(files) >= _COMPARE_FILE_CAP:
        _unverifiable("compare_files_incomplete", file_count=len(files))
    try:
        total_commits = int(comparison.get("total_commits", 0))
    except (TypeError, ValueError):
        _unverifiable("compare_metadata_malformed")
    if total_commits > 0 and not files:
        # A non-empty commit range with no files is an incomplete answer, not a
        # report that those commits touched nothing.
        _unverifiable("compare_files_empty_for_commit_range", total_commits=total_commits)
    changed = sorted(
        {
            str(entry.get("filename", ""))
            for entry in files
            if isinstance(entry, dict)
            and str(entry.get("filename", "")).startswith(_STALENESS_PREFIXES)
        }
    )
    if changed:
        raise ControlPlaneError(
            STALE_DISPOSITION,
            "The trusted planning context changed after this run read it.",
            # Repository-relative paths of trusted contracts, bounded.  No model
            # output and no issue text.
            {
                "stage": "publication",
                "target_sha": target_sha,
                "default_branch_sha": default_branch_sha,
                "changed": changed[:16],
                "changed_count": len(changed),
            },
        )
    return {"compared": True, "reason": "base_moved_without_touching_context"}
