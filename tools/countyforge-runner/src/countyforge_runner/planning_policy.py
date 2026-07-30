"""Dependency-free safety policy for structured planning results."""

from __future__ import annotations

import re
from typing import NoReturn

from countyforge_runner.contracts import JsonObject
from countyforge_runner.errors import KernelError

# Markdown inline code.  Planning documents name identifiers, capabilities, and
# commands this way, so a backtick span is never by itself evidence of command
# substitution; only the text it wraps can be executable.
_INLINE_CODE = re.compile(r"`([^`\n]+)`")

# Substitution and interpreter piping carry no meaning in planning text, so they
# are rejected in every scanned field.
_SUBSTITUTION = (
    re.compile(r"\$\("),
    re.compile(r"\$\{"),
    re.compile(r"\|\s*(?:sh|bash|zsh|python(?:3)?|node)\b"),
)

# Executable shell syntax: chaining, separators, interpreters, and destructive
# commands.  Rejected wherever a field describes work or commands.
_SHELL_SYNTAX = (
    *_SUBSTITUTION,
    re.compile(r"(?:^|\s)(?:rm|sudo|chmod|chown|curl|wget|docker|git\s+(?:push|commit|reset))\b"),
    re.compile(r"(?:^|\s)(?:bash|sh|zsh|python(?:3)?|node)\s+-c\b"),
    re.compile(r"\|\||&&"),
    re.compile(r";\s*(?:rm|git|curl|wget|bash|sh|python(?:3)?)\b"),
)

# `eval` and `source` invoked in command position with any argument.  The policy
# makes no guess about whether that argument looks like a filename: `source
# script.sh` and `source "./setup.sh"` are as executable as `source ./x.sh`, and
# a shape heuristic would only be bypassable.  Both names are also ordinary
# nouns -- this repository plans county source contracts constantly -- so the
# tier applies only where the text is a command rather than a description.
_BUILTINS = (re.compile(r"(?:^|[;&|]\s*)(?:eval|source)\s+\S", re.MULTILINE),)

_COMMAND_PAYLOADS = (*_SHELL_SYNTAX, *_BUILTINS)

_PROSE_FIELDS = (
    "problem_statement",
    "desired_outcome",
    "assumptions",
    "unresolved_decisions",
    "affected_capabilities",
    "acceptance_criteria",
    "risks",
    "security_privacy_considerations",
    "migration_compatibility_concerns",
    "non_goals",
    "blocked_reasons",
)


def _strings(result: JsonObject, fields: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for field in fields:
        value = result.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return values


def _scan(text: str, patterns: tuple[re.Pattern[str], ...]) -> None:
    if any(pattern.search(text) for pattern in patterns):
        _reject()


def _unwrap(value: str) -> str:
    """Drop the backticks so inline code is read as text, not as substitution."""

    return _INLINE_CODE.sub(r" \1 ", value)


def validate_planning_payload(result: JsonObject) -> None:
    """Reject executable-looking content before a plan is reported successful.

    Scanning is tiered by what a field is for.

    ``validation_commands`` names commands, so every rule applies to it,
    including a shell builtin invoked in command position with any argument.

    ``task_slices`` describes work in prose that quotes its commands, so the
    builtin tier applies to its Markdown inline-code spans rather than to the
    surrounding sentence: ``Retain Dallas source records`` is a description and
    ``Run `source ./setup.sh``` is not.  Substitution, chaining, separators,
    interpreters, and destructive commands still apply to the whole slice.

    Every other planning field is architecture prose and is checked only for
    command/parameter substitution and interpreter piping, which have no
    legitimate prose meaning.  Prose remains bounded by the authoritative
    schema, path policy, citations, output budgets, and trusted materialization.

    This policy is intentionally dependency-free so the runner can enforce it
    before writing a completed result; the GitHub adapter repeats the same
    policy alongside its path and citation checks.
    """

    for value in _strings(result, _PROSE_FIELDS):
        _scan(value, _SUBSTITUTION)
    for value in _strings(result, ("task_slices",)):
        _scan(_unwrap(value), _SHELL_SYNTAX)
        for span in _INLINE_CODE.findall(value):
            _scan(span, _COMMAND_PAYLOADS)
    for value in _strings(result, ("validation_commands",)):
        _scan(_unwrap(value), _COMMAND_PAYLOADS)
        for span in _INLINE_CODE.findall(value):
            _scan(span, _COMMAND_PAYLOADS)


def _reject() -> NoReturn:
    raise KernelError(
        "unsafe_plan_payload",
        "Planning output contains executable-looking content.",
        exit_code=5,
    )
