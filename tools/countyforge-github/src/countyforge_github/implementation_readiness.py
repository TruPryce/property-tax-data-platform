"""Prove a materialized plan is implementation-readable before it is published.

PR #56 passed every planning check and would have been refused by the
implementation lane.  Its task markers declared `checks=make check`, which is
not an implementation check identifier and contains a space; the marker parser
captures `checks=([^\\s]+)`, so the whole marker failed to match and every task
silently fell back to the broad default write scope, lost its prerequisites, and
lost `risk=high`.  Nothing between the planner and the merge button noticed.

The gap was structural: planning validated the *result document*, and
implementation parses *materialized markdown*.  Two representations, two
vocabularies, and no step that read the second with the tool that would actually
read it.  This module is that step.  It re-parses the rendered `tasks.md` with
the implementation parser and validates each task against both implementation
schemas, so a plan that cannot be executed cannot be published.

It only refuses.  Nothing here rewrites a plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

from countyforge_runner.contracts import validate_document
from countyforge_runner.errors import KernelError

from countyforge_github.contracts import JsonObject, load_json_object
from countyforge_github.errors import ControlPlaneError
from countyforge_github.implementation import (
    _IMPLEMENTATION_VALIDATION_CHECKS,
    _tasks_from_text,
)

READINESS_DISPOSITION = "planning_not_implementation_ready"

#: The documents an implementation run will validate these tasks against.
_TASK_SCHEMAS = (
    "countyforge-implementation-packet.schema.json",
    "countyforge-implementation-task-plan.schema.json",
)


def implementation_check_ids() -> list[str]:
    """The authoritative check inventory, from the implementation lane itself.

    Planning is handed this rather than being told about it in prose, for the
    same reason `declared_capabilities` is: a vocabulary the model has to guess
    is a vocabulary it will get wrong.
    """

    return sorted(_IMPLEMENTATION_VALIDATION_CHECKS)


def _fail(reason: str, **details: object) -> NoReturn:
    raise ControlPlaneError(
        READINESS_DISPOSITION,
        "The materialized plan cannot be read by the implementation lane.",
        {"reason": reason, **details},
    )


def assert_implementation_readable(
    tasks_markdown: str, *, contract_root: Path, declared_task_ids: list[str]
) -> JsonObject:
    """Re-parse the rendered tasks with the implementation parser, or refuse.

    `declared_task_ids` comes from the planning result.  Comparing it with what
    the parser recovers is the whole point: a marker that fails to match is not
    an error to the parser, it is a task with default metadata, so only the
    round trip reveals it.
    """

    parsed = _tasks_from_text(tasks_markdown)
    recovered = [str(task["task_id"]) for task in parsed]
    if recovered != list(declared_task_ids):
        _fail(
            "task_round_trip_mismatch",
            declared=list(declared_task_ids)[:32],
            recovered=recovered[:32],
        )

    for task in parsed:
        task_id = str(task["task_id"])
        if task.get("metadata_complete") is not True:
            # The marker did not parse, or named a check the lane cannot run.
            # Either way the implementation run would refuse this change.
            _fail(
                "task_metadata_unreadable",
                task=task_id,
                required_checks=[str(item) for item in task.get("required_checks") or []][:8],
                supported_checks=implementation_check_ids(),
            )
        unsupported = sorted(
            str(check)
            for check in task.get("required_checks") or []
            if str(check) not in _IMPLEMENTATION_VALIDATION_CHECKS
        )
        if unsupported:
            _fail(
                "task_check_unsupported",
                task=task_id,
                unsupported=unsupported[:8],
                supported_checks=implementation_check_ids(),
            )
        for schema_name in _TASK_SCHEMAS:
            schema = load_json_object(
                contract_root / ".ai/schemas" / schema_name, kind="implementation task schema"
            )
            try:
                validate_document(
                    task, schema["properties"]["tasks"]["items"], kind="implementation task"
                )
            except KernelError as error:
                details = error.details if isinstance(error.details, dict) else {}
                _fail(
                    "task_rejected_by_implementation_schema",
                    task=task_id,
                    schema=schema_name,
                    path=str(details.get("path", "")),
                    validator=str(details.get("validator", "")),
                )

    return {
        "contract_version": 1,
        "implementation_readable": True,
        "task_count": len(parsed),
        "task_ids": recovered,
        "checks_used": sorted(
            {str(check) for task in parsed for check in task.get("required_checks") or []}
        ),
    }


def readiness_evidence(document: JsonObject) -> str:
    """Bounded, deterministic evidence for the publication manifest."""

    return json.dumps(document, sort_keys=True)
