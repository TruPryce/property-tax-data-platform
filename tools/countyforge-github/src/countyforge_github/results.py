"""Fail-closed interpretation of bounded runner result artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from countyforge_github.contracts import JsonObject

_DISPOSITION = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Mirrors the publisher's closed vocabulary; a progress document naming anything
# else is untrusted evidence and is ignored rather than reported.
PUBLICATION_STAGES = (
    "validate_result",
    "validate_provenance",
    "resolve_predecessor",
    "create_blobs",
    "load_parent_commit",
    "create_tree",
    "create_commit",
    "create_ref",
    "create_pull_request",
    "complete",
)
_PUBLICATION_ACTIONS = frozenset({"created", "superseded", "deduplicated"})


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


def _publication_progress_details(path: Path | None) -> JsonObject:
    """Recover a closed-vocabulary stage from the publisher's progress snapshot.

    A hard kill can leave the redirected stdout empty while the progress file
    still holds the last stage entered, so the fallback document must not report
    `unknown` when that evidence survived.
    """

    document = _read_result(path)
    if document is None:
        return {}
    stage = document.get("stage")
    if not isinstance(stage, str) or stage not in PUBLICATION_STAGES:
        return {}
    raw_completed = document.get("completed")
    completed = (
        [item for item in raw_completed if isinstance(item, str) and item in PUBLICATION_STAGES]
        if isinstance(raw_completed, list)
        else []
    )
    return {"stage": stage, "completed": completed}


def _publication_failure(
    disposition: str, message: str, *, exit_code: int, details: JsonObject
) -> JsonObject:
    return {
        "ok": False,
        "exit_code": exit_code if exit_code != 0 else 5,
        "disposition": disposition,
        "message": message,
        "details": details,
    }


def _publication_outputs(result: JsonObject) -> JsonObject | None:
    """Return the step outputs only when every required field has its type."""

    change_name = result.get("change_name")
    branch = result.get("branch")
    pr_number = result.get("pr_number")
    context_sha = result.get("context_manifest_sha256")
    if (
        result.get("action") not in _PUBLICATION_ACTIONS
        or result.get("stage") != "complete"
        or not isinstance(change_name, str)
        or not change_name
        or not isinstance(branch, str)
        or not branch
        or isinstance(pr_number, bool)
        or not isinstance(pr_number, int)
        or not isinstance(context_sha, str)
        or _SHA256.fullmatch(context_sha) is None
    ):
        return None
    return {
        "change_name": change_name,
        "branch": branch,
        "pr_number": pr_number,
        "context_manifest_sha256": context_sha,
    }


def normalize_publication_result(
    *, result_path: Path | None, progress_path: Path | None, exit_code: int
) -> JsonObject:
    """Reduce publisher stdout and its return code to one consistent document.

    The workflow must never finalize a planning run on evidence it could not
    read.  A missing, malformed, non-object, or internally inconsistent result
    becomes a sanitized failure with a nonzero effective exit code, and step
    outputs are produced only for a zero exit that also reports a complete,
    well-typed success.
    """

    progress = _publication_progress_details(progress_path)
    raw = _read_result(result_path)
    if raw is None:
        empty = result_path is None or not result_path.is_file() or not result_path.read_bytes()
        return _publication_failure(
            "publication_result_missing" if empty else "publication_result_malformed",
            "Publisher returned no usable structured result.",
            exit_code=exit_code,
            details=progress,
        )
    details = raw.get("details")
    merged: JsonObject = {**progress, **(details if isinstance(details, dict) else {})}
    if raw.get("ok") is not True:
        disposition = raw.get("disposition")
        return _publication_failure(
            disposition
            if isinstance(disposition, str) and _DISPOSITION.fullmatch(disposition)
            else "planning_publication_failed",
            "Publication reported a sanitized failure.",
            exit_code=exit_code,
            details=merged,
        )
    if exit_code != 0:
        return _publication_failure(
            "publication_result_inconsistent",
            "Publication reported success with a nonzero exit code.",
            exit_code=exit_code,
            details=merged,
        )
    outputs = _publication_outputs(raw)
    if outputs is None:
        return _publication_failure(
            "publication_result_incomplete",
            "Publication reported success without complete publication facts.",
            exit_code=5,
            details=merged,
        )
    return {
        "ok": True,
        "exit_code": 0,
        "disposition": "planning_publication_completed",
        "message": "Publication completed.",
        "details": merged,
        "outputs": outputs,
    }
