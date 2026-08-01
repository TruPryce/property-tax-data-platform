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


def _publication_stage_details(document: JsonObject | None) -> JsonObject:
    """Accept a stage only with its exact ordered completed prefix.

    The publisher can only enter consecutive stages, so `completed` is always
    the vocabulary prefix ending at the current stage.  Anything reordered,
    duplicated, truncated, or invented is not evidence this publisher produced
    and is discarded rather than reported.
    """

    if document is None:
        return {}
    stage = document.get("stage")
    if not isinstance(stage, str) or stage not in PUBLICATION_STAGES:
        return {}
    expected = list(PUBLICATION_STAGES[: PUBLICATION_STAGES.index(stage)])
    if document.get("completed") != expected:
        return {}
    return {"stage": stage, "completed": expected}


def _raw_stage_details(raw: JsonObject) -> JsonObject:
    """A success reports its stage at the top level; a failure inside `details`."""

    details = raw.get("details")
    if isinstance(details, dict):
        reported = _publication_stage_details(details)
        if reported:
            return reported
    return _publication_stage_details(raw)


def _publication_details(raw: JsonObject, progress: JsonObject) -> JsonObject | None:
    """Merge sanitized publication details, or refuse contradictory evidence.

    `stage` and `completed` are reserved: they come from validated evidence, and
    persisted progress wins because it survives a kill that truncated stdout.
    If a valid raw stage disagrees with a valid persisted one, the two records of
    the same run contradict each other and neither may be reported.  Everything
    else the publisher put in `details` is dropped here; the raw document is
    uploaded intact alongside this one.
    """

    reported = _raw_stage_details(raw)
    if progress and reported and progress != reported:
        return None
    details: JsonObject = dict(progress or reported)
    raw_details = raw.get("details")
    status = raw_details.get("status") if isinstance(raw_details, dict) else None
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        details["status"] = status
    return details


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

    progress = _publication_stage_details(_read_result(progress_path))
    raw = _read_result(result_path)
    if raw is None:
        empty = result_path is None or not result_path.is_file() or not result_path.read_bytes()
        return _publication_failure(
            "publication_result_missing" if empty else "publication_result_malformed",
            "Publisher returned no usable structured result.",
            exit_code=exit_code,
            details=progress,
        )
    merged = _publication_details(raw, progress)
    reported = raw.get("disposition")
    disposition = (
        reported
        if isinstance(reported, str) and _DISPOSITION.fullmatch(reported)
        else "planning_publication_failed"
    )
    if merged is None:
        return _publication_failure(
            "publication_evidence_inconsistent",
            "Publication stage evidence contradicts its persisted progress.",
            exit_code=exit_code,
            details={"reported_disposition": disposition, **progress},
        )
    if raw.get("ok") is not True:
        return _publication_failure(
            disposition,
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
    if outputs is None or merged.get("stage") != "complete":
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


# Exactly one implementation provider lane may execute per request. Run
# 30691544362 failed while building `ghcr.io/openai/codex` (GHCR 403) before the
# model was invoked, so its lane produced no result evidence at all. That is a
# provider/image provisioning failure and must never be reported as a model
# outcome.
IMPLEMENTATION_PROVIDERS = frozenset({"openai", "sakana"})


def classify_implementation_lane(
    *,
    selected_provider: str,
    lane_results: JsonObject,
    result_path: Path | None,
) -> JsonObject:
    """Classify which implementation provider lane owns a run's outcome.

    `lane_results` maps provider name to its GitHub job result, where `skipped`
    means the lane did not run.  The classification is deliberately coarse and
    fail-closed: anything that is not one selected lane with readable result
    evidence is refused rather than validated.
    """

    if selected_provider not in IMPLEMENTATION_PROVIDERS:
        return {"ok": False, "disposition": "unsupported_implementation_provider"}
    executed = sorted(
        provider
        for provider, outcome in lane_results.items()
        if isinstance(outcome, str) and outcome != "skipped"
    )
    if len(executed) != 1:
        return {
            "ok": False,
            "disposition": "implementation_provider_lane_ambiguous",
            "details": {"executed": executed},
        }
    if executed[0] != selected_provider:
        return {
            "ok": False,
            "disposition": "implementation_provider_lane_mismatch",
            "details": {"executed": executed[0], "selected": selected_provider},
        }
    outcome = str(lane_results[selected_provider])
    evidence = _read_result(result_path)
    if evidence is None:
        # No result document means the lane never reached the model: an image
        # pull or build failure, a missing credential, or a runner fault.
        return {
            "ok": False,
            "disposition": "implementation_provider_infrastructure_failed",
            "details": {"provider": selected_provider, "lane_result": outcome},
        }
    if outcome != "success":
        return {
            "ok": False,
            "disposition": "implementation_model_failed",
            "details": {"provider": selected_provider, "lane_result": outcome},
        }
    return {"ok": True, "disposition": "completed", "details": {"provider": selected_provider}}
