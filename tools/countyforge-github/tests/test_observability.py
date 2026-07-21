"""Control-plane event and metric cardinality tests."""

from __future__ import annotations

import pytest
from countyforge_github.observability import control_event, metric_line, validate_metric_labels


def test_control_metric_uses_only_bounded_labels() -> None:
    event = control_event(
        event_type="authorization_decided",
        command="review",
        target_type="pull_request",
        authorization_outcome="denied",
        state="received",
        outcome="denied",
        disposition="permission_denied",
        timestamp="2026-07-19T12:00:00Z",
        repository_id=987654,
        target_number=11,
        run_id=None,
        workflow_run_id=None,
        target_sha=None,
        idempotency_key=None,
        reason_code="permission_denied",
    )
    metrics = metric_line(event)
    assert "repository_id" not in metrics
    assert "target_number" not in metrics
    assert "run_id" not in metrics
    assert "idempotency_key" not in metrics


@pytest.mark.parametrize(
    "label", ["actor", "target_number", "comment_id", "workflow_run_id", "sha", "path", "error"]
)
def test_high_cardinality_metric_labels_fail(label: str) -> None:
    with pytest.raises(ValueError):
        validate_metric_labels({"command", label})
