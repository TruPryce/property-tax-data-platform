"""Runner result artifact interpretation fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from countyforge_github.results import (
    classify_implementation_lane,
    normalize_publication_result,
    resolve_terminal_result,
)


def _write(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    return path


def test_completed_review_requires_valid_zero_exit_code(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "result.json",
        '{"ok":true,"mode":"review","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0}}',
    )
    zero = _write(tmp_path / "exit", "0\n")
    assert resolve_terminal_result(command="review", result_path=result, exit_code_path=zero) == {
        "ok": True,
        "state": "succeeded",
        "disposition": "completed",
    }


def test_nonzero_exit_cannot_publish_completed_review(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "result.json",
        '{"ok":true,"mode":"review","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0}}',
    )
    nonzero = _write(tmp_path / "exit", "2\n")
    resolved = resolve_terminal_result(command="review", result_path=result, exit_code_path=nonzero)
    assert resolved["state"] == "failed"
    assert resolved["disposition"] == "runner_exit_nonzero"


def test_missing_or_malformed_evidence_fails_closed(tmp_path: Path) -> None:
    malformed = _write(tmp_path / "result.json", "{")
    empty = _write(tmp_path / "empty.json", "")
    for result in (None, malformed, empty):
        resolved = resolve_terminal_result(
            command="review", result_path=result, exit_code_path=None
        )
        assert resolved["state"] == "failed"
        assert resolved["disposition"] == "invalid_result_evidence"


def test_missing_or_malformed_review_exit_code_fails_closed(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "result.json",
        '{"ok":true,"mode":"review","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0}}',
    )
    malformed = _write(tmp_path / "exit", "not-an-exit\n")
    for exit_path in (None, malformed):
        resolved = resolve_terminal_result(
            command="review", result_path=result, exit_code_path=exit_path
        )
        assert resolved["state"] == "failed"
        assert resolved["disposition"] == "runner_exit_code_missing"


def test_completed_review_requires_consistent_structured_summary(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "result.json",
        '{"ok":false,"mode":"review","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0}}',
    )
    zero = _write(tmp_path / "exit", "0\n")
    resolved = resolve_terminal_result(command="review", result_path=result, exit_code_path=zero)
    assert resolved["state"] == "failed"
    assert resolved["disposition"] == "invalid_result_evidence"


def test_completed_plan_requires_valid_zero_exit_and_plan_payload(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "result.json",
        '{"ok":true,"mode":"plan","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0},"plan":{}}',
    )
    zero = _write(tmp_path / "exit", "0\n")
    assert resolve_terminal_result(command="plan", result_path=result, exit_code_path=zero) == {
        "ok": True,
        "state": "succeeded",
        "disposition": "completed",
    }


def test_plan_requires_exit_evidence_and_rejects_nonzero_or_missing_payload(
    tmp_path: Path,
) -> None:
    result = _write(
        tmp_path / "result.json",
        '{"ok":true,"mode":"plan","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0},"plan":{}}',
    )
    missing = resolve_terminal_result(command="plan", result_path=result, exit_code_path=None)
    assert missing["disposition"] == "runner_exit_code_missing"
    nonzero = _write(tmp_path / "nonzero", "1\n")
    failed = resolve_terminal_result(command="plan", result_path=result, exit_code_path=nonzero)
    assert failed["disposition"] == "runner_exit_nonzero"
    no_plan = _write(
        tmp_path / "no-plan.json",
        '{"ok":true,"mode":"plan","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0}}',
    )
    zero = _write(tmp_path / "zero", "0\n")
    invalid = resolve_terminal_result(command="plan", result_path=no_plan, exit_code_path=zero)
    assert invalid["disposition"] == "invalid_result_evidence"


def test_plan_failure_and_malformed_result_fail_closed(tmp_path: Path) -> None:
    failed = _write(tmp_path / "failed.json", '{"ok":false,"disposition":"adapter_failed"}')
    nonzero = _write(tmp_path / "exit", "1\n")
    assert resolve_terminal_result(command="plan", result_path=failed, exit_code_path=nonzero) == {
        "ok": True,
        "state": "failed",
        "disposition": "runner_exit_nonzero",
    }
    malformed = _write(tmp_path / "malformed.json", "{")
    assert (
        resolve_terminal_result(command="plan", result_path=malformed, exit_code_path=nonzero)[
            "disposition"
        ]
        == "invalid_result_evidence"
    )


def test_future_mode_keeps_structured_not_implemented_disposition(tmp_path: Path) -> None:
    result = _write(tmp_path / "result.json", '{"disposition":"profile_not_implemented"}')
    assert resolve_terminal_result(
        command="implement", result_path=result, exit_code_path=None
    ) == {
        "ok": True,
        "state": "not_implemented",
        "disposition": "profile_not_implemented",
    }


def test_completed_implementation_requires_structured_result_and_zero_exit(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "implementation.json",
        '{"ok":true,"mode":"implement","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0},"implementation":{}}',
    )
    zero = _write(tmp_path / "zero", "0\n")
    assert resolve_terminal_result(
        command="implement", result_path=result, exit_code_path=zero
    ) == {
        "ok": True,
        "state": "succeeded",
        "disposition": "completed",
    }
    missing = resolve_terminal_result(command="implement", result_path=result, exit_code_path=None)
    assert missing["disposition"] == "runner_exit_code_missing"


def test_implementation_completed_without_payload_fails_closed(tmp_path: Path) -> None:
    result = _write(
        tmp_path / "implementation.json",
        '{"ok":true,"mode":"implement","disposition":"completed",'
        '"summary":{"disposition":"completed","exit_code":0}}',
    )
    zero = _write(tmp_path / "zero", "0\n")
    resolved = resolve_terminal_result(command="implement", result_path=result, exit_code_path=zero)
    assert resolved["disposition"] == "invalid_result_evidence"


# The publisher can only enter consecutive stages, so `completed` is always the
# exact vocabulary prefix ending at the current stage.
_STAGES = (
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


def _prefix(stage: str) -> list[str]:
    return list(_STAGES[: _STAGES.index(stage)])


_SUCCESS = json.dumps(
    {
        "ok": True,
        "action": "created",
        "stage": "complete",
        "completed": _prefix("complete"),
        "branch": "countyforge/plan/issue-6-add-safe-planning",
        "change_name": "add-safe-planning",
        "pr_number": 12,
        "context_manifest_sha256": "a" * 64,
    }
)
_PROGRESS = json.dumps({"stage": "create_ref", "completed": _prefix("create_ref")})


def test_publication_success_yields_typed_outputs(tmp_path: Path) -> None:
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", _SUCCESS),
        progress_path=None,
        exit_code=0,
    )
    assert normalized["ok"] is True
    assert normalized["exit_code"] == 0
    assert normalized["outputs"] == {
        "change_name": "add-safe-planning",
        "branch": "countyforge/plan/issue-6-add-safe-planning",
        "pr_number": 12,
        "context_manifest_sha256": "a" * 64,
    }


def test_publication_missing_result_reports_the_surviving_progress_stage(tmp_path: Path) -> None:
    """A hard kill can empty the redirect while the progress file survives."""

    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", ""),
        progress_path=_write(tmp_path / "progress.json", _PROGRESS),
        exit_code=137,
    )
    assert normalized["ok"] is False
    assert normalized["exit_code"] == 137
    assert normalized["disposition"] == "publication_result_missing"
    assert normalized["details"] == {"stage": "create_ref", "completed": _prefix("create_ref")}


def test_publication_absent_result_file_is_missing_not_malformed(tmp_path: Path) -> None:
    normalized = normalize_publication_result(
        result_path=tmp_path / "absent.json", progress_path=None, exit_code=5
    )
    assert normalized["disposition"] == "publication_result_missing"
    assert normalized["details"] == {}


def test_publication_rejects_an_unreadable_progress_stage(tmp_path: Path) -> None:
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", ""),
        progress_path=_write(tmp_path / "progress.json", '{"stage":"rm -rf /","completed":"no"}'),
        exit_code=1,
    )
    assert normalized["details"] == {}


@pytest.mark.parametrize(
    "body",
    ["not json at all", '{"ok": true', '["ok"]', '"ok"', "null", "42"],
)
def test_publication_malformed_or_non_object_result_fails_closed(tmp_path: Path, body: str) -> None:
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", body), progress_path=None, exit_code=0
    )
    assert normalized["ok"] is False
    assert normalized["disposition"] == "publication_result_malformed"
    # A zero exit must not survive an unreadable document.
    assert normalized["exit_code"] == 5
    assert "outputs" not in normalized


def test_publication_failure_document_keeps_its_sanitized_disposition(tmp_path: Path) -> None:
    body = json.dumps(
        {
            "ok": False,
            "disposition": "github_api_error",
            "details": {
                "status": 403,
                "ref": "refs/heads/countyforge/plan/issue-6-add-safe-planning",
                "stage": "create_ref",
                "completed": _prefix("create_ref"),
            },
        }
    )
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", body), progress_path=None, exit_code=5
    )
    assert normalized["disposition"] == "github_api_error"
    # Only the reserved stage fields and a bounded integer status survive; the
    # raw document keeps everything else and is uploaded intact.
    assert normalized["details"] == {
        "status": 403,
        "stage": "create_ref",
        "completed": _prefix("create_ref"),
    }
    assert normalized["exit_code"] == 5


def test_publication_failure_document_with_zero_exit_still_fails(tmp_path: Path) -> None:
    body = json.dumps({"ok": False, "disposition": "github_api_error", "details": {"status": 422}})
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", body), progress_path=None, exit_code=0
    )
    assert normalized["ok"] is False
    assert normalized["exit_code"] == 5


def test_publication_success_with_nonzero_exit_is_inconsistent(tmp_path: Path) -> None:
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", _SUCCESS), progress_path=None, exit_code=5
    )
    assert normalized["ok"] is False
    assert normalized["disposition"] == "publication_result_inconsistent"
    assert normalized["exit_code"] == 5
    assert "outputs" not in normalized


@pytest.mark.parametrize(
    "override",
    [
        {"change_name": ""},
        {"change_name": 7},
        {"branch": None},
        {"pr_number": "12"},
        {"pr_number": True},
        {"context_manifest_sha256": "short"},
        {"action": "invented"},
        {"stage": "create_ref"},
    ],
)
def test_publication_success_requires_complete_well_typed_facts(
    tmp_path: Path, override: dict[str, object]
) -> None:
    body = json.dumps({**json.loads(_SUCCESS), **override})
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", body), progress_path=None, exit_code=0
    )
    assert normalized["ok"] is False
    assert normalized["disposition"] == "publication_result_incomplete"
    assert normalized["exit_code"] == 5
    assert "outputs" not in normalized


def test_publication_raw_details_cannot_override_persisted_progress(tmp_path: Path) -> None:
    """Two records of the same run that disagree are not evidence of either."""

    body = json.dumps(
        {
            "ok": False,
            "disposition": "github_api_error",
            "details": {
                "status": 403,
                "stage": "create_pull_request",
                "completed": _prefix("create_pull_request"),
            },
        }
    )
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", body),
        progress_path=_write(tmp_path / "progress.json", _PROGRESS),
        exit_code=5,
    )
    assert normalized["ok"] is False
    assert normalized["disposition"] == "publication_evidence_inconsistent"
    assert normalized["exit_code"] == 5
    # The persisted stage still reaches the operator, as does the original code.
    assert normalized["details"] == {
        "reported_disposition": "github_api_error",
        "stage": "create_ref",
        "completed": _prefix("create_ref"),
    }


def test_publication_success_contradicting_progress_fails_closed(tmp_path: Path) -> None:
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", _SUCCESS),
        progress_path=_write(tmp_path / "progress.json", _PROGRESS),
        exit_code=0,
    )
    assert normalized["ok"] is False
    assert normalized["disposition"] == "publication_evidence_inconsistent"
    assert normalized["exit_code"] == 5
    assert "outputs" not in normalized


def test_publication_agreeing_raw_and_persisted_progress_is_accepted(tmp_path: Path) -> None:
    progress = json.dumps({"stage": "complete", "completed": _prefix("complete")})
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", _SUCCESS),
        progress_path=_write(tmp_path / "progress.json", progress),
        exit_code=0,
    )
    assert normalized["ok"] is True
    assert normalized["details"] == {"stage": "complete", "completed": _prefix("complete")}


@pytest.mark.parametrize(
    "completed",
    [
        ["create_blobs", "validate_result"],
        ["validate_result", "validate_result", "resolve_predecessor"],
        ["validate_result"],
        [*_prefix("create_ref"), "complete"],
        "validate_result",
        None,
    ],
)
def test_publication_rejects_a_completed_list_that_is_not_the_exact_prefix(
    tmp_path: Path, completed: object
) -> None:
    progress = json.dumps({"stage": "create_ref", "completed": completed})
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", ""),
        progress_path=_write(tmp_path / "progress.json", progress),
        exit_code=1,
    )
    assert normalized["details"] == {}


@pytest.mark.parametrize(
    "details",
    [
        {"stage": "rm -rf /", "completed": []},
        {"stage": 7, "completed": []},
        {"status": "403"},
        {"status": True},
        {"status": 99},
        {"status": 600},
        {"token": "ghp_secret", "ref": "refs/heads/x"},
    ],
)
def test_publication_drops_unvalidated_auxiliary_details(
    tmp_path: Path, details: dict[str, object]
) -> None:
    body = json.dumps({"ok": False, "disposition": "github_api_error", "details": details})
    normalized = normalize_publication_result(
        result_path=_write(tmp_path / "result.json", body), progress_path=None, exit_code=5
    )
    assert normalized["disposition"] == "github_api_error"
    assert normalized["details"] == {}


# Run 30691544362: the only implementation lane failed while building
# `FROM ghcr.io/openai/codex:0.144.6` (GHCR 403 fetching an anonymous pull
# token), before the model was invoked, so it published no result at all.
_LANE_FIXTURE = (
    Path("tools/countyforge-github/tests/fixtures") / "implementation-lane-run-30691544362.json"
)


def test_the_run_30691544362_image_failure_is_not_a_model_outcome(tmp_path: Path) -> None:
    fixture = json.loads(_LANE_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["model_invoked"] is False
    assert fixture["published_implementation_result"] is False
    assert any("ghcr.io/openai/codex" in line for line in fixture["evidence"])

    classified = classify_implementation_lane(
        selected_provider=fixture["selected_provider"],
        lane_results=fixture["lane_results"],
        # The lane published nothing, so there is no result document to read.
        result_path=tmp_path / "absent.json",
    )
    assert classified["ok"] is False
    assert classified["disposition"] == "implementation_provider_infrastructure_failed"
    assert classified["details"]["provider"] == "openai"
    assert classified["disposition"] != "implementation_model_failed"


@pytest.mark.parametrize("provider", ["", "anthropic", "OPENAI", "unknown", "sakana-v2"])
def test_an_unsupported_provider_fails_closed(tmp_path: Path, provider: str) -> None:
    classified = classify_implementation_lane(
        selected_provider=provider,
        lane_results={"openai": "success", "sakana": "skipped"},
        result_path=None,
    )
    assert classified["ok"] is False
    assert classified["disposition"] == "unsupported_implementation_provider"


@pytest.mark.parametrize(
    "lane_results",
    [
        {"openai": "success", "sakana": "success"},
        {"openai": "failure", "sakana": "failure"},
        {"openai": "skipped", "sakana": "skipped"},
    ],
)
def test_exactly_one_lane_must_execute(tmp_path: Path, lane_results: dict[str, str]) -> None:
    classified = classify_implementation_lane(
        selected_provider="openai", lane_results=lane_results, result_path=None
    )
    assert classified["ok"] is False
    assert classified["disposition"] == "implementation_provider_lane_ambiguous"


def test_the_unselected_lane_cannot_supply_the_outcome(tmp_path: Path) -> None:
    """An artifact from a provider the claim did not select is never accepted."""

    result = _write(tmp_path / "countyforge-result.json", '{"ok":true,"mode":"implement"}')
    classified = classify_implementation_lane(
        selected_provider="sakana",
        lane_results={"openai": "success", "sakana": "skipped"},
        result_path=result,
    )
    assert classified["ok"] is False
    assert classified["disposition"] == "implementation_provider_lane_mismatch"


def test_lane_classification_reaches_terminal_state(tmp_path: Path) -> None:
    """The classification must be trusted evidence, not a shell annotation.

    Without it, terminal resolution sees missing evidence and records
    `invalid_result_evidence`, reporting a model outcome for a run whose
    provider image never built.
    """

    lane = _write(
        tmp_path / "lane.json",
        json.dumps(
            classify_implementation_lane(
                selected_provider="openai",
                lane_results={"openai": "failure", "sakana": "skipped"},
                result_path=tmp_path / "absent.json",
            )
        ),
    )
    assert resolve_terminal_result(
        command="implement", result_path=None, exit_code_path=None, lane_path=lane
    ) == {
        "ok": True,
        "state": "failed",
        "disposition": "implementation_provider_infrastructure_failed",
    }
    # The same inputs without lane evidence degrade to the generic disposition.
    assert (
        resolve_terminal_result(command="implement", result_path=None, exit_code_path=None)[
            "disposition"
        ]
        == "invalid_result_evidence"
    )


def test_a_refused_lane_can_only_produce_a_failure(tmp_path: Path) -> None:
    """Lane evidence must never upgrade an outcome."""

    lane = _write(tmp_path / "lane.json", json.dumps({"ok": True, "disposition": "completed"}))
    resolved = resolve_terminal_result(
        command="implement", result_path=None, exit_code_path=None, lane_path=lane
    )
    # An `ok` lane defers entirely to the ordinary evidence rules.
    assert resolved["state"] == "failed"
    assert resolved["disposition"] == "invalid_result_evidence"


@pytest.mark.parametrize(
    "lane_body",
    ["not json", "[]", '{"ok": false}', '{"ok": false, "disposition": "Bad Code"}', ""],
)
def test_unusable_lane_evidence_is_ignored_rather_than_trusted(
    tmp_path: Path, lane_body: str
) -> None:
    lane = _write(tmp_path / "lane.json", lane_body)
    assert (
        resolve_terminal_result(
            command="implement", result_path=None, exit_code_path=None, lane_path=lane
        )["disposition"]
        == "invalid_result_evidence"
    )


def _lane_inputs(tmp_path: Path, **overrides: object) -> dict[str, object]:
    """A fully successful Sakana lane; individual facts are overridden per case."""

    runner = _write(
        tmp_path / "countyforge-result.json",
        json.dumps(
            {
                "ok": True,
                "mode": "implement",
                "disposition": "completed",
                "summary": {"disposition": "completed", "exit_code": 0},
                "implementation": {"openspec_change": "add-dallas-cad-parser-foundation"},
            }
        ),
    )
    implementation = _write(
        tmp_path / "countyforge-implementation-result.json",
        json.dumps({"openspec_change": "add-dallas-cad-parser-foundation", "file_bundle": []}),
    )
    inputs: dict[str, object] = {
        "selected_provider": "sakana",
        "lane_results": {"openai": "skipped", "sakana": "success"},
        "result_path": runner,
        "exit_code_path": _write(tmp_path / "countyforge-exit-code", "0\n"),
        "implementation_result_path": implementation,
        "implementation_result_present": True,
        "freeze_outcome": "success",
        "frozen_bundle_present": True,
    }
    inputs.update(overrides)
    return inputs


def test_the_successful_sakana_shape_completes(tmp_path: Path) -> None:
    """Only Sakana ran, key present, exit zero, valid result, freeze and bundle."""

    classified = classify_implementation_lane(**_lane_inputs(tmp_path))  # type: ignore[arg-type]
    assert classified["ok"] is True
    assert classified["disposition"] == "completed"
    assert classified["details"]["provider"] == "sakana"
    # Trusted validation is allowed to proceed only on this shape.
    assert resolve_terminal_result(
        command="implement",
        result_path=_lane_inputs(tmp_path)["result_path"],  # type: ignore[arg-type]
        exit_code_path=_lane_inputs(tmp_path)["exit_code_path"],  # type: ignore[arg-type]
        lane_path=_write(tmp_path / "lane.json", json.dumps(classified)),
    ) == {"ok": True, "state": "succeeded", "disposition": "completed"}


def test_the_run_30695076693_shape_can_never_complete(tmp_path: Path) -> None:
    """OpenAI selected, job green, credential absent, nonzero exit, no bundle."""

    runner = _write(
        tmp_path / "countyforge-result.json",
        json.dumps({"ok": False, "mode": "implement", "disposition": "adapter_failed"}),
    )
    classified = classify_implementation_lane(
        selected_provider="openai",
        # The wrapper job concluded success despite doing no work.
        lane_results={"openai": "success", "sakana": "skipped"},
        result_path=runner,
        exit_code_path=_write(tmp_path / "countyforge-exit-code", "2\n"),
        implementation_result_path=None,
        freeze_outcome="failure",
        frozen_bundle_present=False,
    )
    assert classified["ok"] is False
    assert classified["disposition"] == "implementation_provider_infrastructure_failed"
    assert classified["details"]["runner_exit_code"] == 2
    assert classified["details"]["runner_disposition"] == "adapter_failed"
    # And it reaches terminal state as that, not as invalid_result_evidence.
    assert (
        resolve_terminal_result(
            command="implement",
            result_path=runner,
            exit_code_path=_write(tmp_path / "exit2", "2\n"),
            lane_path=_write(tmp_path / "lane.json", json.dumps(classified)),
        )["disposition"]
        == "implementation_provider_infrastructure_failed"
    )


@pytest.mark.parametrize(
    ("overrides", "disposition"),
    [
        # A green wrapper job never proves the lane succeeded.
        ({"exit_code_path": None}, "implementation_provider_infrastructure_failed"),
        ({"result_path": None}, "implementation_provider_infrastructure_failed"),
        ({"implementation_result_present": False}, "implementation_model_failed"),
        ({"implementation_result_path": None}, "implementation_model_failed"),
        ({"freeze_outcome": "failure"}, "implementation_freeze_failed"),
        ({"freeze_outcome": None}, "implementation_freeze_failed"),
        ({"frozen_bundle_present": False}, "implementation_freeze_failed"),
        ({"frozen_bundle_present": None}, "implementation_freeze_failed"),
        ({"selected_provider": "openai"}, "implementation_provider_lane_mismatch"),
        ({"selected_provider": "gemini"}, "unsupported_implementation_provider"),
        (
            {"lane_results": {"openai": "success", "sakana": "success"}},
            "implementation_provider_lane_ambiguous",
        ),
        (
            {"lane_results": {"openai": "skipped", "sakana": "skipped"}},
            "implementation_provider_lane_ambiguous",
        ),
    ],
)
def test_every_unproven_success_condition_refuses_completion(
    tmp_path: Path, overrides: dict[str, object], disposition: str
) -> None:
    classified = classify_implementation_lane(**_lane_inputs(tmp_path, **overrides))  # type: ignore[arg-type]
    assert classified["ok"] is False
    assert classified["disposition"] == disposition


@pytest.mark.parametrize("exit_code", ["1", "2", "5", "137"])
def test_a_nonzero_captured_exit_always_fails(tmp_path: Path, exit_code: str) -> None:
    """Regardless of the GitHub job conclusion."""

    inputs = _lane_inputs(
        tmp_path,
        lane_results={"openai": "skipped", "sakana": "success"},
        exit_code_path=_write(tmp_path / "exit", f"{exit_code}\n"),
    )
    classified = classify_implementation_lane(**inputs)  # type: ignore[arg-type]
    assert classified["ok"] is False
    assert classified["details"]["runner_exit_code"] == int(exit_code)


def test_a_runner_reporting_not_ok_always_fails(tmp_path: Path) -> None:
    runner = _write(
        tmp_path / "not-ok-result.json",
        json.dumps({"ok": False, "mode": "implement", "disposition": "completed"}),
    )
    classified = classify_implementation_lane(
        **_lane_inputs(tmp_path, result_path=runner)  # type: ignore[arg-type]
    )
    assert classified["ok"] is False


def test_an_inconsistent_runner_success_is_a_model_failure(tmp_path: Path) -> None:
    """`ok: true` with a summary that does not corroborate it proves nothing."""

    runner = _write(
        tmp_path / "inconsistent-result.json",
        json.dumps({"ok": True, "mode": "implement", "disposition": "completed"}),
    )
    classified = classify_implementation_lane(
        **_lane_inputs(tmp_path, result_path=runner)  # type: ignore[arg-type]
    )
    assert classified["disposition"] == "implementation_model_failed"


@pytest.mark.parametrize("bundle_present", [False, None])
def test_a_freeze_failure_is_not_reported_as_a_missing_model_result(
    tmp_path: Path, bundle_present: object
) -> None:
    """The frozen result is uploaded only when freezing succeeds.

    Requiring it before checking the freeze outcome would report every real
    freeze failure as `implementation_model_failed reason=implementation_result_missing`.
    """

    classified = classify_implementation_lane(
        **_lane_inputs(
            tmp_path,
            # The model did produce a result; the host saw it before freezing.
            implementation_result_present=True,
            # ...but the frozen copy was never uploaded, so it cannot be read.
            implementation_result_path=tmp_path / "never-frozen.json",
            freeze_outcome="failure",
            frozen_bundle_present=bundle_present,
        )  # type: ignore[arg-type]
    )
    assert classified["disposition"] == "implementation_freeze_failed"
    assert classified["details"]["freeze_outcome"] == "failure"


def test_a_missing_bundle_after_a_successful_freeze_is_still_a_freeze_failure(
    tmp_path: Path,
) -> None:
    classified = classify_implementation_lane(
        **_lane_inputs(tmp_path, frozen_bundle_present=False, implementation_result_present=True)  # type: ignore[arg-type]
    )
    assert classified["disposition"] == "implementation_freeze_failed"
    assert classified["details"]["reason"] == "frozen_bundle_missing"


def test_a_model_that_produced_no_result_is_still_a_model_failure(tmp_path: Path) -> None:
    """The pre-freeze observation is what distinguishes the two."""

    classified = classify_implementation_lane(
        **_lane_inputs(tmp_path, implementation_result_present=False, freeze_outcome="failure")  # type: ignore[arg-type]
    )
    assert classified["disposition"] == "implementation_model_failed"
    assert classified["details"]["reason"] == "implementation_result_missing"


@pytest.mark.parametrize(
    "disposition",
    [
        "implementation_provider_credential_missing",
        "implementation_prompt_budget_exceeded",
        "implementation_prompt_ceiling_drift",
        "implementation_prompt_preparation_failed",
    ],
)
def test_the_adapter_disposition_survives_to_terminal_state(
    tmp_path: Path, disposition: str
) -> None:
    """Writing it to the run directory is not durability.

    Without carrying it through lane evidence, each of these became a generic
    infrastructure failure and the specific reason died in the runner's
    temporary output directory.
    """

    classified = classify_implementation_lane(
        selected_provider="sakana",
        lane_results={"openai": "skipped", "sakana": "failure"},
        adapter_disposition=disposition,
    )
    assert classified["ok"] is False
    assert classified["disposition"] == disposition
    lane = _write(tmp_path / "lane.json", json.dumps(classified))
    assert (
        resolve_terminal_result(
            command="implement", result_path=None, exit_code_path=None, lane_path=lane
        )["disposition"]
        == disposition
    )


def test_an_unusable_adapter_disposition_is_ignored(tmp_path: Path) -> None:
    """Untrusted or malformed text must not become a canonical disposition."""

    for value in ("", "Not A Code", "x" * 200, None):
        classified = classify_implementation_lane(
            selected_provider="sakana",
            lane_results={"openai": "skipped", "sakana": "failure"},
            adapter_disposition=value,
        )
        assert classified["disposition"] == "implementation_provider_infrastructure_failed"


def test_an_adapter_disposition_never_upgrades_a_lane_to_success(tmp_path: Path) -> None:
    classified = classify_implementation_lane(
        **_lane_inputs(tmp_path, adapter_disposition="implementation_prompt_budget_exceeded")  # type: ignore[arg-type]
    )
    assert classified["ok"] is False
