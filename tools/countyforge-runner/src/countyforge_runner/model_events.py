"""Bounded summaries of the provider model-event stream.

Run 30722542853 timed out after exactly one hour without producing an
implementation result.  The event stream existed, but the sanitizer reached it
only through `result.with_name(...)` off a discovered result file, so the one
run whose events would have explained the hour retained none of them.

Discovery is therefore independent of the result, and absence is recorded
explicitly rather than by omission.  Only bounded facts leave this module: no
model reasoning, prompt or source content, provider credentials, or arbitrary
event payloads.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from countyforge_runner.contracts import JsonObject

EVENT_STREAM_NAME = "countyforge-implementation-model-events.ndjson"
#: Plan and review lanes name their stream differently; discovery accepts any of
#: them so one summarizer serves every lane.
EVENT_STREAM_NAMES = (
    EVENT_STREAM_NAME,
    "countyforge-plan-model-events.ndjson",
    "countyforge-review-model-events.ndjson",
)

# Event *types* are a small closed vocabulary from the provider; any other field
# may carry model or source text and is never read.
_MAX_TYPE_CHARS = 64
_MAX_TIMESTAMP_CHARS = 64


def find_model_events(root: Path) -> Path | None:
    """Locate the stream without depending on any other artifact existing."""

    if not root.is_dir():
        return None
    for name in EVENT_STREAM_NAMES:
        matches = sorted(root.rglob(name))
        if matches:
            return matches[0]
    return None


def _safe_field(event: object, key: str, limit: int) -> str | None:
    if not isinstance(event, dict):
        return None
    value = event.get(key)
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    return value


def summarize_model_events(path: Path | None) -> JsonObject:
    """Reduce the stream to bounded facts, or record that it was absent."""

    if path is None or not path.is_file():
        return {
            "contract_version": 1,
            "model_events_present": False,
            "raw_content_omitted": True,
        }
    try:
        raw = path.read_bytes()
    except OSError:
        return {
            "contract_version": 1,
            "model_events_present": False,
            "unreadable": True,
            "raw_content_omitted": True,
        }
    text = raw.decode("utf-8", "replace")
    lines = [line for line in text.splitlines() if line.strip()]
    first_type: str | None = None
    last_type: str | None = None
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    parsed = 0
    provider_error = False
    input_too_large = False
    output_observed = False
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        parsed += 1
        kind = _safe_field(event, "type", _MAX_TYPE_CHARS)
        if kind is not None:
            if first_type is None:
                first_type = kind
            last_type = kind
            lowered = kind.casefold()
            provider_error = provider_error or "error" in lowered
            # `thread.started` and `turn.started` mean the provider accepted the
            # turn, not that the model produced anything.  Run 30836072011 spent
            # its entire then-current 30-minute budget having emitted exactly
            # those two, so they must not count as progress.
            output_observed = output_observed or any(
                token in lowered for token in ("message", "output", "item", "delta")
            )
        stamp = _safe_field(event, "timestamp", _MAX_TIMESTAMP_CHARS)
        if stamp is not None:
            if first_timestamp is None:
                first_timestamp = stamp
            last_timestamp = stamp
    # Substring on the raw stream: the marker may sit in a payload this summary
    # deliberately never reads field-by-field.
    input_too_large = "input_too_large" in text
    provider_error = provider_error or input_too_large
    return {
        "contract_version": 1,
        "model_events_present": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "event_count": len(lines),
        "parsed_event_count": parsed,
        "first_event_type": first_type,
        "last_event_type": last_type,
        "first_event_timestamp": first_timestamp,
        "last_event_timestamp": last_timestamp,
        "provider_error_observed": provider_error,
        "input_too_large_observed": input_too_large,
        "output_event_observed": output_observed,
        # A stream that ends mid-line was cut off rather than closed.
        "ended_cleanly": bool(raw) and raw.endswith(b"\n"),
        "raw_content_omitted": True,
    }
