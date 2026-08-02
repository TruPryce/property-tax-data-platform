"""Bounded model-event evidence, decoupled from the implementation result."""

from __future__ import annotations

import json
from pathlib import Path

from countyforge_runner.model_events import (
    EVENT_STREAM_NAME,
    find_model_events,
    summarize_model_events,
)

# Content a summary must never carry outward, seeded into a stream on purpose.
_CREDENTIAL = "sk-live-abcdefghijklmnopqrstuvwxyz0123456789"  # pragma: allowlist secret
_REASONING = "I should first inspect the Collin County parser before editing it."
_SOURCE = "def parse_collin(row: dict) -> Account:  # verbatim source content"


def _stream(root: Path, *events: dict[str, object], run: str = "run-30722542853") -> Path:
    target = root / run / EVENT_STREAM_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    return target


def test_events_are_discovered_with_no_implementation_result_present(tmp_path: Path) -> None:
    """The timed-out run is exactly the run that has events and no result."""

    _stream(tmp_path, {"type": "response.created", "timestamp": "2026-07-31T10:00:00Z"})
    assert not list(tmp_path.rglob("countyforge-implementation-result.json"))
    found = find_model_events(tmp_path)
    assert found is not None and found.name == EVENT_STREAM_NAME
    assert summarize_model_events(found)["model_events_present"] is True


def test_a_timed_out_run_yields_a_bounded_summary_of_what_the_hour_contained(
    tmp_path: Path,
) -> None:
    summary = summarize_model_events(
        _stream(
            tmp_path,
            {"type": "response.created", "timestamp": "2026-07-31T10:00:00Z"},
            {"type": "response.reasoning.delta", "timestamp": "2026-07-31T10:14:02Z"},
            {"type": "response.reasoning.delta", "timestamp": "2026-07-31T10:59:41Z"},
        )
    )
    assert summary["event_count"] == 3
    assert summary["parsed_event_count"] == 3
    assert summary["first_event_type"] == "response.created"
    assert summary["last_event_type"] == "response.reasoning.delta"
    assert summary["first_event_timestamp"] == "2026-07-31T10:00:00Z"
    assert summary["last_event_timestamp"] == "2026-07-31T10:59:41Z"
    assert summary["provider_error_observed"] is False
    assert summary["ended_cleanly"] is True


def test_absence_is_recorded_as_explicit_evidence_rather_than_by_omission(
    tmp_path: Path,
) -> None:
    for summary in (
        summarize_model_events(None),
        summarize_model_events(find_model_events(tmp_path / "missing")),
        summarize_model_events(find_model_events(tmp_path)),
    ):
        assert summary["model_events_present"] is False
        assert summary["raw_content_omitted"] is True
        assert summary["contract_version"] == 1


def test_no_raw_event_payload_reasoning_source_or_credential_leaves_the_summary(
    tmp_path: Path,
) -> None:
    """Only bounded facts. Everything else in an event is never read."""

    path = _stream(
        tmp_path,
        {
            "type": "response.reasoning.delta",
            "timestamp": "2026-07-31T10:14:02Z",
            "delta": _REASONING,
            "authorization": f"Bearer {_CREDENTIAL}",
            "input": _SOURCE,
            "arbitrary": {"nested": [_SOURCE, _CREDENTIAL]},
        },
    )
    serialized = json.dumps(summarize_model_events(path), sort_keys=True)
    for secret in (_CREDENTIAL, _REASONING, _SOURCE, "Bearer ", "arbitrary", 'delta":'):
        assert secret not in serialized
    # The stream is attested by digest and size, never reproduced.
    assert (
        summarize_model_events(path)["sha256"]
        == __import__("hashlib").sha256(path.read_bytes()).hexdigest()
    )


def test_an_oversized_or_hostile_type_field_cannot_inflate_the_summary(
    tmp_path: Path,
) -> None:
    path = _stream(
        tmp_path,
        {"type": "x" * 5_000, "timestamp": "y" * 5_000},
        {"not json at all": True},
    )
    summary = summarize_model_events(path)
    assert summary["first_event_type"] is None
    assert summary["first_event_timestamp"] is None
    assert len(json.dumps(summary)) < 1_000


def test_a_rejected_input_and_an_unterminated_stream_are_both_visible(
    tmp_path: Path,
) -> None:
    rejected = _stream(tmp_path / "a", {"type": "error", "code": "input_too_large"})
    summary = summarize_model_events(rejected)
    assert summary["input_too_large_observed"] is True
    assert summary["provider_error_observed"] is True

    cut = (tmp_path / "b" / "run") / EVENT_STREAM_NAME
    cut.parent.mkdir(parents=True)
    cut.write_text('{"type":"response.created"}\n{"type":"resp', encoding="utf-8")
    assert summarize_model_events(cut)["ended_cleanly"] is False
