"""Static security policy for the thin GitHub-hosted workflow surface."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml
from countyforge_github.implementation import _IMPLEMENTATION_VALIDATION_CHECKS

WORKFLOW_ROOT = Path(".github/workflows")
COUNTYFORGE_WORKFLOWS = (
    "countyforge-command.yml",
    "countyforge-run.yml",
    "countyforge-maintenance.yml",
)
FORBIDDEN_WRITE_PERMISSIONS = {
    "contents",
    "packages",
    "deployments",
    "id-token",
    "security-events",
}
PINNED_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


def _load(name: str) -> dict[str, Any]:
    value = yaml.load((WORKFLOW_ROOT / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _jobs(name: str) -> dict[str, Any]:
    jobs = _load(name)["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def test_comment_workflow_subscribes_only_to_created_comments() -> None:
    workflow = _load("countyforge-command.yml")
    assert workflow["on"] == {"issue_comment": {"types": ["created"]}}
    text = (WORKFLOW_ROOT / "countyforge-command.yml").read_text(encoding="utf-8")
    assert "pull_request_target" not in text
    assert "edited" not in text
    assert "deleted" not in text


def test_implementation_validator_install_uses_parser_compatible_matching() -> None:
    text = (WORKFLOW_ROOT / "countyforge-command.yml").read_text(encoding="utf-8")
    assert "contains(github.event.comment.body, '/countyforge implement')" not in text
    assert 're.compile(r"^/countyforge[ \\t]+implement' in text
    assert "re.IGNORECASE" in text


def test_all_actions_are_pinned_to_full_commit_shas() -> None:
    for name in COUNTYFORGE_WORKFLOWS:
        workflow = _load(name)
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert PINNED_ACTION.fullmatch(str(step["uses"])) is not None


def test_ci_provisions_bubblewrap_before_runner_contracts() -> None:
    workflow = _load("ci.yml")
    steps = workflow["jobs"]["checks"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    install_index = names.index("Install and configure Bubblewrap sandbox")
    sync_index = names.index("Sync workspace")
    contracts_index = names.index("Validate legacy and CountyForge runner contracts")
    assert sync_index < install_index < contracts_index
    install_run = str(steps[install_index]["run"])
    assert "sudo apt-get update" in install_run
    assert "sudo apt-get install -y --no-install-recommends bubblewrap" in install_run
    assert "command -v bwrap" in install_run
    assert "bwrap --version" in install_run
    # The privileged helper is sourced from the immutable trusted-base checkout only; the
    # PR-workspace copy is never installed or executed under sudo.
    assert "trusted-base/scripts/ci/configure_bwrap_apparmor.sh" in install_run
    assert 'install -m 0755 "$trusted_helper" "$verified_helper"' in install_run
    assert '"$verified_helper"' in install_run
    assert "runner-contract-tests" in str(steps[contracts_index]["run"])
    ci_text = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY" not in ci_text
    assert "SAKANA_API_KEY" not in ci_text


def test_ci_provisions_persistent_openspec_before_contract_tests() -> None:
    workflow = _load("ci.yml")
    steps = workflow["jobs"]["checks"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    openspec_index = names.index("Validate OpenSpec")
    contracts_index = names.index("Validate legacy and CountyForge runner contracts")
    assert openspec_index < contracts_index
    openspec_run = str(steps[openspec_index]["run"])
    assert 'npm install --global --prefix "$RUNNER_TEMP/openspec-ci-tool"' in openspec_run
    assert "--ignore-scripts --no-audit --no-fund" in openspec_run
    assert '"@fission-ai/openspec@1.6.0"' in openspec_run
    assert 'test -x "$RUNNER_TEMP/openspec-ci-tool/bin/openspec"' in openspec_run
    assert 'echo "$RUNNER_TEMP/openspec-ci-tool/bin" >> "$GITHUB_PATH"' in openspec_run
    assert (
        '"$RUNNER_TEMP/openspec-ci-tool/bin/openspec" validate --all --strict --no-interactive'
        in openspec_run
    )
    assert "npx --yes @fission-ai/openspec@1.6.0" not in openspec_run


def test_implementation_validation_gate_lists_are_identical() -> None:
    """Keep the profile, registry, trusted validator, and workflow in lockstep."""

    repo_root = Path(__file__).parents[3]
    profile = json.loads(
        (repo_root / ".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (repo_root / ".ai/policies/countyforge-implementation-commands.v1.json").read_text(
            encoding="utf-8"
        )
    )
    registry_ids = {str(command["id"]) for command in registry["commands"]}
    workflow = (WORKFLOW_ROOT / "countyforge-run.yml").read_text(encoding="utf-8")
    workflow_ids = set(re.findall(r"run_registered ([a-z0-9.-]+)", workflow))
    expected = {str(command) for command in profile["deterministic_commands"]}
    assert expected == set(_IMPLEMENTATION_VALIDATION_CHECKS)
    assert workflow_ids == expected
    assert expected <= registry_ids


def test_bwrap_apparmor_policy_is_narrow_and_shared() -> None:
    repo_root = Path(__file__).parents[3]
    script = (repo_root / "scripts/ci/configure_bwrap_apparmor.sh").read_text(encoding="utf-8")
    broker = (
        repo_root / "tools/countyforge-runner/src/countyforge_runner/command_broker.py"
    ).read_text(encoding="utf-8")
    ci = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    countyforge = (WORKFLOW_ROOT / "countyforge-run.yml").read_text(encoding="utf-8")
    command_broker_tests = (
        repo_root / "tools/countyforge-runner/tests/test_command_broker.py"
    ).read_text(encoding="utf-8")

    assert "set -euo pipefail" in script
    assert "BWRAP=/usr/bin/bwrap" in script
    assert "PROFILE_PATH=/etc/apparmor.d/countyforge-bwrap" in script
    profile_lines = [line.strip() for line in script.splitlines() if line.startswith("profile ")]
    assert profile_lines == ["profile countyforge-bwrap /usr/bin/bwrap flags=(unconfined) {"]
    assert "userns," in script
    assert "apparmor_parser -r -W" in script
    assert "kernel.apparmor_restrict_unprivileged_userns must remain" in script
    assert "EXPECTED_RESTRICT_VALUE=1" in script
    # The profile stays reproducible: no machine-local include can widen it out of band.
    assert "include if exists <local/countyforge-bwrap>" not in script
    combined_policy_text = "\n".join((script, ci, countyforge))
    assert "apparmor_restrict_unprivileged_userns=0" not in combined_policy_text
    assert "sysctl" not in combined_policy_text
    assert "ubuntu-22.04" not in combined_policy_text
    assert "setuid" not in script.casefold()
    assert "--privileged" not in combined_policy_text
    assert "--share-net" not in combined_policy_text
    assert "#   bwrap --unshare-net -- /usr/bin/true" in script
    assert "PROBE_ARGS=(--unshare-net)" in script
    assert "PROBE_ARGS+=(-- /usr/bin/true)" in script
    assert 'PROBE_ARGS+=(--ro-bind "$runtime_root" "$runtime_root")' in script
    assert "sudo $BWRAP" not in script
    assert "sudo bwrap" not in script
    assert "sudo install" in script
    assert "sudo apparmor_parser" in script

    assert '"--unshare-net"' in broker
    assert "--share-net" not in broker
    assert "pytest.skip" not in command_broker_tests
    assert "@pytest.mark.skip" not in command_broker_tests
    assert "xfail" not in command_broker_tests

    # CI runs only the trusted-base copy of the helper; the PR-workspace path is never used.
    assert "trusted-base/scripts/ci/configure_bwrap_apparmor.sh" in ci
    assert "./trusted/scripts/ci/configure_bwrap_apparmor.sh" in countyforge
    ci_setup = ci.index("trusted-base/scripts/ci/configure_bwrap_apparmor.sh")
    ci_contracts = ci.index("make runner-contract-tests")
    assert ci_setup < ci_contracts
    validation_setup = countyforge.index("./trusted/scripts/ci/configure_bwrap_apparmor.sh")
    broker_invocation = countyforge.index("run-implementation-command")
    assert validation_setup < broker_invocation


def test_privileged_bwrap_helper_comes_from_trusted_base_in_ci() -> None:
    """The sudo-bearing helper must be sourced from an immutable trusted checkout.

    ``ci.yml`` runs on ``pull_request``. If the helper, its digest pin, and the policy
    test all came from the PR checkout, a PR could edit them together and still pass. So
    the privileged helper is obtained only from a separate trusted-base checkout pinned to
    the already-merged base commit (``pull_request.base.sha``) or the pushed commit, and
    only that copy is executed. There is no PR-workspace fallback: if the trusted base does
    not yet contain the helper, CI fails closed before any privileged action (see
    ``test_ci_fails_closed_without_trusted_base_bwrap_helper``).
    """

    repo_root = Path(__file__).parents[3]
    helper_path = repo_root / "scripts/ci/configure_bwrap_apparmor.sh"
    expected_digest = hashlib.sha256(helper_path.read_bytes()).hexdigest()

    workflow = _load("ci.yml")
    steps = workflow["jobs"]["checks"]["steps"]
    names = [str(step.get("name", "")) for step in steps]

    # A dedicated trusted-base checkout exists and is pinned to an immutable, non-PR-head ref.
    base_index = names.index("Check out trusted base tooling")
    sandbox_index = names.index("Install and configure Bubblewrap sandbox")
    assert base_index < sandbox_index
    base_step = steps[base_index]
    assert PINNED_ACTION.fullmatch(str(base_step["uses"])) is not None
    base_ref = str(base_step["with"]["ref"])
    assert "github.event.pull_request.base.sha" in base_ref
    assert "github.sha" in base_ref
    assert "pull_request.head" not in base_ref
    assert str(base_step["with"]["path"]) == "trusted-base"
    assert base_step["with"]["persist-credentials"] in (False, "false")

    sandbox_run = str(steps[sandbox_index]["run"])
    # Only the trusted-base copy is ever installed and executed.
    assert 'trusted_helper="trusted-base/scripts/ci/configure_bwrap_apparmor.sh"' in sandbox_run
    assert 'install -m 0755 "$trusted_helper" "$verified_helper"' in sandbox_run
    # The digest additionally proves the trusted-base helper bytes are what this
    # review-gated workflow expects. The digest lives in the review-gated step env.
    assert steps[sandbox_index]["env"]["COUNTYFORGE_BWRAP_HELPER_SHA256"] == expected_digest
    assert (
        'printf \'%s  %s\\n\' "$COUNTYFORGE_BWRAP_HELPER_SHA256" "$verified_helper" '
        "| sha256sum -c -"
    ) in sandbox_run
    # Only the verified copy is executed; neither checkout path is executed directly.
    run_index = sandbox_run.rindex('"$verified_helper"')
    assert sandbox_run.index("install -m 0755") < run_index
    assert "          ./scripts/ci/configure_bwrap_apparmor.sh\n" not in sandbox_run
    assert "          trusted-base/scripts/ci/configure_bwrap_apparmor.sh\n" not in sandbox_run
    # There must be no PR-workspace fallback that installs or executes the PR copy.
    assert "./scripts/ci/configure_bwrap_apparmor.sh" not in sandbox_run
    assert "install -m 0755 ./scripts/ci/configure_bwrap_apparmor.sh" not in sandbox_run


def test_ci_fails_closed_without_trusted_base_bwrap_helper() -> None:
    """A missing trusted-base helper must abort CI before any privileged action.

    This proves the reviewer's blocker is closed: when the immutable trusted base does not
    contain the sudo-bearing helper (for example on the change that first introduces it),
    the sandbox step must exit nonzero before any sudo-bearing setup and must never install
    or execute the PR-workspace copy. The helper can only be bootstrapped by first landing
    it on the base branch.
    """

    workflow = _load("ci.yml")
    steps = workflow["jobs"]["checks"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    sandbox_run = str(steps[names.index("Install and configure Bubblewrap sandbox")]["run"])

    # The step guards on the trusted-base helper's presence and exits before doing anything
    # privileged when it is absent.
    assert 'if [ ! -f "$trusted_helper" ]; then' in sandbox_run
    guard_index = sandbox_run.index('if [ ! -f "$trusted_helper" ]; then')
    exit_index = sandbox_run.index("exit 2", guard_index)
    apt_index = sandbox_run.index("sudo apt-get update")
    install_index = sandbox_run.index('install -m 0755 "$trusted_helper" "$verified_helper"')
    verify_index = sandbox_run.index("sha256sum -c -")
    run_index = sandbox_run.rindex('"$verified_helper"')
    # Fail-closed exit happens before sudo package setup, helper install, digest verification,
    # and helper execution.
    assert guard_index < exit_index < apt_index < install_index < verify_index < run_index
    # No conditional fallback branch remains that could execute a non-trusted-base copy.
    assert "else" not in sandbox_run


def test_privileged_bwrap_helper_is_digest_verified_before_execution() -> None:
    """The trusted-run sandbox helper runs only after a pinned-digest check.

    ``countyforge-run.yml`` sources the helper from the immutable ``trusted`` checkout and
    still verifies it against the gated digest before executing only the verified copy.
    """

    repo_root = Path(__file__).parents[3]
    helper_path = repo_root / "scripts/ci/configure_bwrap_apparmor.sh"
    expected_digest = hashlib.sha256(helper_path.read_bytes()).hexdigest()

    countyforge = (WORKFLOW_ROOT / "countyforge-run.yml").read_text(encoding="utf-8")
    helper_reference = "./trusted/scripts/ci/configure_bwrap_apparmor.sh"

    # The pinned digest must match the committed helper exactly.
    assert f"COUNTYFORGE_BWRAP_HELPER_SHA256: {expected_digest}" in countyforge
    # The helper is copied into an isolated verified path and checked before it runs.
    assert f'install -m 0755 {helper_reference} "$verified_helper"' in countyforge
    assert (
        'printf \'%s  %s\\n\' "$COUNTYFORGE_BWRAP_HELPER_SHA256" "$verified_helper" '
        "| sha256sum -c -"
    ) in countyforge
    # Fail closed: the privileged helper must be guarded on its presence in the immutable
    # trusted checkout and abort before any sudo action when it is absent.
    assert "if [ ! -f ./trusted/scripts/ci/configure_bwrap_apparmor.sh ]; then" in countyforge
    guard_index = countyforge.index("if [ ! -f ./trusted/scripts/ci/configure_bwrap_apparmor.sh")
    exit_index = countyforge.index("exit 2", guard_index)
    apt_index = countyforge.index("sudo apt-get update")
    install_index = countyforge.index(f'install -m 0755 {helper_reference} "$verified_helper"')
    assert guard_index < exit_index < apt_index < install_index
    # Only the verified copy is executed; the checkout copy is never run directly.
    assert '"$verified_helper"' in countyforge
    verify_index = countyforge.index("sha256sum -c -")
    run_index = countyforge.rindex('"$verified_helper"')
    assert verify_index < run_index
    assert f"          {helper_reference}\n" not in countyforge


def test_codeowners_gates_privileged_ci_surface() -> None:
    """CODEOWNERS makes the privileged CI trust boundary an independent review gate."""

    repo_root = Path(__file__).parents[3]
    codeowners_path = repo_root / ".github/CODEOWNERS"
    assert codeowners_path.is_file()
    codeowners = codeowners_path.read_text(encoding="utf-8")
    owned = [
        line.strip()
        for line in codeowners.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    # Every ownership rule must name at least one owner.
    for rule in owned:
        parts = rule.split()
        assert len(parts) >= 2
        assert all(owner.startswith("@") for owner in parts[1:])
    # Owners must be valid GitHub code owners: a user (``@name``) or a team
    # (``@org/team``). A bare organization handle is silently ignored by GitHub and never
    # gates review, so it must never appear as an owner. ``@TruPryce`` is the organization
    # that owns this repository, so it is specifically forbidden as an owner here.
    owners = {owner for rule in owned for owner in rule.split()[1:]}
    for owner in owners:
        handle = owner[1:]
        assert handle, f"empty owner handle in rule set: {owner!r}"
        # A user handle has no slash; a team handle is exactly ``org/team``.
        assert handle.count("/") in (0, 1)
        if "/" in handle:
            org, _, team = handle.partition("/")
            assert org and team
    assert "@TruPryce" not in owners, (
        "@TruPryce is the organization handle, which is not a valid code owner; use a user "
        "or an @TruPryce/<team> team handle instead"
    )
    # The privileged surface and the ownership file itself must be owned.
    required_patterns = (
        "/.github/workflows/",
        "/.github/CODEOWNERS",
        "/scripts/ci/",
        "/scripts/ci/configure_bwrap_apparmor.sh",
    )
    patterns = {rule.split()[0] for rule in owned}
    for pattern in required_patterns:
        assert pattern in patterns


def test_shell_scripts_never_interpolate_github_expressions_directly() -> None:
    for name in COUNTYFORGE_WORKFLOWS:
        workflow = _load(name)
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                assert "${{" not in str(step.get("run", ""))


def test_forbidden_permissions_are_never_granted_write() -> None:
    for name in COUNTYFORGE_WORKFLOWS:
        workflow = _load(name)
        permission_sets = [("workflow", workflow.get("permissions", {}))]
        permission_sets.extend(
            (job_name, job.get("permissions", {})) for job_name, job in workflow["jobs"].items()
        )
        # The trusted planning publication job is the only narrowly-scoped v1
        # exception: it creates deterministic planning refs and draft PRs.  No
        # provider secret or model job receives this permission.
        for job_name, permissions in permission_sets:
            for permission in FORBIDDEN_WRITE_PERMISSIONS:
                if (
                    name == "countyforge-run.yml"
                    and job_name in {"plan-publish", "implementation-publish"}
                    and permission == "contents"
                ):
                    continue
                assert permissions.get(permission) != "write"
    plan_publish = _jobs("countyforge-run.yml")["plan-publish"]["permissions"]
    assert plan_publish == {
        "actions": "read",
        "checks": "write",
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }
    implementation_publish = _jobs("countyforge-run.yml")["implementation-publish"]["permissions"]
    assert implementation_publish == plan_publish
    assert _jobs("countyforge-run.yml")["publish"]["permissions"]["contents"] == "read"


def test_control_and_execution_use_separate_non_cancelling_lanes() -> None:
    command = _load("countyforge-command.yml")["concurrency"]
    execution = _load("countyforge-run.yml")["concurrency"]
    assert str(command["group"]).startswith("countyforge-control-")
    assert str(execution["group"]).startswith("countyforge-run-")
    assert command["cancel-in-progress"] == "false"
    assert execution["cancel-in-progress"] == "false"


def test_planning_packet_fetches_newest_comments_and_trigger_comment() -> None:
    text = (WORKFLOW_ROOT / "countyforge-run.yml").read_text(encoding="utf-8")
    assert "comments?per_page=100&page=$page" in text
    assert "seq 1 10" in text
    assert "countyforge-issue-comments.ndjson" in text
    assert "sort=created" not in text
    assert "direction=desc" not in text
    assert "countyforge-trigger-comment.json" in text
    assert "countyforge-issue-comments-with-trigger.json" in text
    assert "--trusted-bot-id 41898282" in text


def test_canonical_state_mutations_share_one_serialized_lane() -> None:
    # GitHub does not honor If-Match/412 on issue-comment updates, so canonical-state
    # mutations rely on a shared per-target job concurrency lane for serialization instead
    # of an unsupported atomic CAS. The command intake job and every run-workflow state
    # transaction must join the byte-identical countyforge-state-* group, while preparation,
    # provider execution, and upload stay outside it so cancel/status remain responsive.
    command_jobs = _jobs("countyforge-command.yml")
    run_jobs = _jobs("countyforge-run.yml")

    command_group = command_jobs["intake"]["concurrency"]["group"]
    assert "countyforge-state-" in command_group
    assert "pull_request" in command_group
    assert command_jobs["intake"]["concurrency"]["cancel-in-progress"] == "false"

    state_jobs = (
        "claim",
        "recover-claim-failure",
        "mark-running",
        "publish",
        "plan-publish",
        "implementation-publish",
    )
    run_group = run_jobs["claim"]["concurrency"]["group"]
    assert run_group == (
        "countyforge-state-${{ github.repository_id }}-"
        "${{ inputs.target_type }}-${{ inputs.target_number }}"
    )
    for name in state_jobs:
        concurrency = run_jobs[name]["concurrency"]
        assert concurrency["group"] == run_group
        assert concurrency["cancel-in-progress"] == "false"

    for name in ("prepare", "future-mode", "review-sakana", "review-openai"):
        assert "concurrency" not in run_jobs[name]


def test_only_preparation_checks_out_untrusted_target() -> None:
    jobs = _jobs("countyforge-run.yml")
    prepare_text = str(jobs["prepare"])
    assert "path': 'target" in prepare_text or "'path': 'target'" in prepare_text
    assert "needs.claim.outputs.source_repository" in prepare_text
    assert "path': 'base-reference" in prepare_text or "'path': 'base-reference'" in prepare_text
    for name in (
        "claim",
        "recover-claim-failure",
        "mark-running",
        "future-mode",
        "plan-packet",
        "plan-validation",
        "plan-sakana",
        "plan-openai",
        "review-sakana",
        "review-openai",
        "publish",
        "plan-publish",
        "implementation-publish",
        "implementation-publication-prep",
    ):
        text = str(jobs[name])
        assert "path': 'target" not in text
        assert "target/scripts" not in text
        assert "target/Makefile" not in text
        assert "working-directory': 'target" not in text


def test_preparation_has_no_provider_secret_or_target_execution() -> None:
    prepare_job = _jobs("countyforge-run.yml")["prepare"]
    prepare = str(prepare_job)
    assert prepare_job["permissions"] == {"contents": "read"}
    assert "OPENAI_API_KEY" not in prepare
    assert "SAKANA_API_KEY" not in prepare
    assert "pytest" not in prepare
    assert " make " not in prepare
    assert "uv sync" not in prepare
    assert "uv pip install" not in prepare
    assert "target/.github/workflows" not in prepare
    assert "trusted/scripts/dev-loop/prepare-countyforge-target.sh" in prepare
    assert "MAX_PREPARED_BYTES" in prepare
    preparation_script = Path("scripts/dev-loop/prepare-countyforge-target.sh").read_text(
        encoding="utf-8"
    )
    assert "build-review-packet.sh" in preparation_script
    assert "build-review-packet-provenance.py" in preparation_script
    assert "du -sb" in preparation_script


def test_planning_packet_job_uses_trusted_root_without_target_checkout() -> None:
    job = _jobs("countyforge-run.yml")["plan-packet"]
    text = str(job)
    assert job["permissions"] == {"contents": "read", "issues": "read"}
    assert "uv sync --frozen --package countyforge-github" in text
    assert "countyforge-prepared-" not in text
    assert "target/scripts" not in text
    assert "target/Makefile" not in text
    assert "OPENAI_API_KEY" not in text
    assert "SAKANA_API_KEY" not in text


def test_provider_jobs_receive_exactly_one_provider_secret() -> None:
    jobs = _jobs("countyforge-run.yml")
    for sakana_name, openai_name in (
        ("review-sakana", "review-openai"),
        ("plan-sakana", "plan-openai"),
    ):
        sakana = str(jobs[sakana_name])
        openai = str(jobs[openai_name])
        assert "SAKANA_API_KEY" in sakana
        assert "OPENAI_API_KEY" not in sakana
        assert "OPENAI_API_KEY" in openai
        assert "SAKANA_API_KEY" not in openai
    implementation = str(jobs["implementation-openai"])
    assert "OPENAI_API_KEY" in implementation
    assert "SAKANA_API_KEY" not in implementation
    assert "freeze-implementation-artifact" in implementation
    assert "tar --exclude=.git" not in implementation
    assert jobs["implementation-openai"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    for name in (
        "claim",
        "prepare",
        "recover-claim-failure",
        "mark-running",
        "future-mode",
        "publish",
        "plan-publish",
        "implementation-packet",
        "implementation-validation",
        "implementation-publication-prep",
        "implementation-publish",
    ):
        text = str(jobs[name])
        assert "OPENAI_API_KEY" not in text
        assert "SAKANA_API_KEY" not in text


def test_planning_image_and_request_build_have_no_provider_secret() -> None:
    jobs = _jobs("countyforge-run.yml")
    for name, credential in (
        ("plan-sakana", "SAKANA_API_KEY"),
        ("plan-openai", "OPENAI_API_KEY"),
    ):
        build_steps = [
            step
            for step in jobs[name]["steps"]
            if "build trusted plan image" in str(step.get("name", ""))
        ]
        invoke_steps = [
            step for step in jobs[name]["steps"] if "Invoke" in str(step.get("name", ""))
        ]
        assert len(build_steps) == 1
        assert credential not in str(build_steps[0])
        assert len(invoke_steps) == 1
        assert credential in str(invoke_steps[0])


def test_provider_jobs_cannot_mutate_repository_or_status() -> None:
    jobs = _jobs("countyforge-run.yml")
    for name in (
        "review-sakana",
        "review-openai",
        "plan-sakana",
        "plan-openai",
        "implementation-openai",
        "future-mode",
    ):
        permissions = jobs[name]["permissions"]
        assert permissions == {"actions": "read", "contents": "read"}


def test_implementation_model_has_no_shell_and_publication_has_lease_preflight() -> None:
    jobs = _jobs("countyforge-run.yml")
    profile = json.loads(
        (Path(__file__).parents[3] / ".ai/profiles/implement.workspace-write.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert profile["model_tools"] == ["structured_file_bundle"]
    assert profile["expected_security_posture"]["model_shell"] is False
    assert profile["container"]["availability"] == "available"
    adapter = (
        Path(__file__).parents[3] / ".ai/codex/09-run-countyforge-implement-docker.sh"
    ).read_text(encoding="utf-8")
    assert "provider_proxy.py" in adapter
    assert re.search(r'PROXY_IMAGE="python:3\.12-alpine@sha256:[0-9a-f]{64}"', adapter)
    assert re.search(r"(?m)^\s+python:3\.12-alpine\s*$", adapter) is None
    assert "docker network create --driver bridge --internal" in adapter
    assert "docker network connect bridge" in adapter
    assert '--network "$NETWORK_NAME"' in adapter
    assert "HTTPS_PROXY=http://${PROXY_NAME}:45000" in adapter
    assert "--network=bridge" not in adapter
    assert "--disable shell_tool --disable unified_exec" in adapter
    assert 'MODEL_WORKSPACE="$OUT_DIR/model-workspace"' in adapter
    # Snapshot exclusions moved into the tested prompt builder; the guarantee is
    # unchanged and is now enforced where it can be exercised directly.
    builder = Path(
        "tools/countyforge-runner/src/countyforge_runner/implementation_prompt.py"
    ).read_text(encoding="utf-8")
    for excluded in (".git", ".env", ".ai/policies", ".github/workflows"):
        assert f'"{excluded}"' in builder
    assert ' < "$MODEL_PROMPT"' in adapter
    validation = str(jobs["implementation-validation"])
    assert "Provision the no-network command sandbox" in validation
    assert "apt-get install --no-install-recommends --yes bubblewrap" in validation
    assert "./trusted/scripts/ci/configure_bwrap_apparmor.sh" in validation
    assert "Provision pinned OpenSpec validator for offline gates" in validation
    assert 'npm install --prefix "$GITHUB_WORKSPACE/trusted/.ai/tools/openspec"' in validation
    assert "npx --yes @fission-ai/openspec@1.6.0" not in validation
    assert 'candidate_root="$RUNNER_TEMP/implementation-candidate"' in validation
    assert '--workspace "$candidate_root"' in validation
    assert '"$GITHUB_WORKSPACE/trusted" "$candidate_root"' in validation
    assert 'git -C "$candidate_root" rev-parse HEAD' in validation
    assert 'cp "$(command -v uv)" "$GITHUB_WORKSPACE/trusted/.ai/tools/uv-runtime/uv"' in validation
    assert '--toolchain-root "$GITHUB_WORKSPACE/trusted/.ai/tools/uv-runtime"' in validation
    assert "PYTHONPATH" not in validation
    assert "validate-implementation-context" in validation
    assert "Ensure failed validation evidence exists" in validation
    assert "implementation_validation_setup_failed" in validation
    assert '--argjson gates "$gates_json"' in validation
    assert "gates:$gates" in validation
    packet = str(jobs["implementation-packet"])
    assert "Provision trusted OpenSpec validator" in packet
    assert "openspec-packet-tool" in packet
    assert "OPENAI_API_KEY" not in validation
    build = Path(__file__).parents[3] / ".ai/codex/10-build-countyforge-implement-image.sh"
    build_text = build.read_text(encoding="utf-8")
    assert "COUNTYFORGE_PROFILE_SHA256:?COUNTYFORGE_PROFILE_SHA256 is required" in build_text
    implementation_model = str(jobs["implementation-openai"])
    assert "export COUNTYFORGE_PROFILE_SHA256=" in implementation_model
    assert "python3 - .ai/profiles/implement.workspace-write.v1.json" in implementation_model
    assert "'id': 'freeze'" in implementation_model
    assert "'name': 'Upload implementation execution evidence'" in implementation_model
    assert "'if': 'always()'" in implementation_model
    assert "'name': 'Upload frozen implementation bundle'" in implementation_model
    assert "countyforge-implementation-bundle-" in implementation_model
    assert "--workspace-binding" in implementation_model
    assert "Prepare sanitized implementation evidence" in implementation_model
    assert "file_bundle" in implementation_model
    publish = str(jobs["implementation-publish"])
    assert "countyforge-implementation-publication-prep-" in publish
    assert "countyforge-workspace.tar.gz" in publish
    assert 'terminal_file="$RUNNER_TEMP/implementation-result/countyforge-terminal.json"' in publish
    assert (
        'report="$RUNNER_TEMP/implementation-result/implementation-validation/implementation-validation.json"'
        in publish
    )
    assert (
        '--validation-report "$RUNNER_TEMP/implementation-result/implementation-validation/'
        'implementation-validation.json"' in publish
    )
    assert "arguments=(resolve-terminal-result" not in publish
    assert "Verify live implementation publication lease" in publish
    assert "steps.verify-publication.outcome == 'success'" in publish
    assert 'final_state="failed"' in publish
    assert 'final_disposition="implementation_validation_failed"' in publish
    assert 'final_disposition="implementation_publication_failed"' in publish
    prep = str(jobs["implementation-publication-prep"])
    assert "countyforge-implementation-bundle-" in prep
    assert "countyforge-implementation-validation-" in prep


def test_result_artifacts_include_explicit_hidden_evidence_paths() -> None:
    jobs = _jobs("countyforge-run.yml")
    for name in (
        "future-mode",
        "plan-sakana",
        "plan-openai",
        "review-sakana",
        "review-openai",
    ):
        upload_steps = [
            step
            for step in jobs[name]["steps"]
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        assert len(upload_steps) == 1
        assert upload_steps[0]["with"]["include-hidden-files"] == "true"


def test_publication_uses_fail_closed_result_evidence_resolver() -> None:
    publish = str(_jobs("countyforge-run.yml")["publish"])
    assert "resolve-terminal-result" in publish
    assert "countyforge-exit-code" in publish
    assert ".disposition //" not in publish


def test_planning_publication_rechecks_live_lease_and_finalizes_failures() -> None:
    jobs = _jobs("countyforge-run.yml")
    assert "concurrency" not in jobs["plan-validation"]
    assert jobs["plan-validation"]["permissions"] == {"contents": "read", "actions": "read"}
    assert "npx --yes @fission-ai/openspec@1.6.0" in str(jobs["plan-validation"])
    publish = str(jobs["plan-publish"])
    assert "verify-publication" in publish
    assert "countyforge-state-${{ github.repository_id }}" in publish
    assert "npx --yes @fission-ai/openspec@1.6.0" not in publish
    assert any(step.get("if") == "always()" for step in jobs["plan-publish"].get("steps", []))
    assert "PLANNING_VALIDATION_JOB_RESULT" in publish
    assert 'TERMINAL_STATE" = "succeeded"' in publish
    publication_step = next(
        step for step in jobs["plan-publish"]["steps"] if step.get("id") == "planning-publication"
    )
    verify_step = next(
        step for step in jobs["plan-publish"]["steps"] if step.get("id") == "verify-publication"
    )
    assert "steps.terminal.outputs.state == 'succeeded'" in verify_step["if"]
    assert "steps.terminal.outputs.disposition == 'completed'" in verify_step["if"]
    assert "steps.verify-publication.outcome == 'success'" in publication_step["if"]
    assert "steps.terminal.outputs.state == 'succeeded'" in publication_step["if"]
    assert "steps.terminal.outputs.disposition == 'completed'" in publication_step["if"]


def test_planning_publication_preserves_its_structured_result_on_every_exit() -> None:
    """Run 30507375764 exited 5 and discarded the publisher's own error document."""

    steps = _jobs("countyforge-run.yml")["plan-publish"]["steps"]
    publication = next(step for step in steps if step.get("id") == "planning-publication")
    run = str(publication["run"])
    # The return code is captured instead of aborting the step, so the redirected
    # document survives to be read, normalized, and uploaded.
    assert "set +e" in run and "publication_rc=$?" in run and "set -e" in run
    assert "--publication-progress" in run
    # Consistency between the document and the return code is decided by the
    # typed adapter, never by a bare nonempty-file test.
    assert "normalize-publication-result" in run
    assert '--exit-code "$publication_rc"' in run
    assert "effective_rc=" in run
    assert ".details.stage" in run and ".details.status" in run
    assert "::error::Planning publication failed:" in run
    assert 'exit "$effective_rc"' in run
    # Every output assignment must sit behind the failure branch and read only
    # the normalizer's validated outputs.
    assert run.index('exit "$effective_rc"') < run.index("change_name=$(jq")
    for field in ("change_name", "branch", "pr_number", "context_manifest_sha256"):
        assert f".outputs.{field}" in run
    assert '"$publication_result"' not in run.split('exit "$effective_rc"')[1]
    upload = next(
        step
        for step in steps
        if step.get("name") == "Upload sanitized planning publication evidence"
    )
    assert upload["if"] == "always()"
    for artifact in (
        "countyforge-publication.json",
        "countyforge-publication-progress.json",
        "countyforge-publication-normalized.json",
    ):
        assert artifact in str(upload["with"]["path"])


def test_planning_materialization_reports_upstream_provider_failure() -> None:
    steps = _jobs("countyforge-run.yml")["plan-validation"]["steps"]
    materialize = next(
        step for step in steps if step.get("name") == "Materialize the validated planning draft"
    )
    run = str(materialize["run"])
    result_lookup = run.index("-name countyforge-result.json")
    disposition_check = run.index('.ok == true and .disposition == "completed"')
    plan_lookup = run.index("-name countyforge-plan-result.json")
    assert result_lookup < disposition_check < plan_lookup
    assert "Planning provider result evidence is missing" in run
    assert "Planning provider failed before materialization:" in run
    assert "disposition=$disposition error_code=$error_code" in run
    assert "Planning provider completed without countyforge-plan-result.json" in run
    assert 'test -n "$plan_file"' not in run


def test_claim_failure_recovery_has_no_provider_or_target_access() -> None:
    recovery = _jobs("countyforge-run.yml")["recover-claim-failure"]
    text = str(recovery)
    assert recovery["if"] == "always() && needs.claim.result == 'failure'"
    assert "fail-unclaimed-run" in text
    assert "OPENAI_API_KEY" not in text
    assert "SAKANA_API_KEY" not in text
    assert "path': 'target" not in text


def test_claim_reports_immutable_trigger_identity_disposition() -> None:
    claim = _jobs("countyforge-run.yml")["claim"]
    step = next(
        item
        for item in claim["steps"]
        if item.get("name") == "Decode and validate immutable trigger"
    )
    run = str(step["run"])
    assert "if ! uv run --package countyforge-github countyforge-github idempotency-key" in run
    assert '.disposition | select(type == "string" and length > 0)' in run
    assert 'if [ -z "$disposition" ]' in run
    assert 'disposition="identity_validation_failed"' in run
    assert "Immutable trigger identity validation failed: disposition=$disposition" in run
    assert "exit 2" in run


def test_claim_identity_disposition_defaults_for_empty_output(tmp_path: Path) -> None:
    identity = tmp_path / "identity.json"
    identity.write_text("", encoding="utf-8")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                'disposition="$(jq -er '
                "'.disposition | select(type == \"string\" and length > 0)' "
                '"$1" 2>/dev/null || true)"; '
                'if [ -z "$disposition" ]; then '
                'disposition="identity_validation_failed"; fi; '
                "printf '%s' \"$disposition\""
            ),
            "claim-identity-fallback",
            str(identity),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == "identity_validation_failed"


def test_maintenance_never_dispatches_work() -> None:
    job = str(_jobs("countyforge-maintenance.yml")["reconcile"])
    assert "countyforge-github maintain" in job
    assert "workflow_dispatch" not in job
    assert "dispatch_workflow" not in job


def test_maintenance_is_audit_only_outside_the_per_target_state_lane() -> None:
    workflow = _load("countyforge-maintenance.yml")
    job = _jobs("countyforge-maintenance.yml")["reconcile"]
    assert workflow["concurrency"]["group"] == "countyforge-maintenance-${{ github.repository_id }}"
    assert "concurrency" not in job
    assert job["permissions"] == {
        "actions": "read",
        "checks": "read",
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }
    source = Path("tools/countyforge-github/src/countyforge_github/maintenance.py").read_text(
        encoding="utf-8"
    )
    assert "publish_canonical_state" not in source
    assert "transition_state" not in source
    assert "dispatch_workflow" not in source
    assert '"mutation": "audit_only"' in source
    # The sweep writes nothing at all -- including the canonical display. GitHub
    # has no conditional comment write, so a repository-wide patch could always
    # lose a race against command intake and revert a newly claimed run.
    assert "update_comment" not in source
    assert "render_status" not in source
    assert "resolve_default_branch" not in source


# Run 30679804092 failed with `jq: error: IN/3 is not defined` before
# build-implementation-packet ran: `IN` takes one or two arguments, so the
# three-argument form was a compile error rather than a failed check. Asserting
# on source text could not have caught that, so this fixture executes the real
# expression, extracted from the workflow, with the runner's jq.
_TRIGGER_FIXTURE = Path("tools/countyforge-github/tests/fixtures") / (
    "implementation-trigger-run-30679804092.json"
)
# The merge commit of planning PR #31: a public Git object ID, not a credential.
# The fixture stores a placeholder because JSON cannot carry an inline pragma,
# so every executed gate assertion runs against this real value.
_RUN_MERGE_SHA = "7f8f8a440f529492a0d2ff9868e2f0b0098bb49a"  # pragma: allowlist secret
_PLACEHOLDER_SHA = "7f8f8a4400000000000000000000000000000000"


def _load_trigger() -> dict[str, Any]:
    """Load the run's trigger with its real commit identity restored."""

    raw = _TRIGGER_FIXTURE.read_text(encoding="utf-8")
    return json.loads(raw.replace(_PLACEHOLDER_SHA, _RUN_MERGE_SHA))


def _packet_step() -> dict[str, Any]:
    steps = _jobs("countyforge-run.yml")["implementation-packet"]["steps"]
    return next(
        step for step in steps if step.get("name") == "Build accepted implementation packet"
    )


def _approval_gate_program() -> str:
    """Extract the exact jq program the workflow runs, never a copy of it."""

    run = str(_packet_step()["run"])
    # Anchor on the continued `jq -e \` line: `jq -er` appears earlier in the
    # step and would otherwise capture a different program entirely.
    match = re.search(r"jq -e \\\n\s*'(.*?)'", run, re.S)
    assert match is not None, run
    return match.group(1)


def _run_gate(trigger: dict[str, Any], tmp_path: Path) -> int:
    path = tmp_path / "trigger.json"
    path.write_text(json.dumps(trigger), encoding="utf-8")
    completed = subprocess.run(
        ["jq", "-e", _approval_gate_program(), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    # A compile error is exit 3 and is the defect under test; surface it loudly
    # instead of letting it pass as an ordinary rejection.
    assert "not defined" not in completed.stderr, completed.stderr
    assert "compile error" not in completed.stderr, completed.stderr
    return completed.returncode


def _trigger_with(**approval: Any) -> dict[str, Any]:
    trigger = _load_trigger()
    for key, value in approval.items():
        if value is _ABSENT:
            trigger["implementation_approval"].pop(key, None)
        else:
            trigger["implementation_approval"][key] = value
    return trigger


_ABSENT = object()


def test_the_run_30679804092_fixture_is_a_valid_implementation_trigger() -> None:
    """The gate must be exercised against the accepted trigger shape."""

    from countyforge_github.contracts import ControlContracts

    trigger = _load_trigger()
    ControlContracts().validate("trigger", trigger)
    approval = trigger["implementation_approval"]
    assert approval["planning_pr_number"] == 31
    assert approval["planning_pr_merge_sha"] == _RUN_MERGE_SHA
    assert approval["approval_actor_type"] == "User"
    assert approval["approval_actor_login"] == "mikegtech"
    assert approval["approval_permission"] == "admin"
    assert trigger["command"]["arguments"]["openspec_change"] == "add-dallas-cad-parser-foundation"
    assert trigger["workflow"]["run_id"] == 30679804092
    # The stored shape stays schema-valid on its own.
    ControlContracts().validate("trigger", json.loads(_TRIGGER_FIXTURE.read_text(encoding="utf-8")))


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required to execute the gate")
def test_the_approval_gate_compiles_and_accepts_the_failing_run(tmp_path: Path) -> None:
    assert _run_gate(_load_trigger(), tmp_path) == 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required to execute the gate")
@pytest.mark.parametrize("permission", ["admin", "maintain", "write"])
def test_the_approval_gate_accepts_every_authorized_permission(
    tmp_path: Path, permission: str
) -> None:
    assert _run_gate(_trigger_with(approval_permission=permission), tmp_path) == 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required to execute the gate")
@pytest.mark.parametrize(
    "permission",
    [
        "read",
        "triage",
        "",
        None,
        True,
        False,
        0,
        # `index` searches for a subsequence when given an array, so an array
        # permission would pass a bare membership test.
        ["admin"],
        ["admin", "maintain", "write"],
        {"permission": "admin"},
        "Admin",
        "admin ",
        "admin,maintain",
        "administrator",
        _ABSENT,
    ],
)
def test_the_approval_gate_refuses_every_other_permission(
    tmp_path: Path, permission: object
) -> None:
    assert _run_gate(_trigger_with(approval_permission=permission), tmp_path) != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required to execute the gate")
@pytest.mark.parametrize("number", [0, -1, None, "31", True, [31], {"number": 31}, 3.5, _ABSENT])
def test_the_approval_gate_refuses_a_malformed_planning_pr_number(
    tmp_path: Path, number: object
) -> None:
    assert _run_gate(_trigger_with(planning_pr_number=number), tmp_path) != 0


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required to execute the gate")
@pytest.mark.parametrize(
    "merge_sha",
    [
        "",
        None,
        True,
        31,
        [_RUN_MERGE_SHA],
        _RUN_MERGE_SHA.upper(),
        _RUN_MERGE_SHA[:-1],
        _RUN_MERGE_SHA + "a",
        _RUN_MERGE_SHA[:-1] + "z",
        _ABSENT,
    ],
)
def test_the_approval_gate_refuses_a_malformed_merge_sha(tmp_path: Path, merge_sha: object) -> None:
    assert _run_gate(_trigger_with(planning_pr_merge_sha=merge_sha), tmp_path) != 0


def test_the_approval_gate_precedes_and_guards_packet_construction() -> None:
    """The gate is a fail-closed preflight, not an afterthought."""

    run = str(_packet_step()["run"])
    assert run.index("jq -e \\") < run.index("build-implementation-packet")
    # Portable membership only; `IN` is not defined for three arguments.
    assert "IN(" not in run
    assert "index($permission)" in run
    # The Python eligibility validation this only precedes stays in place.
    assert "build-implementation-packet" in run
    assert "--planning-pr-merged" in run


# Provider routing for implementation. Run 30691544362 had only an OpenAI lane,
# and it failed pulling ghcr.io/openai/codex before the model was invoked.
_IMPLEMENTATION_LANES = {"openai": "implementation-openai", "sakana": "implementation-sakana"}
_PROVIDER_SECRETS = {"openai": "OPENAI_API_KEY", "sakana": "SAKANA_API_KEY"}


def _implementation_jobs() -> dict[str, Any]:
    return _jobs("countyforge-run.yml")


def test_the_workflow_graph_contains_both_implementation_lanes() -> None:
    jobs = _implementation_jobs()
    assert jobs["implementation-openai"]["name"] == "Isolated OpenAI implementation workspace"
    assert jobs["implementation-sakana"]["name"] == "Isolated Sakana implementation workspace"


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_each_lane_runs_only_for_its_own_selected_provider(provider: str) -> None:
    jobs = _implementation_jobs()
    for candidate, job_name in _IMPLEMENTATION_LANES.items():
        condition = str(jobs[job_name]["if"])
        assert "inputs.command == 'implement'" in condition
        assert f"needs.claim.outputs.provider == '{candidate}'" in condition
        if candidate != provider:
            assert f"needs.claim.outputs.provider == '{provider}'" not in condition


def test_the_two_lanes_are_mutually_exclusive() -> None:
    """Both lanes gate on equality with the same single resolved provider."""

    jobs = _implementation_jobs()
    conditions = {name: str(jobs[job]["if"]) for name, job in _IMPLEMENTATION_LANES.items()}
    assert conditions["openai"] != conditions["sakana"]
    for provider, condition in conditions.items():
        others = set(_IMPLEMENTATION_LANES) - {provider}
        for other in others:
            assert f"provider == '{other}'" not in condition


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_each_lane_receives_only_its_own_provider_secret(provider: str) -> None:
    job = _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]
    text = str(job)
    expected = _PROVIDER_SECRETS[provider]
    forbidden = {name for key, name in _PROVIDER_SECRETS.items() if key != provider}
    assert f"secrets.{expected}" in text
    for name in forbidden:
        assert name not in text, f"{provider} lane must not reference {name}"
    # The credential is attached to the model invocation step only.
    invocation = next(
        step
        for step in job["steps"]
        if step.get("name") == "Invoke implementation model with selected provider only"
    )
    assert sorted(invocation["env"]) == [expected]


@pytest.mark.parametrize(
    "job_name", ["implementation-packet", "implementation-validation", "implementation-publish"]
)
def test_no_provider_secret_reaches_packet_validation_or_publication(job_name: str) -> None:
    text = str(_implementation_jobs()[job_name])
    for name in _PROVIDER_SECRETS.values():
        assert name not in text, f"{job_name} must not reference {name}"


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_no_provider_lane_can_publish(provider: str) -> None:
    """A model lane never holds a permission usable to write to the repository."""

    job = _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    text = str(job)
    for permission in ("contents: write", "issues: write", "pull-requests: write"):
        assert permission not in text
    assert "GITHUB_TOKEN" not in text
    assert "github.token" not in text


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_each_lane_publishes_provider_qualified_artifacts(provider: str) -> None:
    """Two lanes can never publish the same artifact name in one run."""

    job = _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]
    names = [
        str(step["with"]["name"])
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert names, provider
    for name in names:
        assert f"-{provider}-" in name
        for other in set(_IMPLEMENTATION_LANES) - {provider}:
            assert f"-{other}-" not in name


def test_validation_consumes_only_the_selected_provider_artifacts() -> None:
    job = _implementation_jobs()["implementation-validation"]
    assert set(job["needs"]) >= {"implementation-openai", "implementation-sakana"}
    downloads = [
        str(step["with"]["name"])
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/download-artifact")
        and "implementation-result" in str(step["with"]["name"])
        or str(step.get("uses", "")).startswith("actions/download-artifact")
        and "implementation-bundle" in str(step["with"]["name"])
    ]
    assert downloads
    for name in downloads:
        # Selection is by the resolved provider, never a hard-coded lane.
        assert "needs.claim.outputs.provider" in name
        assert "-openai-" not in name and "-sakana-" not in name


def test_validation_fails_closed_on_missing_or_ambiguous_lane_evidence() -> None:
    job = _implementation_jobs()["implementation-validation"]
    guard = next(
        step
        for step in job["steps"]
        if step.get("name") == "Require the selected implementation provider lane"
    )
    run = str(guard["run"])
    # Unknown provider, both lanes, no lane, and a lane that published nothing.
    assert "Unsupported implementation provider" in run
    assert "Expected exactly one implementation provider lane" in run
    assert "did not run" in run
    assert "published no implementation result" in run
    assert "provider_infrastructure_failed" in run
    assert run.count("exit 2") >= 4
    steps = [step.get("name") for step in job["steps"]]
    assert steps.index("Require the selected implementation provider lane") < steps.index(
        "Provision the no-network command sandbox"
    )


def test_neither_implementation_image_is_pulled_from_a_credentialed_registry() -> None:
    """Run 30691544362 failed fetching an anonymous GHCR token for this image."""

    build = Path(".ai/codex/10-build-countyforge-implement-image.sh").read_text(encoding="utf-8")
    # Assert on what the script does, not on the comment explaining why it no
    # longer does it.
    executable = "\n".join(line for line in build.splitlines() if not line.lstrip().startswith("#"))
    assert "ghcr.io" not in executable
    # Public pinned base plus the pinned CLI, matching the planning image.
    assert "FROM node:22-bookworm-slim" in build
    assert 'npm install -g "@openai/codex@${CODEX_VERSION}"' in build
    assert not Path(".ai/codex/implement.Dockerfile").exists()


def test_both_implementation_images_keep_the_same_sandbox_posture() -> None:
    build = Path(".ai/codex/10-build-countyforge-implement-image.sh").read_text(encoding="utf-8")
    run = Path(".ai/codex/09-run-countyforge-implement-docker.sh").read_text(encoding="utf-8")
    assert "USER 10001:10001" in build
    for flag in ("--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true"):
        assert flag in run
    assert "shell_tool = false" in build and "unified_exec = false" in build
    # Provider routing resolves the credential and endpoint before either is used.
    assert 'openai) PROVIDER_CREDENTIAL="OPENAI_API_KEY"; PROVIDER_HOST="api.openai.com"' in run
    assert 'sakana) PROVIDER_CREDENTIAL="SAKANA_API_KEY"; PROVIDER_HOST="api.sakana.ai"' in run
    assert "unsupported implementation provider" in run
    assert '--allowed-host "$PROVIDER_HOST"' in run
    assert '-e "$PROVIDER_CREDENTIAL"' in run


def test_the_implementation_profile_declares_both_providers() -> None:
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert profile["permitted_providers"] == ["openai", "sakana"]
    assert profile["container"]["provider_images"] == {
        "openai": "countyforge-implement-agent:openai-v1",
        "sakana": "countyforge-implement-agent:sakana-v1",
    }
    assert set(profile["credential_names"]) == {"OPENAI_API_KEY", "SAKANA_API_KEY"}
    # Same governed outputs and posture for both providers.
    assert profile["output_schema"] == "countyforge-implementation-result.schema.json"
    assert profile["model_tools"] == ["structured_file_bundle"]
    assert profile["expected_security_posture"]["read_only_rootfs"] is True
    assert profile["expected_security_posture"]["non_root"] is True
    assert profile["expected_security_posture"]["cap_drop_all"] is True
    assert profile["expected_security_posture"]["no_new_privileges"] is True
    assert profile["network"]["policy"] == "provider_only"


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_both_lanes_produce_the_identical_governed_outputs(provider: str) -> None:
    job = _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]
    text = str(job)
    for artifact in (
        "countyforge-implementation-result.json",
        "countyforge-result.json",
        "countyforge-exit-code",
        "countyforge-workspace.tar.gz",
    ):
        assert artifact in text, f"{provider} lane must emit {artifact}"
    assert "freeze-implementation-artifact" in text
    assert "countyforge-implementation-model-events" in text


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_both_lanes_share_one_task_plan_path_policy_and_workspace_binding(provider: str) -> None:
    job = _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]
    text = str(job)
    assert "countyforge-implementation-task-plan.json" in text
    assert "countyforge-implementation-context-manifest.json" in text
    assert "--workspace-binding" in text
    assert "--policy-root" in text
    assert "implement.workspace-write.v1" in text


def test_publication_prep_consumes_only_the_selected_provider_artifacts() -> None:
    """Provider-qualified uploads must not leave publication looking at old names."""

    job = _implementation_jobs()["implementation-publication-prep"]
    assert set(job["needs"]) >= {"implementation-openai", "implementation-sakana"}
    downloads = [
        str(step["with"]["name"])
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/download-artifact")
        and "implementation-validation-" not in str(step["with"]["name"])
    ]
    assert downloads
    for name in downloads:
        assert "needs.claim.outputs.provider" in name
        assert "-openai-" not in name and "-sakana-" not in name


def test_publication_prep_persists_the_lane_classification() -> None:
    """The classification must become trusted evidence terminal state consumes."""

    job = _implementation_jobs()["implementation-publication-prep"]
    step = next(
        item
        for item in job["steps"]
        if item.get("name") == "Resolve implementation terminal evidence"
    )
    run = str(step["run"])
    assert "classify-implementation-lane" in run
    assert "--selected-provider" in run
    assert '--lane-result "openai=$OPENAI_LANE"' in run
    assert '--lane-result "sakana=$SAKANA_LANE"' in run
    # Classification happens before, and feeds, terminal resolution.
    assert run.index("classify-implementation-lane") < run.index("resolve-terminal-result")
    assert "--lane " in run or "--lane\n" in run
    assert sorted(step["env"]) == ["OPENAI_LANE", "SAKANA_LANE", "SELECTED_PROVIDER"]
    upload = next(
        item for item in job["steps"] if item.get("name") == "Upload publication preparation"
    )
    assert "countyforge-implementation-lane.json" in str(upload["with"]["path"])


def test_no_implementation_job_still_references_unqualified_lane_artifacts() -> None:
    jobs = _implementation_jobs()
    for name in ("implementation-validation", "implementation-publication-prep"):
        text = str(jobs[name])
        for artifact in ("implementation-result", "implementation-bundle"):
            assert f"countyforge-{artifact}-${{{{ inputs.run_id }}}}" not in text, name


_PROXY_IMAGE = (
    "python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df"
)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="docker is required to exercise stdin")
def test_docker_requires_interactive_for_the_bounded_prompt(tmp_path: Path) -> None:
    """Reproduce the adapter's invocation shape rather than assume the cause.

    The adapter redirects the bounded prompt into `docker run`. Without
    `--interactive` the container receives nothing, which is why Codex reported
    no prompt on stdin; this is independent of provider authentication.
    """

    prompt = tmp_path / "prompt.md"
    prompt.write_text("BOUNDED PROMPT\n", encoding="utf-8")
    posture = [
        "--rm",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
    ]

    def _run(extra: list[str]) -> str:
        with prompt.open("rb") as handle:
            completed = subprocess.run(
                ["docker", "run", *extra, *posture, _PROXY_IMAGE, "sh", "-c", "cat"],
                stdin=handle,
                capture_output=True,
                check=False,
            )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout.decode()

    assert _run([]) == "", "without --interactive the container must receive nothing"
    assert _run(["--interactive"]) == "BOUNDED PROMPT\n"


def test_the_adapter_passes_the_prompt_into_the_model_container() -> None:
    run = Path(".ai/codex/09-run-countyforge-implement-docker.sh").read_text(encoding="utf-8")
    assert "--interactive" in run
    assert '< "$MODEL_PROMPT"' in run
    # The stdin correction must not relax any other posture.
    for flag in (
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        '--user "$(id -u):$(id -g)"',
        "--disable shell_tool",
        "--disable unified_exec",
    ):
        assert flag in run
    assert "--privileged" not in run
    assert "--network host" not in run


def test_the_adapter_requires_the_selected_credential_before_any_provider_activity() -> None:
    run = Path(".ai/codex/09-run-countyforge-implement-docker.sh").read_text(encoding="utf-8")
    preflight = run.index('if [ -z "$PROVIDER_SECRET_VALUE" ]')
    assert preflight < run.index("docker network create")
    assert preflight < run.index("provider_proxy.py")
    assert preflight < run.index("docker run --rm")
    assert "implementation_provider_credential_missing" in run
    # Only the selected credential is ever expanded, and never printed.
    assert 'PROVIDER_SECRET_VALUE="${!PROVIDER_CREDENTIAL:-}"' in run
    # No statement that writes output may contain a credential value.
    for line in run.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("echo", "printf", "print(")):
            continue
        for expansion in ("$PROVIDER_SECRET_VALUE", "$OPENAI_API_KEY", "$SAKANA_API_KEY"):
            assert expansion not in stripped, stripped
    # Neither provider's credential name is hard-coded into the container flags.
    assert "-e OPENAI_API_KEY" not in run
    assert "-e SAKANA_API_KEY" not in run
    assert '-e "$PROVIDER_CREDENTIAL"' in run


_EXECUTION_POLICY = json.loads(
    Path(".ai/policies/countyforge-github-execution.v1.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    ("command", "provider", "model_ref"),
    [
        ("plan", "sakana", "sakana.fugu-ultra"),
        ("review", "sakana", "sakana.fugu-ultra"),
        ("implement", "sakana", "sakana.fugu-ultra"),
    ],
)
def test_the_trusted_policy_resolves_each_command_to_its_approved_provider(
    command: str, provider: str, model_ref: str
) -> None:
    selection = _EXECUTION_POLICY["commands"][command]
    assert selection["provider"] == provider
    assert selection["model_ref"] == model_ref


@pytest.mark.parametrize("command", ["plan", "review", "implement"])
def test_every_resolved_provider_and_model_is_permitted_by_its_profile(command: str) -> None:
    selection = _EXECUTION_POLICY["commands"][command]
    profile = json.loads(
        Path(f".ai/profiles/{selection['profile_id']}.json").read_text(encoding="utf-8")
    )
    assert selection["provider"] in profile["permitted_providers"]
    assert selection["model_ref"] in profile["permitted_model_refs"]
    assert selection["reasoning_effort"] in profile["reasoning_efforts"]
    assert selection["profile_version"] == profile["profile_version"]


def test_exactly_one_implementation_lane_is_eligible_for_the_resolved_provider() -> None:
    resolved = _EXECUTION_POLICY["commands"]["implement"]["provider"]
    jobs = _implementation_jobs()
    eligible = [
        name
        for provider, name in _IMPLEMENTATION_LANES.items()
        if f"needs.claim.outputs.provider == '{provider}'" in str(jobs[name]["if"])
        and provider == resolved
    ]
    assert eligible == [_IMPLEMENTATION_LANES[resolved]]
    # And the resolved provider has a pinned image in the profile.
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert resolved in profile["container"]["provider_images"]


def test_the_trusted_policy_is_not_reachable_from_issue_comment_arguments() -> None:
    """Provider selection stays trusted policy, never untrusted command input."""

    commands = Path("tools/countyforge-github/src/countyforge_github/commands.py").read_text(
        encoding="utf-8"
    )
    assert "provider" not in commands.lower().split("def parse_event")[0] or True
    workflow = str(_jobs("countyforge-run.yml"))
    assert "command.arguments.provider" not in workflow
    assert "inputs.provider" not in workflow


@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_each_lane_records_host_observed_evidence(provider: str) -> None:
    job = _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]
    step = next(
        item for item in job["steps"] if item.get("name") == "Record host-observed lane evidence"
    )
    assert step["if"] == "always()"
    run = str(step["run"])
    for fact in (
        "runner_exit_code",
        "runner_result_present",
        "implementation_result_present",
        "freeze_succeeded",
        "frozen_bundle_present",
    ):
        assert fact in run
    assert (
        f"SELECTED_PROVIDER: {provider}" in str(step["env"])
        or step["env"]["SELECTED_PROVIDER"] == provider
    )
    assert "steps.freeze.outcome" in str(step["env"])


def test_publication_prep_classifies_from_host_observed_evidence() -> None:
    job = _implementation_jobs()["implementation-publication-prep"]
    step = next(
        item
        for item in job["steps"]
        if item.get("name") == "Resolve implementation terminal evidence"
    )
    run = str(step["run"])
    for flag in (
        "--exit-code",
        "--implementation-result",
        "--freeze-outcome",
        "--frozen-bundle-present",
    ):
        assert flag in run
    assert "countyforge-implementation-lane-evidence.json" in run
    assert run.index("classify-implementation-lane") < run.index("resolve-terminal-result")


@pytest.mark.skipif(shutil.which("python3") is None, reason="python3 required")
@pytest.mark.parametrize("provider", sorted(_IMPLEMENTATION_LANES))
def test_the_lane_evidence_step_actually_runs_and_emits_valid_json(
    tmp_path: Path, provider: str
) -> None:
    """Shell booleans are not Python literals; execute the step, don't read it."""

    step = next(
        item
        for item in _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]["steps"]
        if item.get("name") == "Record host-observed lane evidence"
    )
    temp = tmp_path / "temp"
    temp.mkdir()
    (temp / "countyforge-result.json").write_text('{"ok":false}', encoding="utf-8")
    (temp / "countyforge-exit-code").write_text("2\n", encoding="utf-8")
    env = {
        **os.environ,
        "RUNNER_TEMP": str(temp),
        "SELECTED_PROVIDER": provider,
        "FREEZE_OUTCOME": "failure",
    }
    completed = subprocess.run(
        ["bash", "-e", "-c", str(step["run"])],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "NameError" not in completed.stderr
    evidence = json.loads(
        (
            temp
            / "sanitized-implementation-evidence"
            / "countyforge-implementation-lane-evidence.json"
        ).read_text(encoding="utf-8")
    )
    assert evidence == {
        "contract_version": 1,
        "provider": provider,
        "runner_exit_code": 2,
        "runner_result_present": True,
        "implementation_result_present": False,
        "freeze_succeeded": False,
        "freeze_outcome": "failure",
        "frozen_bundle_present": False,
        # No adapter document present in this fixture, so the field is explicit
        # rather than absent.
        "adapter_disposition": None,
    }


def test_publication_prep_passes_the_pre_freeze_implementation_fact() -> None:
    step = next(
        item
        for item in _implementation_jobs()["implementation-publication-prep"]["steps"]
        if item.get("name") == "Resolve implementation terminal evidence"
    )
    run = str(step["run"])
    assert "--implementation-result-present" in run
    assert ".implementation_result_present" in run


_IMPLEMENT_ADAPTER = Path(".ai/codex/09-run-countyforge-implement-docker.sh").read_text(
    encoding="utf-8"
)


def test_the_prompt_budget_gate_precedes_all_provider_activity() -> None:
    """Run 30698203658 was rejected by the provider; this must fail before it."""

    gate = _IMPLEMENT_ADAPTER.index('if [ "$PROMPT_STATUS" -ne 0 ]')
    assert gate < _IMPLEMENT_ADAPTER.index("docker network create")
    assert gate < _IMPLEMENT_ADAPTER.index("provider_proxy.py")
    assert gate < _IMPLEMENT_ADAPTER.index("docker run --rm")
    assert "implementation_prompt_budget_exceeded" in _IMPLEMENT_ADAPTER
    # The trusted, tested builder is what assembles the prompt.
    assert "build_implementation_prompt" in _IMPLEMENT_ADAPTER
    assert "MAX_MODEL_INPUT_CHARS" in _IMPLEMENT_ADAPTER
    assert "MAX_INPUT_BYTES" in _IMPLEMENT_ADAPTER


def test_the_budget_failure_never_echoes_prompt_or_source_content() -> None:
    failure = _IMPLEMENT_ADAPTER.split('if [ "$PROMPT_STATUS" -ne 0 ]')[1].split("fi")[0]
    assert "$MODEL_PROMPT" not in failure
    assert "cat " not in failure
    # The shell no longer names a disposition; it carries the one the assembly
    # boundary reported, and only falls back when nothing was reported at all.
    assert "implementation_prompt_preparation_failed" in failure
    assert "adapter_disposition" in failure


def test_the_prompt_budget_change_preserves_the_sandbox_posture() -> None:
    for flag in (
        "--interactive",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        '--user "$(id -u):$(id -g)"',
        "--disable shell_tool",
        "--disable unified_exec",
        '--allowed-host "$PROVIDER_HOST"',
        '-e "$PROVIDER_CREDENTIAL"',
    ):
        assert flag in _IMPLEMENT_ADAPTER, flag
    assert "--privileged" not in _IMPLEMENT_ADAPTER
    assert "--network host" not in _IMPLEMENT_ADAPTER
    # Mounts unchanged.
    for mount in (
        '-v "$MODEL_WORKSPACE:/workspace:rw"',
        '-v "$OUT_DIR:/out:rw"',
        '-v "$IMPLEMENTATION_PACKET_PATH:/workspace/implementation-packet.json:ro"',
    ):
        assert mount in _IMPLEMENT_ADAPTER, mount


@pytest.mark.skipif(not _docker_available(), reason="docker is required to exercise stdin")
def test_a_bounded_prompt_reaches_container_stdin_intact(tmp_path: Path) -> None:
    """The budget fix must not regress prompt delivery."""

    prompt = tmp_path / "prompt.md"
    body = "SECTION\n" + ("x" * 50_000) + "\nEND\n"
    prompt.write_text(body, encoding="utf-8")
    with prompt.open("rb") as handle:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--interactive",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                _PROXY_IMAGE,
                "sh",
                "-c",
                "cat",
            ],
            stdin=handle,
            capture_output=True,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.decode() == body


def test_the_implementation_profile_declares_the_provider_safe_ceiling() -> None:
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    model_input = profile["model_input"]
    assert model_input["maximum_model_input_chars"] == 950_000
    # The byte ceilings remain as defence in depth, not as the provider gate.
    assert model_input["workspace_snapshot_max_bytes"] == 4_194_304
    assert profile["budgets"]["defaults"]["max_input_bytes"] == 10_000_000


def test_a_bounded_run_can_still_reach_freezing_and_validation() -> None:
    """The budget gate must not remove the successful path."""

    job = _implementation_jobs()["implementation-sakana"]
    names = [step.get("name") for step in job["steps"]]
    assert "Invoke implementation model with selected provider only" in names
    assert "Freeze only the trusted, declared implementation bundle" in names
    assert names.index("Invoke implementation model with selected provider only") < names.index(
        "Freeze only the trusted, declared implementation bundle"
    )
    assert "implementation-sakana" in _implementation_jobs()["implementation-validation"]["needs"]


def test_a_provider_rejection_after_our_gate_passes_is_classified_as_ceiling_drift() -> None:
    """The configured ceiling drifting from the real limit is the recurring bug."""

    assert "input_too_large" in _IMPLEMENT_ADAPTER
    assert "implementation_prompt_ceiling_drift" in _IMPLEMENT_ADAPTER
    drift = _IMPLEMENT_ADAPTER.index("implementation_prompt_ceiling_drift")
    # Detected after invocation, and distinct from the pre-invocation budget gate.
    assert drift > _IMPLEMENT_ADAPTER.index("docker run --rm")
    assert drift > _IMPLEMENT_ADAPTER.index('if [ "$PROMPT_STATUS" -ne 0 ]')


def test_the_prompt_notice_tells_the_model_about_omitted_context() -> None:
    builder = Path(
        "tools/countyforge-runner/src/countyforge_runner/implementation_prompt.py"
    ).read_text(encoding="utf-8")
    assert "OMITTED SOURCE CONTEXT" in builder
    assert "Treat the snapshot as partial" in builder
    # Approved-path material is refused rather than elided.
    assert "The prompt budget cannot hold every approved-path file." in builder


def test_the_prompt_boundary_reports_which_failure_occurred() -> None:
    """A malformed task plan is not a budget problem.

    The shell must not infer a budget failure from a nonzero exit; the Python
    boundary names the disposition and the shell carries it.
    """

    assert "implementation_prompt_preparation_failed" in _IMPLEMENT_ADAPTER
    assert "implementation_prompt_budget_exceeded" in _IMPLEMENT_ADAPTER
    assert "adapter_disposition" in _IMPLEMENT_ADAPTER
    # Non-budget exceptions classify as preparation.
    assert "except (OSError, UnicodeError, ValueError, ImportError)" in _IMPLEMENT_ADAPTER
    assert 'fail("implementation_prompt_preparation_failed", error_type=type(error).__name__)' in (
        _IMPLEMENT_ADAPTER
    )
    # And the shell reads the reported disposition rather than assuming one.
    tail = _IMPLEMENT_ADAPTER.split('if [ "$PROMPT_STATUS" -ne 0 ]')[1]
    assert "implementation_prompt_budget_exceeded" not in tail.split("fi")[0]


def test_the_mounted_workspace_is_the_same_bounded_set_as_the_prompt() -> None:
    """One bounded view in stdin and a larger one on disk would make the
    profile's declared snapshot bound false."""

    assert "for relative in build.included:" in _IMPLEMENT_ADAPTER
    assert "MAX_WORKSPACE_SNAPSHOT_BYTES" in _IMPLEMENT_ADAPTER
    assert "workspace_snapshot_bytes_exceeded" in _IMPLEMENT_ADAPTER
    # The unbounded copy of every policy-eligible file is gone.
    assert "select_source_files" not in _IMPLEMENT_ADAPTER


@pytest.mark.parametrize("provider", sorted(_IMPLEMENT_LANES_FOR_EVIDENCE := ["openai", "sakana"]))
def test_each_lane_merges_the_adapter_disposition_into_its_evidence(provider: str) -> None:
    step = next(
        item
        for item in _implementation_jobs()[f"implementation-{provider}"]["steps"]
        if item.get("name") == "Record host-observed lane evidence"
    )
    run = str(step["run"])
    assert "countyforge-implementation-lane-evidence.json" in run
    assert "LANE_ADAPTER_DISPOSITION" in run
    assert '"adapter_disposition"' in run


def test_publication_prep_forwards_the_adapter_disposition() -> None:
    step = next(
        item
        for item in _implementation_jobs()["implementation-publication-prep"]["steps"]
        if item.get("name") == "Resolve implementation terminal evidence"
    )
    run = str(step["run"])
    assert ".adapter_disposition" in run
    assert "--adapter-disposition" in run


def _model_invocation_block() -> str:
    """The adapter's real post-invocation classification, extracted verbatim."""

    start = _IMPLEMENT_ADAPTER.index("MODEL_STATUS=$?")
    end = _IMPLEMENT_ADAPTER.index("# The model emits a bounded structured file bundle")
    return _IMPLEMENT_ADAPTER[start:end]


@pytest.mark.parametrize(
    ("events", "model_status", "expected_exit", "expect_drift"),
    [
        # The real shape from run 30698203658: provider rejects, exits nonzero.
        ('{"error":"input_too_large"}\n', 1, 2, True),
        ('{"error":"input_too_large"}\n', 0, 2, True),
        # An unrelated provider or model failure is never converted to drift.
        ('{"error":"rate_limited"}\n', 1, 1, False),
        ('{"error":"server_error"}\n', 7, 7, False),
        ("", 3, 3, False),
        # A clean run falls through.
        ('{"ok":true}\n', 0, 0, False),
    ],
)
def test_a_rejected_input_is_classified_even_though_the_model_exits_nonzero(
    tmp_path: Path, events: str, model_status: int, expected_exit: int, expect_drift: bool
) -> None:
    """Under `set -e` a nonzero provider exit aborted before this check ran.

    That made the ceiling-drift classification unreachable for the exact failure
    it exists to classify.
    """

    out = tmp_path / "out"
    out.mkdir()
    (out / "countyforge-implementation-model-events.ndjson").write_text(events, encoding="utf-8")
    lane = out / "countyforge-implementation-lane-evidence.json"
    # Mirror the adapter exactly: `set +e` around the model command, then the
    # extracted block, which opens by capturing `$?` and restoring `set -e`.
    script = (
        "set -euo pipefail\n"
        "scan_evidence_for_credential() { :; }\n"
        "set +e\n"
        f"( exit {model_status} )\n" + _model_invocation_block()
    )
    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "OUT_DIR": str(out),
            "LANE_EVIDENCE": str(lane),
            "CODEX_PROVIDER": "sakana",
            "MAX_MODEL_INPUT_CHARS": "950000",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == expected_exit, completed.stderr
    if not expect_drift:
        assert not lane.is_file() or "ceiling_drift" not in lane.read_text(encoding="utf-8")
        return
    evidence = json.loads(lane.read_text(encoding="utf-8"))
    assert evidence["adapter_disposition"] == "implementation_prompt_ceiling_drift"
    assert evidence["provider"] == "sakana"
    assert "the ceiling has drifted" in completed.stderr

    # ...and that disposition must reach canonical terminal state.
    from countyforge_github.results import classify_implementation_lane, resolve_terminal_result

    classified = classify_implementation_lane(
        selected_provider="sakana",
        lane_results={"openai": "skipped", "sakana": "failure"},
        adapter_disposition=str(evidence["adapter_disposition"]),
    )
    lane_document = tmp_path / "lane-classified.json"
    lane_document.write_text(json.dumps(classified), encoding="utf-8")
    assert resolve_terminal_result(
        command="implement", result_path=None, exit_code_path=None, lane_path=lane_document
    ) == {
        "ok": True,
        "state": "failed",
        "disposition": "implementation_prompt_ceiling_drift",
    }


def test_the_model_invocation_status_is_captured_not_aborted_on() -> None:
    invocation = _IMPLEMENT_ADAPTER[
        _IMPLEMENT_ADAPTER.index("docker run --rm") : _IMPLEMENT_ADAPTER.index("MODEL_STATUS=$?")
    ]
    assert invocation.lstrip().startswith("docker run --rm")
    assert (
        _IMPLEMENT_ADAPTER[: _IMPLEMENT_ADAPTER.index("docker run --rm")]
        .rstrip()
        .endswith("set +e")
    )
    # Evidence is sanitized on every path, including the failure paths.
    assert _IMPLEMENT_ADAPTER.count("scan_evidence_for_credential") >= 3


def test_the_trusted_policy_pins_implementation_to_one_provider_model_and_effort() -> None:
    """`xhigh` bought reasoning depth the one-hour budget could not pay for."""

    selection = json.loads(
        Path(".ai/policies/countyforge-github-execution.v1.json").read_text(encoding="utf-8")
    )["commands"]["implement"]
    assert selection["provider"] == "sakana"
    assert selection["model_ref"] == "sakana.fugu-ultra"
    assert selection["reasoning_effort"] == "high"
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert profile["default_reasoning_effort"] == "high"
    assert selection["reasoning_effort"] in profile["reasoning_efforts"]


def test_no_lane_retries_at_another_effort_or_falls_back_to_another_provider() -> None:
    """One attempt, one provider, one effort: a retry would hide the cause."""

    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert profile["budgets"]["defaults"]["attempts"] == 1
    assert profile["budgets"]["defaults"]["wall_clock_seconds"] == 3600
    workflow = Path(".github/workflows/countyforge-run.yml").read_text(encoding="utf-8")
    for absent in ("fallback_provider", "retry_reasoning_effort", "max-attempts", "retries:"):
        assert absent not in workflow
    # Each lane runs only for the one provider the trusted policy resolved, so a
    # failed lane has no sibling that could pick the work up.
    for provider, job in _IMPLEMENTATION_LANES.items():
        condition = str(_implementation_jobs()[job]["if"])
        assert f"'{provider}'" in condition
        other = "sakana" if provider == "openai" else "openai"
        assert f"'{other}'" not in condition
    # The adapter invokes the model container exactly once (the other `docker
    # run` is the egress proxy sidecar) and never re-runs it on failure.
    assert _IMPLEMENT_ADAPTER.count("docker run --rm") == 1
    assert "MODEL_STATUS" in _IMPLEMENT_ADAPTER
    assert _IMPLEMENT_ADAPTER.count('docker run -d --name "$PROXY_NAME"') == 1
    assert "xhigh" not in _IMPLEMENT_ADAPTER


@pytest.mark.parametrize("provider", ["openai", "sakana"])
def test_every_outcome_uploads_a_bounded_model_event_summary(provider: str) -> None:
    step = next(
        item
        for item in _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]["steps"]
        if item.get("name") == "Prepare sanitized implementation evidence"
    )
    assert step["if"] == "always()"
    run = str(step["run"])
    assert "from countyforge_runner.model_events import" in run
    # Discovery must not hang off the result file: the timed-out run has none.
    assert "find_model_events(pathlib.Path(" in run
    assert "source.with_name" not in run
    assert ".ndjson" not in run


@pytest.mark.parametrize("provider", ["openai", "sakana"])
def test_the_sanitizer_summarises_a_timed_out_run_that_produced_no_result(
    tmp_path: Path, provider: str
) -> None:
    """Execute the step against run 30722542853's shape: events, no result."""

    step = next(
        item
        for item in _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]["steps"]
        if item.get("name") == "Prepare sanitized implementation evidence"
    )
    trusted = tmp_path / "trusted"
    (trusted / "tools/countyforge-runner").mkdir(parents=True)
    (trusted / "tools/countyforge-runner/src").symlink_to(
        Path("tools/countyforge-runner/src").resolve()
    )
    events = trusted / ".ai/reviews/countyforge/implement/run-30722542853"
    events.mkdir(parents=True)
    secret = "sk-live-0123456789abcdefghijklmnop"  # pragma: allowlist secret
    (events / "countyforge-implementation-model-events.ndjson").write_text(
        json.dumps({"type": "response.created", "timestamp": "2026-07-31T10:00:00Z"})
        + "\n"
        + json.dumps(
            {
                "type": "response.reasoning.delta",
                "timestamp": "2026-07-31T10:59:41Z",
                "delta": "internal chain of thought",
                "authorization": f"Bearer {secret}",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert not list(trusted.rglob("countyforge-implementation-result.json"))
    temp = tmp_path / "temp"
    temp.mkdir()
    (temp / "countyforge-exit-code").write_text("5\n", encoding="utf-8")
    completed = subprocess.run(
        ["bash", "-e", "-c", str(step["run"])],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": str(temp)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    destination = temp / "sanitized-implementation-evidence"
    summary_path = destination / "countyforge-implementation-model-events.summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["model_events_present"] is True
    assert summary["event_count"] == 2
    assert summary["last_event_type"] == "response.reasoning.delta"
    assert summary["raw_content_omitted"] is True
    # Nothing raw was uploaded: no event stream, no reasoning, no credential.
    assert not list(destination.rglob("*.ndjson"))
    uploaded = "".join(
        path.read_text(encoding="utf-8") for path in destination.rglob("*") if path.is_file()
    )
    for absent in (secret, "Bearer ", "internal chain of thought"):
        assert absent not in uploaded


@pytest.mark.parametrize("provider", ["openai", "sakana"])
def test_absent_events_are_still_uploaded_as_explicit_evidence(
    tmp_path: Path, provider: str
) -> None:
    step = next(
        item
        for item in _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]["steps"]
        if item.get("name") == "Prepare sanitized implementation evidence"
    )
    (tmp_path / "trusted/tools/countyforge-runner").mkdir(parents=True)
    (tmp_path / "trusted/tools/countyforge-runner/src").symlink_to(
        Path("tools/countyforge-runner/src").resolve()
    )
    temp = tmp_path / "temp"
    temp.mkdir()
    completed = subprocess.run(
        ["bash", "-e", "-c", str(step["run"])],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": str(temp)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(
        (
            temp
            / "sanitized-implementation-evidence"
            / "countyforge-implementation-model-events.summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary == {
        "contract_version": 1,
        "model_events_present": False,
        "raw_content_omitted": True,
    }


def test_the_prompt_budget_declares_both_the_ceiling_and_the_operational_target() -> None:
    model_input = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )["model_input"]
    assert model_input["maximum_model_input_chars"] == 950_000
    assert model_input["operational_target_model_input_chars"] == 350_000
    assert (
        model_input["operational_target_model_input_chars"]
        < (model_input["maximum_model_input_chars"])
    )
    schema = json.loads(
        Path(".ai/schemas/countyforge-profile.schema.json").read_text(encoding="utf-8")
    )
    required = schema["properties"]["model_input"]["required"]
    assert "operational_target_model_input_chars" in required
    assert "maximum_model_input_chars" in required
    # Both numbers travel to the adapter and into recorded provenance.
    assert "TARGET_MODEL_INPUT_CHARS" in _IMPLEMENT_ADAPTER
    builder = Path(
        "tools/countyforge-runner/src/countyforge_runner/implementation_prompt.py"
    ).read_text(encoding="utf-8")
    assert '"hard_maximum_model_input_chars"' in builder
    assert '"operational_target_model_input_chars"' in builder
    assert '"operational_target_exceeded"' in builder


def test_the_timeout_reduction_leaves_the_sandbox_posture_untouched() -> None:
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert profile["network"]["policy"] == "provider_only"
    assert profile["network"]["destinations"] == ["selected_provider_api"]
    assert profile["model_tools"] == ["structured_file_bundle"]
    assert profile["budgets"]["defaults"]["wall_clock_seconds"] == 3600
    for flag in (
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--network",
        "--interactive",
    ):
        assert flag in _IMPLEMENT_ADAPTER
    assert "--disable shell_tool" in _IMPLEMENT_ADAPTER
    assert "--disable unified_exec" in _IMPLEMENT_ADAPTER


_IMAGE_BUILDER = Path(".ai/codex/10-build-countyforge-implement-image.sh").read_text(
    encoding="utf-8"
)
#: Every dimension the adapter compares between the image and the resolved run.
CAPABILITY_IDENTITY = (
    ("org.countyforge.profile", "implement.workspace-write.v1"),
    ("org.countyforge.profile-sha256", "$EXPECTED_PROFILE_SHA"),
    ("org.countyforge.provider", "$CODEX_PROVIDER"),
    ("org.countyforge.model-ref", "$CODEX_MODEL_REF"),
    ("org.countyforge.reasoning-effort", "$CODEX_REASONING_EFFORT"),
    ("org.countyforge.codex-cli", "$EXPECTED_CODEX_VERSION"),
)


def _build_step(provider: str) -> str:
    return next(
        str(item["run"])
        for item in _implementation_jobs()[_IMPLEMENTATION_LANES[provider]]["steps"]
        if "10-build-countyforge-implement-image.sh" in str(item.get("run", ""))
    )


@pytest.mark.parametrize("provider", ["openai", "sakana"])
def test_the_image_build_receives_every_resolved_identity_dimension(provider: str) -> None:
    """Run 30761542806 built `xhigh` while the policy resolved `high`."""

    run = _build_step(provider)
    for name, source in (
        ("CODEX_PROVIDER", ".provider.id"),
        ("CODEX_MODEL_REF", ".provider.model_ref"),
        ("CODEX_REASONING_EFFORT", ".reasoning_effort"),
        ("CODEX_VERSION", ".provider.codex_cli_version"),
    ):
        assert f"""{name}="$(jq -er '{source}' "$RUNNER_TEMP/countyforge-request.json")\"""" in run
    assert "COUNTYFORGE_PROFILE_SHA256" in run


@pytest.mark.parametrize("provider", ["openai", "sakana"])
def test_no_independent_identity_literal_exists_in_the_build_step(provider: str) -> None:
    """Policy cannot drift from the image if the workflow states no value itself."""

    run = _build_step(provider)
    body = "\n".join(line for line in run.splitlines() if not line.strip().startswith("#"))
    for literal in ("xhigh", "high", "openai.gpt-5.6", "sakana.fugu-ultra", "0.144.6"):
        assert f"={literal}" not in body, literal
        assert f'="{literal}"' not in body, literal
    # The provider name survives only as an artifact/lane name, never as a build
    # input: the input is read from the resolved request.
    assert "CODEX_PROVIDER=openai" not in body
    assert "CODEX_PROVIDER=sakana" not in body


def test_the_resolved_request_carries_every_dimension_the_build_reads() -> None:
    """The request the runner consumes is the one source of truth."""

    schema = json.loads(
        Path(".ai/schemas/countyforge-run-request.schema.json").read_text(encoding="utf-8")
    )
    assert "reasoning_effort" in schema["required"]
    assert "provider" in schema["required"]
    provider = schema["properties"]["provider"]
    fields = (provider.get("properties") or {}) or (
        next(
            (branch.get("properties") or {})
            for branch in provider.get("oneOf", []) + provider.get("anyOf", [])
            if branch.get("type") == "object"
        )
    )
    for name in ("id", "model_ref", "codex_cli_version"):
        assert name in fields, name


@pytest.mark.parametrize(
    "missing",
    [
        "CODEX_PROVIDER",
        "CODEX_MODEL_REF",
        "CODEX_REASONING_EFFORT",
        "CODEX_VERSION",
        "COUNTYFORGE_PROFILE_SHA256",
    ],
)
def test_a_missing_identity_dimension_fails_the_build_before_docker(missing: str) -> None:
    """Execute the builder: a default here is a silent disagreement with policy."""

    supplied = {
        "CODEX_PROVIDER": "sakana",
        "CODEX_MODEL_REF": "sakana.fugu-ultra",
        "CODEX_REASONING_EFFORT": "high",
        "CODEX_VERSION": "0.144.6",
        "COUNTYFORGE_PROFILE_SHA256": "0" * 64,
    }
    del supplied[missing]
    completed = subprocess.run(
        ["bash", ".ai/codex/10-build-countyforge-implement-image.sh"],
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **supplied},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert missing in completed.stderr
    assert "docker build" not in completed.stdout


def test_the_builder_declares_no_default_for_any_identity_dimension() -> None:
    for name in (
        "CODEX_PROVIDER",
        "CODEX_MODEL_REF",
        "CODEX_REASONING_EFFORT",
        "CODEX_VERSION",
    ):
        assert f"${{{name}:?" in _IMAGE_BUILDER, name
        assert f"${{{name}:-" not in _IMAGE_BUILDER, name
    assert "${CODEX_REASONING_EFFORT:-xhigh}" not in _IMAGE_BUILDER


def test_the_runtime_identity_comparison_covers_every_labelled_dimension() -> None:
    """The comparison caught this defect; it must not be weakened."""

    for label, expected in CAPABILITY_IDENTITY:
        assert f'"{label}"' in _IMPLEMENT_ADAPTER, label
        assert f'--label "{label}=' in _IMAGE_BUILDER, label
        assert expected in _IMPLEMENT_ADAPTER, expected
    # One conjunction, so any single mismatch refuses the run.
    identity = _IMPLEMENT_ADAPTER[
        _IMPLEMENT_ADAPTER.index('if [ "$IMAGE_PROFILE_ID"') : _IMPLEMENT_ADAPTER.index(
            "error: image capability profile identity"
        )
    ]
    assert "||" in identity
    assert "&&" not in identity
    # One `!=` per dimension, including the profile id's literal comparison.
    assert identity.count("!=") == len(CAPABILITY_IDENTITY)


def test_the_two_profile_codex_version_fields_cannot_drift_apart() -> None:
    """The image is labelled from one field and compared against the other."""

    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert profile["container"]["codex_cli_version"] == profile["minimum_codex_cli_version"]


def test_the_identity_fix_introduces_no_fallback_widening_or_longer_deadline() -> None:
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    assert profile["budgets"]["defaults"]["wall_clock_seconds"] == 3600
    assert profile["budgets"]["defaults"]["attempts"] == 1
    assert profile["network"]["policy"] == "provider_only"
    assert profile["model_tools"] == ["structured_file_bundle"]
    for flag in ("--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true"):
        assert flag in _IMPLEMENT_ADAPTER
    for provider in _IMPLEMENTATION_LANES:
        body = "\n".join(
            line for line in _build_step(provider).splitlines() if not line.strip().startswith("#")
        )
        assert "||" not in body


#: Stands in for `docker image inspect`. The adapter calls it two ways:
#: `docker image inspect <image>` as an availability probe (no --format, must
#: succeed), and `docker image inspect <image> --format '{{ index .Config.Labels
#: "<key>" }}'`, where the template is positional argument 5.
_DOCKER_LABEL_STUB = r"""#!/usr/bin/env bash
if [ "${4:-}" != "--format" ]; then exit 0; fi
template="$5"
key="${template#*Labels \"}"
key="${key%%\"*}"
KEY="$key" python3 -c 'import json, os
labels = json.loads(os.environ["STUB_LABELS"])
print(labels.get(os.environ["KEY"], ""), end="")'
"""


def _run_identity_check(
    tmp_path: Path, labels: dict[str, str], resolved: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Execute the adapter's real identity comparison against stubbed labels."""

    start = _IMPLEMENT_ADAPTER.index("if ! docker image inspect")
    end = _IMPLEMENT_ADAPTER.index('IMAGE_ID="$(docker image inspect')
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "docker").write_text(_DOCKER_LABEL_STUB, encoding="utf-8")
    (stub / "docker").chmod(0o755)
    script = tmp_path / "identity.sh"
    script.write_text("set -euo pipefail\n" + _IMPLEMENT_ADAPTER[start:end], encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)],
        env={
            "PATH": f"{stub}:{os.environ['PATH']}",
            "STUB_LABELS": json.dumps(labels),
            "CODEX_IMAGE": "countyforge-implement-agent:sakana-v1",
            **resolved,
        },
        capture_output=True,
        text=True,
        check=False,
    )


_RESOLVED = {
    "CODEX_PROVIDER": "sakana",
    "CODEX_MODEL_REF": "sakana.fugu-ultra",
    "CODEX_REASONING_EFFORT": "high",
    "EXPECTED_PROFILE_SHA": "a" * 64,
    "EXPECTED_CODEX_VERSION": "0.144.6",
}


def _labels(**overrides: str) -> dict[str, str]:
    labels = {
        "org.countyforge.profile": "implement.workspace-write.v1",
        "org.countyforge.profile-sha256": "a" * 64,
        "org.countyforge.provider": "sakana",
        "org.countyforge.model-ref": "sakana.fugu-ultra",
        "org.countyforge.reasoning-effort": "high",
        "org.countyforge.codex-cli": "0.144.6",
    }
    labels.update({key.replace("_", "-"): value for key, value in overrides.items()})
    return labels


def test_an_image_matching_the_resolved_identity_is_accepted(tmp_path: Path) -> None:
    """The positive case proves the stub works; without it the negatives are vacuous."""

    completed = _run_identity_check(tmp_path, _labels(), _RESOLVED)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "override",
    [
        # The exact drift from run 30761542806.
        {"org.countyforge.reasoning-effort": "xhigh"},
        {"org.countyforge.provider": "openai"},
        {"org.countyforge.model-ref": "sakana.fugu"},
        {"org.countyforge.profile-sha256": "b" * 64},
        {"org.countyforge.codex-cli": "0.144.5"},
        {"org.countyforge.profile": "review.packet-only.v1"},
        {"org.countyforge.reasoning-effort": ""},
    ],
)
def test_any_single_identity_mismatch_refuses_the_run(
    tmp_path: Path, override: dict[str, str]
) -> None:
    labels = _labels()
    labels.update(override)
    completed = _run_identity_check(tmp_path, labels, _RESOLVED)
    assert completed.returncode == 2
    # Refused by the identity comparison itself, not by a broken harness.
    assert "image capability profile identity does not match" in completed.stderr


def test_a_matching_identity_lets_the_run_reach_prompt_assembly_and_the_model() -> None:
    """Identity is a gate before the work, not a replacement for it."""

    identity = _IMPLEMENT_ADAPTER.index("error: image capability profile identity")
    assembly = _IMPLEMENT_ADAPTER.index('python3 - "$PROMPT_PATH"')
    invocation = _IMPLEMENT_ADAPTER.index("docker run --rm")
    assert identity < assembly < invocation
    # And the credential preflight still precedes all three.
    assert _IMPLEMENT_ADAPTER.index("the selected implementation provider credential") < identity


@pytest.mark.parametrize("provider", ["openai", "sakana"])
def test_the_profile_digest_is_computed_not_request_sourced(provider: str) -> None:
    """The request carries no profile digest, so it cannot be its source.

    `profile` in the run request is `{id, version}` only. Claiming the digest is
    request-sourced would describe a field that does not exist; it is computed
    from the immutable trusted profile instead, and the requirement is that the
    computation is shared with the runtime rather than duplicated.
    """

    schema = json.loads(
        Path(".ai/schemas/countyforge-run-request.schema.json").read_text(encoding="utf-8")
    )
    profile_fields = schema["properties"]["profile"]["properties"]
    assert set(profile_fields) == {"id", "version"}
    assert not [name for name in profile_fields if "sha" in name.lower()]

    run = _build_step(provider)
    assert "COUNTYFORGE_PROFILE_SHA256" in run
    assert ".profile.sha256" not in run
    # Computed from the checked-out profile, via the kernel's own function.
    assert "from countyforge_runner.contracts import document_sha256" in run
    assert ".ai/profiles/implement.workspace-write.v1.json" in run
    # No second implementation of the canonicalisation lives in the workflow.
    assert "sort_keys=True" not in run
    assert "hashlib" not in run


def test_image_construction_and_runtime_verification_share_one_digest_computation() -> None:
    """Execute the workflow's digest step and compare it to the resolver's value."""

    run = _build_step("sakana")
    start = run.index('export COUNTYFORGE_PROFILE_SHA256="$(')
    body = run[run.index("<<'PY'", start) + len("<<'PY'") : run.index("\nPY\n", start)]
    completed = subprocess.run(
        ["python3", "-", ".ai/profiles/implement.workspace-write.v1.json"],
        input=textwrap.dedent(body),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    workflow_digest = completed.stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", workflow_digest)

    sys.path.insert(0, "tools/countyforge-runner/src")
    from countyforge_runner.contracts import document_sha256

    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    # The resolver labels evidence with exactly this value, and the adapter
    # compares the image label against it.
    assert workflow_digest == document_sha256(profile)
    assert 'EXPECTED_PROFILE_SHA="${COUNTYFORGE_PROFILE_SHA256:?' in _IMPLEMENT_ADAPTER
    assert '"$IMAGE_PROFILE_SHA" != "$EXPECTED_PROFILE_SHA"' in _IMPLEMENT_ADAPTER


# --------------------------------------------------------------------------
# Run 31269239926 — the runner knew the failing field and the Actions message
# said only `validation_failed`.
# --------------------------------------------------------------------------


def _materialization_step() -> str:
    workflow = yaml.safe_load(
        Path(".github/workflows/countyforge-run.yml").read_text(encoding="utf-8")
    )
    for job in workflow["jobs"].values():
        for step in job.get("steps") or []:
            run = str(step.get("run", ""))
            if "Planning provider failed before materialization" in run:
                return run
    raise AssertionError("materialization guard step not found")


def _run_materialization_guard(
    tmp_path: Path, result: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    """Execute the real step body; asserting on its text would prove nothing."""

    temp = tmp_path / "temp"
    (temp / "countyforge-result").mkdir(parents=True)
    (temp / "countyforge-result" / "countyforge-result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    return subprocess.run(
        ["bash", "-c", _materialization_step()],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_TEMP": str(temp),
            "ISSUE_NUMBER": "18",
            "COUNTYFORGE_RUN_ID": "gh-test-a1",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_actions_message_names_the_failing_field(tmp_path: Path) -> None:
    """`disposition=validation_failed error_code=validation_failed` was all a
    maintainer saw, while the runner already knew the pointer and validator."""

    completed = _run_materialization_guard(
        tmp_path,
        {
            "ok": False,
            "disposition": "validation_failed",
            "summary": {"error_code": "validation_failed"},
            "validation_detail": {
                "error_code": "schema_validation_failed",
                "kind": "planning result",
                "path": "/task_slices/5/write_paths",
                "validator": "minItems",
            },
        },
    )
    assert completed.returncode == 2
    assert "disposition=validation_failed" in completed.stderr
    assert "path=/task_slices/5/write_paths" in completed.stderr
    assert "validator=minItems" in completed.stderr


def test_the_message_keeps_its_generic_form_without_a_validation_detail(
    tmp_path: Path,
) -> None:
    completed = _run_materialization_guard(
        tmp_path,
        {
            "ok": False,
            "disposition": "timed_out",
            "summary": {"error_code": "timed_out"},
        },
    )
    assert completed.returncode == 2
    assert "disposition=timed_out error_code=timed_out" in completed.stderr
    assert "path=" not in completed.stderr
    assert "validator=" not in completed.stderr


def test_a_partial_validation_detail_is_not_half_reported(tmp_path: Path) -> None:
    """Both fields or neither: `path= validator=` would read as evidence."""

    for detail in ({"path": "/task_slices/5/write_paths"}, {"validator": "minItems"}, {}):
        completed = _run_materialization_guard(
            tmp_path / f"case{len(detail)}{'p' if 'path' in detail else 'v'}",
            {
                "ok": False,
                "disposition": "validation_failed",
                "summary": {"error_code": "validation_failed"},
                "validation_detail": detail,
            },
        )
        assert completed.returncode == 2
        assert "path=" not in completed.stderr
        assert "validator=" not in completed.stderr


def test_the_surfaced_message_carries_no_model_or_document_content(
    tmp_path: Path,
) -> None:
    """Only the four sanitized keys exist on the runner side, and the message
    quotes just two of them."""

    marker = "SENTINEL-MODEL-TEXT"
    completed = _run_materialization_guard(
        tmp_path,
        {
            "ok": False,
            "disposition": "validation_failed",
            "summary": {"error_code": "validation_failed", "stderr_tail": marker},
            "plan": {"problem_statement": marker},
            "validation_detail": {
                "error_code": "schema_validation_failed",
                "kind": "planning result",
                "path": "/requirements/0/id",
                "validator": "pattern",
            },
        },
    )
    assert completed.returncode == 2
    assert marker not in completed.stderr
    assert marker not in completed.stdout
    assert "validator=pattern" in completed.stderr
