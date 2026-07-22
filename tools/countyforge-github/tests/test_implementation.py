"""Free implementation eligibility, packet, and artifact policy fixtures."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from countyforge_github.cli import main as github_cli_main
from countyforge_github.errors import ControlPlaneError
from countyforge_github.implementation import (
    _has_unresolved_blocking_decision,
    build_implementation_packet,
    evaluate_implementation_eligibility,
    freeze_implementation_artifact,
    implementation_branch,
    publish_implementation,
    resolve_merged_planning_approval,
    validate_implementation_artifact,
    validate_implementation_result,
    validate_implementation_tasks,
)
from countyforge_runner.contracts import load_json_object, validate_document


def _facts() -> tuple[dict[str, object], dict[str, object], str]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    trigger = {
        "repository": {"id": 987654, "full_name": "TruPryce/property-tax-data-platform"},
        "target": {"type": "issue", "number": 7, "base_sha": sha, "head_sha": sha},
    }
    issue = {"number": 7, "title": "Feature implementation", "body": "Feature acceptance criteria"}
    return trigger, issue, sha


def test_unmerged_plan_is_not_eligible(repo_root: Path) -> None:
    _, _, sha = _facts()
    decision = evaluate_implementation_eligibility(
        contract_root=repo_root,
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="add-isolated-openspec-to-code-agents",
        trusted_base_sha=sha,
        planning_pr_merged=False,
    )
    assert decision["eligible"] is False
    assert "planning_pr_not_merged" in decision["blocking_reasons"]


def test_blocking_decisions_are_checked_across_accepted_change_files(tmp_path: Path) -> None:
    design = tmp_path / "design.md"
    design.write_text("decision: unresolved\n", encoding="utf-8")
    assert _has_unresolved_blocking_decision([design]) is True
    design.write_text("There are no unresolved blocking decisions.\n", encoding="utf-8")
    assert _has_unresolved_blocking_decision([design]) is False
    design.write_text(
        "## Unresolved decisions\n\nDecide whether to migrate first.\n", encoding="utf-8"
    )
    assert _has_unresolved_blocking_decision([design]) is True
    design.write_text("## Unresolved decisions\n\nNone.\n", encoding="utf-8")
    assert _has_unresolved_blocking_decision([design]) is False


def test_packet_is_bounded_and_hash_bound(tmp_path: Path, repo_root: Path) -> None:
    trigger, issue, _ = _facts()
    result = build_implementation_packet(
        trigger=trigger,
        issue=issue,
        contract_root=repo_root,
        output_dir=tmp_path,
        run_id="fixture-implementation",
        change_name="add-isolated-openspec-to-code-agents",
        planning_pr_merged=True,
        approval_actor_id=42,
        approval_actor_type="User",
    )
    packet = load_json_object(Path(str(result["packet_path"])), kind="implementation packet")
    schema = load_json_object(
        repo_root / ".ai/schemas/countyforge-implementation-packet.schema.json", kind="schema"
    )
    validate_document(packet, schema, kind="implementation packet")
    assert packet["eligibility"]["eligible"] is True
    assert packet["implementation_revision"] >= 1
    assert packet["sources"][-1]["trust_class"] == "untrusted_evidence"
    assert (
        hashlib.sha256(Path(str(result["packet_path"])).read_bytes()).hexdigest()
        == result["packet_sha256"]
    )
    assert (
        github_cli_main(
            [
                "--contract-root",
                str(repo_root),
                "validate-implementation-context",
                "--packet",
                str(result["packet_path"]),
                "--manifest",
                str(result["manifest_path"]),
                "--task-plan",
                str(result["task_plan_path"]),
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../outside.py", ".github/workflows/evil.yml", ".env"]
)
def test_model_paths_fail_closed(path: str) -> None:
    result = {
        "files_created": [path],
        "files_modified": [],
        "files_deleted": [],
        "publication_eligibility": "not_evaluated",
    }
    with pytest.raises(ControlPlaneError):
        validate_implementation_result(result)


def test_completed_task_requires_trusted_command_evidence() -> None:
    task_plan = {
        "tasks": [{"task_id": "1.1", "required_checks": ["repo.check"], "allowed_paths": ["docs"]}]
    }
    result = {
        "completed_task_ids": ["1.1"],
        "incomplete_task_ids": [],
        "blocked_task_ids": [],
    }
    with pytest.raises(ControlPlaneError, match="command evidence"):
        validate_implementation_tasks(result, task_plan)
    validate_implementation_tasks(
        result,
        task_plan,
        trusted_command_events=[{"command_id": "repo.check", "exit_code": 0, "truncated": False}],
        changed_paths=["docs/generated.md"],
    )


def test_task_reconciliation_requires_complete_accounting_and_allowed_paths() -> None:
    task_plan = {
        "tasks": [
            {"task_id": "1.1", "required_checks": [], "allowed_paths": ["docs"]},
            {"task_id": "1.2", "required_checks": [], "allowed_paths": ["tests"]},
        ]
    }
    with pytest.raises(ControlPlaneError, match="account for every"):
        validate_implementation_tasks(
            {"completed_task_ids": ["1.1"], "incomplete_task_ids": [], "blocked_task_ids": []},
            task_plan,
        )
    with pytest.raises(ControlPlaneError, match="outside"):
        validate_implementation_tasks(
            {
                "completed_task_ids": ["1.1", "1.2"],
                "incomplete_task_ids": [],
                "blocked_task_ids": [],
            },
            task_plan,
            trusted_command_events=[
                {"command_id": "repo.check", "exit_code": 0, "truncated": False}
            ],
            changed_paths=["services/unsafe.py"],
        )


def test_task_reconciliation_accepts_versioned_tools_and_tests_roots() -> None:
    task_plan = {
        "tasks": [
            {
                "task_id": "1.1",
                "required_checks": [],
                "allowed_paths": ["tools", "tests"],
            }
        ]
    }
    validate_implementation_tasks(
        {
            "completed_task_ids": ["1.1"],
            "incomplete_task_ids": [],
            "blocked_task_ids": [],
        },
        task_plan,
        trusted_command_events=[{"command_id": "repo.check", "exit_code": 0, "truncated": False}],
        changed_paths=["tools/generated.py", "tests/test_generated.py"],
    )


def test_incomplete_or_blocked_tasks_never_publish() -> None:
    task_plan = {"tasks": [{"task_id": "1.1", "required_checks": [], "allowed_paths": ["docs"]}]}
    for field in ("incomplete_task_ids", "blocked_task_ids"):
        with pytest.raises(ControlPlaneError, match="complete"):
            validate_implementation_tasks({"completed_task_ids": [], field: ["1.1"]}, task_plan)


def test_higher_risk_claims_fail_without_explicit_approval() -> None:
    with pytest.raises(ControlPlaneError, match="higher-risk"):
        validate_implementation_result(
            {
                "files_created": [],
                "files_modified": [],
                "files_deleted": [],
                "file_bundle": [],
                "security_sensitive_changes": ["authentication"],
                "publication_eligibility": "not_evaluated",
            }
        )


def test_branch_identity_is_deterministic() -> None:
    assert (
        implementation_branch(7, "safe-change", 2) == "countyforge/implement/issue-7-safe-change-r2"
    )


def _artifact_result(path: str = "docs/generated.md", content: str = "safe\n") -> dict[str, object]:
    return {
        "repository": "TruPryce/property-tax-data-platform",
        "issue_number": 7,
        "openspec_change": "safe-change",
        "run_id": "run",
        "base_sha": "a" * 40,
        "profile": {
            "id": "implement.workspace-write.v1",
            "version": 1,
            "provider": "openai",
            "model_ref": "openai.gpt-5.6",
            "reasoning_effort": "xhigh",
        },
        "files_created": [path],
        "files_modified": [],
        "files_deleted": [],
        "file_bundle": [{"path": path, "content": content}],
        "publication_eligibility": "trusted_validation_required",
        "security_sensitive_changes": [],
    }


def test_freeze_rejects_ignored_workspace_files(tmp_path: Path, repo_root: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.email", "fixture@example.test"], check=True
    )
    subprocess.run(["git", "-C", str(workspace), "config", "user.name", "fixture"], check=True)
    baseline = workspace / "README.md"
    baseline.write_text("base\n", encoding="utf-8")
    (workspace / ".gitignore").write_text(".env\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(workspace), "add", "README.md", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(workspace), "commit", "-qm", "base"], check=True)
    (workspace / ".env").write_text("OPENAI_API_KEY=should-not-upload\n", encoding="utf-8")
    result = _artifact_result()
    with pytest.raises(ControlPlaneError, match="Ignored"):
        freeze_implementation_artifact(
            result,
            workspace_root=workspace,
            policy_root=repo_root,
            output_root=tmp_path / "bundle",
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_artifact_policy_rejects_size_and_prohibited_paths(tmp_path: Path, repo_root: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [{"path": "docs/Makefile", "sha256": "a" * 64, "bytes": 1, "kind": "created"}],
        "total_bytes": 1,
    }
    (workspace / "docs").mkdir()
    (workspace / "docs/Makefile").write_text("x", encoding="utf-8")
    with pytest.raises(ControlPlaneError, match="prohibited"):
        validate_implementation_artifact(
            _artifact_result("docs/Makefile", "x"),
            manifest,
            workspace_root=workspace,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_artifact_policy_rejects_oversized_files(tmp_path: Path, repo_root: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    content = "x" * 500_001
    candidate = workspace / "docs/large.md"
    candidate.write_text(content, encoding="utf-8")
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [
            {
                "path": "docs/large.md",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "bytes": len(content.encode()),
                "kind": "created",
            }
        ],
        "total_bytes": len(content.encode()),
    }
    with pytest.raises(ControlPlaneError, match="exceeds"):
        validate_implementation_artifact(
            _artifact_result("docs/large.md", content),
            manifest,
            workspace_root=workspace,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_trusted_artifact_cli_rejects_custom_valid_schema_invalid_result(
    tmp_path: Path, repo_root: Path
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    content = "safe\n"
    (workspace / "docs/generated.md").write_text(content, encoding="utf-8")
    manifest = tmp_path / "countyforge-workspace-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "run_id": "run",
                "issue_number": 7,
                "change_name": "safe-change",
                "base_sha": "a" * 40,
                "files": [
                    {
                        "path": "docs/generated.md",
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "bytes": len(content.encode()),
                        "kind": "created",
                    }
                ],
                "total_bytes": len(content.encode()),
            }
        ),
        encoding="utf-8",
    )
    result = tmp_path / "implementation-result.json"
    result.write_text(json.dumps(_artifact_result()), encoding="utf-8")
    assert (
        github_cli_main(
            [
                "--contract-root",
                str(repo_root),
                "validate-implementation-artifact",
                "--result",
                str(result),
                "--manifest",
                str(manifest),
                "--workspace",
                str(workspace),
                "--policy-root",
                str(repo_root),
                "--run-id",
                "run",
                "--issue-number",
                "7",
                "--change-name",
                "safe-change",
                "--base-sha",
                "a" * 40,
            ]
        )
        == 2
    )


def test_trusted_context_cli_rejects_schema_invalid_task_plan(
    tmp_path: Path, repo_root: Path
) -> None:
    trigger, issue, _ = _facts()
    result = build_implementation_packet(
        trigger=trigger,
        issue=issue,
        contract_root=repo_root,
        output_dir=tmp_path,
        run_id="fixture-context-invalid",
        change_name="add-isolated-openspec-to-code-agents",
        planning_pr_merged=True,
        approval_actor_id=42,
        approval_actor_type="User",
    )
    task_path = Path(str(result["task_plan_path"]))
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["unexpected"] = True
    task_path.write_text(json.dumps(task), encoding="utf-8")
    assert (
        github_cli_main(
            [
                "--contract-root",
                str(repo_root),
                "validate-implementation-context",
                "--packet",
                str(result["packet_path"]),
                "--manifest",
                str(result["manifest_path"]),
                "--task-plan",
                str(task_path),
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    "relative",
    [
        "docs/source.csv",
        "docs/private.pem",
        "pyproject.toml",
        "uv.lock",
        "openspec/specs/unsafe/spec.md",
        "openspec/changes/other-change/tasks.md",
        "openspec/changes/safe-change/proposal.md",
    ],
)
def test_artifact_policy_enforces_versioned_prohibited_globs(
    relative: str, tmp_path: Path, repo_root: Path
) -> None:
    workspace = tmp_path / "workspace"
    candidate = workspace / relative
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("unsafe\n", encoding="utf-8")
    content = candidate.read_text(encoding="utf-8")
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [
            {
                "path": relative,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "bytes": len(content.encode()),
                "kind": "created",
            }
        ],
        "total_bytes": len(content.encode()),
    }
    with pytest.raises(ControlPlaneError, match="outside|prohibited"):
        validate_implementation_artifact(
            _artifact_result(relative, content),
            manifest,
            workspace_root=workspace,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_artifact_policy_rejects_utf8_binary_content(tmp_path: Path, repo_root: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    candidate = workspace / "docs/generated.md"
    candidate.write_bytes(b"text\x00still-binary\n")
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [
            {
                "path": "docs/generated.md",
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "bytes": candidate.stat().st_size,
                "kind": "created",
            }
        ],
        "total_bytes": candidate.stat().st_size,
    }
    result = _artifact_result("docs/generated.md", "text\x00still-binary\n")
    with pytest.raises(ControlPlaneError, match="Binary"):
        validate_implementation_artifact(
            result,
            manifest,
            workspace_root=workspace,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_artifact_policy_rejects_symlink_escape(tmp_path: Path, repo_root: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("not an implementation artifact\n", encoding="utf-8")
    (workspace / "docs/link.md").symlink_to(outside)
    content = outside.read_text(encoding="utf-8")
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [
            {
                "path": "docs/link.md",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "bytes": len(content.encode()),
                "kind": "created",
            }
        ],
        "total_bytes": len(content.encode()),
    }
    with pytest.raises(ControlPlaneError, match="symlink"):
        validate_implementation_artifact(
            _artifact_result("docs/link.md", content),
            manifest,
            workspace_root=workspace,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_artifact_policy_rejects_result_provenance_mismatch(
    tmp_path: Path, repo_root: Path
) -> None:
    content = "safe\n"
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/generated.md").write_text(content, encoding="utf-8")
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [
            {
                "path": "docs/generated.md",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "bytes": len(content.encode()),
                "kind": "created",
            }
        ],
        "total_bytes": len(content.encode()),
    }
    result = _artifact_result()
    result["run_id"] = "different-run"
    with pytest.raises(ControlPlaneError, match="provenance"):
        validate_implementation_artifact(
            result,
            manifest,
            workspace_root=tmp_path,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name="safe-change",
            expected_base_sha="a" * 40,
        )


def test_artifact_policy_rejects_accepted_task_checkbox_mutation(
    tmp_path: Path, repo_root: Path
) -> None:
    change = "add-isolated-openspec-to-code-agents"
    relative = f"openspec/changes/{change}/tasks.md"
    workspace = tmp_path / "workspace"
    (workspace / f"openspec/changes/{change}").mkdir(parents=True)
    baseline = repo_root / relative
    candidate = workspace / relative
    candidate.write_text(
        baseline.read_text(encoding="utf-8").replace("[x]", "[ ]", 1), encoding="utf-8"
    )
    content = candidate.read_text(encoding="utf-8")
    result = _artifact_result(relative, content)
    result["openspec_change"] = change
    manifest = {
        "run_id": "run",
        "issue_number": 7,
        "change_name": change,
        "base_sha": "a" * 40,
        "files": [
            {
                "path": relative,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "bytes": len(content.encode()),
                "kind": "modified",
            }
        ],
        "total_bytes": len(content.encode()),
    }
    with pytest.raises(ControlPlaneError, match="task files are immutable"):
        validate_implementation_artifact(
            result,
            manifest,
            workspace_root=workspace,
            policy_root=repo_root,
            expected_run_id="run",
            expected_issue_number=7,
            expected_change_name=change,
            expected_base_sha="a" * 40,
        )


class _ApprovalGitHub:
    def issue_timeline(self, repository: str, issue_number: int) -> list[dict[str, object]]:
        return [{"source": {"issue": {"number": 123, "pull_request": {"url": "x"}}}}]

    def pull_request(self, repository: str, number: int) -> dict[str, object]:
        return {
            "merged_at": "2026-07-22T00:00:00Z",
            "merge_commit_sha": "b" * 40,
            "body": "Originating issue #7; accepted change safe-change",
            "merged_by": {"id": 42, "login": "maintainer", "type": "User"},
        }

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> dict[str, object]:
        return {"status": "identical", "files": [], "total_commits": 0}

    def pull_request_files(self, repository: str, number: int) -> list[dict[str, object]]:
        return [{"filename": "openspec/changes/safe-change/proposal.md"}]

    def repository_permission(self, repository: str, actor: str) -> dict[str, object]:
        return {"permission": "maintain"}


def test_merged_planning_approval_is_bound_to_human_and_change() -> None:
    approval = resolve_merged_planning_approval(
        _ApprovalGitHub(),
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="safe-change",
        trusted_base_sha="c" * 40,
    )
    assert approval["eligible"] is True
    assert approval["approval_actor_id"] == 42


def test_bot_merged_planning_approval_is_refused() -> None:
    class BotApprovalGitHub(_ApprovalGitHub):
        def pull_request(self, repository: str, number: int) -> dict[str, object]:
            pull = super().pull_request(repository, number)
            pull["merged_by"] = {"id": 42, "login": "automation", "type": "Bot"}
            return pull

    approval = resolve_merged_planning_approval(
        BotApprovalGitHub(),
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="safe-change",
        trusted_base_sha="c" * 40,
    )
    assert approval["eligible"] is False


def test_incomplete_compare_file_evidence_is_refused() -> None:
    class IncompleteCompareGitHub(_ApprovalGitHub):
        def compare_commits(
            self, repository: str, base_sha: str, head_sha: str
        ) -> dict[str, object]:
            return {"status": "ahead", "files": [], "total_commits": 1}

    approval = resolve_merged_planning_approval(
        IncompleteCompareGitHub(),
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="safe-change",
        trusted_base_sha="c" * 40,
    )
    assert approval["eligible"] is False


def test_malformed_compare_metadata_is_refused() -> None:
    class MalformedCompareGitHub(_ApprovalGitHub):
        def compare_commits(
            self, repository: str, base_sha: str, head_sha: str
        ) -> dict[str, object]:
            return {"status": "ahead", "files": [], "total_commits": "unknown"}

    approval = resolve_merged_planning_approval(
        MalformedCompareGitHub(),
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="safe-change",
        trusted_base_sha="c" * 40,
    )
    assert approval["eligible"] is False


class _PublicationGitHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_git_commit(self, repository: str, sha: str) -> dict[str, object]:
        return {"tree": {"sha": "d" * 40}}

    def get_git_ref(self, repository: str, ref: str) -> dict[str, object] | None:
        return None

    def create_git_blob(self, repository: str, content: str) -> str:
        self.calls.append("blob")
        return "e" * 40

    def create_git_tree(
        self, repository: str, base_sha: str, entries: list[dict[str, object]]
    ) -> str:
        self.calls.append("tree")
        return "f" * 40

    def create_git_commit(
        self, repository: str, message: str, tree_sha: str, parent_sha: str
    ) -> str:
        self.calls.append("commit")
        return "1" * 40

    def create_git_ref(self, repository: str, ref: str, sha: str) -> None:
        self.calls.append("ref")

    def list_pull_requests(
        self, repository: str, *, head: str, base: str
    ) -> list[dict[str, object]]:
        return []

    def create_pull_request(self, repository: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append("pr")
        return {"number": 9}


def test_publication_uses_validated_manifest_and_draft_only(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/generated.md").write_text("safe\n", encoding="utf-8")
    content = "safe\n"
    (tmp_path / "countyforge-workspace-manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "issue_number": 7,
                "change_name": "safe-change",
                "base_sha": "a" * 40,
                "files": [
                    {
                        "path": "docs/generated.md",
                        "kind": "created",
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "bytes": len(content.encode()),
                    }
                ],
                "total_bytes": len(content.encode()),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ControlPlaneError, match="preflight"):
        publish_implementation(
            _PublicationGitHub(),
            repository="TruPryce/property-tax-data-platform",
            issue_number=7,
            change_name="safe-change",
            revision=1,
            base_sha="a" * 40,
            run_id="run",
            workspace=tmp_path,
        )
    preflight_calls: list[str] = []
    result = publish_implementation(
        _PublicationGitHub(),
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="safe-change",
        revision=1,
        base_sha="a" * 40,
        run_id="run",
        workspace=tmp_path,
        publication_preflight=lambda: preflight_calls.append("preflight") or {},
        implementation_result=_artifact_result("docs/generated.md", content),
        policy_root=Path.cwd(),
    )
    assert result["pr_number"] == 9
    assert preflight_calls == ["preflight"]


def test_publication_reuses_matching_existing_branch_and_pr(tmp_path: Path) -> None:
    content = "safe\n"
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/generated.md").write_text(content, encoding="utf-8")
    manifest = {
        "contract_version": 1,
        "run_id": "run",
        "issue_number": 7,
        "change_name": "safe-change",
        "base_sha": "a" * 40,
        "files": [
            {
                "path": "docs/generated.md",
                "kind": "created",
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
                "bytes": len(content),
            }
        ],
        "total_bytes": len(content),
    }
    manifest_path = tmp_path / "countyforge-workspace-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    class MatchingGitHub(_PublicationGitHub):
        def get_git_ref(self, repository: str, ref: str) -> dict[str, object] | None:
            return {"object": {"sha": "1" * 40}}

        def get_git_commit(self, repository: str, sha: str) -> dict[str, object]:
            if sha == "a" * 40:
                return {"tree": {"sha": "d" * 40}}
            return {
                "message": (
                    "CountyForge implementation: safe-change (issue #7; run run; "
                    f"bundle {manifest_sha[:12]})"
                ),
                "parents": [{"sha": "a" * 40}],
            }

        def list_pull_requests(
            self, repository: str, *, head: str, base: str
        ) -> list[dict[str, object]]:
            return [
                {
                    "number": 9,
                    "body": (
                        "Accepted OpenSpec change: `safe-change`\n"
                        "CountyForge run: `run`\n"
                        "Base SHA: `aaaaaaaaaaaa`"
                    ),
                }
            ]

    result = publish_implementation(
        MatchingGitHub(),
        repository="TruPryce/property-tax-data-platform",
        issue_number=7,
        change_name="safe-change",
        revision=1,
        base_sha="a" * 40,
        run_id="run",
        workspace=tmp_path,
        publication_preflight=lambda: {},
        implementation_result=_artifact_result("docs/generated.md", content),
        policy_root=Path.cwd(),
    )
    assert result["pr_number"] == 9
    assert result["commit_sha"] == "1" * 40


def test_publication_refuses_divergent_existing_branch(tmp_path: Path) -> None:
    class DivergentGitHub(_PublicationGitHub):
        def get_git_ref(self, repository: str, ref: str) -> dict[str, object] | None:
            return {"object": {"sha": "1" * 40}}

        def get_git_commit(self, repository: str, sha: str) -> dict[str, object]:
            return {"message": "human edit", "parents": [{"sha": "b" * 40}]}

    with pytest.raises(ControlPlaneError, match="branch diverges"):
        publish_implementation(
            DivergentGitHub(),
            repository="TruPryce/property-tax-data-platform",
            issue_number=7,
            change_name="safe-change",
            revision=1,
            base_sha="a" * 40,
            run_id="run",
            workspace=tmp_path,
            publication_preflight=lambda: {},
            implementation_result=_artifact_result(),
            policy_root=Path.cwd(),
        )
