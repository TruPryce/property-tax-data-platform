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

# Shell vocabulary, scanned only in fields that describe commands.  Words such
# as "source", "docker", and "git" are ordinary architecture prose everywhere
# else, and this repository plans county source-onboarding work constantly.
_COMMAND_PAYLOADS = (
    *_SUBSTITUTION,
    re.compile(r"(?:^|\s)(?:rm|sudo|chmod|chown|curl|wget|docker|git\s+(?:push|commit|reset))\b"),
    re.compile(r"(?:^|\s)(?:bash|sh|zsh|python(?:3)?|node)\s+-c\b"),
    # `eval` and `source` are builtins only in command position, and `source`
    # must additionally take something path-shaped: "source record" and "source
    # onboarding" are this project's own vocabulary, `source ./script.sh` is not.
    re.compile(r"(?:^|[;&|]\s*)eval\s+\S", re.MULTILINE),
    re.compile(r"(?:^|[;&|]\s*)source\s+(?:\S*/|\.\w|[$~])", re.MULTILINE),
    re.compile(r"\|\||&&"),
    re.compile(r";\s*(?:rm|git|curl|wget|bash|sh|python(?:3)?)\b"),
)

_COMMAND_FIELDS = ("task_slices", "validation_commands")
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


def _command_candidates(value: str) -> list[str]:
    """Scan a command field as written and once per inline-code span.

    Unwrapping the backticks keeps ``make check`` readable to the payload rules
    instead of rejecting every Markdown identifier.  Re-scanning each span on its
    own puts its first word in command position, so a quoted ``source ./x.sh``
    is still caught wherever the plan happens to quote it.
    """

    return [_INLINE_CODE.sub(r" \1 ", value), *_INLINE_CODE.findall(value)]


def validate_planning_payload(result: JsonObject) -> None:
    """Reject executable-looking content before a plan is reported successful.

    Scanning is tiered by what a field is for.  ``task_slices`` and
    ``validation_commands`` describe work and commands, so they carry the full
    shell-payload policy.  Every other planning field is architecture prose and
    is checked only for command/parameter substitution and interpreter piping,
    which have no legitimate prose meaning.  Prose remains bounded by the
    authoritative schema, path policy, citations, output budgets, and trusted
    materialization.  This policy is intentionally dependency-free so the runner
    can enforce it before writing a completed result; the GitHub adapter repeats
    the same policy alongside its path and citation checks.
    """

    for value in _strings(result, _PROSE_FIELDS):
        if any(pattern.search(value) for pattern in _SUBSTITUTION):
            _reject()
    for value in _strings(result, _COMMAND_FIELDS):
        for candidate in _command_candidates(value):
            if any(pattern.search(candidate) for pattern in _COMMAND_PAYLOADS):
                _reject()


def _reject() -> NoReturn:
    raise KernelError(
        "unsafe_plan_payload",
        "Planning output contains executable-looking content.",
        exit_code=5,
    )
