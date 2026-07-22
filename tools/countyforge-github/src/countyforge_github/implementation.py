"""Trusted implementation eligibility, packet, policy, and artifact helpers.

The implementation model is deliberately treated as an untrusted producer.  This module
only selects bounded evidence and validates declarations; it never applies a model patch or
performs a GitHub mutation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from countyforge_runner.contracts import (
    JsonObject,
    canonical_bytes,
    file_sha256,
)

from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.redaction import redact_untrusted_text

_CHANGE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TASK = re.compile(r"^- \[([ xX])\] ([0-9]+\.[0-9]+)\s+(.+?)\s*$")
_FORBIDDEN = (
    ".github/workflows/",
    "codeowners",
    ".ai/policies/",
    ".ai/providers/",
    ".env",
    ".git/",
    "infrastructure/",
    "data/",
)


def _source_id(category: str, path: str) -> str:
    return hashlib.sha256(f"{category}:{path}".encode()).hexdigest()[:24]


def _read_bounded(
    root: Path,
    relative: str,
    *,
    category: str = "accepted_openspec",
    selection_reason: str = "accepted OpenSpec change and traceability",
    trust_class: str = "trusted_contract",
    limit: int = 50_000,
) -> JsonObject:
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
        if not resolved.is_relative_to(root_resolved) or not resolved.is_file():
            raise OSError
        raw = resolved.read_bytes()
    except (OSError, RuntimeError):
        raise ControlPlaneError(
            "implementation_context_unavailable", "Implementation context is unavailable."
        ) from None
    content = raw[:limit].decode("utf-8", errors="replace")
    return {
        "source_id": _source_id(category, relative),
        "path": relative,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "category": category,
        "bytes": len(raw),
        "truncated": len(raw) > limit,
        "selection_reason": selection_reason,
        "trust_class": trust_class,
        "content": content,
    }


def _change_issue(metadata: Path) -> int | None:
    for line in metadata.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("issue:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _change_hash(files: Iterable[Path], root: Path) -> str:
    entries: list[JsonObject] = []
    for path in sorted(files):
        relative = str(path.relative_to(root))
        entries.append({"path": relative, "sha256": file_sha256(path)})
    return hashlib.sha256(canonical_bytes({"files": entries})).hexdigest()


def _tasks_from_text(text: str) -> list[JsonObject]:
    tasks: list[JsonObject] = []
    for line in text.splitlines():
        match = _TASK.match(line.strip())
        if match is None:
            continue
        _, task_id, description = match.groups()
        tasks.append(
            {
                "task_id": task_id,
                "description": description[:1024],
                "status": "incomplete",
                "allowed_paths": ["libs", "services", "dags", "docs", "openspec"],
                "required_checks": ["make check"],
                "risk": "normal",
            }
        )
    return tasks


def implementation_change_files(contract_root: Path, change_name: str) -> list[Path]:
    if _CHANGE.fullmatch(change_name) is None:
        raise ControlPlaneError("invalid_openspec_change", "OpenSpec change name is invalid.")
    change_root = (contract_root / "openspec" / "changes" / change_name).resolve()
    root = contract_root.resolve(strict=True)
    if not change_root.is_relative_to(root) or not change_root.is_dir():
        raise ControlPlaneError(
            "openspec_change_not_found", "The approved OpenSpec change is unavailable."
        )
    required = [
        change_root / name for name in (".openspec.yaml", "proposal.md", "design.md", "tasks.md")
    ]
    spec_files = sorted((change_root / "specs").glob("*/spec.md"))
    files = required + spec_files
    if any(not path.is_file() for path in files) or not spec_files:
        raise ControlPlaneError(
            "openspec_change_incomplete", "The approved OpenSpec change is incomplete."
        )
    return files


def implementation_change_hash(contract_root: Path, change_name: str) -> str:
    """Hash the complete accepted OpenSpec change for semantic run identity."""

    return _change_hash(implementation_change_files(contract_root, change_name), contract_root)


def implementation_revision(change_hash: str, base_sha: str) -> int:
    """Derive a stable positive revision from accepted content and immutable base facts."""

    if (
        re.fullmatch(r"[0-9a-f]{64}", change_hash) is None
        or re.fullmatch(r"[0-9a-f]{40}", base_sha) is None
    ):
        raise ControlPlaneError(
            "invalid_implementation_identity", "Implementation revision facts are invalid."
        )
    value = int(hashlib.sha256(f"{change_hash}:{base_sha}".encode()).hexdigest()[:15], 16)
    return (value % 2_000_000_000) + 1


def evaluate_implementation_eligibility(
    *,
    contract_root: Path,
    repository: str,
    issue_number: int,
    change_name: str,
    trusted_base_sha: str,
    planning_pr_merged: bool,
    approval_actor_id: int | None = None,
) -> JsonObject:
    """Return a strict, credential-free eligibility decision from trusted facts."""

    reasons: list[str] = []
    files: list[Path] = []
    change_hash = "0" * 64
    try:
        files = implementation_change_files(contract_root, change_name)
        change_hash = _change_hash(files, contract_root)
        issue = _change_issue(files[0])
        if issue != issue_number:
            reasons.append("issue_traceability_missing")
        tasks = (contract_root / "openspec" / "changes" / change_name / "tasks.md").read_text(
            encoding="utf-8"
        )
        if not _tasks_from_text(tasks):
            reasons.append("tasks_missing")
        if (
            "blocking decision" in tasks.casefold()
            or "implementation_blocked: true" in tasks.casefold()
        ):
            reasons.append("blocking_decision_unresolved")
    except ControlPlaneError as error:
        reasons.append(error.code)
    if not planning_pr_merged:
        reasons.append("planning_pr_not_merged")
    elif approval_actor_id is None:
        reasons.append("approval_actor_missing")
    if not re.fullmatch(r"[0-9a-f]{40}", trusted_base_sha):
        reasons.append("trusted_base_sha_invalid")
    return {
        "contract_version": 1,
        "eligible": not reasons,
        "repository": repository,
        "issue_number": issue_number,
        "change_name": change_name,
        "change_sha256": change_hash,
        "trusted_base_sha": trusted_base_sha,
        "planning_pr_merged": planning_pr_merged,
        "approval_actor_id": approval_actor_id,
        "blocking_reasons": sorted(set(reasons)),
    }


def build_implementation_packet(
    *,
    trigger: JsonObject,
    issue: JsonObject,
    contract_root: Path,
    output_dir: Path,
    run_id: str,
    change_name: str,
    planning_pr_merged: bool,
    approval_actor_id: int | None = None,
    comments: Iterable[JsonObject] = (),
) -> JsonObject:
    """Build an immutable packet, manifest, and task plan under ``output_dir``."""

    repository = trigger.get("repository")
    target = trigger.get("target")
    if not isinstance(repository, dict) or not isinstance(target, dict):
        raise ControlPlaneError(
            "implementation_provenance_mismatch", "Implementation trigger facts are incomplete."
        )
    raw_issue_number = issue.get("number")
    issue_number = int(
        raw_issue_number if raw_issue_number is not None else target.get("number", 0)
    )
    eligibility = evaluate_implementation_eligibility(
        contract_root=contract_root,
        repository=str(repository["full_name"]),
        issue_number=issue_number,
        change_name=change_name,
        trusted_base_sha=str(target["base_sha"]),
        planning_pr_merged=planning_pr_merged,
        approval_actor_id=approval_actor_id,
    )
    trigger_hash = trigger.get("implementation_change_sha256")
    if trigger_hash is not None and trigger_hash != eligibility["change_sha256"]:
        raise ControlPlaneError(
            "implementation_change_hash_mismatch",
            "Implementation trigger does not match the accepted OpenSpec change.",
        )
    if not eligibility["eligible"]:
        raise ControlPlaneError(
            "implementation_ineligible",
            "The accepted OpenSpec change is not implementation-eligible.",
        )
    files = implementation_change_files(contract_root, change_name)
    sources = [_read_bounded(contract_root, str(path.relative_to(contract_root))) for path in files]
    # Keep the implementation packet useful without dumping the repository. These are
    # trusted, versioned policy/architecture documents selected by a fixed allowlist.
    context_candidates = (
        ("AGENTS.md", "repository_guidance"),
        ("tools/AGENTS.md", "repository_guidance"),
        (
            "docs/decisions/0005-mode-aware-runner-kernel-and-immutable-capability-profiles.md",
            "adr",
        ),
        ("docs/decisions/0006-github-native-countyforge-control-plane.md", "adr"),
        ("docs/decisions/0007-issue-to-openspec-planning.md", "adr"),
        ("docs/decisions/0008-isolated-openspec-to-code-implementation.md", "adr"),
        ("docs/engineering/countyforge-runner-kernel.md", "engineering_guidance"),
        ("docs/engineering/countyforge-github-control-plane.md", "engineering_guidance"),
        ("docs/engineering/countyforge-planning-agent.md", "engineering_guidance"),
        ("README.md", "architecture_guidance"),
        ("CONTRIBUTING.md", "workflow_guidance"),
    )
    existing_paths = {str(source["path"]) for source in sources}
    for relative, category in context_candidates:
        if relative in existing_paths:
            continue
        candidate = contract_root / relative
        if candidate.is_file():
            sources.append(
                _read_bounded(
                    contract_root,
                    relative,
                    category=category,
                    selection_reason="fixed implementation context allowlist",
                )
            )
    title, _ = redact_untrusted_text(str(issue.get("title", ""))[:512])
    body, _ = redact_untrusted_text(str(issue.get("body", ""))[:20_000])
    issue_source = {
        "source_id": _source_id("issue", str(issue_number)),
        "path": f"github/issues/{issue_number}",
        "sha256": hashlib.sha256(f"{title}\n{body}".encode()).hexdigest(),
        "category": "originating_issue",
        "bytes": len(f"TITLE (untrusted): {title}\nBODY (untrusted):\n{body}".encode()),
        "truncated": len(str(issue.get("body", ""))) > 20_000,
        "selection_reason": "originating issue evidence",
        "trust_class": "untrusted_evidence",
        "content": f"TITLE (untrusted): {title}\nBODY (untrusted):\n{body}",
    }
    sources.append(issue_source)
    tasks_text = next(
        source["content"] for source in sources if source["path"].endswith("/tasks.md")
    )
    tasks = _tasks_from_text(tasks_text)
    if not tasks:
        raise ControlPlaneError(
            "implementation_tasks_missing", "The accepted change has no incomplete tasks."
        )
    change_sha = str(eligibility["change_sha256"])
    packet: JsonObject = {
        "contract_version": 1,
        "repository": {"id": int(repository["id"]), "full_name": str(repository["full_name"])},
        "issue": {"number": issue_number, "title": title, "body": body},
        "change": {
            "name": change_name,
            "sha256": change_sha,
            "files": [
                source["path"] for source in sources if source["category"] == "accepted_openspec"
            ],
        },
        "trusted_base_sha": str(target["base_sha"]),
        "run_id": run_id,
        "implementation_revision": implementation_revision(
            str(eligibility["change_sha256"]), str(target["base_sha"])
        ),
        "eligibility": eligibility,
        "sources": sources,
        "tasks": tasks,
        "policies": {
            "path_policy": "countyforge-implementation-paths.v1",
            "network": "disabled",
            "command_registry": "countyforge-implementation-commands.v1",
        },
        "non_goals": [
            "automatic merge",
            "automatic deployment",
            "production credentials",
            "arbitrary shell",
            "unrestricted network",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / "countyforge-implementation-packet.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest: JsonObject = {
        "contract_version": 1,
        "repository": str(repository["full_name"]),
        "issue_number": issue_number,
        "change_name": change_name,
        "trusted_base_sha": str(target["base_sha"]),
        "run_id": run_id,
        "implementation_revision": packet["implementation_revision"],
        "packet_sha256": file_sha256(packet_path),
        "sources": [
            {
                key: source[key]
                for key in (
                    "source_id",
                    "path",
                    "sha256",
                    "category",
                    "bytes",
                    "truncated",
                    "selection_reason",
                    "trust_class",
                )
            }
            for source in sources
        ],
        "excluded_candidates": [],
    }
    manifest_path = output_dir / "countyforge-implementation-context-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    task_plan: JsonObject = {
        "contract_version": 1,
        "run_id": run_id,
        "change_name": change_name,
        "tasks": [{**task, "prerequisites": []} for task in tasks],
    }
    task_path = output_dir / "countyforge-implementation-task-plan.json"
    task_path.write_text(json.dumps(task_plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "packet_path": str(packet_path),
        "manifest_path": str(manifest_path),
        "task_plan_path": str(task_path),
        "packet_sha256": file_sha256(packet_path),
        "manifest_sha256": file_sha256(manifest_path),
        "task_plan_sha256": file_sha256(task_path),
        "change_sha256": change_sha,
    }


def validate_implementation_result(
    result: JsonObject,
    *,
    workspace_root: Path | None = None,
    expected_revision: int | None = None,
) -> None:
    """Reject model claims that contain unsafe or undeclared paths."""

    for field in ("files_created", "files_modified", "files_deleted"):
        for raw in result.get(field, []):
            path = str(raw)
            if path.startswith("/") or ".." in Path(path).parts or path.startswith(".git"):
                raise ControlPlaneError(
                    "prohibited_change", "Implementation result declares a prohibited path."
                )
            normalized = path.casefold()
            if any(token in normalized for token in _FORBIDDEN):
                raise ControlPlaneError(
                    "prohibited_change", "Implementation result declares a protected path."
                )
    if result.get("publication_eligibility") == "eligible":
        raise ControlPlaneError(
            "model_cannot_authorize_publication",
            "Trusted validation must determine publication eligibility.",
        )
    if expected_revision is not None and result.get("implementation_revision") != expected_revision:
        raise ControlPlaneError(
            "implementation_revision_mismatch",
            "Implementation result revision does not match trusted packet facts.",
        )
    if result.get("security_sensitive_changes"):
        raise ControlPlaneError(
            "higher_risk_change_not_approved",
            "Security-sensitive implementation changes require an explicit higher-risk approval.",
        )
    if workspace_root is not None and not workspace_root.is_dir():
        raise ControlPlaneError("workspace_unavailable", "Implementation workspace is unavailable.")


def validate_implementation_tasks(result: JsonObject, task_plan: JsonObject) -> None:
    """Reconcile model task claims with the trusted accepted task plan."""

    planned_tasks = {
        str(task["task_id"]): task
        for task in task_plan.get("tasks", [])
        if isinstance(task, dict) and isinstance(task.get("task_id"), str)
    }
    planned = set(planned_tasks)
    completed = {str(value) for value in result.get("completed_task_ids", [])}
    incomplete = {str(value) for value in result.get("incomplete_task_ids", [])}
    blocked = {str(value) for value in result.get("blocked_task_ids", [])}
    if not planned or (completed | incomplete | blocked) - planned:
        raise ControlPlaneError(
            "implementation_task_mismatch",
            "Implementation result contains an undeclared task.",
        )
    if (completed & incomplete) or (completed & blocked) or (incomplete & blocked):
        raise ControlPlaneError(
            "implementation_task_mismatch",
            "Implementation task states overlap.",
        )
    if completed and not result.get("command_evidence"):
        raise ControlPlaneError(
            "implementation_task_evidence_missing",
            "Completed implementation tasks require command evidence.",
        )
    evidence = {
        str(value)
        for field in ("tests_run", "validation_results", "command_evidence")
        for value in result.get(field, [])
    }
    for task_id in completed:
        required = planned_tasks[task_id].get("required_checks", [])
        if any(str(check) not in evidence for check in required):
            raise ControlPlaneError(
                "implementation_task_evidence_missing",
                "A completed implementation task lacks a required check.",
            )


def validate_implementation_artifact(
    result: JsonObject,
    manifest: JsonObject,
    *,
    workspace_root: Path,
    policy_root: Path,
    expected_run_id: str,
    expected_issue_number: int,
    expected_change_name: str,
    expected_base_sha: str,
) -> None:
    """Reconcile the model result with the trusted, post-run workspace manifest."""

    if (
        manifest.get("run_id") != expected_run_id
        or manifest.get("issue_number") != expected_issue_number
        or manifest.get("change_name") != expected_change_name
        or manifest.get("base_sha") != expected_base_sha
    ):
        raise ControlPlaneError(
            "implementation_provenance_mismatch",
            "Implementation artifact provenance does not match the run.",
        )
    validate_implementation_result(result, workspace_root=workspace_root)
    declared = {
        str(path)
        for field in ("files_created", "files_modified", "files_deleted")
        for path in result.get(field, [])
    }
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise ControlPlaneError(
            "workspace_manifest_invalid", "Implementation workspace manifest is invalid."
        )
    manifest_paths = {str(row.get("path")) for row in rows if isinstance(row, dict)}
    if manifest_paths != declared or len(manifest_paths) != len(rows):
        raise ControlPlaneError(
            "implementation_artifact_mismatch",
            "Implementation result and workspace manifest disagree.",
        )
    policy_path = policy_root / ".ai" / "policies" / "countyforge-implementation-paths.v1.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ControlPlaneError(
            "implementation_policy_unavailable", "Implementation path policy is unavailable."
        ) from None
    allowed_roots = tuple(
        str(item).rstrip("/") for item in (policy or {}).get("allowed_write_roots", ())
    )
    total_bytes = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ControlPlaneError(
                "workspace_manifest_invalid", "Implementation workspace manifest is invalid."
            )
        raw_path = str(row.get("path", ""))
        pure = PurePosixPath(raw_path)
        if not raw_path or pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains a prohibited path."
            )
        if allowed_roots and not any(
            raw_path == root or raw_path.startswith(f"{root}/") for root in allowed_roots
        ):
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact is outside the approved path policy."
            )
        candidate = (workspace_root / raw_path).resolve()
        if not candidate.is_relative_to(workspace_root.resolve()):
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact escapes the workspace."
            )
        kind = row.get("kind")
        if kind == "deleted":
            if candidate.exists():
                raise ControlPlaneError(
                    "implementation_artifact_mismatch", "Deleted artifact remains in workspace."
                )
            continue
        if not candidate.is_file() or candidate.is_symlink():
            raise ControlPlaneError(
                "implementation_artifact_mismatch", "Declared workspace file is unavailable."
            )
        raw = candidate.read_bytes()
        try:
            _, redactions = redact_untrusted_text(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise ControlPlaneError(
                "prohibited_change", "Binary implementation artifacts are not permitted."
            ) from None
        if redactions:
            raise ControlPlaneError(
                "secret_detected", "Implementation artifact contains a credential-like literal."
            )
        if len(raw) != row.get("bytes") or hashlib.sha256(raw).hexdigest() != row.get("sha256"):
            raise ControlPlaneError(
                "implementation_artifact_mismatch", "Workspace file checksum mismatch."
            )
        total_bytes += len(raw)
    if total_bytes != manifest.get("total_bytes"):
        raise ControlPlaneError(
            "implementation_artifact_mismatch", "Workspace byte count mismatch."
        )


def implementation_branch(issue_number: int, change_name: str, revision: int) -> str:
    if _CHANGE.fullmatch(change_name) is None or revision < 1:
        raise ControlPlaneError(
            "invalid_implementation_identity", "Implementation branch identity is invalid."
        )
    return f"countyforge/implement/issue-{issue_number}-{change_name}-r{revision}"


def publish_implementation(
    github: GitHubPort,
    *,
    repository: str,
    issue_number: int,
    change_name: str,
    revision: int,
    base_sha: str,
    run_id: str,
    workspace: Path,
    evidence_url: str | None = None,
) -> JsonObject:
    """Publish a trusted validated workspace bundle as a draft implementation PR."""

    branch = implementation_branch(issue_number, change_name, revision)
    base_commit = github.get_git_commit(repository, base_sha)
    base_tree = base_commit.get("tree")
    if not isinstance(base_tree, dict) or not isinstance(base_tree.get("sha"), str):
        raise ControlPlaneError("git_base_tree_unavailable", "Trusted base tree is unavailable.")
    manifest_path = workspace / "countyforge-workspace-manifest.json"
    declared: set[str] | None = None
    deleted: set[str] = set()
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            declared = {
                str(item["path"]) for item in manifest.get("files", []) if isinstance(item, dict)
            }
            deleted = {
                str(item["path"])
                for item in manifest.get("files", [])
                if isinstance(item, dict) and item.get("kind") == "deleted"
            }
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            raise ControlPlaneError(
                "workspace_manifest_invalid", "Implementation workspace manifest is invalid."
            ) from None
    entries: list[JsonObject] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = str(path.relative_to(workspace))
        if relative == "countyforge-workspace-manifest.json":
            continue
        if declared is not None and relative not in declared:
            continue
        if relative.startswith(".") and relative in {".env", ".git"}:
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains protected files."
            )
        if any(token in relative.casefold() for token in _FORBIDDEN):
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains protected paths."
            )
        content = path.read_text(encoding="utf-8")
        blob = github.create_git_blob(repository, content)
        entries.append({"path": relative, "mode": "100644", "type": "blob", "sha": blob})
    for relative in sorted(deleted):
        entries.append({"path": relative, "mode": "100644", "type": "blob", "sha": None})
    if not entries:
        raise ControlPlaneError(
            "empty_implementation_artifact", "No validated implementation files were produced."
        )
    tree_sha = github.create_git_tree(repository, str(base_tree["sha"]), entries)
    commit_sha = github.create_git_commit(
        repository,
        f"CountyForge implementation: {change_name} (issue #{issue_number})",
        tree_sha,
        base_sha,
    )
    ref = f"refs/heads/{branch}"
    try:
        github.create_git_ref(repository, ref, commit_sha)
    except ControlPlaneError as error:
        # Never force-update an existing branch: it may contain human edits or a
        # predecessor run's evidence. A caller must choose a fresh revision branch.
        raise ControlPlaneError(
            "implementation_branch_conflict",
            "The deterministic implementation branch already exists or is unavailable.",
        ) from error
    pulls = github.list_pull_requests(
        repository, head=f"{repository.split('/', 1)[0]}:{branch}", base="main"
    )
    if pulls:
        pr_number = int(pulls[0]["number"])
        github.update_pull_request(
            repository,
            pr_number,
            {
                "title": f"CountyForge implementation: {change_name}",
                "body": _implementation_pr_body(
                    issue_number, change_name, run_id, base_sha, evidence_url
                ),
            },
        )
    else:
        pr = github.create_pull_request(
            repository,
            {
                "title": f"CountyForge implementation: {change_name}",
                "head": branch,
                "base": "main",
                "body": _implementation_pr_body(
                    issue_number, change_name, run_id, base_sha, evidence_url
                ),
                "draft": True,
            },
        )
        pr_number = int(pr["number"])
    return {
        "branch": branch,
        "commit_sha": commit_sha,
        "pr_number": pr_number,
        "run_id": run_id,
        "change_name": change_name,
    }


def _implementation_pr_body(
    issue_number: int, change_name: str, run_id: str, base_sha: str, evidence_url: str | None
) -> str:
    evidence = (
        evidence_url
        if evidence_url and evidence_url.startswith("https://github.com/")
        else "Pending"
    )
    return (
        f"Originating issue: #{issue_number}\n\n"
        f"Accepted OpenSpec change: `{change_name}`\n\n"
        f"CountyForge run: `{run_id}`\n\nBase SHA: `{base_sha[:12]}`\n\n"
        "This draft was published by trusted CountyForge tooling from a validated artifact. "
        "The model had no GitHub write token and this PR requires human review.\n\n"
        f"Evidence: {evidence}"
    )


__all__ = [
    "build_implementation_packet",
    "evaluate_implementation_eligibility",
    "implementation_branch",
    "implementation_change_hash",
    "implementation_revision",
    "implementation_change_files",
    "validate_implementation_artifact",
    "validate_implementation_result",
    "validate_implementation_tasks",
]
