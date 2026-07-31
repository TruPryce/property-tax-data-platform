"""Read-only scheduled stale-lease discovery without dispatch or state writes."""

from __future__ import annotations

from countyforge_github.contracts import JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError
from countyforge_github.freshness import resolve_default_branch
from countyforge_github.github_api import GitHubPort
from countyforge_github.leases import mark_expired_stale
from countyforge_github.observability import control_event, state_event, with_audit
from countyforge_github.state import ACTIVE_STATES, RETRYABLE_STATES, decode_marker, render_status

# A repository-wide scan must stay bounded; refreshing a display is cheap but a
# runaway loop over every historical comment is not.
MAX_DISPLAY_REFRESHES = 16
_REFRESHABLE_STATES = ACTIVE_STATES | RETRYABLE_STATES


def _refresh_display(
    github: GitHubPort,
    *,
    repository: str,
    comment_id: int,
    state: JsonObject,
    trusted_bot_id: int,
    freshness: JsonObject,
) -> bool:
    """Re-render one canonical comment from unchanged state and fresh metadata.

    This is a display-only write.  The rendered marker encodes exactly the state
    that was read, so history, revision, lifecycle, and idempotency identity are
    untouched and a repository-wide scan cannot mutate a run.  The comment is
    reread immediately before the PATCH, and a state that moved in the meantime
    is left to its own target lane rather than overwritten.
    """

    body = render_status(state, None, freshness)
    comment = github.get_comment(repository, comment_id)
    if str(comment.get("body", "")) == body:
        return False
    user = comment.get("user")
    if not isinstance(user, dict):
        return False
    current = decode_marker(
        str(comment.get("body", "")),
        author_id=int(user.get("id", 0)),
        author_type=str(user.get("type", "")),
        trusted_bot_id=trusted_bot_id,
    )
    if current is None or canonical_bytes(current) != canonical_bytes(state):
        return False
    github.update_comment(repository, comment_id, body)
    return True


def audit_expired_leases(
    github: GitHubPort,
    *,
    repository: str,
    trusted_bot_id: int,
    at: str,
    refresh_displays: bool = False,
) -> JsonObject:
    """Discover candidates; leave every canonical mutation to a target state lane.

    Scheduled maintenance deliberately remains repository-wide and read-only.  A status
    command or a later authorized command performs the actual stale/claim-timeout
    transition inside the existing ``countyforge-state-*`` lane.  This prevents a
    repository-wide scan from racing a per-target claim, heartbeat, cancellation, or
    terminal publication while retaining an auditable discovery signal.
    """

    inspected = 0
    candidates = 0
    invalid_state = 0
    refreshed = 0
    events: list[JsonObject] = []
    # Resolved once per scan: every refreshed comment then reports the same
    # observation instant instead of drifting across a long repository sweep.
    freshness = (
        resolve_default_branch(github, repository=repository, at=at) if refresh_displays else None
    )
    for comment in github.list_repository_comments(repository):
        user = comment.get("user")
        if not isinstance(user, dict):
            continue
        try:
            state = decode_marker(
                str(comment.get("body", "")),
                author_id=int(user.get("id", 0)),
                author_type=str(user.get("type", "")),
                trusted_bot_id=trusted_bot_id,
            )
        except ControlPlaneError as error:
            invalid_state += 1
            events.append(
                control_event(
                    event_type="invalid_state_detected",
                    command="maintenance",
                    target_type="repository",
                    authorization_outcome="not_applicable",
                    state="failed",
                    outcome="failed",
                    disposition="invalid_status_marker",
                    timestamp=at,
                    reason_code=error.code,
                )
            )
            continue
        if state is None:
            continue
        inspected += 1
        if (
            freshness is not None
            and refreshed < MAX_DISPLAY_REFRESHES
            and str(state["lifecycle_state"]) in _REFRESHABLE_STATES
            and _refresh_display(
                github,
                repository=repository,
                comment_id=int(comment["id"]),
                state=state,
                trusted_bot_id=trusted_bot_id,
                freshness=freshness,
            )
        ):
            refreshed += 1
            events.append(
                state_event(
                    state,
                    event_type="state_reconciled",
                    authorization_outcome="not_applicable",
                    outcome="pending",
                    disposition="display_refreshed",
                    timestamp=at,
                )
            )
        updated = mark_expired_stale(state, at=at)
        if updated == state:
            continue
        candidates += 1
        events.append(
            state_event(
                state,
                event_type="state_reconciled",
                authorization_outcome="not_applicable",
                outcome="pending",
                disposition="maintenance_candidate",
                timestamp=at,
            )
        )
    return with_audit(
        {
            "ok": True,
            "inspected": inspected,
            "reconciliation_candidates": candidates,
            "marked_stale": 0,
            "marked_failed": 0,
            "write_conflicts": 0,
            "invalid_state": invalid_state,
            "dispatched": 0,
            "displays_refreshed": refreshed,
            "mutation": "display_refresh" if refreshed else "audit_only",
        },
        events,
    )


# Keep the operator-facing import stable while making the no-write behavior explicit.
reconcile_expired_leases = audit_expired_leases
