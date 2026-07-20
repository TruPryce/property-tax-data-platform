"""Execution-workflow claims, heartbeats, and terminal publication."""

from __future__ import annotations

import copy

from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.control import publish_canonical_state
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.leases import acquire_lease, heartbeat_lease
from countyforge_github.state import TERMINAL_STATES, decode_marker, transition_state


def _load_owned_state(
    github: GitHubPort,
    *,
    repository: str,
    status_comment_id: int,
    trusted_bot_id: int,
    idempotency_key: str,
    run_id: str,
) -> JsonObject:
    comment = github.get_comment(repository, status_comment_id)
    user = comment.get("user")
    if not isinstance(user, dict):
        raise ControlPlaneError(
            "invalid_status_comment", "CountyForge status ownership is invalid."
        )
    state = decode_marker(
        str(comment.get("body", "")),
        author_id=int(user.get("id", 0)),
        author_type=str(user.get("type", "")),
        trusted_bot_id=trusted_bot_id,
    )
    if state is None or state["idempotency_key"] != idempotency_key or state["run_id"] != run_id:
        raise ControlPlaneError(
            "workflow_state_mismatch", "Workflow inputs do not own canonical CountyForge state."
        )
    return state


def claim_run(
    github: GitHubPort,
    *,
    repository: str,
    status_comment_id: int,
    trusted_bot_id: int,
    idempotency_key: str,
    run_id: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    at: str,
    nonce: str | None = None,
) -> JsonObject:
    """Claim the queued canonical run for this exact execution workflow."""

    state = _load_owned_state(
        github,
        repository=repository,
        status_comment_id=status_comment_id,
        trusted_bot_id=trusted_bot_id,
        idempotency_key=idempotency_key,
        run_id=run_id,
    )
    if state["lifecycle_state"] != "queued":
        raise ControlPlaneError("workflow_state_mismatch", "CountyForge run is not queued.")
    expected = copy.deepcopy(state)
    state = acquire_lease(
        state,
        owner_workflow_run_id=workflow_run_id,
        owner_run_attempt=workflow_run_attempt,
        at=at,
        nonce=nonce,
    )
    state = transition_state(
        state,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "preparing",
            "at": at,
            "reason_code": "workflow_claimed",
        },
    )
    publish_canonical_state(
        github,
        repository=repository,
        target_number=int(state["target_number"]),
        trusted_bot_id=trusted_bot_id,
        expected_state=expected,
        state=state,
    )
    return state


def fail_unclaimed_run(
    github: GitHubPort,
    *,
    repository: str,
    status_comment_id: int,
    trusted_bot_id: int,
    idempotency_key: str,
    run_id: str,
    at: str,
    disposition: str = "workflow_claim_failed",
) -> JsonObject:
    """Make a dispatched run recoverable when failure occurs before lease ownership."""

    state = _load_owned_state(
        github,
        repository=repository,
        status_comment_id=status_comment_id,
        trusted_bot_id=trusted_bot_id,
        idempotency_key=idempotency_key,
        run_id=run_id,
    )
    if state["lifecycle_state"] != "queued" or state["lease"] is not None:
        return state
    expected = copy.deepcopy(state)
    failed = transition_state(
        state,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "failed",
            "at": at,
            "reason_code": disposition,
        },
    )
    publish_canonical_state(
        github,
        repository=repository,
        target_number=int(failed["target_number"]),
        trusted_bot_id=trusted_bot_id,
        expected_state=expected,
        state=failed,
    )
    return failed


def advance_run(
    github: GitHubPort,
    *,
    repository: str,
    status_comment_id: int,
    trusted_bot_id: int,
    idempotency_key: str,
    run_id: str,
    workflow_run_id: int,
    nonce: str,
    target_state: str,
    at: str,
    disposition: str,
    evidence_url: str | None = None,
) -> JsonObject:
    """Advance an owned workflow stage and publish only sanitized state."""

    state = _load_owned_state(
        github,
        repository=repository,
        status_comment_id=status_comment_id,
        trusted_bot_id=trusted_bot_id,
        idempotency_key=idempotency_key,
        run_id=run_id,
    )
    lease = state["lease"]
    if not isinstance(lease, dict) or lease["owner_workflow_run_id"] != workflow_run_id:
        raise ControlPlaneError("lease_ownership_mismatch", "Workflow does not own the lease.")
    expected = copy.deepcopy(state)
    if state["lifecycle_state"] == "cancel_requested" and target_state == "not_implemented":
        target_state = "cancelled"
        disposition = "cancelled"
    state = heartbeat_lease(
        state,
        owner_workflow_run_id=workflow_run_id,
        nonce=nonce,
        at=at,
        allow_expired_owner=target_state in TERMINAL_STATES,
    )
    state = transition_state(
        state,
        {
            "contract_version": 1,
            "from": state["lifecycle_state"],
            "to": target_state,
            "at": at,
            "reason_code": disposition,
        },
    )
    updated = copy.deepcopy(state)
    updated["disposition"] = disposition
    if evidence_url is not None:
        updated["evidence_url"] = evidence_url
    ControlContracts().validate("state", updated)
    publish_canonical_state(
        github,
        repository=repository,
        target_number=int(updated["target_number"]),
        trusted_bot_id=trusted_bot_id,
        expected_state=expected,
        state=updated,
    )
    return updated
