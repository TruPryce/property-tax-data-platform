"""Live default-branch identity for canonical display and reconciliation.

Retry eligibility depends on whether the repository's default branch still points
at the SHA a run targeted, but canonical state records only the target.  A reader
therefore could not tell a retryable run from an unretryable one without checking
GitHub by hand.  This module resolves that fact at render time.

It is display and reconciliation metadata only.  Nothing here is persisted into
canonical state, participates in semantic run identity, or authorizes execution:
`/countyforge retry` resolves the live target independently through the trusted
port and compares it itself.
"""

from __future__ import annotations

import re

from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort

_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def unavailable_freshness(at: str) -> JsonObject:
    """Return the bounded record used when GitHub cannot be consulted."""

    return {
        "available": False,
        "default_branch": None,
        "default_branch_sha": None,
        "checked_at": at,
    }


def resolve_default_branch(github: GitHubPort, *, repository: str, at: str) -> JsonObject:
    """Resolve the live default branch and its head SHA.

    Never raises.  Canonical status must still publish when GitHub is degraded,
    so a failed lookup becomes an explicitly unavailable record rather than a
    missing or, worse, a silently stale value.
    """

    if not all(hasattr(github, name) for name in ("repository_profile", "get_git_ref")):
        return unavailable_freshness(at)
    try:
        profile = github.repository_profile(repository)
        branch = profile.get("default_branch") if isinstance(profile, dict) else None
        if not isinstance(branch, str) or _BRANCH.fullmatch(branch) is None:
            return unavailable_freshness(at)
        ref = github.get_git_ref(repository, f"refs/heads/{branch}")
        target = ref.get("object") if isinstance(ref, dict) else None
        sha = target.get("sha") if isinstance(target, dict) else None
        if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
            return unavailable_freshness(at)
    except ControlPlaneError:
        return unavailable_freshness(at)
    return {
        "available": True,
        "default_branch": branch,
        "default_branch_sha": sha,
        "checked_at": at,
    }
