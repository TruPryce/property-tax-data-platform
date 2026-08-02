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
    *,
    command: str,
    result_path: Path | None,
    exit_code_path: Path | None,
    lane_path: Path | None = None,
) -> JsonObject:
    """Map only valid, internally consistent runner evidence to terminal state.

    A refused implementation lane classification takes precedence, because it
    explains *why* the evidence is absent: `invalid_result_evidence` would report
    a model outcome for a run whose provider image never built.  It can only
    produce a failure, never upgrade one.
    """

    lane = _read_result(lane_path)
    if lane is not None and lane.get("ok") is False:
        disposition = lane.get("disposition")
        if isinstance(disposition, str) and _DISPOSITION.fullmatch(disposition):
            return {"ok": True, "state": "failed", "disposition": disposition}
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


# Exactly one implementation provider lane may execute per request.
#
# A GitHub job result of `success` does not prove the lane succeeded: the runner
# invocation is wrapped in `set +e` so its exit code is captured as evidence, and
# the freeze step is `continue-on-error`. Run 30695076693 concluded `success`
# with an empty credential, a nonzero captured exit, and no frozen bundle.
# Classification therefore reads host-observed execution facts, never the
# wrapper's conclusion alone, and never a model-authored field.
IMPLEMENTATION_PROVIDERS = frozenset({"openai", "sakana"})


def _lane_failure(disposition: str, **details: object) -> JsonObject:
    return {"ok": False, "disposition": disposition, "details": details}


def _runner_reports_success(document: JsonObject) -> bool:
    """A runner result counts only when it is internally consistent."""

    summary = document.get("summary")
    return (
        document.get("ok") is True
        and document.get("mode") == "implement"
        and document.get("disposition") == "completed"
        and isinstance(summary, dict)
        and summary.get("disposition") == "completed"
        and summary.get("exit_code") == 0
        and isinstance(document.get("implementation"), dict)
    )


def classify_implementation_lane(
    *,
    selected_provider: str,
    lane_results: JsonObject,
    result_path: Path | None = None,
    exit_code_path: Path | None = None,
    implementation_result_path: Path | None = None,
    implementation_result_present: bool | None = None,
    freeze_outcome: str | None = None,
    frozen_bundle_present: bool | None = None,
    adapter_disposition: str | None = None,
) -> JsonObject:
    """Classify which implementation provider lane owns a run's outcome.

    `lane_results` maps provider name to its GitHub job result, where `skipped`
    means the lane did not run.  Everything else is host-observed evidence the
    provider job captured.  `completed` requires every success condition to be
    independently proven; anything unproven is a failure, and the distinction
    between an infrastructure failure and a model failure is drawn only where
    trusted evidence supports it.
    """

    if selected_provider not in IMPLEMENTATION_PROVIDERS:
        return _lane_failure("unsupported_implementation_provider", selected=selected_provider)
    executed = sorted(
        provider
        for provider, outcome in lane_results.items()
        if isinstance(outcome, str) and outcome != "skipped"
    )
    if len(executed) != 1:
        return _lane_failure("implementation_provider_lane_ambiguous", executed=executed)
    if executed[0] != selected_provider:
        return _lane_failure(
            "implementation_provider_lane_mismatch",
            executed=executed[0],
            selected=selected_provider,
        )

    # The adapter says exactly why it stopped when it stopped before the model.
    # That is strictly more specific than anything inferable downstream, so it
    # wins over the generic infrastructure classification.
    if isinstance(adapter_disposition, str) and _DISPOSITION.fullmatch(adapter_disposition):
        return _lane_failure(adapter_disposition, provider=selected_provider)

    # Before a valid runner result exists, any failure is infrastructure: the
    # image, the credential, the container, or the adapter -- not the model.
    exit_code = _read_exit_code(exit_code_path)
    runner = _read_result(result_path)
    if runner is None:
        return _lane_failure(
            "implementation_provider_infrastructure_failed",
            provider=selected_provider,
            reason="runner_result_missing",
        )
    if exit_code is None:
        return _lane_failure(
            "implementation_provider_infrastructure_failed",
            provider=selected_provider,
            reason="runner_exit_code_missing",
        )
    disposition = runner.get("disposition")
    if disposition == "timed_out":
        # The request was admitted and ran; it simply did not finish. That is
        # neither provider infrastructure nor a model producing a bad result,
        # and it is checked only after every earlier, more specific cause.
        return _lane_failure(
            "implementation_model_timed_out",
            provider=selected_provider,
            runner_exit_code=exit_code,
        )
    if exit_code != 0 or runner.get("ok") is not True:
        # The runner ran and reported; a nonzero exit with an adapter-level
        # disposition is the container or provider failing, not the model.
        infrastructure = disposition in {"adapter_failed", "profile_not_implemented", None}
        return _lane_failure(
            "implementation_provider_infrastructure_failed"
            if infrastructure
            else "implementation_model_failed",
            provider=selected_provider,
            runner_exit_code=exit_code,
            runner_disposition=disposition if isinstance(disposition, str) else None,
        )
    if not _runner_reports_success(runner):
        return _lane_failure(
            "implementation_model_failed",
            provider=selected_provider,
            reason="runner_result_inconsistent",
        )

    # A valid model result exists from here on, so remaining failures are about
    # trusted host-side materialization rather than the provider.
    #
    # `implementation_result_present` is the host's pre-freeze observation and is
    # the only honest signal for "did the model produce a result".  The frozen
    # copy is uploaded only when freezing succeeds, so requiring it first would
    # report every freeze failure as a missing model result.
    if implementation_result_present is False:
        return _lane_failure(
            "implementation_model_failed",
            provider=selected_provider,
            reason="implementation_result_missing",
        )
    if freeze_outcome != "success":
        return _lane_failure(
            "implementation_freeze_failed",
            provider=selected_provider,
            freeze_outcome=freeze_outcome,
        )
    if frozen_bundle_present is not True:
        return _lane_failure(
            "implementation_freeze_failed",
            provider=selected_provider,
            reason="frozen_bundle_missing",
        )
    # Freezing reported success, so the frozen result must be readable; its
    # absence now is a materialization defect, not a freeze outcome.
    if _read_result(implementation_result_path) is None:
        return _lane_failure(
            "implementation_model_failed",
            provider=selected_provider,
            reason="implementation_result_missing",
        )
    return {
        "ok": True,
        "disposition": "completed",
        "details": {"provider": selected_provider, "runner_exit_code": exit_code},
    }
