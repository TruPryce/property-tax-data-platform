"""Canonical comment state, legal transitions, checks, and reconciliation."""

from __future__ import annotations

import base64
import copy
import json
import re
from typing import Final
from urllib.parse import quote, urlsplit

from countyforge_runner.errors import KernelError

from countyforge_github.contracts import ControlContracts, JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError
from countyforge_github.identity import retry_idempotency_key

MARKER_PREFIX: Final = "<!-- countyforge-status:v1:"
MARKER_SUFFIX: Final = " -->"
MAX_MARKER_BYTES: Final = 24_576
MAX_HISTORY_ENTRIES: Final = 20
MAX_RECENT_RUNS: Final = 5
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


def _history_entry(state: JsonObject) -> JsonObject:
    """Capture immutable display facts before replacing the canonical current run."""

    return {
        "run_id": state["run_id"],
        "command": state["command"],
        "profile_id": state["profile_id"],
        "profile_version": state["profile_version"],
        "target_head_sha": state["target_head_sha"],
        "idempotency_key": state["idempotency_key"],
        "attempt": state["attempt"],
        "revision": state["revision"],
        "lifecycle_state": state["lifecycle_state"],
        "disposition": state["disposition"],
        "evidence_url": state["evidence_url"],
        "finished_at": state["updated_at"],
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
        "revision": 1,
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
        "planning_revision": 1 if command == "plan" else None,
        "planning_change_name": None,
        "planning_branch": None,
        "planning_pr_number": None,
        "planning_predecessor_run_id": None,
        "planning_context_sha256": (
            str(trigger.get("planning_context_sha256"))
            if command == "plan" and trigger.get("planning_context_sha256") is not None
            else None
        ),
        "planning_result_sha256": None,
        "implementation_eligible": False,
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
    command = str(trigger["command"]["command"])
    if previous is None:
        return state
    if previous["lifecycle_state"] not in TERMINAL_STATES:
        raise ControlPlaneError(
            "active_run_exists", "This target already has active CountyForge work."
        )
    history = list(previous["history"])
    history.append(_history_entry(previous))
    state["history"] = history[-MAX_HISTORY_ENTRIES:]
    state["revision"] = int(previous["revision"]) + 1
    if command == "plan":
        state["planning_revision"] = int(previous.get("planning_revision") or 1) + 1
        state["planning_predecessor_run_id"] = previous["run_id"]
    return state


def transition_state(
    state: JsonObject,
    transition: JsonObject,
    *,
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Apply one declared legal edge without mutating the input document."""

    resolved = contracts or ControlContracts()
    if "expected_revision" not in transition:
        transition = {**transition, "expected_revision": state.get("revision", 1)}
    resolved.validate("state", state)
    resolved.validate("transition", transition)
    current = str(state["lifecycle_state"])
    expected_revision = int(transition["expected_revision"])
    if expected_revision != int(state["revision"]):
        raise ControlPlaneError(
            "revision_conflict", "State revision changed before this transition."
        )
    if transition["from"] != current:
        raise ControlPlaneError("transition_conflict", "State changed before this transition.")
    target = str(transition["to"])
    if target not in LEGAL_TRANSITIONS[current]:
        raise ControlPlaneError(
            "illegal_transition", "The requested lifecycle transition is illegal."
        )
    updated = copy.deepcopy(state)
    updated["lifecycle_state"] = target
    updated["revision"] = expected_revision + 1
    updated["updated_at"] = transition["at"]
    if target in TERMINAL_STATES:
        updated["lease"] = None
        updated["disposition"] = str(transition["reason_code"])
    resolved.validate("state", updated)
    return updated


def bump_revision(state: JsonObject, *, at: str) -> JsonObject:
    """Record one non-lifecycle canonical mutation with the next revision."""

    updated = copy.deepcopy(state)
    updated["revision"] = int(state["revision"]) + 1
    updated["updated_at"] = at
    (ControlContracts()).validate("state", updated)
    return updated


def _display_value(value: object, fallback: str, max_length: int) -> str:
    """Return one bounded Markdown-table value with control syntax neutralized."""

    text = fallback if value is None else str(value)
    text = " ".join(text.split()).replace("`", "'").replace("|", "\\|")
    return text[:max_length] or fallback


def _display_evidence(entry: JsonObject) -> str:
    """Render only an approved GitHub evidence URL; otherwise show a bounded result."""

    value = entry.get("evidence_url")
    if (
        isinstance(value, str)
        and len(value) <= 1024
        and not any(character in value for character in "\r\n`")
    ):
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc == "github.com":
            safe_url = quote(value, safe=":/?#[]@!$&'*+,;=%-._~")
            return f"[Evidence]({safe_url})"
    result = entry.get("disposition") or entry.get("lifecycle_state") or "unavailable"
    return f"`{_display_value(result, 'unavailable', 64)}`"


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
    short_sha = _display_value(str(state["target_head_sha"])[:12], "unknown", 12)
    guidance = ""
    if state["lifecycle_state"] in {"queued", "preparing", "running"}:
        guidance = "\n\nAuthorized maintainers may use `/countyforge cancel`."
    elif state["lifecycle_state"] in RETRYABLE_STATES:
        guidance = (
            "\n\nAuthorized maintainers may use `/countyforge retry` "
            "while the target SHA is unchanged."
        )
    evidence = "Pending" if state["evidence_url"] is None else _display_evidence(state)
    planning_rows = ""
    if state["command"] == "plan":
        pr_number = state.get("planning_pr_number")
        draft_pr = (
            f"[#{pr_number}](https://github.com/TruPryce/property-tax-data-platform/pull/{pr_number})"
            if pr_number
            else "Pending"
        )
        planning_rows = (
            f"| Planning revision | `{_display_value(state.get('planning_revision'), '1', 12)}` |\n"
            "| Proposed change | `"
            f"{_display_value(state.get('planning_change_name'), 'Pending', 96)}` |\n"
            f"| Draft PR | {draft_pr} |\n"
            "| Implementation eligible | `false` |\n"
        )
    recent_rows: list[str] = []
    for entry in reversed(list(state.get("history", []))):
        if not isinstance(entry, dict):
            continue
        result = entry.get("disposition") or entry.get("lifecycle_state") or "unknown"
        profile_id = entry.get("profile_id") or "legacy"
        profile_version = entry.get("profile_version")
        profile = (
            f"{_display_value(profile_id, 'legacy', 80)}@{_display_value(profile_version, '?', 12)}"
            if profile_version is not None
            else _display_value(profile_id, "legacy", 80)
        )
        recent_rows.append(
            f"| `{_display_value(entry.get('command'), 'legacy', 32)}` | `{profile}` | "
            "`"
            f"{_display_value(str(entry.get('target_head_sha', 'unknown'))[:12], 'unknown', 12)}` "
            "| "
            f"`{_display_value(result, 'unknown', 64)}` | "
            f"`{_display_value(entry.get('attempt'), '?', 12)}` | "
            f"`{_display_value(entry.get('finished_at'), 'unknown', 40)}` | "
            f"{_display_evidence(entry)} |"
        )
        if len(recent_rows) == MAX_RECENT_RUNS:
            break
    recent_runs = ""
    if recent_rows:
        recent_runs = (
            "\n\n### Recent runs\n\n"
            "| Command | Profile | Target | Result | Attempt | Finished | Evidence |\n"
            "|---|---|---|---|---:|---|---|\n" + "\n".join(recent_rows)
        )
    return (
        "## CountyForge status\n\n"
        "| Field | Value |\n"
        "|---|---|\n"
        f"| Command | `{_display_value(state.get('command'), 'unknown', 32)}` |\n"
        "| Profile | `"
        f"{_display_value(state.get('profile_id'), 'unknown', 80)}@"
        f"{_display_value(state.get('profile_version'), '?', 12)}` |\n"
        f"| Target | `{short_sha}` |\n"
        f"| State | `{_display_value(state.get('lifecycle_state'), 'unknown', 32)}` |\n"
        f"| Attempt | `{_display_value(state.get('attempt'), '?', 12)}` |\n"
        f"{planning_rows}"
        f"| Updated | `{_display_value(state.get('updated_at'), 'unknown', 40)}` |\n"
        f"| Evidence | {evidence} |"
        f"{guidance}{recent_runs}\n\n{marker}"
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
    history.append(_history_entry(state))
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
            "history": history[-MAX_HISTORY_ENTRIES:],
            "revision": int(state["revision"]) + 1,
        }
    )
    if updated["command"] == "plan":
        updated["planning_revision"] = int(state.get("planning_revision") or 1) + 1
        updated["planning_predecessor_run_id"] = state["run_id"]
    ControlContracts().validate("state", updated)
    return updated
