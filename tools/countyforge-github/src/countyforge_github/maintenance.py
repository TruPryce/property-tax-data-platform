"""Read-only scheduled stale-lease discovery without dispatch or state writes."""

from __future__ import annotations

from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.leases import mark_expired_stale
from countyforge_github.observability import control_event, state_event, with_audit
from countyforge_github.state import decode_marker


def audit_expired_leases(
    github: GitHubPort,
    *,
    repository: str,
    trusted_bot_id: int,
    at: str,
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
    events: list[JsonObject] = []
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
            "mutation": "audit_only",
        },
        events,
    )


# Keep the operator-facing import stable while making the no-write behavior explicit.
reconcile_expired_leases = audit_expired_leases
