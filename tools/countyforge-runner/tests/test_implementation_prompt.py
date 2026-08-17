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


def _budget(
    chars: int = CEILING, byte_limit: int = 10_000_000, target: int | None = None
) -> PromptBudget:
    return PromptBudget(
        maximum_model_input_chars=chars,
        max_input_bytes=byte_limit,
        operational_target_model_input_chars=chars if target is None else target,
    )


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
    # The exact count is recorded as evidence, not asserted: what matters is
    # that it exceeded the provider ceiling and how that is classified.
    assert fixture["actual_chars"] > fixture["provider_max_chars"]
    assert fixture["actual_chars"] > CEILING
    # The adapter's own ceilings could not have caught it.
    budgets = fixture["adapter_budgets_at_failure"]
    assert budgets["assembled_prompt_max_bytes"] > fixture["provider_max_chars"]
    # The configured ceiling leaves margin beneath the provider's hard limit.
    assert CEILING < fixture["provider_max_chars"]
    assert fixture["classified_disposition"] == "implementation_prompt_budget_exceeded"


def test_the_corrected_builder_stays_within_the_configured_ceiling(tmp_path: Path) -> None:
    """A workspace far larger than the ceiling still produces a bounded prompt."""

    files = {"libs/pkg/a.py": "keep"}
    files.update({f"other/module_{index:04d}.py": "x" * 4_000 for index in range(400)})
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
    workspace = _workspace(tmp_path, {"libs/pkg/a.py": "A" * 5_000})
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

    files = {f"other/f{index}.py": f"UNIQUE-{index}\n" + "y" * 20_000 for index in range(20)}
    files["libs/pkg/keep.py"] = "APPROVED"
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
    files = {f"other/m{index:03d}.py": "z" * 9_000 for index in range(60)}
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
        budget=_budget(chars=90_000),
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
    files = {f"other/f{index:02d}.py": "f" * 15_000 for index in range(20)}
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


def test_dropping_an_approved_path_file_is_a_refusal_not_an_omission(tmp_path: Path) -> None:
    """The task is literally about this material.

    A model editing files it was never shown produces work that fails validation
    for reasons it could not have known, so degrading here is not acceptable.
    """

    files = {f"libs/pkg/src/big{index:02d}.py": "b" * 30_000 for index in range(10)}
    workspace = _workspace(tmp_path, files)
    with pytest.raises(KernelError) as raised:
        build_implementation_prompt(
            instructions="I",
            contracts=_contracts(),
            workspace=workspace,
            task_plan=_task_plan("libs/pkg"),
            budget=_budget(chars=60_000),
        )
    assert raised.value.code == "implementation_prompt_budget_exceeded"
    assert raised.value.details["path"].startswith("libs/pkg/")


def test_an_oversized_approved_path_file_is_also_a_refusal(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"libs/pkg/huge.py": "h" * 300_000})
    with pytest.raises(KernelError) as raised:
        build_implementation_prompt(
            instructions="I",
            contracts=_contracts(),
            workspace=workspace,
            task_plan=_task_plan("libs/pkg"),
            budget=_budget(),
        )
    assert raised.value.code == "implementation_prompt_budget_exceeded"
    assert (
        raised.value.details["per_file_limit_exceeded" if False else "path"] == "libs/pkg/huge.py"
    )


def test_the_model_is_told_what_it_was_not_shown(tmp_path: Path) -> None:
    """Omission evidence in provenance is post-hoc audit; the model needs it too."""

    files = {"libs/pkg/a.py": "keep"}
    files.update({f"other/f{index:03d}.py": "o" * 12_000 for index in range(40)})
    workspace = _workspace(tmp_path, files)
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan("libs/pkg"),
        budget=_budget(chars=80_000),
    )
    assert "===== OMITTED SOURCE CONTEXT =====" in build.prompt
    assert "Treat the snapshot as partial" in build.prompt
    elided = [path for path, reason in build.omitted if reason == "character_budget_exceeded"]
    assert elided and elided[0] in build.prompt
    # And the approved-path file survived.
    assert "libs/pkg/a.py" in build.included


def test_a_complete_snapshot_carries_no_omission_notice(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"libs/pkg/a.py": "small"})
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan("libs/pkg"),
        budget=_budget(),
    )
    assert "OMITTED SOURCE CONTEXT" not in build.prompt
    assert build.provenance(_budget())["source_context_elided"] is False


def test_astral_characters_count_under_the_worst_case_definition() -> None:
    """`len()` counts code points; a provider may count UTF-16 code units."""

    from countyforge_runner.implementation_prompt import measured_length

    assert measured_length("abc") == 3
    # One astral character is two UTF-16 code units.
    assert len("\U0001f600") == 1
    assert measured_length("\U0001f600") == 2


def test_budget_pressure_is_reported_as_evidence(tmp_path: Path) -> None:
    """A run that starts degrading must be visible, not merely auditable."""

    files = {"libs/pkg/a.py": "keep"}
    files.update({f"other/f{index:03d}.py": "o" * 12_000 for index in range(40)})
    workspace = _workspace(tmp_path, files)
    budget = _budget(chars=80_000)
    build = build_implementation_prompt(
        instructions="I",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan("libs/pkg"),
        budget=budget,
    )
    provenance = build.provenance(budget)
    assert provenance["source_context_elided"] is True
    assert 0.0 < provenance["budget_utilisation"] <= 1.0
    assert provenance["total_chars"] >= provenance["total_code_points"]


TARGET = 350_000


def test_the_operational_target_bounds_the_prompt_while_the_ceiling_stays_the_fail_safe(
    tmp_path: Path,
) -> None:
    workspace = _workspace(
        tmp_path,
        {
            "libs/pkg/core.py": "a" * 40_000,
            **{f"services/other/mod{index}.py": "b" * 40_000 for index in range(20)},
        },
    )
    build = build_implementation_prompt(
        instructions="instructions",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan("libs/pkg"),
        budget=_budget(chars=CEILING, target=TARGET),
    )
    provenance = build.provenance(_budget(chars=CEILING, target=TARGET))
    assert provenance["total_chars"] <= TARGET
    assert provenance["operational_target_exceeded"] is False
    assert provenance["hard_maximum_model_input_chars"] == CEILING
    assert provenance["operational_target_model_input_chars"] == TARGET
    # Unrelated services were dropped by the target, and the model is told so.
    assert omitted_by_reason(build.omitted)["character_budget_exceeded"] > 0
    assert "libs/pkg/core.py" in build.included


def test_approved_material_may_exceed_the_target_and_the_pressure_is_recorded(
    tmp_path: Path,
) -> None:
    """The target orders selection; it never silently drops the task's own files."""

    workspace = _workspace(
        tmp_path,
        {f"libs/pkg/part{index}.py": "a" * 60_000 for index in range(9)},
    )
    budget = _budget(chars=CEILING, target=TARGET)
    build = build_implementation_prompt(
        instructions="instructions",
        contracts=_contracts(),
        workspace=workspace,
        task_plan=_task_plan("libs/pkg"),
        budget=budget,
    )
    provenance = build.provenance(budget)
    assert len(build.included) == 9
    assert not [path for path, _ in build.omitted if path.startswith("libs/pkg/")]
    assert provenance["total_chars"] > TARGET
    assert provenance["total_chars"] <= CEILING
    assert provenance["operational_target_exceeded"] is True


def test_approved_material_beyond_the_hard_ceiling_still_fails_closed(
    tmp_path: Path,
) -> None:
    workspace = _workspace(
        tmp_path,
        {f"libs/pkg/part{index}.py": "a" * 150_000 for index in range(9)},
    )
    with pytest.raises(KernelError) as raised:
        build_implementation_prompt(
            instructions="instructions",
            contracts=_contracts(),
            workspace=workspace,
            task_plan=_task_plan("libs/pkg"),
            budget=_budget(chars=1_000_000, target=TARGET),
        )
    assert raised.value.code == "implementation_prompt_budget_exceeded"
    assert raised.value.exit_code == 2
    assert "aaaa" not in json.dumps(raised.value.details)


def test_the_target_orders_the_approved_package_ahead_of_unrelated_trees(
    tmp_path: Path,
) -> None:
    workspace = _workspace(
        tmp_path,
        {
            "libs/pkg/core.py": "approved",
            "libs/sibling/core.py": "sibling",
            "pyproject.toml": "root config",
            "services/unrelated/app.py": "unrelated",
            "tools/unrelated/cli.py": "unrelated",
            "docs/handbook.md": "docs",
        },
    )
    files, _ = select_source_files(workspace, task_plan=_task_plan("libs/pkg"))
    order = [path.relative_to(workspace).as_posix() for path in files]
    assert order.index("libs/pkg/core.py") == 0
    assert order.index("pyproject.toml") < order.index("libs/sibling/core.py")
    assert order.index("libs/sibling/core.py") < order.index("services/unrelated/app.py")
    assert order.index("libs/sibling/core.py") < order.index("tools/unrelated/cli.py")
    assert order.index("services/unrelated/app.py") < order.index("docs/handbook.md")


def _real_profile() -> dict[str, object]:
    return json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )["model_input"]


def _real_build(*allowed: str) -> tuple[dict[str, object], dict[str, object]]:
    profile = _real_profile()
    budget = PromptBudget(
        maximum_model_input_chars=int(profile["maximum_model_input_chars"]),
        max_input_bytes=10_000_000,
        operational_target_model_input_chars=int(profile["operational_target_model_input_chars"]),
    )
    build = build_implementation_prompt(
        instructions=Path(str(profile["prompt_path"])).read_text(encoding="utf-8"),
        contracts=_contracts(),
        workspace=Path.cwd(),
        task_plan=_task_plan(*allowed),
        budget=budget,
    )
    return profile, build.provenance(budget)


def test_this_repository_at_real_task_scale_stays_under_the_operational_target() -> None:
    """The real regression, at the granularity real tasks actually declare.

    Every accepted task declares file-exact `paths=`, never a directory, so a
    file-exact plan is what the implement lane builds from.  Asserting a
    whole-directory plan against the operational target measured something no
    plan asks for, and the adapters library crossing 350,000 chars in aggregate
    would have failed this for any change to any county.
    """

    profile, provenance = _real_build(
        "libs/property-tax-adapters/src/property_tax_adapters/sources/contracts.py",
        "libs/property-tax-adapters/tests/test_source_contracts.py",
    )
    assert provenance["total_chars"] <= profile["operational_target_model_input_chars"]
    assert provenance["operational_target_exceeded"] is False
    assert [
        path
        for path in provenance["included_source_paths"]
        if path.startswith("libs/property-tax-adapters/")
    ]


_ADAPTERS = "libs/property-tax-adapters"
_UNDER = f"{_ADAPTERS}/"

# Measured at 542,412 chars over 43 approved files when the bounded release
# boundary landed, up from roughly 465,000 before it.  A tripwire, not a target:
# because approved paths are never elided, the library outgrowing the ceiling
# does not degrade the prompt, it fails the run.  When this fires, decide whether
# the library grew legitimately or whether a directory-wide plan has stopped
# being a reasonable thing to hand the lane.  Raising the number without
# answering that is how the ceiling gets discovered in production instead.
_WHOLE_LIBRARY_TRIPWIRE_CHARS = 700_000
# Omission for want of room, as distinct from a deliberate policy exclusion or
# unreadable bytes.  Only these two mean the model lost material it may edit.
_BUDGET_OMISSIONS = frozenset({"character_budget_exceeded", "per_file_limit_exceeded"})


def test_the_whole_adapters_library_still_lands_far_below_the_provider_ceiling() -> None:
    """The scale guard the previous assertion was really protecting.

    A directory-wide plan is the worst case the lane could ever be handed, and
    an approved path is never elided: it fits under the hard ceiling or the
    build raises.  So the guarantee is binary before it is numeric — every
    approved file is present — and the tripwire only says how much room is left
    before that binary guarantee is the one at risk.
    """

    profile, provenance = _real_build(_ADAPTERS)
    included = [path for path in provenance["included_source_paths"] if path.startswith(_UNDER)]
    elided = [
        entry["path"]
        for entry in provenance["omitted_source_paths"]
        if entry["path"].startswith(_UNDER) and entry["reason"] in _BUDGET_OMISSIONS
    ]

    assert included, "the plan's own library was not included"
    assert elided == [], (
        "an approved file was dropped for budget; a model cannot edit what it was not shown"
    )
    assert (
        provenance["total_chars"]
        < _WHOLE_LIBRARY_TRIPWIRE_CHARS
        < int(profile["maximum_model_input_chars"])
    )
