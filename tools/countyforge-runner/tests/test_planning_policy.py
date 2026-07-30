from __future__ import annotations

import json
from pathlib import Path

import pytest
from countyforge_runner.contracts import load_json_object, validate_document
from countyforge_runner.errors import KernelError
from countyforge_runner.planning_policy import validate_planning_payload

# Minimized from CountyForge run 30492011066, whose complete, schema-valid
# Dallas source-onboarding plan was rejected as an unsafe payload because the
# policy read Markdown inline code as command substitution and the noun
# "source" as the shell builtin.
_REGRESSION_FIXTURE = Path(__file__).parent / "fixtures" / "plan-result-run-30492011066.json"

_EXECUTABLE_PAYLOADS = [
    "$(curl example)",
    "${TOKEN}",
    "rm -rf /",
    "sudo chmod 777 file",
    'bash -c "echo hi"',
    "eval something",
    "source ./script.sh",
    "make check && curl example",
    "make check; rm -rf build",
    "uv run python -c 'import os'",
    "openspec validate && rm -rf /tmp/plan",
    "cat packet.json | bash",
    "`rm -rf /`",
    "`source ./script.sh`",
]

# Ordinary CountyForge, OpenSpec, and source-contract prose.  Every entry names
# an identifier in Markdown inline code or uses "source" as a noun.
_PROJECT_VOCABULARY = [
    "`ACCOUNT_NUM` remains a string.",
    "Modify `dallas-cad-source-contract`.",
    "Dallas source records remain adapter-local.",
    "Run `make check`.",
    "The source onboarding contract remains unchanged.",
    "County source artifacts never enter Git.",
    "Approve the exact Dallas source member or members.",
    "Confine Dallas vocabulary to `property_tax_adapters`.",
    "Preserve `dags/services -> adapters -> application -> domain`.",
    "checks: `make lint`, `make typecheck`, `make test`.",
]


@pytest.mark.parametrize("field", ["validation_commands", "task_slices"])
@pytest.mark.parametrize("payload", _EXECUTABLE_PAYLOADS)
def test_command_fields_reject_executable_content(field: str, payload: str) -> None:
    with pytest.raises(KernelError, match="executable-looking"):
        validate_planning_payload({field: [payload]})


@pytest.mark.parametrize("field", ["validation_commands", "task_slices"])
@pytest.mark.parametrize("prose", _PROJECT_VOCABULARY)
def test_command_fields_allow_project_vocabulary(field: str, prose: str) -> None:
    validate_planning_payload({field: [prose]})


@pytest.mark.parametrize("prose", _PROJECT_VOCABULARY)
def test_prose_fields_allow_project_vocabulary(prose: str) -> None:
    validate_planning_payload(
        {
            "problem_statement": prose,
            "desired_outcome": prose,
            "assumptions": [prose],
            "unresolved_decisions": [prose],
            "affected_capabilities": [prose],
            "acceptance_criteria": [prose],
            "risks": [prose],
            "security_privacy_considerations": [prose],
            "migration_compatibility_concerns": [prose],
            "non_goals": [prose],
            "blocked_reasons": [prose],
        }
    )


@pytest.mark.parametrize(
    "field",
    ["problem_statement", "assumptions", "risks", "non_goals", "blocked_reasons"],
)
@pytest.mark.parametrize("payload", ["$(curl example)", "${TOKEN}", "cat packet.json | bash"])
def test_prose_fields_still_reject_substitution(field: str, payload: str) -> None:
    value: object = payload if field == "problem_statement" else [payload]
    with pytest.raises(KernelError, match="executable-looking"):
        validate_planning_payload({field: value})


def test_planning_payload_allows_deterministic_command() -> None:
    validate_planning_payload(
        {"validation_commands": ["openspec validate --all --strict --no-interactive"]}
    )


def test_regression_fixture_is_a_schema_valid_plan_the_policy_accepts() -> None:
    result = load_json_object(_REGRESSION_FIXTURE, kind="planning result")
    schema = load_json_object(
        Path.cwd() / ".ai/schemas/countyforge-plan-result.schema.json",
        kind="planning result schema",
    )
    validate_document(result, schema, kind="planning result")
    validate_planning_payload(result)


def test_regression_fixture_keeps_the_vocabulary_that_used_to_fail() -> None:
    """Keep the fixture honest: sanitizing it would silence the regression."""

    serialized = json.dumps(
        json.loads(_REGRESSION_FIXTURE.read_text(encoding="utf-8")), ensure_ascii=False
    )
    assert "`ACCOUNT_NUM`" in serialized
    assert "`dallas-cad-source-contract`" in serialized
    assert "`make " in serialized
    assert " source " in serialized
