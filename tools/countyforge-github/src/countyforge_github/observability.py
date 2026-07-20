"""Sanitized structured events and fixed-cardinality metrics."""

from __future__ import annotations

from countyforge_github.contracts import ControlContracts, JsonObject

METRIC_LABELS = frozenset(
    {"command", "target_type", "authorization_outcome", "state", "outcome", "disposition"}
)
_STATE_OUTCOMES = {
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "timed_out": "timed_out",
    "stale": "failed",
    "not_implemented": "not_implemented",
    "deduplicated": "duplicate",
}


def control_event(**values: object) -> JsonObject:
    """Build a schema-valid event from bounded lifecycle values."""

    document: JsonObject = {"contract_version": 1, **values}
    ControlContracts().validate("event", document)
    return document


def metric_line(event: JsonObject) -> str:
    """Render one low-cardinality counter without structured identifiers."""

    labels = ",".join(f'{name}="{event[name]}"' for name in sorted(METRIC_LABELS))
    return f"countyforge_github_control_events_total{{{labels}}} 1\n"


def state_event(
    state: JsonObject,
    *,
    event_type: str,
    authorization_outcome: str,
    outcome: str,
    disposition: str,
    timestamp: str,
) -> JsonObject:
    """Build an event from canonical state without adding actor or path labels."""

    return control_event(
        event_type=event_type,
        command=state["command"],
        target_type=state["target_type"],
        authorization_outcome=authorization_outcome,
        state=state["lifecycle_state"],
        outcome=outcome,
        disposition=disposition,
        timestamp=timestamp,
        repository_id=state["repository_id"],
        target_number=state["target_number"],
        run_id=state["run_id"],
        workflow_run_id=state["workflow_run_id"],
        target_sha=state["target_head_sha"],
        idempotency_key=state["idempotency_key"],
        reason_code=disposition,
    )


def outcome_for_state(state: str) -> str:
    """Map lifecycle state to the bounded event outcome vocabulary."""

    return _STATE_OUTCOMES.get(state, "pending")


def with_audit(document: JsonObject, events: list[JsonObject]) -> JsonObject:
    """Attach schema-valid structured events and matching low-cardinality metrics."""

    return {**document, "events": events, "metrics": [metric_line(event) for event in events]}


def validate_metric_labels(labels: set[str]) -> None:
    """Reject every undeclared or high-cardinality label."""

    if not labels.issubset(METRIC_LABELS):
        raise ValueError("CountyForge control metric contains an undeclared label")
