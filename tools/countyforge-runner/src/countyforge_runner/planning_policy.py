"""Dependency-free safety policy for structured planning results."""

from __future__ import annotations

import json
import re

from countyforge_runner.contracts import JsonObject
from countyforge_runner.errors import KernelError

_SHELL_PAYLOADS = (
    re.compile(r"\$\("),
    re.compile(r"\$\{"),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"(?:^|\s)(?:rm|sudo|chmod|chown|curl|wget|docker|git\s+(?:push|commit|reset))\b"),
    re.compile(r"(?:^|\s)(?:bash|sh|zsh|python(?:3)?|node)\s+-c\b"),
    re.compile(r"(?:^|\s)(?:eval|source)\s+"),
    re.compile(r"\|\||&&|\|\s*(?:sh|bash|zsh|python(?:3)?|node)\b"),
    re.compile(r";\s*(?:rm|git|curl|wget|bash|sh|python(?:3)?)\b"),
)


def validate_planning_payload(result: JsonObject) -> None:
    """Reject executable-looking content before a plan is reported successful.

    Planning prose remains free-form, but structured task/command fields cannot
    carry shell substitutions, command chaining, interpreters, or destructive
    operations.  This policy is intentionally dependency-free so the runner can
    enforce it before writing a completed result; the GitHub adapter repeats the
    same policy alongside its path and citation checks.
    """

    fields = (
        "problem_statement",
        "desired_outcome",
        "assumptions",
        "unresolved_decisions",
        "task_slices",
        "acceptance_criteria",
        "risks",
        "security_privacy_considerations",
        "migration_compatibility_concerns",
        "validation_commands",
        "non_goals",
    )
    values: list[str] = []
    for field in fields:
        value = result.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    serialized = json.dumps(values, ensure_ascii=False)
    if any(pattern.search(serialized) for pattern in _SHELL_PAYLOADS):
        raise KernelError(
            "unsafe_plan_payload",
            "Planning output contains executable-looking content.",
            exit_code=5,
        )
