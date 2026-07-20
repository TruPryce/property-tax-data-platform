"""Canonical comment state, legal transitions, checks, and reconciliation."""

from __future__ import annotations

import base64
import copy
import json
import re
from typing import Final

from countyforge_runner.errors import KernelError

from countyforge_github.contracts import ControlContracts, JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError
from countyforge_github.identity import retry_idempotency_key

MARKER_PREFIX: Final = "<!-- countyforge-status:v1:"
MARKER_SUFFIX: Final = " -->"
MAX_MARKER_BYTES: Final = 24_576
_MARKER = re.compile(r"<!-- countyforge-status:v1:([A-Za-z0-9_-]+) -->")

ACTIVE_STATES = frozenset(
    {"received", "authorized", "queued", "preparing", "running", "cancel_requested"}
)
TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out", "stale", "not_implemented"}
)
RETRYABLE_STATES = frozenset({"failed", "cancelled", "timed_out", "stale", "not_implemented"})
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"authorized", "failed"}),
    "authorized": frozenset({"queued", "deduplicated", "failed"}),
    "deduplicated": frozenset(),
    "queued": frozenset(
        {
            "preparing",
            "running",
            "cancel_requested",
            "succeeded",
            "cancelled",
            "failed",
            "timed_out",
            "stale",
            "not_implemented",
        }
    ),
    "preparing": frozenset(
        {
            "running",
            "cancel_requested",
            "succeeded",
            "cancelled",
            "failed",
            "timed_out",
            "stale",
            "not_implemented",
        }
    ),
    "running": frozenset(
        {
            "succeeded",
            "failed",
            "cancel_requested",
            "cancelled",
            "timed_out",
            "stale",
            "not_implemented",
        }
    ),
    "cancel_requested": frozenset({"cancelled", "failed", "succeeded", "timed_out", "stale"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "timed_out": frozenset(),
    "stale": frozenset(),
    "not_implemented": frozenset(),
}


def initial_state(
    trigger: JsonObject,
    execution_policy: JsonObject,
    idempotency_key: str,
) -> JsonObject:
    """Create a received state for one eligible execution command."""

    command = str(trigger["command"]["command"])
    selection = execution_policy["commands"][command]
    timestamp = str(trigger["timestamp"])
    state: JsonObject = {
        "contract_version": 1,
        "repository_id": trigger["repository"]["id"],
        "target_type": trigger["target"]["type"],
        "target_number": trigger["target"]["number"],
        "command": command,
        "command_arguments": copy.deepcopy(trigger["command"]["arguments"]),
        "profile_id": selection["profile_id"],
        "profile_version": selection["profile_version"],
        "target_head_sha": trigger["target"]["head_sha"],
        "run_id": f"gh-{idempotency_key[:24]}-a1",
        "idempotency_key": idempotency_key,
        "original_idempotency_key": idempotency_key,
        "attempt": 1,
        "lifecycle_state": "received",
        "workflow_run_id": None,
        "workflow_run_attempt": 1,
        "check_run_id": None,
        "lease": None,
        "disposition": None,
        "evidence_url": None,
        "original_comment_id": trigger["comment"]["id"],
        "original_delivery_id": trigger["comment"]["delivery_id"],
        "original_actor_id": trigger["actor"]["id"],
        "trusted_tool_sha": trigger["trusted_tool_sha"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "history": [],
    }
    return state


def begin_new_state(
    trigger: JsonObject,
    execution_policy: JsonObject,
    idempotency_key: str,
    previous: JsonObject | None,
) -> JsonObject:
    """Begin a distinct semantic command while preserving terminal run history."""

    state = initial_state(trigger, execution_policy, idempotency_key)
    if previous is None:
        return state
    if previous["lifecycle_state"] not in TERMINAL_STATES:
        raise ControlPlaneError(
            "active_run_exists", "This target already has active CountyForge work."
        )
    history = list(previous["history"])
    history.append(
        {
            "run_id": previous["run_id"],
            "idempotency_key": previous["idempotency_key"],
            "attempt": previous["attempt"],
            "lifecycle_state": previous["lifecycle_state"],
            "disposition": previous["disposition"],
            "evidence_url": previous["evidence_url"],
            "finished_at": previous["updated_at"],
        }
    )
    state["history"] = history[-20:]
    return state


def transition_state(
    state: JsonObject,
    transition: JsonObject,
    *,
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Apply one declared legal edge without mutating the input document."""

    resolved = contracts or ControlContracts()
    resolved.validate("state", state)
    resolved.validate("transition", transition)
    current = str(state["lifecycle_state"])
    if transition["from"] != current:
        raise ControlPlaneError("transition_conflict", "State changed before this transition.")
    target = str(transition["to"])
    if target not in LEGAL_TRANSITIONS[current]:
        raise ControlPlaneError(
            "illegal_transition", "The requested lifecycle transition is illegal."
        )
    updated = copy.deepcopy(state)
    updated["lifecycle_state"] = target
    updated["updated_at"] = transition["at"]
    if target in TERMINAL_STATES:
        updated["lease"] = None
        updated["disposition"] = str(transition["reason_code"])
    resolved.validate("state", updated)
    return updated


def encode_marker(state: JsonObject, contracts: ControlContracts | None = None) -> str:
    """Encode bounded canonical state for a bot-owned hidden comment marker."""

    resolved = contracts or ControlContracts()
    resolved.validate("state", state)
    raw = canonical_bytes(state)
    if len(raw) > MAX_MARKER_BYTES:
        raise ControlPlaneError("state_too_large", "Canonical CountyForge state is too large.")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{MARKER_PREFIX}{encoded}{MARKER_SUFFIX}"


def decode_marker(
    body: str,
    *,
    author_id: int,
    author_type: str,
    trusted_bot_id: int,
    contracts: ControlContracts | None = None,
) -> JsonObject | None:
    """Trust a marker only from the immutable configured bot identity."""

    if author_type != "Bot" or author_id != trusted_bot_id:
        return None
    prefix_count = body.count(MARKER_PREFIX)
    if prefix_count == 0:
        return None
    matches = list(_MARKER.finditer(body))
    if prefix_count != 1 or len(matches) != 1:
        raise ControlPlaneError("invalid_status_marker", "Canonical CountyForge state is invalid.")
    match = matches[0]
    encoded = match.group(1)
    if len(encoded) > MAX_MARKER_BYTES * 2:
        raise ControlPlaneError("state_too_large", "Canonical CountyForge state is too large.")
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(raw) > MAX_MARKER_BYTES:
            raise ValueError
        value = json.loads(raw)
    except (ValueError, UnicodeError, json.JSONDecodeError):
        raise ControlPlaneError(
            "invalid_status_marker", "Canonical CountyForge state is invalid."
        ) from None
    if not isinstance(value, dict):
        raise ControlPlaneError("invalid_status_marker", "Canonical CountyForge state is invalid.")
    state: JsonObject = value
    try:
        (contracts or ControlContracts()).validate("state", state)
    except KernelError:
        raise ControlPlaneError(
            "invalid_status_marker", "Canonical CountyForge state is invalid."
        ) from None
    return state


def render_status(state: JsonObject, contracts: ControlContracts | None = None) -> str:
    """Render bounded human status and the machine-owned canonical marker."""

    marker = encode_marker(state, contracts)
    short_sha = str(state["target_head_sha"])[:12]
    guidance = ""
    if state["lifecycle_state"] in {"queued", "preparing", "running"}:
        guidance = "\n\nAuthorized maintainers may use `/countyforge cancel`."
    elif state["lifecycle_state"] in RETRYABLE_STATES:
        guidance = (
            "\n\nAuthorized maintainers may use `/countyforge retry` "
            "while the target SHA is unchanged."
        )
    evidence = (
        f"[Sanitized evidence]({state['evidence_url']})"
        if state["evidence_url"] is not None
        else "Pending"
    )
    return (
        "## CountyForge status\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        f"| Command | `{state['command']}` |\n"
        f"| Profile | `{state['profile_id']}@{state['profile_version']}` |\n"
        f"| Target | `{short_sha}` |\n"
        f"| State | `{state['lifecycle_state']}` |\n"
        f"| Attempt | `{state['attempt']}` |\n"
        f"| Updated | `{state['updated_at']}` |\n"
        f"| Evidence | {evidence} |"
        f"{guidance}\n\n{marker}"
    )


def check_status(state: str) -> tuple[str, str | None]:
    """Map lifecycle state to GitHub check status and conclusion."""

    if state in {"received", "authorized", "queued", "preparing", "running", "cancel_requested"}:
        return "in_progress", None
    conclusions = {
        "succeeded": "success",
        "failed": "failure",
        "cancelled": "cancelled",
        "timed_out": "timed_out",
        "stale": "neutral",
        "not_implemented": "neutral",
        "deduplicated": "neutral",
    }
    if state not in conclusions:
        raise ControlPlaneError("invalid_check_state", "Lifecycle state cannot map to a check.")
    return "completed", conclusions[state]


def reconcile_workflow(state: JsonObject, workflow: JsonObject, at: str) -> JsonObject:
    """Reconcile only an owned workflow run using bounded API facts."""

    expected = state["workflow_run_id"]
    if expected is None or int(workflow.get("id", 0)) != expected:
        raise ControlPlaneError(
            "workflow_ownership_mismatch", "Workflow run is not owned by this target."
        )
    if int(workflow.get("repository_id", 0)) != state["repository_id"]:
        raise ControlPlaneError(
            "workflow_ownership_mismatch", "Workflow run is not owned by this target."
        )
    if (
        str(workflow.get("event", "")) != "workflow_dispatch"
        or str(workflow.get("path", "")) != ".github/workflows/countyforge-run.yml"
        or str(workflow.get("display_title", "")).find(str(state["run_id"])) < 0
    ):
        raise ControlPlaneError(
            "workflow_ownership_mismatch", "Workflow run is not the owned CountyForge run."
        )
    status = str(workflow.get("status", ""))
    conclusion = workflow.get("conclusion")
    if status != "completed":
        target = (
            "running"
            if status == "in_progress" and state["lifecycle_state"] != "cancel_requested"
            else str(state["lifecycle_state"])
        )
    else:
        target = {
            "success": "succeeded",
            "failure": "failed",
            "cancelled": "cancelled",
            "timed_out": "timed_out",
            "neutral": "not_implemented",
        }.get(str(conclusion), "failed")
    if target == state["lifecycle_state"] or state["lifecycle_state"] in TERMINAL_STATES:
        return copy.deepcopy(state)
    return transition_state(
        state,
        {
            "contract_version": 1,
            "from": state["lifecycle_state"],
            "to": target,
            "at": at,
            "reason_code": f"workflow_{conclusion or status}",
        },
    )


def retry_state(state: JsonObject, *, current_head_sha: str, at: str) -> JsonObject:
    """Create a distinct retry state and preserve the completed attempt."""

    current = str(state["lifecycle_state"])
    if current not in RETRYABLE_STATES:
        raise ControlPlaneError("retry_not_allowed", "The current run is not retry-eligible.")
    if current_head_sha != state["target_head_sha"]:
        raise ControlPlaneError(
            "retry_stale_head",
            "Target changed; issue a new CountyForge execution command.",
        )
    attempt = int(state["attempt"]) + 1
    new_key = retry_idempotency_key(str(state["original_idempotency_key"]), attempt)
    updated = copy.deepcopy(state)
    history = list(updated["history"])
    history.append(
        {
            "run_id": state["run_id"],
            "idempotency_key": state["idempotency_key"],
            "attempt": state["attempt"],
            "lifecycle_state": state["lifecycle_state"],
            "disposition": state["disposition"],
            "evidence_url": state["evidence_url"],
            "finished_at": state["updated_at"],
        }
    )
    updated.update(
        {
            "run_id": f"gh-{new_key[:24]}-a{attempt}",
            "idempotency_key": new_key,
            "attempt": attempt,
            "lifecycle_state": "received",
            "workflow_run_id": None,
            "workflow_run_attempt": attempt,
            "check_run_id": None,
            "lease": None,
            "disposition": None,
            "evidence_url": None,
            "created_at": at,
            "updated_at": at,
            "history": history[-20:],
        }
    )
    ControlContracts().validate("state", updated)
    return updated
