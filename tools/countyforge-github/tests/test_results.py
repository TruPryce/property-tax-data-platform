"""Runner result artifact interpretation fixtures."""

from __future__ import annotations

from pathlib import Path

from countyforge_github.results import resolve_terminal_result


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


def test_future_mode_keeps_structured_not_implemented_disposition(tmp_path: Path) -> None:
    result = _write(tmp_path / "result.json", '{"disposition":"profile_not_implemented"}')
    assert resolve_terminal_result(command="plan", result_path=result, exit_code_path=None) == {
        "ok": True,
        "state": "not_implemented",
        "disposition": "profile_not_implemented",
    }
