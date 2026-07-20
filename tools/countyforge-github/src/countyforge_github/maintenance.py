"""Idempotent scheduled stale-lease reconciliation without dispatch."""

from __future__ import annotations

from countyforge_github.contracts import JsonObject
from countyforge_github.control import publish_canonical_state
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.leases import mark_expired_stale
from countyforge_github.observability import control_event, state_event, with_audit
from countyforge_github.state import decode_marker


def reconcile_expired_leases(
    github: GitHubPort,
    *,
    repository: str,
    trusted_bot_id: int,
    at: str,
) -> JsonObject:
    """Mark owned expired leases stale and never start replacement work."""

    inspected = 0
    stale = 0
    failed = 0
    conflicts = 0
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
        try:
            publish_canonical_state(
                github,
                repository=repository,
                target_number=int(updated["target_number"]),
                trusted_bot_id=trusted_bot_id,
                expected_state=state,
                state=updated,
            )
        except ControlPlaneError as error:
            if error.code != "state_write_conflict":
                raise
            conflicts += 1
            continue
        disposition = str(updated["disposition"] or "lease_expired")
        if updated["lifecycle_state"] == "stale":
            stale += 1
        else:
            failed += 1
        events.append(
            state_event(
                updated,
                event_type=(
                    "lease_reclaimed"
                    if updated["lifecycle_state"] == "stale"
                    else "terminal_outcome"
                ),
                authorization_outcome="not_applicable",
                outcome="failed",
                disposition=disposition,
                timestamp=at,
            )
        )
    return with_audit(
        {
            "ok": True,
            "inspected": inspected,
            "marked_stale": stale,
            "marked_failed": failed,
            "write_conflicts": conflicts,
            "invalid_state": invalid_state,
            "dispatched": 0,
        },
        events,
    )
