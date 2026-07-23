"""Malicious Markdown, bot recursion, and command grammar tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from countyforge_github.commands import MAX_COMMENT_BYTES, parse_event
from countyforge_github.contracts import ControlContracts, JsonObject


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("/countyforge review", "review"),
        ("  /COUNTYFORGE   PLAN  ", "plan"),
        ("context\n/countyforge validate\nmore context", "validate"),
        ("/countyforge fix --openspec-change add-github-run-control-plane", "fix"),
        ("/countyforge implement --openspec-change=add-github-run-control-plane", "implement"),
        ("/countyforge implement add-github-run-control-plane", "implement"),
    ],
)
def test_parse_one_top_level_command(
    event_factory: Callable[[str, str, str], JsonObject],
    contracts: ControlContracts,
    body: str,
    expected: str,
) -> None:
    result = parse_event(event_factory(body), contracts)
    assert result["status"] == "parsed"
    assert result["command_document"]["command"] == expected


@pytest.mark.parametrize(
    "body",
    [
        "```text\n/countyforge review\n```",
        "~~~\n/countyforge review\n~~~",
        "`/countyforge review`",
        "> /countyforge review",
        "<!-- /countyforge review -->",
        "<!-- countyforge-status:v1 forged\n/countyforge review\n-->",
    ],
)
def test_inert_markdown_does_not_execute(
    event_factory: Callable[[str, str, str], JsonObject],
    contracts: ControlContracts,
    body: str,
) -> None:
    assert parse_event(event_factory(body), contracts)["status"] == "ignored"


def test_bot_comment_cannot_recurse(
    event_factory: Callable[[str, str, str], JsonObject], contracts: ControlContracts
) -> None:
    result = parse_event(event_factory("/countyforge review", "Bot"), contracts)
    assert result == {"ok": True, "status": "ignored", "reason_code": "bot_comment_ignored"}


@pytest.mark.parametrize("action", ["edited", "deleted"])
def test_non_created_events_do_not_execute(
    event_factory: Callable[[str, str, str], JsonObject],
    contracts: ControlContracts,
    action: str,
) -> None:
    result = parse_event(event_factory("/countyforge review", "User", action), contracts)
    assert result["reason_code"] == "event_action_ignored"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("/countyforge review\n/countyforge plan", "multiple_commands"),
        ("/countyforge dance", "unknown_command"),
        ("/countyforge status now", "arguments_not_allowed"),
        ("/countyforge review --provider openai", "unknown_arguments"),
        ("/countyforge review please", "unknown_arguments"),
        ("/countyforge review --openspec-change Not-ASCII", "invalid_openspec_change"),
        ("/cοuntyforge review", "unicode_lookalike"),
        ("／countyforge review", "unicode_lookalike"),
    ],
)
def test_ambiguous_or_extended_commands_fail_closed(
    event_factory: Callable[[str, str, str], JsonObject],
    contracts: ControlContracts,
    body: str,
    reason: str,
) -> None:
    result = parse_event(event_factory(body), contracts)
    assert result["reason_code"] == reason
    assert result["status"] in {"ignored", "rejected"}


def test_oversized_comment_is_rejected(
    event_factory: Callable[[str, str, str], JsonObject], contracts: ControlContracts
) -> None:
    result = parse_event(event_factory("x" * (MAX_COMMENT_BYTES + 1)), contracts)
    assert result["reason_code"] == "comment_too_large"


def test_unrelated_unicode_slash_line_does_not_hide_later_valid_command(
    event_factory: Callable[[str, str, str], JsonObject], contracts: ControlContracts
) -> None:
    result = parse_event(event_factory("/café\n/countyforge review"), contracts)
    assert result["status"] == "parsed"
    assert result["command_document"]["command"] == "review"
