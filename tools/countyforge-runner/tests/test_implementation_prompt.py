"""Character-budgeted implementation prompt assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from countyforge_runner.errors import KernelError
from countyforge_runner.implementation_prompt import (
    EXCLUDED_PREFIXES,
    PromptBudget,
    build_implementation_prompt,
    omitted_by_reason,
    select_source_files,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "implementation-prompt-run-30698203658.json"
CEILING = 950_000
_CONTRACT_KEYS = ("packet", "manifest", "task_plan", "result_schema", "command_policy")


def _contracts(**overrides: str) -> dict[str, str]:
    contracts = {key: json.dumps({"contract_version": 1, "kind": key}) for key in _CONTRACT_KEYS}
    contracts.update(overrides)
    return contracts


def _task_plan(*allowed: str) -> dict[str, object]:
    return {"tasks": [{"task_id": "1.1", "allowed_paths": list(allowed) or ["libs/pkg"]}]}


def _budget(chars: int = CEILING, byte_limit: int = 10_000_000) -> PromptBudget:
    return PromptBudget(maximum_model_input_chars=chars, max_input_bytes=byte_limit)


def _workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "workspace"
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_the_run_30698203658_input_exceeded_the_provider_ceiling() -> None:
    """The recorded failure: twice the provider's accepted input."""

    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert fixture["input_error_code"] == "input_too_large"
    assert fixture["actual_chars"] == 2_103_429
    assert fixture["provider_max_chars"] == 1_048_576
    assert fixture["actual_chars"] > fixture["provider_max_chars"]
    # The adapter's own ceilings could not have caught it.
    budgets = fixture["adapter_budgets_at_failure"]
    assert budgets["assembled_prompt_max_bytes"] > fixture["provider_max_chars"]
    # The configured ceiling leaves margin beneath the provider's hard limit.
    assert CEILING < fixture["provider_max_chars"]


def test_the_corrected_builder_stays_within_the_configured_ceiling(tmp_path: Path) -> None:
    """A workspace far larger than the ceiling still produces a bounded prompt."""

    files = {f"libs/pkg/src/module_{index:04d}.py": "x" * 4_000 for index in range(400)}
    workspace = _workspace(tmp_path, files)
    build = build_implementation_prompt(
        instructions="INSTRUCTIONS",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(),
    )
    assert len(build.prompt) <= CEILING
    assert len(build.prompt.encode("utf-8")) <= 10_000_000
    assert build.omitted, "a workspace this large must record omissions"
    assert omitted_by_reason(build.omitted)["character_budget_exceeded"] > 0


def test_mandatory_contracts_are_present_and_byte_identical(tmp_path: Path) -> None:
    contracts = _contracts(packet='{"packet":"exact \\u00e9 bytes"}')
    workspace = _workspace(tmp_path, {"libs/pkg/a.py": "A" * 500_000})
    build = build_implementation_prompt(
        instructions="INSTRUCTIONS",
        contracts=contracts,
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(),
    )
    assert build.prompt.startswith("INSTRUCTIONS")
    for title, key in (
        ("IMPLEMENTATION PACKET", "packet"),
        ("IMPLEMENTATION CONTEXT MANIFEST", "manifest"),
        ("IMPLEMENTATION TASK PLAN", "task_plan"),
        ("IMPLEMENTATION RESULT SCHEMA", "result_schema"),
        ("IMPLEMENTATION COMMAND POLICY", "command_policy"),
    ):
        assert f"===== {title} =====\n{contracts[key]}" in build.prompt


def test_mandatory_contracts_alone_exceeding_the_ceiling_fail_closed(tmp_path: Path) -> None:
    """Unfixable by truncation, so it must be loud rather than silently elided."""

    workspace = _workspace(tmp_path, {"libs/pkg/a.py": "a"})
    with pytest.raises(KernelError) as raised:
        build_implementation_prompt(
            instructions="I" * 60_000,
            contracts=_contracts(packet="P" * 60_000),
            workspace=workspace,
            task_plan=_task_plan(),
            budget=_budget(chars=50_000),
        )
    assert raised.value.code == "implementation_prompt_budget_exceeded"
    assert raised.value.details["mandatory_chars"] > 50_000


def test_source_files_are_included_only_whole(tmp_path: Path) -> None:
    """A partial file would misrepresent the source to the model."""

    files = {f"libs/pkg/f{index}.py": f"UNIQUE-{index}\n" + "y" * 20_000 for index in range(20)}
    workspace = _workspace(tmp_path, files)
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(chars=90_000),
    )
    for relative in build.included:
        assert (workspace / relative).read_text(encoding="utf-8") in build.prompt
    for relative, _ in build.omitted:
        assert f"--- {relative} ---" not in build.prompt


def test_selection_is_deterministic_across_repeated_builds(tmp_path: Path) -> None:
    files = {f"libs/pkg/m{index:03d}.py": "z" * 9_000 for index in range(60)}
    files.update({f"docs/d{index:03d}.md": "d" * 9_000 for index in range(60)})
    workspace = _workspace(tmp_path, files)
    builds = [
        build_implementation_prompt(
            instructions="I",
            contracts=_contracts(),
            workspace=workspace,
            task_plan=_task_plan(),
            budget=_budget(chars=120_000),
        )
        for _ in range(3)
    ]
    assert builds[0].included == builds[1].included == builds[2].included
    assert builds[0].omitted == builds[1].omitted == builds[2].omitted
    assert builds[0].prompt == builds[1].prompt == builds[2].prompt


def test_approved_write_roots_are_prioritized_over_unrelated_files(tmp_path: Path) -> None:
    """Issue #17's task plan must pull in the adapter package, not stray files."""

    files = {f"aaa_unrelated/{index:03d}.py": "u" * 8_000 for index in range(40)}
    files.update(
        {f"libs/property-tax-adapters/src/s{index:03d}.py": "s" * 8_000 for index in range(5)}
    )
    workspace = _workspace(tmp_path, files)
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan("libs/property-tax-adapters"),
        budget=_budget(chars=60_000),
    )
    approved = [item for item in build.included if item.startswith("libs/property-tax-adapters/")]
    # Every approved-root file is present...
    assert len(approved) == 5
    # ...and all of them precede any unrelated file, despite sorting after it
    # alphabetically. Leftover budget may still admit unrelated context.
    first_unrelated = next(
        (index for index, item in enumerate(build.included) if item.startswith("aaa_unrelated/")),
        len(build.included),
    )
    assert build.included[:5] == approved
    assert first_unrelated >= 5
    assert any(path.startswith("aaa_unrelated/") for path, _ in build.omitted)


def test_included_and_omitted_evidence_is_complete(tmp_path: Path) -> None:
    files = {f"libs/pkg/f{index:02d}.py": "f" * 15_000 for index in range(20)}
    workspace = _workspace(tmp_path, files)
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(chars=80_000),
    )
    accounted = set(build.included) | {path for path, _ in build.omitted}
    assert accounted == set(files)
    provenance = build.provenance(_budget(chars=80_000))
    assert provenance["included_source_file_count"] == len(build.included)
    assert provenance["omitted_source_file_count"] == len(build.omitted)
    assert {entry["reason"] for entry in provenance["omitted_source_paths"]} <= {
        "character_budget_exceeded",
        "excluded_by_policy",
        "binary_or_invalid_utf8",
        "per_file_limit_exceeded",
    }
    # Bounded facts only: no source content in provenance.
    assert "f" * 100 not in json.dumps(provenance)


def test_multibyte_content_is_constrained_by_both_budgets(tmp_path: Path) -> None:
    """Characters and UTF-8 bytes differ; both ceilings must hold."""

    workspace = _workspace(tmp_path, {"libs/pkg/u.py": "é" * 20_000})
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(chars=100_000),
    )
    assert len(build.prompt) <= 100_000
    assert len(build.prompt.encode("utf-8")) > len(build.prompt)

    with pytest.raises(KernelError) as raised:
        build_implementation_prompt(
            instructions="I",
            contracts=_contracts(),
            workspace=workspace,
            task_plan=_task_plan(),
            budget=PromptBudget(maximum_model_input_chars=100_000, max_input_bytes=1_000),
        )
    assert raised.value.code == "implementation_prompt_budget_exceeded"


def test_binary_and_invalid_utf8_files_are_omitted_safely(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"libs/pkg/ok.py": "ok"})
    (workspace / "libs/pkg/blob.bin").write_bytes(b"\xff\xfe\x00\x01binary")
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(),
    )
    assert "libs/pkg/ok.py" in build.included
    assert ("libs/pkg/blob.bin", "binary_or_invalid_utf8") in build.omitted


@pytest.mark.parametrize(
    "relative",
    [
        ".git/config",
        ".github/workflows/countyforge-run.yml",
        ".ai/policies/countyforge-implementation-paths.v1.json",
        ".env",
        "libs/pkg/.venv/lib/thing.py",
        "libs/pkg/__pycache__/mod.pyc",
        "libs/pkg/service_secret.py",
        "libs/pkg/api_token.py",
    ],
)
def test_excluded_paths_never_reach_the_prompt(tmp_path: Path, relative: str) -> None:
    workspace = _workspace(tmp_path, {relative: "FORBIDDEN-CONTENT", "libs/pkg/a.py": "ok"})
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan(),
        budget=_budget(),
    )
    assert relative not in build.included
    assert "FORBIDDEN-CONTENT" not in build.prompt
    assert (relative, "excluded_by_policy") in build.omitted


def test_the_documented_exclusions_match_the_enforced_ones() -> None:
    assert ".git" in EXCLUDED_PREFIXES
    assert ".github/workflows" in EXCLUDED_PREFIXES
    assert ".ai/policies" in EXCLUDED_PREFIXES
    assert ".env" in EXCLUDED_PREFIXES


def test_selection_omits_policy_paths_before_any_budget_is_spent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {".git/config": "x", "libs/pkg/a.py": "ok"})
    selected, omitted = select_source_files(workspace, task_plan=_task_plan())
    assert [path.name for path in selected] == ["a.py"]
    assert (".git/config", "excluded_by_policy") in omitted


def test_the_configured_ceiling_applies_to_every_provider() -> None:
    """The budget is profile configuration, not a provider-specific constant."""

    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    ceiling = profile["model_input"]["maximum_model_input_chars"]
    assert ceiling == CEILING
    assert ceiling < 1_048_576, "must leave margin beneath the provider hard limit"
    # Both providers resolve through the same profile and therefore the same budget.
    assert set(profile["permitted_providers"]) == {"openai", "sakana"}
