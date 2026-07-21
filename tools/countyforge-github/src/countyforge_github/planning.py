"""Bounded issue-to-OpenSpec planning packet and publication primitives.

This module is deliberately GitHub-API neutral.  It accepts immutable trigger facts and
untrusted issue evidence, and returns typed documents that the trusted workflow can pass to
the CountyForge kernel or materialize in an isolated publication worktree.
"""

# Generated OpenSpec templates intentionally contain long prose lines.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from countyforge_runner.contracts import (
    JsonObject,
    canonical_bytes,
    document_sha256,
    validate_document,
)
from countyforge_runner.errors import KernelError
from countyforge_runner.planning_policy import validate_planning_payload

from countyforge_github.contracts import ControlContracts, load_json_object
from countyforge_github.errors import ControlPlaneError
from countyforge_github.redaction import redact_untrusted_text

_CHANGE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_PATH = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))openspec/changes/[a-z0-9]+(?:-[a-z0-9]+)*(?:/.*)?$"
)
_CLASSIFICATION_RULES = (
    ("source_onboarding", ("onboard", "county", "source", "adapter")),
    ("defect", ("bug", "defect", "fix", "broken", "regression")),
    ("architecture_decision", ("adr", "architecture", "decision", "trade-off")),
    ("feature_work", ("feature", "add", "implement", "support")),
)
_ALLOWED_FILES = {
    ".openspec.yaml",
    "proposal.md",
    "design.md",
    "tasks.md",
    "spec.md",
}
MAX_PLANNING_COMMENTS = 16


def _spec_capability(result: JsonObject) -> str:
    """Return the bounded capability directory shared by all publication paths."""

    capabilities = result.get("affected_capabilities")
    candidate = str(capabilities[0]) if isinstance(capabilities, list) and capabilities else ""
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", candidate):
        return candidate
    return "issue-to-openspec-planning"


@dataclass(frozen=True, slots=True)
class ContextLimits:
    max_files: int = 48
    max_file_bytes: int = 20_000
    max_total_bytes: int = 240_000
    max_issue_bytes: int = 20_000


def _comment_sort_key(comment: JsonObject) -> tuple[int, str, str]:
    """Order GitHub comments newest-first using immutable ID then timestamps."""

    raw_id = comment.get("id", 0)
    try:
        comment_id = int(raw_id)
    except (TypeError, ValueError):
        comment_id = 0
    return (
        comment_id,
        str(comment.get("created_at", "")),
        str(comment.get("updated_at", "")),
    )


def select_planning_comments(
    comments: Iterable[JsonObject], *, trigger_comment_id: int | None = None
) -> list[JsonObject]:
    """Return a stable newest-first window, retaining the triggering comment when present."""

    unique: dict[int, JsonObject] = {}
    no_id: list[JsonObject] = []
    for comment in comments:
        try:
            comment_id = int(comment.get("id", 0))
        except (TypeError, ValueError):
            comment_id = 0
        if comment_id > 0:
            unique[comment_id] = comment
        else:
            no_id.append(comment)
    ordered = sorted([*unique.values(), *no_id], key=_comment_sort_key, reverse=True)
    window = ordered[:MAX_PLANNING_COMMENTS]
    if trigger_comment_id is not None and trigger_comment_id in unique:
        trigger = unique[trigger_comment_id]
        if not any(int(item.get("id", 0)) == trigger_comment_id for item in window):
            window = [*window[: MAX_PLANNING_COMMENTS - 1], trigger]
            window.sort(key=_comment_sort_key, reverse=True)
    return window


def planning_context_fingerprint(
    issue: JsonObject,
    comments: Iterable[JsonObject] = (),
    limits: ContextLimits | None = None,
    *,
    trigger_comment_id: int | None = None,
) -> str:
    """Hash the bounded, redacted issue discussion before execution deduplication."""

    effective = limits or ContextLimits()
    title, _ = redact_untrusted_text(str(issue.get("title", ""))[:512])
    raw_body = str(issue.get("body", ""))
    issue_prefix_bytes = len(f"TITLE (untrusted): {title}\nBODY (untrusted):\n".encode())
    body_limit = max(min(effective.max_issue_bytes, 20_000 - issue_prefix_bytes), 0)
    body = raw_body.encode("utf-8")[:body_limit].decode("utf-8", "ignore")
    body, _ = redact_untrusted_text(body)
    issue_record: JsonObject = {
        "number": int(issue.get("number", 0)),
        "title": title,
        "body": body,
        "labels": sorted(
            str(value.get("name")) if isinstance(value, dict) else str(value)
            for value in issue.get("labels", [])
            if isinstance(value, (str, dict))
            and (isinstance(value, str) or isinstance(value.get("name"), str))
        ),
    }
    comment_records: list[JsonObject] = []
    for comment in select_planning_comments(comments, trigger_comment_id=trigger_comment_id):
        raw_comment = str(comment.get("body", ""))[:4000]
        comment_body, _ = redact_untrusted_text(raw_comment)
        comment_records.append({"id": int(comment.get("id", 0)), "body": comment_body})
    return hashlib.sha256(
        canonical_bytes({"issue": issue_record, "comments": comment_records})
    ).hexdigest()


def classify_issue(title: str, body: str, labels: Iterable[str] = ()) -> str:
    """Classify a structured issue deterministically without treating text as policy."""

    label_text = " ".join(str(label).casefold() for label in labels)
    text = f"{title} {body} {label_text}".casefold()
    for classification, terms in _CLASSIFICATION_RULES:
        if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
            return classification
    raise ControlPlaneError(
        "insufficient_issue_intake",
        "The issue does not contain enough structured information for planning.",
    )


def _source_id(category: str, path: str) -> str:
    return hashlib.sha256(f"{category}:{path}".encode()).hexdigest()[:24]


def _bounded_text(path: Path, limits: ContextLimits) -> tuple[str, bool, int, str]:
    try:
        raw = path.read_bytes()
    except (OSError, UnicodeError):
        raise ControlPlaneError(
            "context_unavailable", "A selected planning context file is unavailable."
        ) from None
    digest = hashlib.sha256(raw).hexdigest()
    truncated = len(raw) > limits.max_file_bytes
    content = raw[: limits.max_file_bytes].decode("utf-8", errors="replace")
    return content, truncated, len(raw), digest


def _select_files(root: Path, limits: ContextLimits) -> tuple[list[JsonObject], list[JsonObject]]:
    """Select only stable, trusted documentation/contracts from the contract root."""

    candidates: list[tuple[str, str, Path]] = []
    fixed = [
        ("agent_guidance", "AGENTS.md", root / "AGENTS.md"),
        ("architecture", "README.md", root / "README.md"),
        ("validation", "CONTRIBUTING.md", root / "CONTRIBUTING.md"),
    ]
    candidates.extend(fixed)
    for pattern, category in (
        ("**/AGENTS.md", "agent_guidance"),
        ("docs/decisions/[0-9][0-9][0-9][0-9]-*.md", "adr"),
        ("docs/engineering/*.md", "architecture"),
        ("docs/sources/*.md", "source_contract"),
        ("openspec/specs/**/*.md", "openspec"),
        ("openspec/changes/*/proposal.md", "openspec"),
        ("openspec/changes/*/design.md", "openspec"),
    ):
        for path in sorted(root.glob(pattern)):
            candidates.append((category, str(path.relative_to(root)), path))
    candidates = list(
        {relative: (category, relative, path) for category, relative, path in candidates}.values()
    )
    selected: list[JsonObject] = []
    excluded: list[JsonObject] = []
    total = 0
    for category, relative, candidate in sorted(candidates, key=lambda item: item[1]):
        if len(selected) >= limits.max_files:
            excluded.append({"path": relative, "reason_code": "file_limit"})
            continue
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve(strict=True)):
                excluded.append({"path": relative, "reason_code": "symlink_escape"})
                continue
            if not resolved.is_file():
                excluded.append({"path": relative, "reason_code": "non_regular"})
                continue
        except (OSError, RuntimeError):
            excluded.append({"path": relative, "reason_code": "outside_root"})
            continue
        content, truncated, raw_bytes, digest = _bounded_text(resolved, limits)
        if total + len(content.encode("utf-8")) > limits.max_total_bytes:
            excluded.append({"path": relative, "reason_code": "byte_limit"})
            continue
        total += len(content.encode("utf-8"))
        selected.append(
            {
                "source_id": _source_id(category, relative),
                "category": category,
                "path": relative,
                "sha256": digest,
                "bytes": raw_bytes,
                "content": content,
                "truncated": truncated,
                "selection_reason": "approved planning context root",
                "untrusted": False,
            }
        )
    return selected, excluded


def build_planning_packet(
    *,
    trigger: JsonObject,
    issue: JsonObject,
    contract_root: Path,
    output_dir: Path,
    run_id: str,
    comments: Iterable[JsonObject] = (),
    limits: ContextLimits | None = None,
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Write a bounded packet and manifest and return their provenance facts."""

    if contracts is None:
        ControlContracts(contract_root)
    limits = limits or ContextLimits()
    repository = trigger.get("repository")
    target = trigger.get("target")
    if not isinstance(repository, dict) or not isinstance(target, dict):
        raise ControlPlaneError(
            "planning_provenance_mismatch", "Planning trigger facts are incomplete."
        )
    raw_title = str(issue.get("title", ""))[:512]
    title, title_redactions = redact_untrusted_text(raw_title)
    raw_body = str(issue.get("body", ""))
    issue_prefix_bytes = len(f"TITLE (untrusted): {title}\nBODY (untrusted):\n".encode())
    body_limit = max(min(limits.max_issue_bytes, 20_000 - issue_prefix_bytes), 0)
    raw_body_bounded = raw_body.encode("utf-8")[:body_limit].decode("utf-8", "ignore")
    body, body_redactions = redact_untrusted_text(raw_body_bounded)
    labels: list[str] = []
    for value in issue.get("labels", []):
        if isinstance(value, str):
            labels.append(value)
        elif isinstance(value, dict) and isinstance(value.get("name"), str):
            labels.append(str(value["name"]))
    classification = classify_issue(title, body, labels)
    issue_content = f"TITLE (untrusted): {title}\nBODY (untrusted):\n{body}"
    issue_content_bytes = len(issue_content.encode())
    trigger_comment = trigger.get("comment")
    trigger_comment_id = (
        int(trigger_comment["id"])
        if isinstance(trigger_comment, dict) and trigger_comment.get("id") is not None
        else None
    )
    comment_records = select_planning_comments(comments, trigger_comment_id=trigger_comment_id)
    computed_context_sha256 = planning_context_fingerprint(
        issue, comment_records, limits, trigger_comment_id=trigger_comment_id
    )
    supplied_context_sha256 = trigger.get("planning_context_sha256")
    if (
        supplied_context_sha256 is not None
        and str(supplied_context_sha256) != computed_context_sha256
    ):
        raise ControlPlaneError(
            "planning_context_mismatch",
            "Planning context changed between intake and packet preparation.",
        )
    bounded_comments: list[str] = []
    comment_redactions = 0
    comment_redaction_counts: list[int] = []
    for comment in comment_records:
        bounded, redactions = redact_untrusted_text(str(comment.get("body", ""))[:4000])
        bounded_comments.append(bounded)
        comment_redactions += redactions
        comment_redaction_counts.append(redactions)
    comment_contents = [f"COMMENT (untrusted):\n{text}" for text in bounded_comments]
    comment_content_bytes = sum(len(content.encode()) for content in comment_contents)
    context_budget = max(limits.max_total_bytes - issue_content_bytes - comment_content_bytes, 1)
    selection_limits = replace(limits, max_total_bytes=context_budget)
    selected, excluded = _select_files(contract_root.resolve(strict=True), selection_limits)
    issue_source: JsonObject = {
        "source_id": _source_id("issue", f"issue-{issue.get('number', 0)}"),
        "category": "issue",
        "path": f"github://issue/{issue.get('number', 0)}",
        "sha256": hashlib.sha256(issue_content.encode()).hexdigest(),
        "bytes": len(issue_content.encode("utf-8")),
        "content": issue_content,
        "truncated": len(raw_body.encode("utf-8")) > len(raw_body_bounded.encode("utf-8")),
        "selection_reason": "originating structured issue",
        "untrusted": True,
        "redacted": title_redactions + body_redactions > 0,
        "redaction_count": title_redactions + body_redactions,
    }
    comment_sources: list[JsonObject] = []
    for comment, _text, comment_content, redactions in zip(
        comment_records, bounded_comments, comment_contents, comment_redaction_counts, strict=True
    ):
        path = f"github://issue/{issue.get('number', 0)}/comment/{comment.get('id', 0)}"
        comment_sources.append(
            {
                "source_id": _source_id("comment", path),
                "category": "comment",
                "path": path,
                "sha256": hashlib.sha256(comment_content.encode()).hexdigest(),
                "bytes": len(comment_content.encode("utf-8")),
                "content": comment_content,
                "truncated": len(str(comment.get("body", ""))) > 4000,
                "selection_reason": "bounded issue discussion",
                "untrusted": True,
                "redacted": redactions > 0,
                "redaction_count": redactions,
            }
        )
    packet: JsonObject = {
        "contract_version": 1,
        "packet_id": hashlib.sha256(f"{run_id}:planning".encode()).hexdigest()[:32],
        "run_id": run_id,
        "repository": {
            "id": int(repository["id"]),
            "full_name": str(repository["full_name"]),
            "target_sha": str(target["head_sha"]),
        },
        "issue": {
            "number": int(issue["number"]),
            "title": title,
            "body": body,
            "classification": classification,
            "untrusted": True,
        },
        "sources": [issue_source, *comment_sources, *selected],
        "selection": {
            "max_files": limits.max_files,
            "max_bytes": limits.max_total_bytes,
            "selected_files": len(selected),
            "excluded_candidates": excluded,
        },
        "planning_context_sha256": computed_context_sha256,
        "redactions": {
            "applied": title_redactions + body_redactions + comment_redactions > 0,
            "count": title_redactions + body_redactions + comment_redactions,
        },
    }
    packet_schema = load_json_object(
        contract_root / ".ai/schemas/countyforge-planning-packet.schema.json",
        kind="planning packet schema",
    )
    validate_document(packet, packet_schema, kind="planning packet")
    packet_bytes = canonical_bytes(packet) + b"\n"
    packet_sha = hashlib.sha256(packet_bytes).hexdigest()
    manifest: JsonObject = {
        "contract_version": 1,
        "run_id": run_id,
        "repository_full_name": str(repository["full_name"]),
        "issue_number": int(issue["number"]),
        "target_sha": str(target["head_sha"]),
        "packet_sha256": packet_sha,
        "planning_context_sha256": packet["planning_context_sha256"],
        "sources": [
            {
                key: source[key]
                for key in (
                    "source_id",
                    "path",
                    "category",
                    "sha256",
                    "bytes",
                    "truncated",
                    "redacted",
                    "redaction_count",
                )
                if key in source
            }
            for source in packet["sources"]
        ],
        "redaction_count": packet["redactions"]["count"],
        "excluded_candidates": [
            {
                "path": str(candidate["path"]),
                "category": "context_candidate",
                "reason_code": str(candidate["reason_code"]),
            }
            for candidate in excluded
        ],
    }
    manifest_schema = load_json_object(
        contract_root / ".ai/schemas/countyforge-planning-context-manifest.schema.json",
        kind="planning manifest schema",
    )
    validate_document(manifest, manifest_schema, kind="planning context manifest")
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / "countyforge-planning-packet.json"
    manifest_path = output_dir / "countyforge-context-manifest.json"
    packet_path.write_bytes(packet_bytes)
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    return {
        "packet_path": str(packet_path),
        "manifest_path": str(manifest_path),
        "packet_sha256": packet_sha,
        "manifest_sha256": document_sha256(manifest),
        "classification": classification,
        "issue_number": int(issue["number"]),
        "run_id": run_id,
    }


def validate_planning_result(
    result: JsonObject, *, contract_root: Path, source_ids: set[str] | None = None
) -> None:
    for field in ("files_to_create", "files_to_modify", "proposed_files"):
        values = result.get(field, [])
        if isinstance(values, list):
            for raw_path in values:
                path = str(raw_path)
                if not _SAFE_PATH.fullmatch(path) or "/" not in path:
                    raise ControlPlaneError(
                        "prohibited_plan_path", "Planning output contains a prohibited path."
                    )
    schema = load_json_object(
        contract_root / ".ai/schemas/countyforge-plan-result.schema.json",
        kind="planning result schema",
    )
    try:
        validate_document(result, schema, kind="planning result")
    except KernelError:
        raise ControlPlaneError(
            "invalid_plan_result", "Planning output does not satisfy its strict contract."
        ) from None
    try:
        validate_planning_payload(result)
    except KernelError:
        raise ControlPlaneError(
            "unsafe_plan_payload", "Planning output contains executable-looking content."
        ) from None
    if not _CHANGE.fullmatch(str(result["proposed_change_name"])):
        raise ControlPlaneError(
            "invalid_plan_result", "The proposed OpenSpec change name is invalid."
        )
    for field in ("files_to_create", "files_to_modify", "proposed_files"):
        for raw_path in result[field]:
            path = str(raw_path)
            if not _SAFE_PATH.fullmatch(path) or "/" not in path:
                raise ControlPlaneError(
                    "prohibited_plan_path", "Planning output contains a prohibited path."
                )
            # A change name may legitimately discuss workflows, policies, or
            # secrets.  Reject only prohibited path segments below that name.
            segments = path.split("/")[3:]
            if any(
                segment.casefold()
                in {
                    "workflow",
                    "workflows",
                    "secret",
                    "secrets",
                    "policy",
                    "policies",
                    "src",
                    "dags",
                    "migrations",
                }
                for segment in segments
            ):
                raise ControlPlaneError(
                    "prohibited_plan_path", "Planning output contains a prohibited path."
                )
    if result["status"] == "planned" and result["blocked_reasons"]:
        raise ControlPlaneError(
            "invalid_plan_result", "A planned result cannot contain blocked reasons."
        )
    serialized = json.dumps(result, sort_keys=True).casefold()
    if any(
        token in serialized
        for token in (
            "-----begin ",
            "openai_api_key",
            "sakana_api_key",
            "bitwarden_token",
            "bws_access_token",
            "authorization: bearer",
        )
    ) or re.search(r"\bakia[0-9a-z]{16}\b", serialized):
        raise ControlPlaneError(
            "secret_in_plan_result", "Planning output contains a prohibited credential value."
        )
    if source_ids is not None:
        for citation in result["evidence_citations"]:
            if citation["source_id"] not in source_ids:
                raise ControlPlaneError(
                    "invalid_plan_citation", "Planning output cites an unknown packet source."
                )


def planning_branch(issue_number: int, change_name: str) -> str:
    if issue_number < 1 or not _CHANGE.fullmatch(change_name):
        raise ControlPlaneError("invalid_planning_identity", "Planning branch identity is invalid.")
    return f"countyforge/plan/issue-{issue_number}-{change_name}"


def _markdown_heading(value: object) -> str:
    """Keep model text on one structural line before using it as a heading."""

    text = re.sub(r"\s+", " ", str(value)).strip()
    return re.sub(r"^(?:#{1,6}|>)+\s*", "", text).strip() or "Unspecified"


def planning_identity(
    *, issue_number: int, target_sha: str, change_name: str, context_sha256: str
) -> str:
    payload = f"1|{issue_number}|{target_sha}|{change_name}|{context_sha256}".encode()
    return hashlib.sha256(payload).hexdigest()


def materialize_plan(
    result: JsonObject,
    *,
    publication_root: Path,
    issue_number: int,
    run_id: str,
    parent_issue: int = 2,
) -> JsonObject:
    """Render a validated plan using trusted templates, never a model patch."""

    validate_planning_result(result, contract_root=publication_root)
    change = str(result["proposed_change_name"])
    change_root = publication_root / "openspec" / "changes" / change
    spec_capability = _spec_capability(result)
    spec_root = change_root / "specs" / spec_capability
    if change_root.exists() and any(change_root.iterdir()):
        raise ControlPlaneError(
            "planning_change_exists",
            "The proposed OpenSpec change already exists in the trusted base.",
        )
    for path in (change_root, spec_root):
        path.mkdir(parents=True, exist_ok=True)
    proposal = f"""## Why\n\n{result["problem_statement"]}\n\n## Outcome\n\n{result["desired_outcome"]}\n\n## Scope\n\n- Originating issue: #{issue_number}\n- CountyForge planning run: `{run_id}`\n- Affected capabilities: {", ".join(result["affected_capabilities"])}\n\n## Constraints\n\n{chr(10).join(f"- {item}" for item in result["security_privacy_considerations"])}\n\n## Non-goals\n\n{chr(10).join(f"- {item}" for item in result["non_goals"])}\n\n## Unresolved decisions\n\n{chr(10).join(f"- {item}" for item in result["unresolved_decisions"]) or "- None recorded."}\n\nThis draft requires human maintainer approval before implementation.\n"""
    citation_lines = "\n".join(
        f"- `{citation['source_id']}`: {citation['excerpt']}"
        for citation in result["evidence_citations"]
    )
    design = f"""## Current-state evidence\n\n{citation_lines or "- See the bound planning packet."}\n\n## Proposed architecture\n\n{result["desired_outcome"]}\n\n## Dependency direction\n\nThe implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.\n\n## Trust boundaries\n\nIssue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.\n\n## Data and contract changes\n\nThe planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.\n\n## Alternatives considered\n\nNo alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.\n\n## Decisions and assumptions\n\n{chr(10).join(f"- {item}" for item in result["assumptions"]) or "- None recorded."}\n\n## Unresolved decisions\n\n{chr(10).join(f"- {item}" for item in result["unresolved_decisions"]) or "- None recorded."}\n\n## Risks and compatibility\n\n{chr(10).join(f"- {item}" for item in result["risks"])}\n{chr(10).join(f"- {item}" for item in result["migration_compatibility_concerns"])}\n\n## Rollout and failure recovery\n\nValidation commands: {", ".join(result["validation_commands"])}. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.\n\n## Testing strategy\n\nRun the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.\n"""
    tasks = (
        "## Tasks\n\n"
        + "\n".join(
            f"- [ ] 1.{index} {task}" for index, task in enumerate(result["task_slices"], 1)
        )
        + "\n"
    )
    spec = "## ADDED Requirements\n\n" + "\n".join(
        f"### Requirement: {_markdown_heading(criterion)}\n\nThe implementation SHALL satisfy this criterion.\n\n#### Scenario: Acceptance\n- **WHEN** the implementation is evaluated\n- **THEN** the criterion is demonstrably satisfied\n"
        for criterion in result["acceptance_criteria"]
    )
    files = {
        ".openspec.yaml": f"schema: spec-driven\ncreated: 2026-07-21\nissue: {issue_number}\nparent: {parent_issue}\ncapability: {spec_capability}\n",
        "proposal.md": proposal,
        "design.md": design,
        "tasks.md": tasks,
        f"specs/{spec_capability}/spec.md": spec,
    }
    for relative, content in files.items():
        destination = change_root / relative
        if destination.name not in _ALLOWED_FILES and destination.name != ".openspec.yaml":
            raise ControlPlaneError(
                "prohibited_plan_path", "Trusted materializer selected an invalid path."
            )
        destination.write_text(content, encoding="utf-8")
    return {
        "change_name": change,
        "issue_number": issue_number,
        "run_id": run_id,
        "files": [f"openspec/changes/{change}/{key}" for key in files],
        "implementation_eligibility": False,
    }


def publish_plan(
    github: Any,
    *,
    repository: str,
    default_branch: str,
    target_sha: str,
    issue_number: int,
    run_id: str,
    result: JsonObject,
    publication_root: Path,
    planning_packet_path: Path,
    context_manifest_path: Path,
    evidence_url: str | None = None,
    already_materialized: bool = False,
) -> JsonObject:
    """Publish a validated plan through GitHub's Git data API.

    The caller supplies a trusted checkout and a GitHub port.  The model result is
    rendered first; only those deterministic files become blobs in the new commit.
    """

    required = (
        "list_pull_requests",
        "create_git_blob",
        "get_git_commit",
        "create_git_tree",
        "create_git_commit",
        "create_git_ref",
        "create_pull_request",
    )
    if not all(hasattr(github, name) for name in required):
        raise ControlPlaneError("github_port_incomplete", "GitHub publication port is incomplete.")
    validate_planning_result(result, contract_root=publication_root)
    issue = int(issue_number)
    if int(result["originating_issue"]) != issue:
        raise ControlPlaneError(
            "planning_provenance_mismatch", "Planning result issue does not match the trigger."
        )
    try:
        packet = load_json_object(planning_packet_path, kind="planning packet")
        manifest = load_json_object(context_manifest_path, kind="planning context manifest")
        validate_document(
            packet,
            load_json_object(
                publication_root / ".ai/schemas/countyforge-planning-packet.schema.json",
                kind="planning packet schema",
            ),
            kind="planning packet",
        )
        validate_document(
            manifest,
            load_json_object(
                publication_root / ".ai/schemas/countyforge-planning-context-manifest.schema.json",
                kind="planning manifest schema",
            ),
            kind="planning context manifest",
        )
    except (OSError, UnicodeError, ValueError, KernelError):
        raise ControlPlaneError(
            "planning_provenance_mismatch", "Planning provenance is invalid."
        ) from None
    packet_sha = hashlib.sha256(planning_packet_path.read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(context_manifest_path.read_bytes()).hexdigest()
    repository_facts = packet.get("repository")
    if (
        not isinstance(repository_facts, dict)
        or packet["run_id"] != run_id
        or packet["issue"]["number"] != issue
        or repository_facts["full_name"] != repository
        or repository_facts["target_sha"] != target_sha
        or manifest["run_id"] != run_id
        or manifest["issue_number"] != issue
        or manifest["repository_full_name"] != repository
        or manifest["target_sha"] != target_sha
        or manifest["packet_sha256"] != packet_sha
        or manifest.get("planning_context_sha256") != packet.get("planning_context_sha256")
    ):
        raise ControlPlaneError(
            "planning_provenance_mismatch",
            "Planning packet does not match the publication trigger.",
        )
    validate_planning_result(
        result,
        contract_root=publication_root,
        source_ids={str(source["source_id"]) for source in packet["sources"]},
    )
    change = str(result["proposed_change_name"])
    base_branch = planning_branch(issue, change)
    branch = base_branch
    owner = repository.split("/", 1)[0]
    existing = github.list_pull_requests(repository, head=f"{owner}:{branch}", base=default_branch)
    bot_marker = f"<!-- countyforge-plan:v1 run={run_id} context={manifest_sha} -->"
    for pull in existing:
        body = str(pull.get("body", ""))
        if f"run={run_id}" in body and f"context={manifest_sha}" in body:
            return {
                "ok": True,
                "action": "deduplicated",
                "branch": branch,
                "commit_sha": str(pull.get("head", {}).get("sha", "")),
                "pr_number": pull.get("number"),
                "pr_url": pull.get("html_url"),
                "change_name": change,
                "run_id": run_id,
                "context_manifest_sha256": manifest_sha,
                "implementation_eligible": False,
            }
    predecessor: JsonObject | None = existing[0] if existing else None
    if predecessor is not None:
        branch = f"{base_branch}-r{manifest_sha[:8]}"
        versioned = github.list_pull_requests(
            repository, head=f"{owner}:{branch}", base=default_branch
        )
        for pull in versioned:
            body = str(pull.get("body", ""))
            if f"context={manifest_sha}" in body:
                return {
                    "ok": True,
                    "action": "deduplicated",
                    "branch": branch,
                    "commit_sha": str(pull.get("head", {}).get("sha", "")),
                    "pr_number": pull.get("number"),
                    "pr_url": pull.get("html_url"),
                    "change_name": change,
                    "run_id": run_id,
                    "context_manifest_sha256": manifest_sha,
                    "implementation_eligible": False,
                }
    if already_materialized:
        files = [
            f"openspec/changes/{change}/.openspec.yaml",
            f"openspec/changes/{change}/proposal.md",
            f"openspec/changes/{change}/design.md",
            f"openspec/changes/{change}/tasks.md",
            f"openspec/changes/{change}/specs/{_spec_capability(result)}/spec.md",
        ]
        if not all((publication_root / relative).is_file() for relative in files):
            raise ControlPlaneError(
                "planning_materialization_missing",
                "Trusted planning files are missing before publication.",
            )
        manifest = {
            "change_name": change,
            "issue_number": issue,
            "run_id": run_id,
            "files": files,
            "implementation_eligibility": False,
        }
    else:
        manifest = materialize_plan(
            result, publication_root=publication_root, issue_number=issue, run_id=run_id
        )
    entries: list[JsonObject] = []
    for relative in manifest["files"]:
        path = publication_root / relative
        entries.append(
            {
                "path": relative,
                "mode": "100644",
                "type": "blob",
                "sha": github.create_git_blob(repository, path.read_text(encoding="utf-8")),
            }
        )
    # Every revision is based on the immutable trusted default-branch SHA.  This
    # prevents a human edit on an earlier draft from becoming an implicit input to
    # a later generated plan.
    parent = target_sha
    commit_document = github.get_git_commit(repository, parent)
    tree_document = commit_document.get("tree")
    if not isinstance(tree_document, dict) or not isinstance(tree_document.get("sha"), str):
        raise ControlPlaneError(
            "github_api_invalid_response", "GitHub commit tree identity is unavailable."
        )
    tree = github.create_git_tree(repository, str(tree_document["sha"]), entries)
    commit = github.create_git_commit(
        repository, f"plan: draft OpenSpec for issue #{issue}", tree, parent
    )
    ref = f"refs/heads/{branch}"
    github.create_git_ref(repository, ref, commit)
    predecessor_link = (
        f"\nPredecessor draft: #{predecessor['number']} (superseded without modifying it).\n"
        if predecessor is not None
        else ""
    )
    evidence = f"\nEvidence: {evidence_url}\n" if evidence_url else ""
    body = (
        f"{bot_marker}\n\n## CountyForge planning draft\n\n"
        f"Originating issue: https://github.com/{repository}/issues/{issue}\n\n"
        f"Proposed OpenSpec change: `{change}`\n\n"
        f"CountyForge run: `{run_id}`\n\n"
        f"Assumptions: {len(result['assumptions'])}; unresolved decisions: {len(result['unresolved_decisions'])}; "
        f"blockers: {len(result['blocked_reasons'])}.\n\n"
        f"Validation commands: {', '.join(result['validation_commands']) or 'none recorded'}\n"
        f"{predecessor_link}{evidence}\n"
        "No production code is included. An authorized maintainer must approve this planning PR before implementation.\n"
    )
    pr = github.create_pull_request(
        repository,
        {
            "title": f"[CountyForge plan] {change}",
            "head": branch,
            "base": default_branch,
            "body": body,
            "draft": True,
        },
    )
    action = "superseded" if predecessor is not None else "created"
    revision = 2 if predecessor is not None else 1
    revision_document: JsonObject = {
        "contract_version": 1,
        "revision": revision,
        "semantic_identity": planning_identity(
            issue_number=issue,
            target_sha=target_sha,
            change_name=change,
            context_sha256=manifest_sha,
        ),
        "context_sha256": manifest_sha,
        "predecessor_run_id": None,
        "predecessor_pr_number": int(predecessor["number"]) if predecessor else None,
        "supersession_reason": "new bounded issue context" if predecessor else "initial plan",
    }
    validate_document(
        revision_document,
        load_json_object(
            publication_root / ".ai/schemas/countyforge-planning-revision.schema.json",
            kind="planning revision schema",
        ),
        kind="planning revision",
    )
    publication_manifest: JsonObject = {
        "contract_version": 1,
        "run_id": run_id,
        "issue_number": issue,
        "change_name": change,
        "branch": branch,
        "target_sha": target_sha,
        "files": manifest["files"]
        if "files" in manifest
        else [
            f"openspec/changes/{change}/.openspec.yaml",
            f"openspec/changes/{change}/proposal.md",
            f"openspec/changes/{change}/design.md",
            f"openspec/changes/{change}/tasks.md",
            f"openspec/changes/{change}/specs/{_spec_capability(result)}/spec.md",
        ],
        "validation": {
            "passed": True,
            "gates": [
                "planning-result-schema",
                "openspec-validate",
                "openspec-doctor",
                "documentation-links",
                "artifact-policy",
            ],
        },
        "implementation_eligibility": False,
    }
    validate_document(
        publication_manifest,
        load_json_object(
            publication_root / ".ai/schemas/countyforge-planning-publication-manifest.schema.json",
            kind="planning publication schema",
        ),
        kind="planning publication manifest",
    )
    return {
        "ok": True,
        "action": action,
        "branch": branch,
        "commit_sha": commit,
        "pr_number": pr.get("number"),
        "pr_url": pr.get("html_url"),
        "change_name": change,
        "run_id": run_id,
        "context_manifest_sha256": manifest_sha,
        "planning_revision": revision,
        "publication_manifest": publication_manifest,
        "revision": revision_document,
        "implementation_eligible": False,
    }
