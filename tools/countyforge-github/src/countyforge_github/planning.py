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
import os
import re
from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
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
from countyforge_github.decision_input import (
    MAX_MARKED_COMMENT_BYTES,
    assert_unedited_since_trigger,
    collect_decision_input,
    decision_marker,
)
from countyforge_github.errors import ControlPlaneError
from countyforge_github.freshness import resolve_default_branch
from countyforge_github.implementation_readiness import (
    assert_implementation_readable,
    implementation_check_ids,
)
from countyforge_github.planning_context import (
    UNVERIFIABLE_DISPOSITION,
    assert_base_context_unmoved,
    trusted_context_digest,
)
from countyforge_github.planning_scope import resolve_planning_scope
from countyforge_github.planning_semantics import (
    declared_capabilities,
    folded_outcome_detail,
    validate_planning_semantics,
)
from countyforge_github.redaction import redact_untrusted_text
from countyforge_github.results import PUBLICATION_STAGES

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
_IMPLEMENTATION_TASK_PATHS = (
    "libs",
    "services",
    "dags",
    "docs",
    "tools",
    "tests",
    "README.md",
    "CONTRIBUTING.md",
)
_IMPLEMENTATION_TASK_CHECK = "repo.check"
MAX_PLANNING_COMMENTS = 16
DEFAULT_TRUSTED_BOT_ID = 41898282
_TRUSTED_COUNTYFORGE_MARKERS = (
    "<!-- countyforge-status:v1:",
    "<!-- countyforge-feedback:v1 -->",
)


def _spec_capability(result: JsonObject) -> str:
    """Return the affected capability, or refuse to guess one.

    PR #46 materialized `specs/issue-to-openspec-planning/spec.md` for a change
    to `collin-cad-source-contract`, because an unusable value fell through to
    the planner's own capability.  A change filed against the wrong capability
    is worse than no change: it reads as a decision about the planner.
    """

    capabilities = result.get("affected_capabilities")
    if not isinstance(capabilities, list) or len(capabilities) != 1:
        raise ControlPlaneError(
            "planning_semantic_validation_failed",
            "The planning result must name exactly one affected capability.",
            {"reason": "affected_capability_ambiguous", "count": len(capabilities or [])},
        )
    entry = capabilities[0]
    candidate = str(entry.get("name", "")) if isinstance(entry, dict) else ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", candidate):
        raise ControlPlaneError(
            "planning_semantic_validation_failed",
            "The planning result names no usable affected capability.",
            {"reason": "affected_capability_malformed"},
        )
    return candidate


def _capability_change_type(result: JsonObject) -> str:
    capabilities = result.get("affected_capabilities")
    entry = capabilities[0] if isinstance(capabilities, list) and capabilities else {}
    return str(entry.get("change_type", "MODIFIED")) if isinstance(entry, dict) else "MODIFIED"


def _decision_lines(result: JsonObject) -> str:
    """Render decisions with their status, so a draft never reads as accepted."""

    decisions = [
        entry for entry in result.get("planning_decisions") or [] if isinstance(entry, dict)
    ]
    if not decisions:
        return "- None recorded."
    return "\n".join(
        f"- **{entry.get('decision_id', '?')}** ({entry.get('status', 'proposed')}, "
        f"requires human merge): {str(entry.get('decision_text', '')).strip()}"
        for entry in sorted(decisions, key=lambda item: str(item.get("decision_id", "")))
    )


def _boundary_lines(result: JsonObject) -> str:
    """Render cross-issue boundaries so the limits travel with the change."""

    dependencies = [
        entry for entry in result.get("cross_issue_dependencies") or [] if isinstance(entry, dict)
    ]
    if not dependencies:
        return "- None recorded."
    lines: list[str] = []
    for entry in sorted(dependencies, key=lambda item: int(item.get("issue_number", 0))):
        boundary = ", ".join(str(item) for item in entry.get("boundary") or [])
        lines.append(
            f"- #{entry.get('issue_number')} ({entry.get('relationship', 'related_to')}): "
            f"out of scope here and owned there: {boundary}"
        )
    return "\n".join(lines)


def _render_requirement(requirement: JsonObject) -> str:
    """Render the authored normative rule and its observable scenarios."""

    lines = [
        f"### Requirement: {_markdown_heading(str(requirement.get('title', '')))}",
        "",
        str(requirement.get("normative_rule", "")).strip(),
        "",
    ]
    for scenario in requirement.get("scenarios") or []:
        if not isinstance(scenario, dict):
            continue
        lines.append(f"#### Scenario: {_markdown_heading(str(scenario.get('name', '')))}")
        for given in scenario.get("given") or []:
            lines.append(f"- **GIVEN** {str(given).strip()}")
        lines.append(f"- **WHEN** {str(scenario.get('when', '')).strip()}")
        for then in scenario.get("then") or []:
            lines.append(f"- **THEN** {str(then).strip()}")
        lines.append("")
    source_ids = ", ".join(str(item) for item in requirement.get("source_ids") or [])
    if source_ids:
        lines.append(f"[source_ids: {source_ids}]")
        lines.append("")
    return "\n".join(lines)


def _render_task(task: JsonObject) -> str:
    """Render declared scope and ordering verbatim; infer nothing."""

    task_id = str(task.get("task_id", ""))
    paths = ",".join(str(item) for item in task.get("write_paths") or [])
    checks = ",".join(str(item) for item in task.get("validation_checks") or [])
    prerequisites = ",".join(str(item) for item in task.get("prerequisites") or []) or "-"
    title = str(task.get("title", "")).replace(chr(10), " ").replace(chr(13), " ")
    description = str(task.get("description", "")).replace(chr(10), " ").replace(chr(13), " ")
    source_ids = ", ".join(str(item) for item in task.get("source_ids") or [])
    citation = f" [source_ids: {source_ids}]" if source_ids else ""
    return (
        f"<!-- countyforge-task: {task_id} paths={paths} checks={checks} "
        f"risk={task.get('risk', 'normal')} prerequisites={prerequisites} -->\n"
        f"- [ ] {task_id} {title} — {description}{citation}"[:2048]
    )


@dataclass(frozen=True, slots=True)
class ContextLimits:
    max_files: int = 48
    max_file_bytes: int = 20_000
    #: Hard fail-safe.  Retained; nothing may exceed it.
    max_total_bytes: int = 240_000
    #: What repository context selection actually aims at.  Run 30836072011 sent
    #: a 262,974-byte packet to `fugu-ultra` at `xhigh`, and the provider
    #: accepted the turn and emitted nothing but `thread.started` and
    #: `turn.started` before the then-current 1,800-second deadline killed it.
    #: A planner does
    #: not need a quarter of a megabyte of repository prose to turn four explicit
    #: decisions into a structured delta, so selection stops here and the ceiling
    #: stays a fail-safe rather than a target.
    operational_target_bytes: int = 160_000
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
    comments: Iterable[JsonObject],
    *,
    trigger_comment_id: int | None = None,
    comment_id_upper_bound: int | None = None,
    trusted_bot_id: int | None = DEFAULT_TRUSTED_BOT_ID,
) -> list[JsonObject]:
    """Return a stable bounded window at or before an optional immutable comment boundary."""

    unique: dict[int, JsonObject] = {}
    no_id: list[JsonObject] = []
    for comment in comments:
        if _is_trusted_countyforge_comment(comment, trusted_bot_id):
            continue
        try:
            comment_id = int(comment.get("id", 0))
        except (TypeError, ValueError):
            comment_id = 0
        if comment_id > 0:
            if comment_id_upper_bound is not None and comment_id > comment_id_upper_bound:
                continue
            unique[comment_id] = comment
        elif comment_id_upper_bound is None:
            no_id.append(comment)
    ordered = sorted([*unique.values(), *no_id], key=_comment_sort_key, reverse=True)
    window = ordered[:MAX_PLANNING_COMMENTS]
    if trigger_comment_id is not None and trigger_comment_id in unique:
        trigger = unique[trigger_comment_id]
        if not any(int(item.get("id", 0)) == trigger_comment_id for item in window):
            window = [*window[: MAX_PLANNING_COMMENTS - 1], trigger]
            window.sort(key=_comment_sort_key, reverse=True)
    return window


def _is_trusted_countyforge_comment(comment: JsonObject, trusted_bot_id: int | None) -> bool:
    """Exclude only bot-owned CountyForge output; user-authored marker text stays evidence."""

    if trusted_bot_id is None:
        return False
    user = comment.get("user")
    if not isinstance(user, dict):
        return False
    try:
        author_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        return False
    if author_id != trusted_bot_id or str(user.get("type", "")) != "Bot":
        return False
    body = str(comment.get("body", ""))
    return any(marker in body for marker in _TRUSTED_COUNTYFORGE_MARKERS)


def planning_context_fingerprint(
    issue: JsonObject,
    comments: Iterable[JsonObject] = (),
    limits: ContextLimits | None = None,
    *,
    trigger_comment_id: int | None = None,
    comment_id_upper_bound: int | None = None,
    trusted_bot_id: int | None = DEFAULT_TRUSTED_BOT_ID,
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
    for comment in select_planning_comments(
        comments,
        trigger_comment_id=trigger_comment_id,
        comment_id_upper_bound=comment_id_upper_bound,
        trusted_bot_id=trusted_bot_id,
    ):
        raw_body = str(comment.get("body", ""))
        # A marked decision part is bounded by its own contract and is carried
        # whole. Clipping one silently is what made a complete D1-D4 package
        # read as incomplete on issue #18; an oversized part is excluded with a
        # recorded reason instead, inside `collect_decision_input`.
        marked = decision_marker(raw_body) is not None
        limit = MAX_MARKED_COMMENT_BYTES if marked else 4000
        comment_body, _ = redact_untrusted_text(raw_body[:limit])
        comment_records.append(
            {
                "id": int(comment.get("id", 0)),
                "body": comment_body,
                "decision_part": marked,
            }
        )
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


_CATEGORY_RANK = {
    "openspec": 0,
    "source_contract": 1,
    "agent_guidance": 2,
    "architecture": 3,
    "adr": 4,
    "validation": 5,
}


def _context_priority(category: str, relative: str, relevance: Sequence[str]) -> tuple[int, int]:
    """Lower sorts first: what this issue is about, before general background.

    `relevance` is derived from the issue itself, so the ordering is a pure
    function of trusted inputs rather than of the filesystem's alphabet.
    """

    lowered = relative.casefold()
    matched = 0 if any(term and term in lowered for term in relevance) else 1
    return (matched, _CATEGORY_RANK.get(category, 6))


def _crosses_nested_repository_boundary(root: Path, candidate: Path) -> bool:
    """Return whether a candidate belongs to a child Git repository."""

    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    current = root
    for component in relative.parts[:-1]:
        current /= component
        if (current / ".git").exists():
            return True
    return False


def _select_files(
    root: Path, limits: ContextLimits, relevance: Sequence[str] = ()
) -> tuple[list[JsonObject], list[JsonObject]]:
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
    # Alphabetical order filled the packet with whatever sorted first, so an
    # unrelated ADR could crowd out the capability the issue is actually about.
    for category, relative, candidate in sorted(
        candidates, key=lambda item: (_context_priority(item[0], item[1], relevance), item[1])
    ):
        if _crosses_nested_repository_boundary(root, candidate):
            excluded.append({"path": relative, "reason_code": "nested_repository"})
            continue
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
        budget = min(limits.operational_target_bytes, limits.max_total_bytes)
        if total + len(content.encode("utf-8")) > budget:
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


#: Sources the packet may drop to fit its ceiling, least valuable first.  The
#: issue and the maintainer's decision parts are absent by design: a plan built
#: on half a decision is the failure this contract exists to prevent.
#: Repository-file categories.  `selected_files` counts these and only these,
#: so the number stays comparable with the declared `max_files` selection limit.
_REPOSITORY_FILE_CATEGORIES = (
    "adr",
    "architecture",
    "validation",
    "agent_guidance",
    "openspec",
    "source_contract",
)

#: Shedding priority, least valuable first.  This is a *different* question from
#: what counts as a repository file: folding the two together made retained
#: issue comments count toward `selected_files`, reporting six selected files
#: against a declared limit of two.
#:
#: Ordinary issue discussion sheds first: it is untrusted, ad hoc, and the least
#: valuable thing in the packet, and trusted committed material should outlive
#: it.  Omitting `comment` here previously gave it the fallback rank and shed it
#: *last*, so an unmarked comment could survive while the capability
#: specification the issue is about was deleted.  The maintainer's decision
#: parts are protected separately and never enter this ordering.
_SHEDDABLE_CATEGORIES = (
    "comment",
    *_REPOSITORY_FILE_CATEGORIES,
    "context_candidate",
)


def _serialized_size(packet: JsonObject) -> int:
    return len(canonical_bytes(packet)) + 1


def _with_exclusions(
    packet: JsonObject, kept: list[JsonObject], shed: list[JsonObject]
) -> JsonObject:
    """The exact document that would be returned for this kept/shed split."""

    selection = dict(packet.get("selection") or {})
    selection["selected_files"] = sum(
        1 for source in kept if str(source.get("category")) in _REPOSITORY_FILE_CATEGORIES
    )
    excluded = list(selection.get("excluded_candidates") or [])
    excluded.extend(
        {"path": str(source.get("path", "")), "reason_code": "packet_ceiling"} for source in shed
    )
    selection["excluded_candidates"] = excluded
    return {**packet, "sources": kept, "selection": selection}


def _fit_packet_to_ceiling(
    packet: JsonObject, limits: ContextLimits, mandatory_source_ids: frozenset[str]
) -> JsonObject:
    """Drop optional context until the serialized packet fits, or refuse.

    Every measurement is taken on the document that would actually be returned,
    exclusion evidence included.  Measuring only the surviving sources meant each
    shed source removed its content and then added a `packet_ceiling` record, and
    with long paths the records cost more than the content they freed: a packet
    could be declared fitting at 239,950 bytes and returned above the ceiling.

    Returns the packet unchanged when it already fits.  Raises when what remains
    still does not fit, because the alternative -- shortening a decision or
    dropping the evidence of what was dropped -- trades a bounded refusal for a
    silent misrepresentation.
    """

    if _serialized_size(packet) <= limits.max_total_bytes:
        return packet
    sources = list(packet.get("sources") or [])
    # Mandatory is the issue plus the maintainer's decision parts, named
    # explicitly.  An ordinary issue comment shares the `comment` category with a
    # decision part but is ordinary evidence, and shedding it is preferable to
    # refusing a legitimate maximum-size decision package.
    mandatory = [
        source
        for source in sources
        if str(source.get("category")) == "issue"
        or str(source.get("source_id")) in mandatory_source_ids
    ]
    optional = [source for source in sources if source not in mandatory]
    # Least valuable first, and largest first within that, so the fewest sources
    # are lost.
    order = sorted(
        optional,
        key=lambda source: (
            _SHEDDABLE_CATEGORIES.index(str(source.get("category")))
            if str(source.get("category")) in _SHEDDABLE_CATEGORIES
            else len(_SHEDDABLE_CATEGORIES) + 1,
            -int(source.get("bytes", 0) or 0),
        ),
    )
    kept = list(sources)
    shed: list[JsonObject] = []
    trimmed = _with_exclusions(packet, kept, shed)
    for candidate in order:
        if _serialized_size(trimmed) <= limits.max_total_bytes:
            break
        kept = [source for source in kept if source is not candidate]
        shed.append(candidate)
        trimmed = _with_exclusions(packet, kept, shed)
    if _serialized_size(trimmed) > limits.max_total_bytes:
        raise ControlPlaneError(
            "planning_packet_ceiling_exceeded",
            "The bounded planning packet cannot be reduced within its ceiling.",
            {
                "serialized_bytes": _serialized_size(trimmed),
                "max_total_bytes": limits.max_total_bytes,
                "mandatory_source_count": len(mandatory),
                "shed_source_count": len(shed),
            },
        )
    return trimmed


#: Mirrors the packet schema's bound on `declared_capabilities`.
MAX_DECLARED_CAPABILITIES = 128


def planning_trusted_digest(contract_root: Path) -> str:
    """The one derivation of a plan's trusted context, used on both sides.

    The packet records this; the provider step re-derives it from its own
    checkout before invoking the model.  Both call this function rather than
    assembling the same `extra` separately, because two copies of a derivation
    is how the vocabularies in PR #56 came to disagree in the first place.

    The inventory is re-derived from the root, never read back out of the
    packet: a capability archived between packet and provider changes no
    contract file at all, and reading the packet's own copy would compare a
    value with itself.
    """

    return trusted_context_digest(
        contract_root,
        extra={
            "capabilities": _bounded_capability_inventory(contract_root),
            "checks": implementation_check_ids(),
        },
    )


def _bounded_capability_inventory(contract_root: Path) -> list[str]:
    """The inventory, or a refusal -- never a silent truncation.

    The schema caps this list, and writing it unbounded meant the 129th promoted
    capability would fail packet construction with an opaque schema error.
    Truncating instead would be worse: an inventory the model is told is
    authoritative must be complete, or it will choose `ADDED` for something that
    already exists.
    """

    inventory = sorted(declared_capabilities(contract_root))
    if len(inventory) > MAX_DECLARED_CAPABILITIES:
        raise ControlPlaneError(
            "declared_capability_inventory_too_large",
            "The declared capability inventory exceeds the bounded packet contract.",
            {
                "declared_capability_count": len(inventory),
                "max_declared_capabilities": MAX_DECLARED_CAPABILITIES,
            },
        )
    return inventory


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
    trusted_bot_id: int | None = DEFAULT_TRUSTED_BOT_ID,
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
    context_trigger_comment_id = trigger_comment_id
    retry = trigger.get("retry")
    if isinstance(retry, dict):
        context_trigger_comment_id = int(retry["original_comment_id"])
    comment_id_upper_bound = context_trigger_comment_id
    comment_records = select_planning_comments(
        comments,
        trigger_comment_id=context_trigger_comment_id,
        comment_id_upper_bound=comment_id_upper_bound,
        trusted_bot_id=trusted_bot_id,
    )
    computed_context_sha256 = planning_context_fingerprint(
        issue,
        comment_records,
        limits,
        trigger_comment_id=context_trigger_comment_id,
        comment_id_upper_bound=comment_id_upper_bound,
        trusted_bot_id=trusted_bot_id,
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
    # A marked decision package is assembled whole or refused; ordinary comments
    # keep the existing bound.  Assembling here means the packet the model reads
    # and the manifest a reviewer reads describe the same decision input.
    # Only the actor the trigger already authorized may supply decision content.
    # Without this the marker alone would be enough for any commenter to post a
    # newer complete package and supersede the maintainer's.
    actor = trigger.get("actor")
    authorized_author_ids: list[int] = []
    if isinstance(actor, dict):
        try:
            authorized_author_ids.append(int(actor.get("id", 0)))
        except (TypeError, ValueError):
            authorized_author_ids = []
    decision_input = collect_decision_input(
        comment_records,
        issue_number=int(issue.get("number", 0)),
        authorized_author_ids=[value for value in authorized_author_ids if value > 0],
        trusted_bot_id=trusted_bot_id,
        comment_id_upper_bound=comment_id_upper_bound,
    )
    decision_part_ids = {part.comment_id for part in decision_input.parts}
    bounded_comments: list[str] = []
    comment_redactions = 0
    comment_redaction_counts: list[int] = []
    comment_limits: list[int] = []
    for comment in comment_records:
        raw = str(comment.get("body", ""))
        limit = MAX_MARKED_COMMENT_BYTES if int(comment.get("id", 0)) in decision_part_ids else 4000
        bounded, redactions = redact_untrusted_text(raw[:limit])
        bounded_comments.append(bounded)
        comment_redactions += redactions
        comment_redaction_counts.append(redactions)
        comment_limits.append(limit)
    comment_contents = [f"COMMENT (untrusted):\n{text}" for text in bounded_comments]
    comment_content_bytes = sum(len(content.encode()) for content in comment_contents)
    # The decision package and the issue come first; repository context fills
    # what remains of the operational target, not of the hard ceiling.
    context_budget = max(
        min(limits.operational_target_bytes, limits.max_total_bytes)
        - issue_content_bytes
        - comment_content_bytes,
        1,
    )
    selection_limits = replace(limits, max_total_bytes=context_budget)
    # Relevance comes from the issue a maintainer filed, never from model output.
    relevance = tuple(
        term
        for term in re.findall(r"[a-z][a-z0-9-]{3,}", str(issue.get("title", "")).casefold())
        if term not in {"feature", "issue", "add", "the", "and", "for", "with", "foundation"}
    )[:6]
    selected, excluded = _select_files(
        contract_root.resolve(strict=True), selection_limits, relevance
    )
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
    for comment, _text, comment_content, redactions, limit in zip(
        comment_records,
        bounded_comments,
        comment_contents,
        comment_redaction_counts,
        comment_limits,
        strict=True,
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
                # Against the bound that was applied: a marked decision part
                # is carried whole, so reporting it clipped would be false.
                "truncated": len(str(comment.get("body", ""))) > limit,
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
        # The canonical capability inventory, from the same function the
        # semantic gate enforces with.  Run 31281189305 declared `MODIFIED` for
        # a capability that does not exist, because nothing in the packet said
        # which do: `openspec/specs/` is empty, and zero selected spec sources
        # is indistinguishable from "the packet omitted them".
        "declared_capabilities": _bounded_capability_inventory(contract_root),
        # The authoritative check vocabulary, from the implementation lane
        # itself.  Told in prose, the planner emitted `make check`; given the
        # inventory it has no reason to invent one.
        "implementation_check_ids": implementation_check_ids(),
        # What the trusted half of this plan's input was, at the moment the
        # model read it.  The provider step re-derives this from its own
        # checkout and refuses a packet built against other contracts.
        "trusted_context_sha256": planning_trusted_digest(contract_root),
        "planning_context_sha256": computed_context_sha256,
        "redactions": {
            "applied": title_redactions + body_redactions + comment_redactions > 0,
            "count": title_redactions + body_redactions + comment_redactions,
        },
    }
    # The ceiling has to be measured on what is actually sent.  Bounding selected
    # *content* left JSON framing, source metadata, digests, and provenance
    # unaccounted for: a maximum decision package plus ordinary comments
    # serialized to 245,614 bytes against a 240,000-byte ceiling, and run
    # 30836072011 shipped 262,974.  Optional repository context and ordinary
    # comments are shed until it fits; mandatory content -- the issue and the
    # maintainer's decision parts -- is never truncated to make room.
    mandatory_source_ids = frozenset(
        _source_id("comment", f"github://issue/{issue.get('number', 0)}/comment/{part.comment_id}")
        for part in decision_input.parts
    )
    packet = _fit_packet_to_ceiling(packet, limits, mandatory_source_ids)
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
        # Every part that was carried, and every one that was not, with its
        # reason.  Exclusion is evidence; silence was the original defect.
        "decision_input": decision_input.manifest_entry(),
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


#: Plain-language hints for the validators a planning result actually trips.
_VALIDATOR_HINTS = {
    "minItems": "should be non-empty",
    "minLength": "is too short",
    "maxLength": "is too long",
    "required": "is missing a required property",
    "type": "has the wrong type",
    "enum": "is not one of the permitted values",
    "pattern": "does not match its required shape",
    "additionalProperties": "contains a property the contract does not define",
}


def _json_path(pointer: str) -> str:
    """Render an RFC 6901 pointer the way a person reads a document."""

    rendered = ""
    for token in [part for part in str(pointer).split("/") if part != ""]:
        rendered += f"[{token}]" if token.isdigit() else (f".{token}" if rendered else token)
    return rendered or "(document root)"


def _schema_failure_details(error: KernelError) -> JsonObject:
    """Bounded, actionable detail: where it failed and what was wrong there."""

    details = error.details if isinstance(error.details, dict) else {}
    pointer = str(details.get("path", ""))
    validator = str(details.get("validator", ""))
    path = _json_path(pointer)
    hint = _VALIDATOR_HINTS.get(validator, f"failed the {validator} constraint")
    return {
        "path": path,
        "pointer": pointer,
        "validator": validator,
        "detail": f"{path}: {hint}",
    }


def validate_planning_result(
    result: JsonObject,
    *,
    contract_root: Path,
    source_ids: set[str] | None = None,
    declared_scope: Sequence[str] | None = None,
    required_cross_issues: Iterable[int] | None = None,
) -> JsonObject:
    """Validate the strict contract *and* what the contract cannot express.

    Semantic validation runs here rather than only at publication, so the local
    plan check, the GitHub plan-validation job, and publication all reach it
    through the one function they already share.

    `declared_scope` and `required_cross_issues` default to the *trusted* policy
    ceiling, never to "whatever the plan said".  An earlier version defaulted
    them to empty, which let the provider author both sides of the write-scope
    subset check and let a plan pass by omitting the cross-issue boundary that
    bound it.  A caller may narrow the ceiling; it cannot widen it.

    Returns the bounded scope provenance so publication can bind it.
    """

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
    # Before the schema, because the schema rejects `then: []` on `minItems`
    # and a more specific diagnosis placed after it could never run.
    folded = folded_outcome_detail(result)
    if folded is not None:
        raise ControlPlaneError(
            "invalid_plan_result",
            "Planning output does not satisfy its strict contract.",
            folded,
        )
    try:
        validate_document(result, schema, kind="planning result")
    except KernelError as error:
        # The validator already knows the exact pointer; discarding it left a
        # 12-scenario failure reported as one opaque sentence.  A run that says
        # `requirements[0].scenarios[0].then: [] should be non-empty` can be
        # acted on without re-deriving the cause from the artifact.
        raise ControlPlaneError(
            "invalid_plan_result",
            "Planning output does not satisfy its strict contract.",
            _schema_failure_details(error),
        ) from None
    try:
        validate_planning_payload(result)
    except KernelError:
        raise ControlPlaneError(
            "unsafe_plan_payload", "Planning output contains executable-looking content."
        ) from None
    if not _CHANGE.fullmatch(str(result["proposed_change_name"])):
        # Unreachable today, and deliberately kept: the result schema enforces
        # this exact pattern and is validated first, so an invalid name is
        # already reported as `proposed_change_name` / `pattern` with its
        # pointer. A test pins that equivalence, so if the schema ever relaxes
        # this guard still refuses. The reason exists for that case, not as a
        # diagnostic anything can currently produce.
        raise ControlPlaneError(
            "invalid_plan_result",
            "The proposed OpenSpec change name is invalid.",
            {"reason": "invalid_change_name", "expected_pattern": _CHANGE.pattern},
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
        # Run 31293882847 emitted three: the human-merge gate, OpenSpec
        # acceptance, and the issue-43 boundary.  All true, none a blocker of
        # this plan -- they are standing conditions the contract represents
        # elsewhere.  The count and status are reported; the strings are model
        # prose and are not.
        raise ControlPlaneError(
            "invalid_plan_result",
            "A planned result cannot contain blocked reasons.",
            {
                "reason": "planned_result_has_blocked_reasons",
                "status": str(result["status"]),
                "blocked_reason_count": len(result["blocked_reasons"]),
            },
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
    capabilities = result.get("affected_capabilities")
    capability = ""
    if isinstance(capabilities, list) and len(capabilities) == 1:
        entry = capabilities[0]
        capability = str(entry.get("name", "")) if isinstance(entry, dict) else ""
    scope = resolve_planning_scope(
        contract_root,
        issue_number=int(result.get("originating_issue", 0) or 0),
        capability=capability,
        change_name=str(result.get("proposed_change_name", "")),
    )
    effective_scope = list(scope.write_roots) if declared_scope is None else list(declared_scope)
    effective_issues = (
        list(scope.required_cross_issues)
        if required_cross_issues is None
        else list(required_cross_issues)
    )
    validate_planning_semantics(
        result,
        contract_root=contract_root,
        declared_scope=effective_scope,
        required_cross_issues=effective_issues,
    )
    return scope.provenance()


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

    scope_provenance = validate_planning_result(result, contract_root=publication_root)
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
    proposal = f"""## Why\n\n{result["problem_statement"]}\n\n## Outcome\n\n{result["desired_outcome"]}\n\n## Scope\n\n- Originating issue: #{issue_number}\n- CountyForge planning run: `{run_id}`\n- Affected capability: {_spec_capability(result)} ({_capability_change_type(result)})\n\n## Constraints\n\n{chr(10).join(f"- {item}" for item in result["security_privacy_considerations"])}\n\n## Non-goals\n\n{chr(10).join(f"- {item}" for item in result["non_goals"])}\n\n## Decisions\n\n{_decision_lines(result)}\n\n## Unresolved decisions\n\n{chr(10).join(f"- {item}" for item in result["unresolved_decisions"]) or "- None recorded."}\n\n## Cross-issue boundaries\n\n{_boundary_lines(result)}\n\nThis draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.\n"""
    citation_lines = "\n".join(
        f"- `{citation['source_id']}`: {citation['excerpt']}"
        for citation in result["evidence_citations"]
    )
    design = f"""## Current-state evidence\n\n{citation_lines or "- See the bound planning packet."}\n\n## Proposed architecture\n\n{result["desired_outcome"]}\n\n## Dependency direction\n\nThe implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.\n\n## Trust boundaries\n\nIssue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.\n\n## Data and contract changes\n\nThe planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.\n\n## Alternatives considered\n\nNo alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.\n\n## Decisions and assumptions\n\n{_decision_lines(result)}\n\n{chr(10).join(f"- {item}" for item in result["assumptions"]) or "- None recorded."}\n\n## Cross-issue boundaries\n\n{_boundary_lines(result)}\n\n## Unresolved decisions\n\n{chr(10).join(f"- {item}" for item in result["unresolved_decisions"]) or "- None recorded."}\n\n## Risks and compatibility\n\n{chr(10).join(f"- {item}" for item in result["risks"])}\n{chr(10).join(f"- {item}" for item in result["migration_compatibility_concerns"])}\n\n## Rollout and failure recovery\n\nValidation commands: {", ".join(result["validation_commands"])}. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.\n\n## Testing strategy\n\nRun the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.\n"""
    tasks = "## Tasks\n\n" + "\n".join(_render_task(task) for task in result["task_slices"]) + "\n"
    spec = f"## {_capability_change_type(result)} Requirements\n\n" + "\n".join(
        _render_requirement(requirement) for requirement in result["requirements"]
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
    # The rendered markdown is what the implementation lane will parse, so it is
    # re-read here with that parser.  Validating the result document alone let
    # PR #56 through: `checks=make check` is valid JSON and unreadable markup.
    readiness = assert_implementation_readable(
        tasks,
        contract_root=publication_root,
        declared_task_ids=[str(task["task_id"]) for task in result["task_slices"]],
    )
    return {
        "change_name": change,
        "issue_number": issue_number,
        "run_id": run_id,
        "planning_scope": scope_provenance,
        "implementation_readiness": readiness,
        "files": [f"openspec/changes/{change}/{key}" for key in files],
        "implementation_eligibility": False,
    }


# Publication is a multi-step sequence against GitHub's Git data API.  Failing
# before the ref exists is operationally different from failing after the branch
# is visible, and a sanitized status code alone cannot tell the two apart.
#
# The sequence itself lives in `results.py`, which normalizes what the publisher
# writes.  This module used to hold a second copy, and adding a stage here and
# not there made a complete publication read as incomplete.
_PUBLICATION_STAGES = PUBLICATION_STAGES


class PublicationProgress:
    """Record the last entered publication stage on every exit path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        # Tracking opens inside the first stage rather than at a null one, so no
        # persisted snapshot and no sanitized failure can name a stage outside
        # the closed vocabulary -- not even a kill during the very first write.
        self.stage: str = _PUBLICATION_STAGES[0]
        self.completed: list[str] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._write()

    def enter(self, stage: str) -> None:
        # Consecutive-only transitions keep `completed` an exact ordered prefix
        # of the vocabulary, which is what readers of this evidence validate.
        if (
            stage not in _PUBLICATION_STAGES
            or _PUBLICATION_STAGES.index(stage) != _PUBLICATION_STAGES.index(self.stage) + 1
        ):
            raise ControlPlaneError(
                "invalid_publication_stage", "Publication reported an out-of-order stage."
            )
        self.completed.append(self.stage)
        self.stage = stage
        self._write()

    def as_document(self) -> JsonObject:
        return {"stage": self.stage, "completed": list(self.completed)}

    def _write(self) -> None:
        """Persist each transition atomically so a hard kill still leaves evidence.

        `write_text` would truncate first, so a kill inside that window could
        leave neither the previous nor the current snapshot.
        """

        if self._path is None:
            return
        document = json.dumps(self.as_document(), indent=2, sort_keys=True) + "\n"
        pending = self._path.with_name(f"{self._path.name}.pending")
        try:
            pending.write_text(document, encoding="utf-8")
            os.replace(pending, self._path)
        except OSError:
            pending.unlink(missing_ok=True)
            raise


@contextmanager
def publication_progress(path: Path | None = None) -> Iterator[PublicationProgress]:
    """Open the publication evidence boundary.

    Callers open this before reading inputs or constructing a GitHub client, so
    an unreadable result artifact or a missing token is attributed like any
    other publication failure instead of escaping without a stage.  Every exit
    leaves a sanitized `ControlPlaneError` carrying the stage it reached.
    """

    progress = PublicationProgress(path)
    try:
        yield progress
    except ControlPlaneError as error:
        error.details.update(progress.as_document())
        raise
    except KernelError as error:
        # A trusted contract check failed inside publication; keep its stable
        # code but re-envelope it so the stage travels with it.
        raise ControlPlaneError(
            error.code,
            "Publication failed a trusted contract check.",
            dict(progress.as_document()),
            exit_code=5,
        ) from None
    except Exception as error:  # noqa: BLE001 - sanitize every publication failure
        # GitHub responses and the filesystem are untrusted here, so an
        # AttributeError, TypeError, or OSError must still name its stage.  Only
        # the exception class name crosses the boundary; no value does.
        raise ControlPlaneError(
            "publication_internal_error",
            "Publication failed unexpectedly.",
            {"error_type": type(error).__name__, **progress.as_document()},
            exit_code=5,
        ) from None


def _marker_match(
    pulls: Iterable[JsonObject], *, run_id: str, manifest_sha: str, require_run: bool = True
) -> JsonObject | None:
    """Find the draft whose bot marker claims this plan.

    A marker is a mutable substring of a pull-request body and is only a
    candidate: the branch behind it may since have been deleted, force-pushed,
    or edited.  Deduplication is decided later, against the verified ref.
    """

    for pull in pulls:
        body = str(pull.get("body", ""))
        if require_run and f"run={run_id}" not in body:
            continue
        if f"context={manifest_sha}" in body:
            return pull
    return None


def _publish_ref(
    github: Any, *, repository: str, ref: str, commit: str, tree: str, parent: str
) -> tuple[str, bool]:
    """Create the deterministic planning ref, or resume the one already there.

    A retry cannot reproduce a commit SHA, but the tree is content-addressed, so
    an existing ref whose commit carries this exact tree and parent is a prior
    attempt of this same plan and is safe to resume.  Anything else on that ref
    is human-owned or divergent and fails closed rather than being moved.
    """

    existing = github.get_git_ref(repository, ref)
    if existing is None:
        github.create_git_ref(repository, ref, commit)
        return commit, False
    object_facts = existing.get("object") if isinstance(existing, dict) else None
    head_sha = object_facts.get("sha") if isinstance(object_facts, dict) else None
    if not isinstance(head_sha, str) or not head_sha:
        raise ControlPlaneError(
            "github_api_invalid_response", "GitHub ref identity is unavailable."
        )
    head_commit = github.get_git_commit(repository, head_sha)
    head_tree = head_commit.get("tree") if isinstance(head_commit, dict) else None
    parents = head_commit.get("parents") if isinstance(head_commit, dict) else None
    parent_shas = (
        [item.get("sha") for item in parents if isinstance(item, dict)]
        if isinstance(parents, list)
        else []
    )
    if not isinstance(head_tree, dict) or head_tree.get("sha") != tree or parent_shas != [parent]:
        raise ControlPlaneError(
            "planning_branch_conflict",
            "The deterministic planning branch already exists and does not hold this plan.",
            {"ref": ref},
            exit_code=5,
        )
    return head_sha, True


def _assert_decision_input_unchanged(
    github: Any,
    *,
    repository: str,
    issue_number: int,
    manifest: JsonObject,
) -> None:
    """Re-read the decision package and refuse if it moved since the packet.

    The packet binds each part's author, comment ID, digest, and `updated_at`.
    Nothing checked them again, so a maintainer could edit a decision after
    packet construction and the run would publish against evidence that no
    longer exists.  This runs before the first Git object is created.
    """

    bound = manifest.get("decision_input")
    if not isinstance(bound, dict) or bound.get("decision_input_present") is not True:
        return
    parts = [item for item in bound.get("included_parts") or [] if isinstance(item, dict)]
    if not parts:
        return
    try:
        comments = github.list_comments(repository, int(issue_number))
    except Exception as error:  # noqa: BLE001 - re-raised as a bounded refusal
        raise ControlPlaneError(
            "decision_input_unverifiable",
            "The bound decision input could not be re-read before publication.",
            {"reason": type(error).__name__},
        ) from None
    authorized = sorted({int(item.get("author_id", 0)) for item in parts})
    upper_bound = max(int(item.get("comment_id", 0)) for item in parts)
    observed = collect_decision_input(
        comments,
        issue_number=int(issue_number),
        authorized_author_ids=authorized,
        comment_id_upper_bound=upper_bound,
    )
    assert_unedited_since_trigger(observed, parts)


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
    progress: PublicationProgress | None = None,
) -> JsonObject:
    """Publish a validated plan through GitHub's Git data API.

    The caller supplies a trusted checkout and a GitHub port.  The model result is
    rendered first; only those deterministic files become blobs in the new commit.
    Every stage transition is recorded, and any sanitized failure carries the
    stage it failed in so a partially applied publication can be diagnosed.
    A caller that already opened `publication_progress` passes it in and owns
    that boundary; otherwise one is opened for the duration of this call.
    """

    required = (
        "list_pull_requests",
        "create_git_blob",
        "get_git_commit",
        "create_git_tree",
        "create_git_commit",
        "create_git_ref",
        "get_git_ref",
        "create_pull_request",
    )
    # Every fallible preflight runs under initialized tracking; an unusable port
    # must not be the one failure that reports no stage.
    boundary: AbstractContextManager[PublicationProgress] = (
        nullcontext(progress) if progress is not None else publication_progress()
    )
    with boundary as progress:
        if not all(hasattr(github, name) for name in required):
            raise ControlPlaneError(
                "github_port_incomplete", "GitHub publication port is incomplete."
            )
        validate_planning_result(result, contract_root=publication_root)
        issue = int(issue_number)
        if int(result["originating_issue"]) != issue:
            raise ControlPlaneError(
                "planning_provenance_mismatch", "Planning result issue does not match the trigger."
            )
        progress.enter("validate_provenance")
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
                    publication_root
                    / ".ai/schemas/countyforge-planning-context-manifest.schema.json",
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
        _assert_decision_input_unchanged(
            github,
            repository=repository,
            issue_number=issue,
            manifest=manifest,
        )
        # The untrusted half of the input has been re-checked; this is the
        # trusted half.  Also before the first Git object is created.
        progress.enter("verify_trusted_context")
        live = resolve_default_branch(github, repository=repository, at=run_id)
        head = live.get("default_branch_sha")
        if not isinstance(head, str):
            # Fails closed.  Recording the skip in the manifest was still
            # publishing a plan whose base nobody had checked, and an unverified
            # base is exactly the condition this stage exists to refuse.
            raise ControlPlaneError(
                UNVERIFIABLE_DISPOSITION,
                "The trusted planning context could not be verified before publication.",
                {"stage": "publication", "reason": "default_branch_unavailable"},
            )
        context_freshness = assert_base_context_unmoved(
            github,
            repository=repository,
            target_sha=target_sha,
            default_branch_sha=head,
        )
        progress.enter("resolve_predecessor")
        change = str(result["proposed_change_name"])
        base_branch = planning_branch(issue, change)
        branch = base_branch
        owner = repository.split("/", 1)[0]
        existing = github.list_pull_requests(
            repository, head=f"{owner}:{branch}", base=default_branch
        )
        bot_marker = f"<!-- countyforge-plan:v1 run={run_id} context={manifest_sha} -->"
        # A marker only nominates a candidate draft.  Nothing returns success
        # here: the tree has not been built yet, so the ref behind that draft is
        # still unverified.
        marker_pull = _marker_match(existing, run_id=run_id, manifest_sha=manifest_sha)
        predecessor: JsonObject | None = (
            None if marker_pull is not None else (existing[0] if existing else None)
        )
        if predecessor is not None:
            branch = f"{base_branch}-r{manifest_sha[:8]}"
            versioned = github.list_pull_requests(
                repository, head=f"{owner}:{branch}", base=default_branch
            )
            marker_pull = _marker_match(
                versioned, run_id=run_id, manifest_sha=manifest_sha, require_run=False
            )
        progress.enter("create_blobs")
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
            # This is the branch production takes: the files were materialized
            # in an earlier job and copied here as an artifact, so readiness
            # runs against the bytes that are about to become blobs rather than
            # against whatever the materializer wrote somewhere else.
            manifest = {
                "change_name": change,
                "issue_number": issue,
                "run_id": run_id,
                "files": files,
                "implementation_eligibility": False,
                "implementation_readiness": assert_implementation_readable(
                    (publication_root / f"openspec/changes/{change}/tasks.md").read_text(
                        encoding="utf-8"
                    ),
                    contract_root=publication_root,
                    declared_task_ids=[
                        str(task["task_id"]) for task in result.get("task_slices") or []
                    ],
                ),
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
        progress.enter("load_parent_commit")
        parent = target_sha
        commit_document = github.get_git_commit(repository, parent)
        tree_document = commit_document.get("tree")
        if not isinstance(tree_document, dict) or not isinstance(tree_document.get("sha"), str):
            raise ControlPlaneError(
                "github_api_invalid_response", "GitHub commit tree identity is unavailable."
            )
        progress.enter("create_tree")
        tree = github.create_git_tree(repository, str(tree_document["sha"]), entries)
        progress.enter("create_commit")
        commit = github.create_git_commit(
            repository, f"plan: draft OpenSpec for issue #{issue}", tree, parent
        )
        progress.enter("create_ref")
        ref = f"refs/heads/{branch}"
        commit, resumed = _publish_ref(
            github, repository=repository, ref=ref, commit=commit, tree=tree, parent=parent
        )
        progress.enter("create_pull_request")
        if marker_pull is None and resumed:
            # A prior attempt already left the branch in place; its draft may have
            # been created between that listing and now.
            marker_pull = _marker_match(
                github.list_pull_requests(
                    repository, head=f"{owner}:{branch}", base=default_branch
                ),
                run_id=run_id,
                manifest_sha=manifest_sha,
                require_run=predecessor is None,
            )
        if marker_pull is not None:
            # Only now, against the verified ref, can a marker be believed.  A
            # draft whose head is not that ref is stale, force-pushed, or edited,
            # and must never be reported as this plan's publication.
            head = marker_pull.get("head")
            head_sha = str(head.get("sha", "")) if isinstance(head, dict) else ""
            if not resumed or head_sha != commit:
                raise ControlPlaneError(
                    "planning_draft_conflict",
                    "An existing planning draft does not match the verified planning ref.",
                    {"ref": ref},
                    exit_code=5,
                )
            progress.enter("complete")
            return {
                "ok": True,
                "action": "deduplicated",
                "branch": branch,
                "commit_sha": commit,
                "pr_number": marker_pull.get("number"),
                "pr_url": marker_pull.get("html_url"),
                "change_name": change,
                "run_id": run_id,
                "context_manifest_sha256": manifest_sha,
                "implementation_eligible": False,
                **progress.as_document(),
            }
        predecessor_link = (
            f"\nPredecessor draft: #{predecessor['number']} (superseded without modifying it).\n"
            if predecessor is not None
            else ""
        )
        evidence = f"\nEvidence: {evidence_url}\n" if evidence_url else ""
        body = (
            f"{bot_marker}\n\n## CountyForge planning draft\n\n"
            f"Originating issue: [#{issue}](https://github.com/{repository}/issues/{issue})\n\n"
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
        # Read the response while still in this stage, so a malformed one is
        # attributed to the mutation that produced it rather than to `complete`.
        if not isinstance(pr, dict):
            raise ControlPlaneError(
                "github_api_invalid_response", "GitHub pull-request identity is unavailable."
            )
        pr_number = pr.get("number")
        pr_url = pr.get("html_url")
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
            "trusted_context_freshness": context_freshness,
            # Never defaulted. Both branches above run the gate, so a manifest
            # missing this field means the gate did not run, and asserting
            # readability that was never checked is worse than not asserting it.
            "implementation_readiness": manifest["implementation_readiness"],
        }
        validate_document(
            publication_manifest,
            load_json_object(
                publication_root
                / ".ai/schemas/countyforge-planning-publication-manifest.schema.json",
                kind="planning publication schema",
            ),
            kind="planning publication manifest",
        )
        progress.enter("complete")
        return {
            "ok": True,
            "action": action,
            "branch": branch,
            "commit_sha": commit,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "change_name": change,
            "run_id": run_id,
            "context_manifest_sha256": manifest_sha,
            "planning_revision": revision,
            "publication_manifest": publication_manifest,
            "revision": revision_document,
            "implementation_eligible": False,
            **progress.as_document(),
        }
