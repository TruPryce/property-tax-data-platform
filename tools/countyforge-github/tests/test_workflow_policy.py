"""Static security policy for the thin GitHub-hosted workflow surface."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

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


def test_all_actions_are_pinned_to_full_commit_shas() -> None:
    for name in COUNTYFORGE_WORKFLOWS:
        workflow = _load(name)
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert PINNED_ACTION.fullmatch(str(step["uses"])) is not None


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
    assert "--tmpfs /workspace/.github/workflows:ro" in adapter
    assert "--tmpfs /workspace/.ai/policies:ro" in adapter
    assert "--tmpfs /workspace/.env:ro" in adapter
    validation = str(jobs["implementation-validation"])
    assert "Provision the no-network command sandbox" in validation
    assert "apt-get install --no-install-recommends --yes bubblewrap" in validation
    assert "Provision pinned OpenSpec validator for offline gates" in validation
    assert 'npm install --prefix "$GITHUB_WORKSPACE/trusted/.ai/tools/openspec"' in validation
    assert "npx --yes @fission-ai/openspec@1.6.0" not in validation
    assert 'candidate_root="$RUNNER_TEMP/implementation-candidate"' in validation
    assert '--workspace "$candidate_root"' in validation
    assert '"$GITHUB_WORKSPACE/trusted" "$candidate_root"' in validation
    assert 'git -C "$candidate_root" rev-parse HEAD' in validation
    assert "validate-implementation-context" in validation
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
    publish = str(jobs["implementation-publish"])
    assert "countyforge-implementation-bundle-" in publish
    assert "Download frozen implementation bundle" in publish
    assert "countyforge-workspace.tar.gz" in publish
    assert "Verify live implementation publication lease" in publish
    assert "steps.verify-publication.outcome == 'success'" in publish
    assert 'final_state="failed"' in publish
    assert 'final_disposition="implementation_validation_failed"' in publish
    assert 'final_disposition="implementation_publication_failed"' in publish


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


def test_claim_failure_recovery_has_no_provider_or_target_access() -> None:
    recovery = _jobs("countyforge-run.yml")["recover-claim-failure"]
    text = str(recovery)
    assert recovery["if"] == "always() && needs.claim.result == 'failure'"
    assert "fail-unclaimed-run" in text
    assert "OPENAI_API_KEY" not in text
    assert "SAKANA_API_KEY" not in text
    assert "path': 'target" not in text


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
    assert "update_comment" not in source
    assert '"mutation": "audit_only"' in source
