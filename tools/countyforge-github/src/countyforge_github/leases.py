"""Target lease acquisition, heartbeats, release, and stale recovery."""

from __future__ import annotations

import copy
import secrets
from datetime import UTC, datetime, timedelta

from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.state import ACTIVE_STATES, TERMINAL_STATES, transition_state

DEFAULT_LEASE_TTL_SECONDS = 14_400
PRECLAIM_TTL_SECONDS = 1_800


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ControlPlaneError("invalid_timestamp", "A lease timestamp is invalid.") from None
    if parsed.tzinfo is None:
        raise ControlPlaneError("invalid_timestamp", "A lease timestamp is invalid.")
    return parsed.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def lease_expired(lease: JsonObject, at: str) -> bool:
    """Return whether one schema-valid lease has passed its expiry."""

    ControlContracts().validate("lease", lease)
    return _parse_time(at) >= _parse_time(str(lease["expires_at"]))


def acquire_lease(
    state: JsonObject,
    *,
    owner_workflow_run_id: int,
    owner_run_attempt: int,
    at: str,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    nonce: str | None = None,
) -> JsonObject:
    """Acquire only an empty lease; expired work must first be marked stale."""

    if ttl_seconds < 60 or ttl_seconds > 86_400:
        raise ControlPlaneError("invalid_lease_ttl", "Lease duration is outside policy.")
    if state["lifecycle_state"] in TERMINAL_STATES:
        raise ControlPlaneError("lease_terminal_state", "A completed run cannot acquire a lease.")
    existing = state["lease"]
    if existing is not None:
        reason = "lease_expired" if lease_expired(existing, at) else "lease_held"
        raise ControlPlaneError(reason, "The target already has a CountyForge lease.")
    acquired = _parse_time(at)
    lease: JsonObject = {
        "contract_version": 1,
        "owner_workflow_run_id": owner_workflow_run_id,
        "owner_run_attempt": owner_run_attempt,
        "idempotency_key": state["idempotency_key"],
        "command": state["command"],
        "target_sha": state["target_head_sha"],
        "acquired_at": at,
        "heartbeat_at": at,
        "expires_at": _format_time(acquired + timedelta(seconds=ttl_seconds)),
        "nonce": nonce or secrets.token_urlsafe(18),
    }
    ControlContracts().validate("lease", lease)
    updated = copy.deepcopy(state)
    updated["lease"] = lease
    updated["workflow_run_id"] = owner_workflow_run_id
    updated["workflow_run_attempt"] = owner_run_attempt
    updated["updated_at"] = at
    ControlContracts().validate("state", updated)
    return updated


def heartbeat_lease(
    state: JsonObject,
    *,
    owner_workflow_run_id: int,
    nonce: str,
    at: str,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> JsonObject:
    """Renew a lease only for its exact owner and nonce.

    An expired lease always fails closed, even for the exact owner. Post-expiry publication
    is forbidden so an expired lease truly means no owner writer remains; recovery of an
    expired run is the exclusive responsibility of the ``stale`` reclamation path (a new
    authorized command or maintenance). Without an atomic comment primitive this is what
    keeps a late owner publish from racing an out-of-lane maintenance reclaim and
    overwriting completed or reclaimed evidence.
    """

    lease = state["lease"]
    if not isinstance(lease, dict):
        raise ControlPlaneError("lease_missing", "No active CountyForge lease exists.")
    if lease["owner_workflow_run_id"] != owner_workflow_run_id or lease["nonce"] != nonce:
        raise ControlPlaneError("lease_ownership_mismatch", "Lease ownership does not match.")
    if lease_expired(lease, at):
        raise ControlPlaneError("lease_expired", "The CountyForge lease has expired.")
    updated = copy.deepcopy(state)
    updated_lease: JsonObject = updated["lease"]
    updated_lease["heartbeat_at"] = at
    updated_lease["expires_at"] = _format_time(_parse_time(at) + timedelta(seconds=ttl_seconds))
    updated["updated_at"] = at
    ControlContracts().validate("state", updated)
    return updated


def release_lease(
    state: JsonObject,
    *,
    owner_workflow_run_id: int,
    nonce: str,
    at: str,
) -> JsonObject:
    """Release a lease without changing lifecycle state."""

    lease = state["lease"]
    if not isinstance(lease, dict):
        return copy.deepcopy(state)
    if lease["owner_workflow_run_id"] != owner_workflow_run_id or lease["nonce"] != nonce:
        raise ControlPlaneError("lease_ownership_mismatch", "Lease ownership does not match.")
    updated = copy.deepcopy(state)
    updated["lease"] = None
    updated["updated_at"] = at
    ControlContracts().validate("state", updated)
    return updated


def mark_expired_stale(state: JsonObject, *, at: str) -> JsonObject:
    """Recover expired leased work or a queued run that was never claimed."""

    lease = state["lease"]
    if state["lifecycle_state"] not in ACTIVE_STATES:
        return copy.deepcopy(state)
    if (
        state["lifecycle_state"] == "queued"
        and lease is None
        and state["workflow_run_id"] is None
        and _parse_time(at)
        >= _parse_time(str(state["created_at"])) + timedelta(seconds=PRECLAIM_TTL_SECONDS)
    ):
        return transition_state(
            state,
            {
                "contract_version": 1,
                "from": "queued",
                "to": "failed",
                "at": at,
                "reason_code": "workflow_claim_timeout",
            },
        )
    if not isinstance(lease, dict):
        return copy.deepcopy(state)
    if not lease_expired(lease, at):
        return copy.deepcopy(state)
    return transition_state(
        state,
        {
            "contract_version": 1,
            "from": state["lifecycle_state"],
            "to": "stale",
            "at": at,
            "reason_code": "lease_expired",
        },
    )
