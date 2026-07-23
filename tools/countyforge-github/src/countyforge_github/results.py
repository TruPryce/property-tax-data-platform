"""Fail-closed interpretation of bounded runner result artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from countyforge_github.contracts import JsonObject

_DISPOSITION = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _read_result(path: Path | None) -> JsonObject | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _read_exit_code(path: Path | None) -> int | None:
    if path is None or not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        value = int(raw)
    except (OSError, UnicodeError, ValueError):
        return None
    return value if 0 <= value <= 255 else None


def resolve_terminal_result(
    *, command: str, result_path: Path | None, exit_code_path: Path | None
) -> JsonObject:
    """Map only valid, internally consistent runner evidence to terminal state."""

    result = _read_result(result_path)
    if result is None:
        return {"ok": True, "state": "failed", "disposition": "invalid_result_evidence"}
    raw_disposition = result.get("disposition")
    if not isinstance(raw_disposition, str) or _DISPOSITION.fullmatch(raw_disposition) is None:
        return {"ok": True, "state": "failed", "disposition": "invalid_result_evidence"}
    if command in {"review", "plan"} or (command == "implement" and raw_disposition == "completed"):
        exit_code = _read_exit_code(exit_code_path)
        if exit_code is None:
            return {
                "ok": True,
                "state": "failed",
                "disposition": "runner_exit_code_missing",
            }
        if exit_code != 0:
            return {
                "ok": True,
                "state": "failed",
                "disposition": "runner_exit_nonzero",
            }
        summary = result.get("summary")
        if (
            command in {"review", "implement"}
            and raw_disposition == "completed"
            and (
                result.get("ok") is not True
                or result.get("mode") != command
                or not isinstance(summary, dict)
                or summary.get("disposition") != "completed"
                or summary.get("exit_code") != 0
                or (command == "implement" and not isinstance(result.get("implementation"), dict))
            )
        ):
            return {
                "ok": True,
                "state": "failed",
                "disposition": "invalid_result_evidence",
            }
    if command == "plan" and raw_disposition == "completed":
        summary = result.get("summary")
        if (
            result.get("ok") is not True
            or result.get("mode") != "plan"
            or not isinstance(summary, dict)
            or summary.get("disposition") != "completed"
            or summary.get("exit_code") != 0
            or not isinstance(result.get("plan"), dict)
        ):
            return {"ok": True, "state": "failed", "disposition": "invalid_result_evidence"}
    states = {
        "completed": "succeeded",
        "profile_not_implemented": "not_implemented",
        "timed_out": "timed_out",
    }
    return {
        "ok": True,
        "state": states.get(raw_disposition, "failed"),
        "disposition": raw_disposition,
    }
