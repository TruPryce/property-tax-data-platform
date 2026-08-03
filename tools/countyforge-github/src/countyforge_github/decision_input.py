"""Bounded multipart maintainer decision input.

A detailed D1-D4 decision package was posted on issue #18 and the planner treated
it as incomplete, because `planning_context_fingerprint` clipped every comment at
4,000 characters.  The truncation was silent: nothing in the packet or the
manifest said the decisions had been cut in half, so the model reasoned over a
fragment and correctly reported that it could not decide.

A maintainer may now split a decision package across several comments carrying an
exact versioned marker:

    <!-- countyforge-plan-input:v1 issue=18 input=collin-decoder-decisions-1 part=1/4 -->

The marker changes *selection*, never trust.  Marked comments are still untrusted
evidence, their author must still pass normal CountyForge authorization, and
nothing in them becomes policy.  What the marker buys is that the parts are
assembled whole or not at all: a part that will not fit is excluded with a stable
reason rather than clipped, and a set that is missing, duplicated, contradictory,
or edited after the trigger fails planning closed as `incomplete_decision_input`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import NoReturn

from countyforge_github.contracts import JsonObject
from countyforge_github.errors import ControlPlaneError

MARKER_VERSION = "v1"
#: Exact marker only. A near-miss is not a decision part; it is a comment that
#: happens to mention the convention, and it is treated as ordinary evidence.
#:
#: Anchored: the payload is everything *after* the marker, so a marker found
#: mid-body would silently discard everything before it -- the same
#: quiet-truncation failure this whole contract exists to remove. A comment that
#: quotes the marker in prose or inside a fenced example is ordinary evidence.
MARKER = re.compile(
    r"\A\s*<!--\s*countyforge-plan-input:v1\s+"
    r"issue=(?P<issue>[0-9]{1,9})\s+"
    r"input=(?P<input>[A-Za-z0-9][A-Za-z0-9._-]{0,63})\s+"
    r"part=(?P<part>[0-9]{1,3})/(?P<total>[0-9]{1,3})\s*-->"
)

#: Bounds. Every one of these is a refusal boundary, never a truncation point.
MAX_PARTS = 12
#: The payload, measured after the marker.
MAX_PART_BYTES = 24_000
#: The whole comment, marker included.  `MAX_PART_BYTES` bounds the payload, so
#: anything applying a bound to the raw body -- the packet, the fingerprint --
#: must leave room for the marker too, or a part at exactly the documented
#: payload limit gets clipped by the very code meant to carry it whole.  The
#: marker is bounded by its own expression: 9 issue digits, a 64-character input
#: id, and 3+3 part digits, comfortably under this margin.
MAX_MARKER_BYTES = 256
MAX_MARKED_COMMENT_BYTES = MAX_PART_BYTES + MAX_MARKER_BYTES
MAX_TOTAL_DECISION_BYTES = 160_000

INCOMPLETE = "incomplete_decision_input"
EXCLUDED_TOO_LARGE = "comment_too_large"
EXCLUDED_SUPERSEDED = "superseded_decision_input"
EXCLUDED_TOTAL_BUDGET = "total_decision_input_budget_exceeded"


def decision_marker(body: str) -> re.Match[str] | None:
    """The one predicate for "is this comment a decision part".

    Every path -- context fingerprinting, decision collection, and packet
    construction -- must agree on this, or a comment could be bounded as a
    decision part in one place and as ordinary evidence in another.
    """

    return MARKER.match(body)


def _fail(reason: str, **details: object) -> NoReturn:
    raise ControlPlaneError(
        INCOMPLETE,
        "The maintainer decision input is incomplete and cannot be planned from.",
        {"reason": reason, **details},
    )


@dataclass(frozen=True, slots=True)
class DecisionPart:
    """One marked comment, bound to the immutable facts that identify it."""

    issue_number: int
    input_id: str
    part: int
    total: int
    comment_id: int
    author_id: int
    author_login: str
    updated_at: str
    body: str
    body_sha256: str
    byte_length: int

    def provenance(self) -> JsonObject:
        """Bounded provenance; the body itself lives in the packet, not here."""

        return {
            "issue_number": self.issue_number,
            "input_id": self.input_id,
            "part": self.part,
            "total": self.total,
            "comment_id": self.comment_id,
            "author_id": self.author_id,
            "author_login": self.author_login,
            "updated_at": self.updated_at,
            "body_sha256": self.body_sha256,
            "byte_length": self.byte_length,
        }


@dataclass(slots=True)
class DecisionInput:
    """The assembled package, plus everything deliberately left out of it."""

    input_id: str = ""
    parts: list[DecisionPart] = field(default_factory=list)
    excluded: list[JsonObject] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.parts)

    def text(self) -> str:
        """Parts in declared order, whole, with their boundaries visible."""

        return "\n\n".join(
            f"--- DECISION INPUT {part.input_id} PART {part.part}/{part.total} "
            f"(untrusted maintainer evidence) ---\n{part.body}"
            for part in self.parts
        )

    def manifest_entry(self) -> JsonObject:
        """What the context manifest records, including every exclusion."""

        return {
            "contract_version": 1,
            "decision_input_present": self.present,
            "input_id": self.input_id,
            "declared_total": self.parts[0].total if self.parts else 0,
            "included_part_count": len(self.parts),
            "included_parts": [part.provenance() for part in self.parts],
            "excluded": list(self.excluded),
            "total_byte_length": sum(part.byte_length for part in self.parts),
            "truncated": False,
        }


def _author(comment: JsonObject) -> tuple[int, str]:
    user = comment.get("user")
    if not isinstance(user, dict):
        return 0, ""
    try:
        author_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        author_id = 0
    return author_id, str(user.get("login", ""))


def _is_command_comment(body: str) -> bool:
    """A command is an instruction, never decision content."""

    return any(line.strip().startswith("/countyforge") for line in body.splitlines())


def collect_decision_input(
    comments: Iterable[JsonObject],
    *,
    issue_number: int,
    authorized_author_ids: Sequence[int],
    trusted_bot_id: int | None = None,
    comment_id_upper_bound: int | None = None,
    max_parts: int = MAX_PARTS,
    max_part_bytes: int = MAX_PART_BYTES,
    max_total_bytes: int = MAX_TOTAL_DECISION_BYTES,
) -> DecisionInput:
    """Assemble the newest complete decision package, or refuse to plan.

    `authorized_author_ids` is required and is not defaulted: an empty
    allowlist authorizes nobody.  The marker selects a comment; it never confers
    trust, and the author must independently be one the trigger authorized.

    `comment_id_upper_bound` is the trigger boundary: a part created after the
    trigger is not part of the package the trigger referred to.  A part *edited*
    after that boundary fails closed rather than being silently accepted, since
    its content is no longer what the run was claimed against.
    """

    collected: dict[str, dict[int, DecisionPart]] = {}
    excluded: list[JsonObject] = []
    totals: dict[str, set[int]] = {}
    for comment in comments:
        body = str(comment.get("body", ""))
        match = decision_marker(body)
        if match is None:
            continue
        try:
            comment_id = int(comment.get("id", 0))
        except (TypeError, ValueError):
            comment_id = 0
        author_id, author_login = _author(comment)
        if trusted_bot_id is not None and author_id == trusted_bot_id:
            # The bot's own status comments can carry any text; they are never
            # decision content, whatever markers they happen to quote.
            continue
        if _is_command_comment(body):
            excluded.append(
                {"comment_id": comment_id, "reason": "command_comment_not_decision_content"}
            )
            continue
        if int(match.group("issue")) != issue_number:
            excluded.append({"comment_id": comment_id, "reason": "issue_number_mismatch"})
            continue
        if author_id not in set(authorized_author_ids):
            # Fail closed. An empty allowlist means *no* author is authorized,
            # not "skip the check": otherwise any commenter could post a newer
            # complete package and supersede the maintainer's.
            excluded.append({"comment_id": comment_id, "reason": "author_not_authorized"})
            continue
        if comment_id_upper_bound is not None and comment_id > comment_id_upper_bound:
            excluded.append({"comment_id": comment_id, "reason": "posted_after_trigger"})
            continue
        payload = body[match.end() :].strip()
        encoded = payload.encode("utf-8")
        if len(encoded) > max_part_bytes:
            # Whole parts only: half a decision reads as a complete one.
            excluded.append(
                {
                    "comment_id": comment_id,
                    "reason": EXCLUDED_TOO_LARGE,
                    "byte_length": len(encoded),
                    "max_part_bytes": max_part_bytes,
                }
            )
            continue
        input_id = match.group("input")
        part_number = int(match.group("part"))
        total = int(match.group("total"))
        part = DecisionPart(
            issue_number=issue_number,
            input_id=input_id,
            part=part_number,
            total=total,
            comment_id=comment_id,
            author_id=author_id,
            author_login=author_login,
            updated_at=str(comment.get("updated_at", "")),
            body=payload,
            body_sha256=hashlib.sha256(encoded).hexdigest(),
            byte_length=len(encoded),
        )
        bucket = collected.setdefault(input_id, {})
        if part_number in bucket:
            _fail(
                "duplicate_part",
                input_id=input_id,
                part=part_number,
                comment_ids=sorted({bucket[part_number].comment_id, comment_id}),
            )
        bucket[part_number] = part
        totals.setdefault(input_id, set()).add(total)

    if not collected:
        # Exclusions survive an empty package: "no decision input" and "every
        # part was too large" must not look the same in the manifest.
        return DecisionInput(excluded=excluded)

    # Newest package wins; older ones are recorded as superseded rather than
    # merged, so two decision rounds can never be spliced into one.
    selected_id = max(collected, key=lambda key: max(p.comment_id for p in collected[key].values()))
    for other in sorted(set(collected) - {selected_id}):
        for part in sorted(collected[other].values(), key=lambda item: item.part):
            excluded.append(
                {
                    "comment_id": part.comment_id,
                    "reason": EXCLUDED_SUPERSEDED,
                    "input_id": other,
                    "part": part.part,
                }
            )

    bucket = collected[selected_id]
    declared = totals[selected_id]
    if len(declared) != 1:
        _fail("conflicting_total", input_id=selected_id, declared_totals=sorted(declared))
    total = declared.pop()
    if total < 1 or total > max_parts:
        _fail("total_out_of_range", input_id=selected_id, total=total, max_parts=max_parts)
    if any(number < 1 or number > total for number in bucket):
        _fail("part_out_of_range", input_id=selected_id, total=total, parts=sorted(bucket))
    missing = sorted(set(range(1, total + 1)) - set(bucket))
    if missing:
        _fail("missing_part", input_id=selected_id, total=total, missing=missing)

    ordered = [bucket[number] for number in range(1, total + 1)]
    total_bytes = sum(part.byte_length for part in ordered)
    if total_bytes > max_total_bytes:
        # Refuse rather than drop a part: an assembled package missing its
        # fourth part is indistinguishable from a three-part one.
        _fail(
            "total_budget_exceeded",
            input_id=selected_id,
            total_byte_length=total_bytes,
            max_total_bytes=max_total_bytes,
        )
    return DecisionInput(input_id=selected_id, parts=ordered, excluded=excluded)


def assert_unedited_since_trigger(
    decision_input: DecisionInput, bound_provenance: Sequence[JsonObject]
) -> None:
    """Fail closed when a bound part's content changed after the trigger.

    The packet binds each part's `body_sha256` and `updated_at` when the trigger
    is constructed.  Re-reading the comments at publication time and finding a
    different digest means the maintainer edited a decision mid-run, so the
    result was produced against evidence that no longer exists.
    """

    bound = {
        int(entry.get("comment_id", 0)): entry
        for entry in bound_provenance
        if isinstance(entry, dict)
    }
    for part in decision_input.parts:
        previous = bound.get(part.comment_id)
        if previous is None:
            _fail("part_not_bound_to_trigger", comment_id=part.comment_id, part=part.part)
        # Both, not either.  A maintainer can edit a comment and restore its
        # original text: the digest matches again, but GitHub's `updated_at`
        # stays newer, and the run would otherwise publish against a comment
        # that demonstrably moved after the packet bound it.  The provenance
        # records both facts, so both are enforced.
        digest_changed = str(previous.get("body_sha256")) != part.body_sha256
        timestamp_changed = str(previous.get("updated_at", "")) != part.updated_at
        if digest_changed or timestamp_changed:
            _fail(
                "part_edited_after_trigger",
                comment_id=part.comment_id,
                part=part.part,
                bound_updated_at=str(previous.get("updated_at", "")),
                observed_updated_at=part.updated_at,
                body_digest_changed=digest_changed,
                updated_at_changed=timestamp_changed,
            )
    for comment_id in sorted(set(bound) - {part.comment_id for part in decision_input.parts}):
        _fail("bound_part_disappeared", comment_id=comment_id)
