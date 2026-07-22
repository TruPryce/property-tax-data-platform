"""Bounded Markdown command parsing without executing untrusted text."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from countyforge_github.contracts import ControlContracts, JsonObject

MAX_COMMENT_BYTES = 65_536
MAX_COMMAND_LINE_CHARS = 512
EXECUTION_COMMANDS = frozenset({"plan", "implement", "validate", "review", "fix"})
CONTROL_COMMANDS = frozenset({"status", "cancel", "retry"})
COMMANDS = EXECUTION_COMMANDS | CONTROL_COMMANDS
_COMMAND = re.compile(r"^/countyforge[ \t]+([A-Za-z]+)(?:[ \t]+(.+))?$", re.ASCII | re.IGNORECASE)
_OPEN_SPEC = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", re.ASCII)
_CONFUSABLE_NAMESPACE = str.maketrans(
    {
        "／": "/",
        "∕": "/",
        "⁄": "/",
        "а": "a",
        "е": "e",
        "і": "i",
        "ј": "j",
        "ο": "o",
        "о": "o",
        "р": "p",
        "ρ": "p",
        "с": "c",
        "у": "y",
        "υ": "y",
        "х": "x",
        "χ": "x",
    }
)


def _without_inline_code(line: str) -> str:
    """Replace inline-code spans so command-looking text cannot match."""

    result: list[str] = []
    index = 0
    while index < len(line):
        if line[index] != "`":
            result.append(line[index])
            index += 1
            continue
        end = index
        while end < len(line) and line[end] == "`":
            end += 1
        delimiter = line[index:end]
        closing = line.find(delimiter, end)
        if closing < 0:
            break
        result.append(" " * (closing + len(delimiter) - index))
        index = closing + len(delimiter)
    return "".join(result)


def _parse_arguments(command: str, raw: str | None) -> JsonObject:
    if raw is None:
        return {}
    pieces = raw.split()
    if command not in EXECUTION_COMMANDS:
        raise ValueError("arguments_not_allowed")
    if command == "implement" and len(pieces) == 1 and not pieces[0].startswith("-"):
        change = pieces[0]
    elif len(pieces) == 2 and pieces[0].casefold() == "--openspec-change":
        change = pieces[1]
    elif len(pieces) == 1 and pieces[0].casefold().startswith("--openspec-change="):
        change = pieces[0].split("=", 1)[1]
    else:
        raise ValueError("unknown_arguments")
    if len(change) > 128 or _OPEN_SPEC.fullmatch(change) is None:
        raise ValueError("invalid_openspec_change")
    return {"openspec_change": change}


def _is_countyforge_lookalike(candidate: str) -> bool:
    """Reject a non-ASCII spelling only when its command namespace is confusable."""

    if candidate.isascii():
        return False
    namespace = candidate.split(maxsplit=1)[0]
    skeleton = unicodedata.normalize("NFKC", namespace).casefold().translate(_CONFUSABLE_NAMESPACE)
    return skeleton == "/countyforge"


def parse_comment(
    body: str,
    *,
    action: str = "created",
    actor_type: str = "User",
    actor_login: str = "",
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Parse exactly one eligible top-level command from a comment body."""

    if action != "created":
        return {"ok": True, "status": "ignored", "reason_code": "event_action_ignored"}
    if actor_type.casefold() == "bot" or actor_login.casefold().endswith("[bot]"):
        return {"ok": True, "status": "ignored", "reason_code": "bot_comment_ignored"}
    if len(body.encode("utf-8")) > MAX_COMMENT_BYTES:
        return {"ok": False, "status": "rejected", "reason_code": "comment_too_large"}

    matches: list[JsonObject] = []
    fence: str | None = None
    in_html_comment = False
    for raw_line in body.splitlines():
        stripped = raw_line.lstrip()
        if in_html_comment:
            if "-->" in stripped:
                in_html_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_html_comment = True
            continue
        fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence_match is not None:
            marker = fence_match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None or stripped.startswith(">"):
            continue
        candidate = _without_inline_code(raw_line).strip()
        if _is_countyforge_lookalike(candidate):
            return {
                "ok": False,
                "status": "rejected",
                "reason_code": "unicode_lookalike",
            }
        if not candidate.startswith("/"):
            continue
        if len(candidate) > MAX_COMMAND_LINE_CHARS:
            return {"ok": False, "status": "rejected", "reason_code": "command_too_long"}
        command_match = _COMMAND.fullmatch(candidate)
        if command_match is None:
            if candidate.casefold().startswith("/countyforge"):
                return {"ok": False, "status": "rejected", "reason_code": "invalid_command_syntax"}
            continue
        command = command_match.group(1).casefold()
        if command not in COMMANDS:
            return {"ok": False, "status": "rejected", "reason_code": "unknown_command"}
        try:
            arguments = _parse_arguments(command, command_match.group(2))
        except ValueError as error:
            return {"ok": False, "status": "rejected", "reason_code": str(error)}
        matches.append({"contract_version": 1, "command": command, "arguments": arguments})

    if not matches:
        return {"ok": True, "status": "ignored", "reason_code": "no_command"}
    if len(matches) != 1:
        return {"ok": False, "status": "rejected", "reason_code": "multiple_commands"}
    selected = matches[0]
    (contracts or ControlContracts()).validate("command", selected)
    return {"ok": True, "status": "parsed", "command_document": selected}


def parse_event(event: dict[str, Any], contracts: ControlContracts | None = None) -> JsonObject:
    """Read only the bounded comment and author fields from an issue_comment payload."""

    comment = event.get("comment", {})
    if not isinstance(comment, dict):
        comment = {}
    actor = comment.get("user", event.get("sender", {}))
    if not isinstance(actor, dict):
        actor = {}
    return parse_comment(
        str(comment.get("body", "")),
        action=str(event.get("action", "")),
        actor_type=str(actor.get("type", "")),
        actor_login=str(actor.get("login", "")),
        contracts=contracts,
    )
