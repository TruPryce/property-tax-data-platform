"""Execution-workflow claims, heartbeats, and terminal publication."""

from __future__ import annotations

import copy

from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.control import publish_canonical_state
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.leases import acquire_lease, heartbeat_lease, lease_expired
from countyforge_github.state import decode_marker, transition_state


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


def verify_publication_lease(
    github: GitHubPort,
    *,
    repository: str,
    status_comment_id: int,
    trusted_bot_id: int,
    idempotency_key: str,
    run_id: str,
    workflow_run_id: int,
    nonce: str,
    at: str,
) -> JsonObject:
    """Authorize a publication before any Git data API mutation.

    The caller runs in the per-target state lane.  This read is deliberately not a
    heartbeat or state mutation: cancellation and terminal publication must be able
    to win the same lane before this gate runs.  Once it succeeds, the publication
    job performs only the bounded deterministic writes for this owned live lease.
    """

    state = _load_owned_state(
        github,
        repository=repository,
        status_comment_id=status_comment_id,
        trusted_bot_id=trusted_bot_id,
        idempotency_key=idempotency_key,
        run_id=run_id,
    )
    if state["lifecycle_state"] != "running":
        raise ControlPlaneError(
            "publication_not_active", "Planning publication is no longer active."
        )
    lease = state.get("lease")
    if (
        not isinstance(lease, dict)
        or int(lease.get("owner_workflow_run_id", 0)) != workflow_run_id
        or str(lease.get("nonce", "")) != nonce
        or lease_expired(lease, at)
    ):
        raise ControlPlaneError(
            "publication_lease_invalid", "Planning publication does not own a live lease."
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
    planning_change_name: str | None = None,
    planning_branch: str | None = None,
    planning_pr_number: int | None = None,
    planning_context_sha256: str | None = None,
    planning_result_sha256: str | None = None,
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
    # A publish (including a terminal one) requires a live lease. If the lease has expired,
    # this owner is no longer the sole writer: an out-of-lane maintenance reclaim may already
    # have marked the run stale, and a plain reread/compare/PATCH cannot atomically settle
    # that race. Fail closed here so the stale-reclamation path is the only recovery of an
    # expired run, and completed evidence is never overwritten.
    state = heartbeat_lease(
        state,
        owner_workflow_run_id=workflow_run_id,
        nonce=nonce,
        at=at,
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
    if planning_change_name is not None:
        updated["planning_change_name"] = planning_change_name
    if planning_branch is not None:
        updated["planning_branch"] = planning_branch
    if planning_pr_number is not None:
        updated["planning_pr_number"] = planning_pr_number
    if planning_context_sha256 is not None:
        updated["planning_context_sha256"] = planning_context_sha256
    if planning_result_sha256 is not None:
        updated["planning_result_sha256"] = planning_result_sha256
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
