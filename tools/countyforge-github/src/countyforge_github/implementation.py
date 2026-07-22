"""Trusted implementation eligibility, packet, policy, and artifact helpers.

The implementation model is deliberately treated as an untrusted producer.  This module
only selects bounded evidence and validates declarations; it never applies a model patch or
performs a GitHub mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from countyforge_runner.contracts import (
    JsonObject,
    canonical_bytes,
    file_sha256,
    load_json_object,
    validate_document,
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
_HIGHER_RISK = (
    ".github/workflows/",
    "codeowners",
    ".ai/policies/",
    ".ai/providers/",
    "pyproject.toml",
    "uv.lock",
    "migrations/",
    "infrastructure/",
    "authentication",
    "cryptography",
    "secret",
)


def _has_unresolved_blocking_decision(files: Iterable[Path]) -> bool:
    """Detect affirmative blocking markers and non-empty unresolved sections.

    The planning agent is not allowed to turn prose into approval evidence.  Eligibility
    therefore accepts only explicit structured markers (or an explicitly populated
    ``Unresolved decisions``/``Blocking decisions`` section) from the trusted OpenSpec
    files.  A section containing ``None``/``N/A`` is considered resolved; any other
    content remains blocked for human clarification.
    """

    markers = (
        re.compile(
            r"^\s*(?:implementation_blocked|blocking_decisions?)\s*:\s*(?:true|yes|blocked)\b", re.I
        ),
        re.compile(r"^\s*(?:status|decision)\s*:\s*(?:blocked|unresolved)\b", re.I),
    )
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        in_unresolved_section = False
        section_lines: list[str] = []
        for line in lines + ["# __countyforge_end__"]:
            heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
            if heading:
                if in_unresolved_section and _section_has_decision(section_lines):
                    return True
                title = heading.group(1).casefold()
                in_unresolved_section = (
                    "unresolved decision" in title
                    or "blocking decision" in title
                    or title in {"unresolved", "blocked"}
                )
                section_lines = []
                continue
            if any(marker.search(line) for marker in markers):
                return True
            if in_unresolved_section and line.strip():
                section_lines.append(line.strip())
    return False


def _section_has_decision(lines: Iterable[str]) -> bool:
    """Return true when an unresolved-decision section has substantive content."""

    normalized = " ".join(line.strip(" -*") for line in lines).strip().casefold()
    return bool(normalized) and normalized not in {
        "none",
        "none.",
        "n/a",
        "n/a.",
        "not applicable",
        "not applicable.",
        "no unresolved decisions",
        "no unresolved decisions.",
    }


def _validate_accepted_change(contract_root: Path, change_name: str) -> None:
    """Run the trusted OpenSpec validator before implementation eligibility is granted."""

    executable = shutil.which("openspec")
    if executable is None:
        raise ControlPlaneError(
            "openspec_validator_unavailable",
            "The trusted OpenSpec validator is unavailable.",
        )
    try:
        completed = subprocess.run(
            [executable, "validate", "--all", "--strict", "--no-interactive"],
            cwd=contract_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            # Preserve the hosted runner's Node/Python tool paths while passing no
            # provider or workflow environment into eligibility validation.
            env={"PATH": os.environ.get("PATH", "")},
        )
    except (OSError, subprocess.SubprocessError):
        raise ControlPlaneError(
            "openspec_validation_failed", "The accepted OpenSpec change could not be validated."
        ) from None
    if completed.returncode != 0:
        raise ControlPlaneError(
            "openspec_validation_failed", "The accepted OpenSpec change is not valid."
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


def _tasks_from_text(text: str, *, allowed_paths: Iterable[str] | None = None) -> list[JsonObject]:
    task_paths = list(allowed_paths or ("libs", "services", "dags", "docs", "openspec"))
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
                "allowed_paths": task_paths,
                "required_checks": ["repo.check"],
                "risk": "normal",
            }
        )
    return tasks


def _load_implementation_path_policy(policy_root: Path) -> JsonObject:
    policy_path = policy_root / ".ai" / "policies" / "countyforge-implementation-paths.v1.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ControlPlaneError(
            "implementation_policy_unavailable", "Implementation path policy is unavailable."
        ) from None
    if not isinstance(policy, dict) or not policy.get("allowed_write_roots"):
        raise ControlPlaneError(
            "implementation_policy_unavailable", "Implementation path policy is invalid."
        )
    return policy


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
    approval_actor_type: str | None = None,
    planning_pr_number: int | None = None,
    planning_pr_merge_sha: str | None = None,
    approval_actor_login: str | None = None,
    approval_permission: str | None = None,
) -> JsonObject:
    """Return a strict, credential-free eligibility decision from trusted facts."""

    reasons: list[str] = []
    files: list[Path] = []
    change_hash = "0" * 64
    try:
        files = implementation_change_files(contract_root, change_name)
        _validate_accepted_change(contract_root, change_name)
        change_hash = _change_hash(files, contract_root)
        issue = _change_issue(files[0])
        if issue != issue_number:
            reasons.append("issue_traceability_missing")
        tasks = (contract_root / "openspec" / "changes" / change_name / "tasks.md").read_text(
            encoding="utf-8"
        )
        if not _tasks_from_text(tasks):
            reasons.append("tasks_missing")
        if _has_unresolved_blocking_decision(files):
            reasons.append("blocking_decision_unresolved")
    except ControlPlaneError as error:
        reasons.append(error.code)
    if not planning_pr_merged:
        reasons.append("planning_pr_not_merged")
    elif approval_actor_id is None:
        reasons.append("approval_actor_missing")
    elif approval_actor_type != "User":
        reasons.append("approval_actor_not_human")
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
        "approval_actor_type": approval_actor_type,
        "planning_pr_number": planning_pr_number,
        "planning_pr_merge_sha": planning_pr_merge_sha,
        "approval_actor_login": approval_actor_login,
        "approval_permission": approval_permission,
        "blocking_reasons": sorted(set(reasons)),
    }


def resolve_merged_planning_approval(
    github: GitHubPort,
    *,
    repository: str,
    issue_number: int,
    change_name: str,
    trusted_base_sha: str,
) -> JsonObject:
    """Resolve immutable approval evidence before implementation claim/provider use."""

    prefix = f"openspec/changes/{change_name}/"
    candidates: list[int] = []
    for event in github.issue_timeline(repository, issue_number):
        source = event.get("source")
        issue = source.get("issue") if isinstance(source, dict) else None
        if isinstance(issue, dict) and isinstance(issue.get("pull_request"), dict):
            number = issue.get("number")
            if isinstance(number, int) and number not in candidates:
                candidates.append(number)
    for number in candidates:
        pull = github.pull_request(repository, number)
        merged_at = pull.get("merged_at")
        merged_sha = str(pull.get("merge_commit_sha") or "")
        body = str(pull.get("body") or "")
        if not merged_at or not re.fullmatch(r"[0-9a-f]{40}", merged_sha):
            continue
        if change_name not in body or f"#{issue_number}" not in body:
            continue
        comparison = github.compare_commits(repository, merged_sha, trusted_base_sha)
        if comparison.get("status") not in {"identical", "ahead"}:
            continue
        later_files = comparison.get("files", [])
        if isinstance(later_files, list) and any(
            isinstance(item, dict) and str(item.get("filename", "")).startswith(prefix)
            for item in later_files
        ):
            # The accepted planning content changed after its approval merge. Require a
            # fresh planning PR rather than silently implementing a different hash.
            continue
        if comparison.get("status") == "ahead" and not isinstance(later_files, list):
            # GitHub did not provide a bounded changed-file list, so exact content binding
            # cannot be proven safely.
            continue
        if int(comparison.get("total_commits", 0)) > 250:
            # Compare responses are bounded by GitHub; an unbounded history cannot prove
            # that the approved OpenSpec files were untouched.
            continue
        files = github.pull_request_files(repository, number)
        if not any(str(item.get("filename", "")).startswith(prefix) for item in files):
            continue
        merged_by = pull.get("merged_by")
        if (
            not isinstance(merged_by, dict)
            or merged_by.get("type") != "User"
            or not isinstance(merged_by.get("login"), str)
            or not isinstance(merged_by.get("id"), int)
            or int(merged_by["id"]) < 1
        ):
            continue
        permission = github.repository_permission(repository, str(merged_by["login"])).get(
            "permission"
        )
        if permission not in {"admin", "maintain", "write"}:
            continue
        return {
            "eligible": True,
            "planning_pr_number": number,
            "planning_pr_merge_sha": merged_sha,
            "approval_actor_id": int(merged_by["id"]),
            "approval_actor_type": "User",
            "approval_actor_login": str(merged_by["login"]),
            "approval_permission": str(permission),
        }
    return {"eligible": False, "reason": "planning_pr_approval_not_found"}


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
    approval_actor_type: str | None = None,
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
    approval = trigger.get("implementation_approval")
    if not isinstance(approval, dict) or not approval.get("eligible", True):
        # Older local packet fixtures use an explicit planning_pr_merged argument. GitHub
        # dispatched implementation runs must carry the immutable approval envelope.
        if not planning_pr_merged:
            raise ControlPlaneError(
                "implementation_approval_missing",
                "Implementation trigger lacks immutable planning approval evidence.",
            )
        approval = {}
    eligibility = evaluate_implementation_eligibility(
        contract_root=contract_root,
        repository=str(repository["full_name"]),
        issue_number=issue_number,
        change_name=change_name,
        trusted_base_sha=str(target["base_sha"]),
        planning_pr_merged=planning_pr_merged,
        approval_actor_id=approval_actor_id,
        approval_actor_type=(
            str(approval["approval_actor_type"])
            if isinstance(approval, dict) and approval.get("approval_actor_type")
            else approval_actor_type
        ),
        planning_pr_number=(
            int(approval["planning_pr_number"])
            if isinstance(approval, dict) and approval.get("planning_pr_number")
            else None
        ),
        planning_pr_merge_sha=(
            str(approval["planning_pr_merge_sha"])
            if isinstance(approval, dict) and approval.get("planning_pr_merge_sha")
            else None
        ),
        approval_actor_login=(
            str(approval["approval_actor_login"])
            if isinstance(approval, dict) and approval.get("approval_actor_login")
            else None
        ),
        approval_permission=(
            str(approval["approval_permission"])
            if isinstance(approval, dict) and approval.get("approval_permission")
            else None
        ),
    )
    trigger_hash = trigger.get("implementation_change_sha256")
    if trigger_hash is not None and trigger_hash != eligibility["change_sha256"]:
        raise ControlPlaneError(
            "implementation_change_hash_mismatch",
            "Implementation trigger does not match the accepted OpenSpec change.",
        )
    eligibility.update(
        {
            key: approval.get(key)
            for key in (
                "planning_pr_number",
                "planning_pr_merge_sha",
                "approval_actor_login",
                "approval_actor_type",
                "approval_permission",
            )
            if key in approval
        }
    )
    if not eligibility["eligible"]:
        raise ControlPlaneError(
            "implementation_ineligible",
            "The accepted OpenSpec change is not implementation-eligible.",
        )
    validate_document(
        eligibility,
        load_json_object(
            contract_root
            / ".ai"
            / "schemas"
            / "countyforge-implementation-eligibility.schema.json",
            kind="implementation eligibility schema",
        ),
        kind="implementation eligibility",
    )
    files = implementation_change_files(contract_root, change_name)
    sources = [_read_bounded(contract_root, str(path.relative_to(contract_root))) for path in files]
    # Keep the implementation packet useful without dumping the repository. These are
    # trusted, versioned policy/architecture documents selected by a fixed allowlist.
    context_candidates = (
        ("AGENTS.md", "repository_guidance"),
        ("tools/AGENTS.md", "repository_guidance"),
        (
            "docs/decisions/0005-mode-aware-runner-kernel.md",
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
    path_policy = _load_implementation_path_policy(contract_root)
    tasks = _tasks_from_text(
        tasks_text,
        allowed_paths=[str(path) for path in path_policy["allowed_write_roots"]],
    )
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
            # Repository commands are offline; only the model invocation has the
            # selected-provider HTTPS proxy.
            "network": "provider_only",
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

    declaration_sets: dict[str, set[str]] = {}
    for field in ("files_created", "files_modified", "files_deleted"):
        values = [str(value) for value in result.get(field, [])]
        if len(values) != len(set(values)):
            raise ControlPlaneError(
                "implementation_bundle_invalid",
                "Implementation result repeats a declared path.",
            )
        declaration_sets[field] = set(values)
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
    if (
        declaration_sets["files_created"] & declaration_sets["files_modified"]
        or declaration_sets["files_created"] & declaration_sets["files_deleted"]
        or declaration_sets["files_modified"] & declaration_sets["files_deleted"]
    ):
        raise ControlPlaneError(
            "implementation_bundle_invalid",
            "Implementation result overlaps file declarations.",
        )
    bundle = result.get("file_bundle")
    if not isinstance(bundle, list):
        raise ControlPlaneError(
            "implementation_bundle_missing",
            "Implementation result must include a declared file bundle.",
        )
    declared_paths = {
        str(path)
        for field in ("files_created", "files_modified", "files_deleted")
        for path in result.get(field, [])
    }
    bundle_paths: set[str] = set()
    for item in bundle:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("content"), str)
        ):
            raise ControlPlaneError(
                "implementation_bundle_invalid", "Implementation file bundle is invalid."
            )
        path = str(item["path"])
        if path in bundle_paths or path not in declared_paths:
            raise ControlPlaneError(
                "implementation_bundle_invalid",
                "Implementation file bundle paths do not match declarations.",
            )
        bundle_paths.add(path)
    if bundle_paths != declared_paths - {str(path) for path in result.get("files_deleted", [])}:
        raise ControlPlaneError(
            "implementation_bundle_invalid", "Implementation file bundle is incomplete."
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


def validate_implementation_tasks(
    result: JsonObject,
    task_plan: JsonObject,
    *,
    trusted_command_events: Iterable[JsonObject] | None = None,
    changed_paths: Iterable[str] = (),
) -> None:
    """Reconcile task claims with trusted task and command evidence.

    Model-authored prose is never accepted as completion evidence. Every task must be
    accounted for exactly once, and publication validation requires every task to be complete
    with its required checks observed as successful broker events.
    """

    planned_tasks = {
        str(task["task_id"]): task
        for task in task_plan.get("tasks", [])
        if isinstance(task, dict) and isinstance(task.get("task_id"), str)
    }
    planned = set(planned_tasks)
    completed = {str(value) for value in result.get("completed_task_ids", [])}
    incomplete = {str(value) for value in result.get("incomplete_task_ids", [])}
    blocked = {str(value) for value in result.get("blocked_task_ids", [])}
    accounted = completed | incomplete | blocked
    if not planned or accounted - planned or accounted != planned:
        raise ControlPlaneError(
            "implementation_task_mismatch",
            "Implementation result must account for every accepted task exactly once.",
        )
    if (completed & incomplete) or (completed & blocked) or (incomplete & blocked):
        raise ControlPlaneError(
            "implementation_task_mismatch",
            "Implementation task states overlap.",
        )
    if incomplete or blocked:
        raise ControlPlaneError(
            "implementation_tasks_incomplete",
            "All accepted implementation tasks must be complete before publication.",
        )
    events = list(trusted_command_events or ())
    successful_commands = {
        str(event.get("command_id"))
        for event in events
        if event.get("exit_code") == 0 and event.get("truncated") is False
    }
    if completed and not events:
        raise ControlPlaneError(
            "implementation_task_evidence_missing",
            "Completed implementation tasks require trusted command evidence.",
        )
    declared_paths = [str(path) for path in changed_paths]
    allowed_roots = [
        str(path)
        for task_id in completed
        for path in planned_tasks[task_id].get("allowed_paths", [])
    ]
    for changed in declared_paths:
        if not any(
            changed == root or changed.startswith(f"{root.rstrip('/')}/") or fnmatch(changed, root)
            for root in allowed_roots
        ):
            raise ControlPlaneError(
                "implementation_task_path_mismatch",
                "A changed path is outside the accepted task paths.",
            )
    for task_id in completed:
        task = planned_tasks[task_id]
        required = {str(check) for check in task.get("required_checks", [])}
        if not required.issubset(successful_commands):
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
    if (
        result.get("run_id") != expected_run_id
        or result.get("issue_number") != expected_issue_number
        or result.get("openspec_change") != expected_change_name
        or result.get("base_sha") != expected_base_sha
    ):
        raise ControlPlaneError(
            "implementation_provenance_mismatch",
            "Implementation result provenance does not match the run.",
        )
    profile = result.get("profile")
    if not isinstance(profile, dict) or profile.get("id") != "implement.workspace-write.v1":
        raise ControlPlaneError(
            "implementation_provenance_mismatch",
            "Implementation result profile does not match the executable profile.",
        )
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
    policy = _load_implementation_path_policy(policy_root)
    allowed_roots = tuple(
        str(item).rstrip("/") for item in (policy or {}).get("allowed_write_roots", ())
    )
    prohibited_roots = tuple(str(item) for item in (policy or {}).get("prohibited_roots", ()))
    max_files = int((policy or {}).get("max_files", 0))
    max_total_bytes = int((policy or {}).get("max_total_bytes", 0))
    max_file_bytes = int((policy or {}).get("max_file_bytes", 0))
    if (policy or {}).get("symlinks") != "reject":
        raise ControlPlaneError(
            "implementation_policy_unavailable", "Symlink policy is not fail-closed."
        )
    if (policy or {}).get("binary_files") != "reject":
        raise ControlPlaneError(
            "implementation_policy_unavailable", "Binary-file policy is not fail-closed."
        )
    if (policy or {}).get("generated_files") != "allow_declared_only":
        raise ControlPlaneError(
            "implementation_policy_unavailable", "Generated-file policy is not fail-closed."
        )
    if max_files and len(rows) > max_files:
        raise ControlPlaneError("implementation_limits_exceeded", "Too many implementation files.")
    total_bytes = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ControlPlaneError(
                "workspace_manifest_invalid", "Implementation workspace manifest is invalid."
            )
        raw_path = str(row.get("path", ""))
        pure = PurePosixPath(raw_path)
        if row.get("kind") not in {"created", "modified", "deleted"}:
            raise ControlPlaneError(
                "workspace_manifest_invalid", "Implementation artifact kind is invalid."
            )
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
        if any(
            raw_path == pattern
            or raw_path.startswith(f"{pattern}/")
            or fnmatch(raw_path, pattern)
            or fnmatch(pure.name, pattern)
            for pattern in prohibited_roots
        ):
            raise ControlPlaneError(
                "prohibited_change",
                "Implementation artifact matches a prohibited path policy rule.",
            )
        if any(token in raw_path.casefold() for token in _HIGHER_RISK):
            raise ControlPlaneError(
                "higher_risk_change_not_approved",
                "Higher-risk implementation paths require an explicit accepted approval.",
            )
        if raw_path == f"openspec/changes/{expected_change_name}/tasks.md":
            baseline = policy_root / raw_path
            candidate_tasks = workspace_root / raw_path
            if (
                row.get("kind") == "deleted"
                or not baseline.is_file()
                or not candidate_tasks.is_file()
            ):
                raise ControlPlaneError(
                    "openspec_tasks_mutation", "Accepted OpenSpec task files are immutable."
                )
            if baseline.read_bytes() != candidate_tasks.read_bytes():
                raise ControlPlaneError(
                    "openspec_tasks_mutation", "Accepted OpenSpec task files are immutable."
                )
        raw_candidate = workspace_root / raw_path
        if raw_candidate.is_symlink():
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains a symlink."
            )
        candidate = raw_candidate.resolve()
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
        if max_file_bytes and len(raw) > max_file_bytes:
            raise ControlPlaneError(
                "implementation_limits_exceeded", "An implementation file exceeds its size limit."
            )
        if b"\x00" in raw:
            raise ControlPlaneError(
                "prohibited_change", "Binary implementation artifacts are not permitted."
            )
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
    if max_total_bytes and total_bytes > max_total_bytes:
        raise ControlPlaneError(
            "implementation_limits_exceeded", "Implementation output exceeds its byte limit."
        )
    if total_bytes != manifest.get("total_bytes"):
        raise ControlPlaneError(
            "implementation_artifact_mismatch", "Workspace byte count mismatch."
        )


def freeze_implementation_artifact(
    result: JsonObject,
    *,
    workspace_root: Path,
    policy_root: Path,
    output_root: Path,
    expected_run_id: str,
    expected_issue_number: int,
    expected_change_name: str,
    expected_base_sha: str,
) -> JsonObject:
    """Create a minimal declared-file bundle before any artifact upload.

    The model-controlled workspace is inspected with Git's ignored-file view. Only declared,
    policy-approved regular files are copied to ``output_root``; the complete workspace is
    never archived or uploaded.
    """

    validate_implementation_result(result, workspace_root=workspace_root)
    root = workspace_root.resolve(strict=True)
    try:
        lines = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignored",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        raise ControlPlaneError(
            "workspace_manifest_invalid", "The implementation workspace cannot be inspected."
        ) from None
    changed: dict[str, str] = {}
    for line in lines:
        if len(line) < 4:
            continue
        state, raw_path = line[:2], line[3:]
        if raw_path.startswith('"') or " -> " in raw_path or "R" in state or "C" in state:
            raise ControlPlaneError(
                "prohibited_change", "Renamed or copied paths are not permitted."
            )
        if state == "!!":
            raise ControlPlaneError(
                "prohibited_change", "Ignored implementation files cannot enter the artifact."
            )
        kind = (
            "deleted"
            if "D" in state
            else ("created" if "?" in state or "A" in state else "modified")
        )
        changed[raw_path] = kind
    declared = {
        str(path)
        for field in ("files_created", "files_modified", "files_deleted")
        for path in result.get(field, [])
    }
    if set(changed) != declared:
        raise ControlPlaneError(
            "implementation_artifact_mismatch",
            "The complete workspace diff does not match the declared implementation files.",
        )
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[JsonObject] = []
    total_bytes = 0
    for relative in sorted(changed):
        pure = PurePosixPath(relative)
        raw_candidate = root / relative
        if raw_candidate.is_symlink():
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains an unsafe symlink."
            )
        candidate = raw_candidate.resolve()
        if pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts:
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains a prohibited path."
            )
        if not candidate.is_relative_to(root) or candidate.is_symlink():
            raise ControlPlaneError(
                "prohibited_change", "Implementation artifact contains an unsafe path."
            )
        if changed[relative] == "deleted":
            rows.append({"path": relative, "sha256": "0" * 64, "bytes": 0, "kind": "deleted"})
            continue
        if not candidate.is_file():
            raise ControlPlaneError(
                "implementation_artifact_mismatch", "Declared file is unavailable."
            )
        content = candidate.read_bytes()
        if b"\x00" in content:
            raise ControlPlaneError(
                "prohibited_change", "Binary implementation artifacts are not permitted."
            )
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise ControlPlaneError(
                "prohibited_change", "Binary implementation artifacts are not permitted."
            ) from None
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, destination)
        rows.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "kind": changed[relative],
            }
        )
        total_bytes += len(content)
    manifest: JsonObject = {
        "contract_version": 1,
        "run_id": expected_run_id,
        "issue_number": expected_issue_number,
        "change_name": expected_change_name,
        "base_sha": expected_base_sha,
        "files": rows,
        "total_bytes": total_bytes,
    }
    manifest_path = output_root / "countyforge-workspace-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    validate_implementation_artifact(
        result,
        manifest,
        workspace_root=output_root,
        policy_root=policy_root,
        expected_run_id=expected_run_id,
        expected_issue_number=expected_issue_number,
        expected_change_name=expected_change_name,
        expected_base_sha=expected_base_sha,
    )
    return manifest


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
    publication_preflight: Callable[[], JsonObject] | None = None,
    implementation_result: JsonObject | None = None,
    policy_root: Path | None = None,
) -> JsonObject:
    """Publish a trusted validated workspace bundle as a draft implementation PR."""

    if publication_preflight is None:
        raise ControlPlaneError(
            "publication_preflight_required",
            "A live lease preflight is required before implementation publication.",
        )
    # This callback rereads canonical state in the serialized target lane.  It must
    # complete immediately before this function performs any Git data API mutation.
    publication_preflight()
    if implementation_result is None or policy_root is None:
        raise ControlPlaneError(
            "publication_artifact_required",
            "Trusted publication requires the validated implementation artifact.",
        )
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
    if declared is None:
        raise ControlPlaneError(
            "workspace_manifest_invalid", "Implementation workspace manifest is required."
        )
    try:
        manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ControlPlaneError(
            "workspace_manifest_invalid", "Implementation workspace manifest is invalid."
        ) from None
    validate_implementation_artifact(
        implementation_result,
        manifest_document,
        workspace_root=workspace,
        policy_root=policy_root,
        expected_run_id=run_id,
        expected_issue_number=issue_number,
        expected_change_name=change_name,
        expected_base_sha=base_sha,
    )
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
    "freeze_implementation_artifact",
    "implementation_branch",
    "implementation_change_hash",
    "implementation_revision",
    "implementation_change_files",
    "resolve_merged_planning_approval",
    "validate_implementation_artifact",
    "validate_implementation_result",
    "validate_implementation_tasks",
]
