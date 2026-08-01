"""Deterministic, character-budgeted implementation prompt assembly.

Run 30698203658 shipped a 2,103,429-character prompt to a provider that accepts
1,048,576, and the request was rejected before the model ever ran.  The adapter's
own ceilings were 4 MiB of source snapshot and 10 MiB of assembled prompt, so
nothing in the stack represented the provider's real input limit.

The provider counts *characters*, so characters are the authoritative gate here;
the byte ceiling is kept as defence in depth.  Mandatory contracts are never
silently truncated: they are measured first, and if they alone exceed the ceiling
the build fails before any provider invocation.  Source files are then added
whole, in a deterministic priority order, until the remaining budget is spent,
and every included and omitted path is recorded as evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from countyforge_runner.contracts import JsonObject
from countyforge_runner.errors import KernelError

# Never sent to a provider, and never used as approved write paths.
EXCLUDED_PREFIXES: tuple[str, ...] = (
    ".git",
    ".github/workflows",
    ".ai/policies",
    ".env",
)
EXCLUDED_PARTS = frozenset(
    {
        ".venv",
        "venv",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        ".tox",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)
_SECRETISH = re.compile(r"(^|/)\.env(\.|$)|(^|/)[^/]*(secret|credential|token)[^/]*$", re.I)

# Bounded: the notice must not itself consume meaningful budget, and it is
# reserved for up front because it is assembled after source selection and
# would otherwise be able to push the finished prompt past the ceiling.
_MAX_LISTED_OMISSIONS = 200
_NOTICE_RESERVE_CHARS = 24_000

OMISSION_REASONS = (
    "character_budget_exceeded",
    "excluded_by_policy",
    "binary_or_invalid_utf8",
    "per_file_limit_exceeded",
)

_MANDATORY_SECTIONS = (
    ("IMPLEMENTATION PACKET", "packet"),
    ("IMPLEMENTATION CONTEXT MANIFEST", "manifest"),
    ("IMPLEMENTATION TASK PLAN", "task_plan"),
    ("IMPLEMENTATION RESULT SCHEMA", "result_schema"),
    ("IMPLEMENTATION COMMAND POLICY", "command_policy"),
)
_SNAPSHOT_HEADING = "\n\n===== SOURCE WORKSPACE SNAPSHOT (TRUSTED READ-ONLY CONTEXT) ====="
_CLOSING = (
    "\n\nThe dynamic context above is the complete bounded input to this run. "
    "Use only the declared file_bundle output; do not claim commands or tests that are not "
    "represented by trusted evidence."
)


def measured_length(text: str) -> int:
    """The character count this contract gates on.

    "Characters" is ambiguous: `len()` counts Unicode code points, while a
    provider may count UTF-16 code units, where an astral character counts
    twice.  Gating on the larger of the two makes the configured margin real
    under either definition instead of assuming BMP-only source.  Tokens are
    deliberately not modelled; the ceiling's margin covers that gap.
    """

    code_points = len(text)
    astral = sum(1 for character in text if ord(character) > 0xFFFF)
    return max(code_points, code_points + astral)


@dataclass(frozen=True, slots=True)
class PromptBudget:
    """Limits this build must satisfy, all declared in trusted configuration."""

    maximum_model_input_chars: int
    max_input_bytes: int
    per_file_max_chars: int = 200_000


@dataclass(slots=True)
class PromptBuild:
    prompt: str
    included: list[str] = field(default_factory=list)
    omitted: list[tuple[str, str]] = field(default_factory=list)
    mandatory_chars: int = 0
    source_chars: int = 0

    def provenance(self, budget: PromptBudget) -> JsonObject:
        """Bounded facts only; no source content ever enters provenance."""

        return {
            "contract_version": 1,
            "maximum_model_input_chars": budget.maximum_model_input_chars,
            "mandatory_chars": self.mandatory_chars,
            "source_chars": self.source_chars,
            "total_chars": measured_length(self.prompt),
            "total_code_points": len(self.prompt),
            "total_utf8_bytes": len(self.prompt.encode("utf-8")),
            "included_source_paths": list(self.included),
            "omitted_source_paths": [
                {"path": path, "reason": reason} for path, reason in self.omitted
            ],
            "included_source_file_count": len(self.included),
            "omitted_source_file_count": len(self.omitted),
            "budget_utilisation": round(
                measured_length(self.prompt) / budget.maximum_model_input_chars, 4
            ),
            "source_context_elided": any(
                reason == "character_budget_exceeded" for _, reason in self.omitted
            ),
            "prompt_sha256": hashlib.sha256(self.prompt.encode("utf-8")).hexdigest(),
        }


def _is_excluded(relative: str, parts: Sequence[str]) -> bool:
    if any(relative == item or relative.startswith(item + "/") for item in EXCLUDED_PREFIXES):
        return True
    if any(part in EXCLUDED_PARTS for part in parts):
        return True
    return _SECRETISH.search(relative) is not None


def _approved_roots(task_plan: JsonObject) -> list[str]:
    """The trusted task plan's approved write roots, deterministically ordered."""

    roots: list[str] = []
    tasks = task_plan.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for candidate in task.get("allowed_paths") or []:
                value = str(candidate).strip("/")
                if value and value not in roots:
                    roots.append(value)
    return sorted(roots)


def under_approved_root(relative: str, roots: Sequence[str]) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in roots)


def _priority(relative: str, roots: Sequence[str]) -> int:
    """Lower sorts first: implementation-relevant context before the rest.

    Ordering is a pure function of the path and the trusted task plan, so two
    builds over the same workspace select the same files.
    """

    under_root = under_approved_root(relative, roots)
    is_test = "/tests/" in f"/{relative}" or relative.startswith("tests/")
    if under_root and not is_test:
        return 0 if relative.endswith((".py", ".sql", ".toml", ".cfg")) else 1
    if under_root:
        return 2
    if relative.startswith("libs/") or relative.startswith("services/"):
        return 3
    if relative.startswith("tests/"):
        return 4
    if relative.startswith("docs/") or relative.endswith((".md", ".toml")):
        return 5
    return 6


def select_source_files(
    workspace: Path, *, task_plan: JsonObject
) -> tuple[list[Path], list[tuple[str, str]]]:
    """Return candidate files in deterministic priority order, plus policy omissions."""

    roots = _approved_roots(task_plan)
    candidates: list[tuple[int, str, Path]] = []
    omitted: list[tuple[str, str]] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative_path = path.relative_to(workspace)
        relative = relative_path.as_posix()
        if _is_excluded(relative, relative_path.parts):
            omitted.append((relative, "excluded_by_policy"))
            continue
        candidates.append((_priority(relative, roots), relative, path))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in candidates], omitted


def build_implementation_prompt(
    *,
    instructions: str,
    contracts: dict[str, str],
    workspace: Path,
    task_plan: JsonObject,
    budget: PromptBudget,
) -> PromptBuild:
    """Assemble the bounded prompt, or fail before any provider is contacted.

    `contracts` maps each mandatory contract input to its exact text.  Those
    sections are byte-identical in the output; only source context is elided.
    """

    sections = [instructions]
    for title, key in _MANDATORY_SECTIONS:
        sections.append(f"\n\n===== {title} =====\n{contracts[key]}")
    mandatory = "".join(sections)
    mandatory_chars = len(mandatory) + len(_SNAPSHOT_HEADING) + len(_CLOSING)
    if mandatory_chars > budget.maximum_model_input_chars:
        raise KernelError(
            "implementation_prompt_budget_exceeded",
            "Mandatory implementation contracts exceed the model input budget.",
            {
                "maximum_model_input_chars": budget.maximum_model_input_chars,
                "mandatory_chars": mandatory_chars,
            },
            exit_code=2,
        )

    files, omitted = select_source_files(workspace, task_plan=task_plan)
    roots = _approved_roots(task_plan)
    remaining = budget.maximum_model_input_chars - mandatory_chars - _NOTICE_RESERVE_CHARS
    included: list[str] = []
    source_sections: list[str] = []
    source_chars = 0
    for path in files:
        relative = path.relative_to(workspace).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            omitted.append((relative, "binary_or_invalid_utf8"))
            continue
        block = f"\n\n--- {relative} ---\n{text}"
        measured = measured_length(block)
        approved = under_approved_root(relative, roots)
        if measured > budget.per_file_max_chars:
            if approved:
                # The task is literally about this material.  A model editing a
                # file it was never shown produces work that fails validation for
                # reasons it could not have known.
                raise KernelError(
                    "implementation_prompt_budget_exceeded",
                    "An approved-path file exceeds the per-file prompt budget.",
                    {"path": relative, "per_file_max_chars": budget.per_file_max_chars},
                    exit_code=2,
                )
            omitted.append((relative, "per_file_limit_exceeded"))
            continue
        if source_chars + measured > remaining:
            if approved:
                raise KernelError(
                    "implementation_prompt_budget_exceeded",
                    "The prompt budget cannot hold every approved-path file.",
                    {
                        "path": relative,
                        "maximum_model_input_chars": budget.maximum_model_input_chars,
                        "mandatory_chars": mandatory_chars,
                    },
                    exit_code=2,
                )
            # Whole files only: a partial file would misrepresent the source.
            omitted.append((relative, "character_budget_exceeded"))
            continue
        source_sections.append(block)
        source_chars += measured
        included.append(relative)

    omitted.sort()
    # The model is told what it was not shown.  Without this it reasons over a
    # partial view and reports success without knowing the view was partial.
    elided = [path for path, reason in omitted if reason == "character_budget_exceeded"]
    notice = ""
    if elided:
        listed = "\n".join(f"- {path}" for path in elided[:_MAX_LISTED_OMISSIONS])
        overflow = len(elided) - min(len(elided), _MAX_LISTED_OMISSIONS)
        notice = (
            "\n\n===== OMITTED SOURCE CONTEXT ====="
            f"\n{len(elided)} repository files were not included because the bounded input"
            " budget was exhausted. None is under this task's approved paths."
            " Treat the snapshot as partial: if you need one of these, say so in your"
            " result instead of assuming its contents.\n"
            f"{listed}" + (f"\n- ... and {overflow} more" if overflow else "")
        )
        if measured_length(notice) > _NOTICE_RESERVE_CHARS:
            # Never spend more than the reservation, whatever the path lengths.
            notice = notice[: _NOTICE_RESERVE_CHARS - 32] + "\n- ... (list truncated)"

    prompt = mandatory + notice + _SNAPSHOT_HEADING + "".join(source_sections) + _CLOSING
    # The notice is assembled after budgeting, so re-verify the final artefact
    # against both ceilings rather than trusting the running total.
    if measured_length(prompt) > budget.maximum_model_input_chars:
        raise KernelError(
            "implementation_prompt_budget_exceeded",
            "The assembled implementation prompt exceeds the model input budget.",
            {
                "maximum_model_input_chars": budget.maximum_model_input_chars,
                "total_chars": measured_length(prompt),
            },
            exit_code=2,
        )
    if len(prompt.encode("utf-8")) > budget.max_input_bytes:
        raise KernelError(
            "implementation_prompt_budget_exceeded",
            "The assembled implementation prompt exceeds the model input byte budget.",
            {
                "max_input_bytes": budget.max_input_bytes,
                "total_utf8_bytes": len(prompt.encode("utf-8")),
            },
            exit_code=2,
        )
    return PromptBuild(
        prompt=prompt,
        included=included,
        omitted=omitted,
        mandatory_chars=mandatory_chars,
        source_chars=source_chars,
    )


def omitted_by_reason(omitted: Iterable[tuple[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {reason: 0 for reason in OMISSION_REASONS}
    for _, reason in omitted:
        counts[reason] = counts.get(reason, 0) + 1
    return counts
