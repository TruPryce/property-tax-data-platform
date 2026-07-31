"""Read-only scheduled stale-lease discovery without dispatch or state writes."""

from __future__ import annotations

from datetime import UTC, datetime

from countyforge_github.contracts import JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError
from countyforge_github.freshness import resolve_default_branch
from countyforge_github.github_api import GitHubPort
from countyforge_github.leases import mark_expired_stale
from countyforge_github.observability import control_event, state_event, with_audit
from countyforge_github.state import (
    CHECKED_ROW_PREFIX,
    RETRYABLE_STATES,
    decode_marker,
    render_status,
)

# A repository-wide scan must stay bounded; refreshing a display is cheap but a
# runaway loop over every historical comment is not.
MAX_DISPLAY_REFRESHES = 16

# Only settled runs are refreshed.  An active run's own `countyforge-state-*`
# lane rewrites its comment on every transition, so its display is never stale;
# refreshing it from this out-of-lane sweep could only lose that race and revert
# lifecycle, revision, disposition, and history to an older marker.
_REFRESHABLE_STATES = RETRYABLE_STATES

# A settled comment written moments ago is almost certainly a new run claiming
# the target.  Leaving it alone keeps the sweep clear of the one window where
# reverting a marker would break a live writer.
MIN_COMMENT_AGE_SECONDS = 300

# How long a displayed observation may lag before it is renewed even though the
# facts are unchanged.  Without this the timestamp would freeze; without the
# unchanged-facts check the newest comments would be rewritten every sweep and
# permanently starve older ones, because the listing is newest-updated first.
MAX_DISPLAY_AGE_SECONDS = 21_600


def _instant(value: object) -> datetime | None:
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=UTC)


def _age_seconds(earlier: object, later: object) -> float | None:
    start, end = _instant(earlier), _instant(later)
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _display_signature(body: str) -> str:
    """Everything the display asserts except when it was observed."""

    return "\n".join(line for line in body.splitlines() if not line.startswith(CHECKED_ROW_PREFIX))


def _displayed_checked_at(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith(CHECKED_ROW_PREFIX):
            return line.split("|")[2].strip().strip("`")
    return None


def _refresh_display(
    github: GitHubPort,
    *,
    repository: str,
    comment_id: int,
    state: JsonObject,
    trusted_bot_id: int,
    freshness: JsonObject,
    at: str,
) -> bool:
    """Re-render one settled canonical comment from unchanged state.

    This is a display-only write.  The rendered marker encodes exactly the state
    that was read, so history, revision, lifecycle, and idempotency identity are
    untouched and a repository-wide scan cannot mutate a run.  The comment is
    reread immediately before the PATCH, and a state that moved in the meantime
    is left to its own target lane rather than overwritten.

    A write happens only when the branch, its SHA, or retry eligibility actually
    changed, or when the displayed observation has aged past its bound.  A sweep
    that rewrote every comment it read would keep the same newest ones at the
    front of the newest-updated listing forever and never reach older ones.
    """

    comment = github.get_comment(repository, comment_id)
    existing = str(comment.get("body", ""))
    comment_age = _age_seconds(comment.get("updated_at"), at)
    if comment_age is not None and comment_age < MIN_COMMENT_AGE_SECONDS:
        return False
    body = render_status(state, None, freshness)
    aged = _age_seconds(_displayed_checked_at(existing), at)
    if _display_signature(existing) == _display_signature(body) and (
        aged is not None and aged < MAX_DISPLAY_AGE_SECONDS
    ):
        return False
    user = comment.get("user")
    if not isinstance(user, dict):
        return False
    current = decode_marker(
        existing,
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
                at=at,
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
