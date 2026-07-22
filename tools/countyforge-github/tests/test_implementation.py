"""Free implementation eligibility, packet, and artifact policy fixtures."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from countyforge_github.errors import ControlPlaneError
from countyforge_github.implementation import (
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
    task_plan = {"tasks": [{"task_id": "1.1", "required_checks": ["make check"]}]}
    result = {
        "completed_task_ids": ["1.1"],
        "incomplete_task_ids": [],
        "blocked_task_ids": [],
        "command_evidence": [],
    }
    with pytest.raises(ControlPlaneError, match="command evidence"):
        validate_implementation_tasks(result, task_plan)
    result["command_evidence"] = ["make check"]
    validate_implementation_tasks(result, task_plan)


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


def test_artifact_policy_rejects_result_provenance_mismatch(tmp_path: Path, repo_root: Path) -> None:
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
            "merged_by": {"id": 42, "login": "maintainer"},
        }

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> dict[str, object]:
        return {"status": "ahead", "files": []}

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


class _PublicationGitHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_git_commit(self, repository: str, sha: str) -> dict[str, object]:
        return {"tree": {"sha": "d" * 40}}

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
