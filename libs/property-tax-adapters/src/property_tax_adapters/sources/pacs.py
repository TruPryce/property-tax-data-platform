"""Reusable PACS fixed-width serialization mechanics.

Accepted in OpenSpec change ``add-denton-cad-pacs-parser-foundation``.

This module is deliberately county-free. It names no county, no county field,
no threshold, and no policy, because Issue #21 requires Ellis to *bind* to it
rather than fork it, and a component that knew ``prop_id`` could not be bound by
a county that spells its account identifier differently.

What lives here: field positions, layout validation, the layout fingerprint, and
record slicing that never emits a partial value. What lives in the county
binding: field names, lexical grammars, grain rules, thresholds, privacy policy,
and the diagnostic vocabulary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

#: Bumped only when the fingerprint document's shape changes, never when a
#: county layout changes. A county layout version travels in the document.
PACS_COMPONENT_CONTRACT_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class PacsField:
    """One fixed-width field at 1-indexed inclusive positions.

    `start` and `end` are both inclusive, so a field at 1-5 is five characters
    wide. That convention comes from the published PACS layouts, and converting
    to half-open ranges at the boundary is exactly where off-by-one slicing
    defects come from, so the inclusive form is kept end to end.
    """

    name: str
    start: int
    end: int
    required: bool = True
    #: The width the published layout states, when it states one. Published PACS
    #: layouts carry positions *and* a length, and transcribing them into code is
    #: where a digit gets dropped. Supplying it here cross-checks the transcription;
    #: a value that disagrees with the positions is the defect this catches.
    declared_length: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a PACS field requires a name")
        if self.start < 1:
            raise ValueError(f"{self.name}: positions are 1-indexed")
        if self.end < self.start:
            raise ValueError(f"{self.name}: end position precedes start position")
        if self.declared_length is not None and self.declared_length != self.length:
            raise ValueError(
                f"{self.name}: declared length {self.declared_length} disagrees with "
                f"positions {self.start}-{self.end} ({self.length})"
            )

    @property
    def length(self) -> int:
        """Width implied by the positions, inclusive of both endpoints."""

        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class TrailingRegion:
    """A structural fingerprint of bytes beyond the layout's declared end.

    The content is deliberately absent: an undocumented region may carry
    identity or address data, so it is measured and digested but never carried.
    Both values describe the source bytes in the member's own encoding.
    """

    byte_length: int
    digest: str


@dataclass(frozen=True, slots=True)
class SlicedRecord:
    """One record's sliced values, plus what could not be sliced.

    `values` holds only fields that fit entirely within the observed width.
    `truncated_required` names required fields whose declared end exceeded it;
    a partial slice is never offered as a value.
    """

    values: dict[str, str]
    truncated_required: tuple[str, ...]
    absent_optional: tuple[str, ...]
    trailing: TrailingRegion | None


class PacsLayout:
    """An ordered, non-overlapping fixed-width layout.

    Order, overlap, and length agreement are validated at construction and
    raise `ValueError` rather than producing a diagnostic. A layout is written
    in trusted repository code, so a defect in one is an authoring mistake, not
    something a source file did; reporting it as source data would misattribute
    the fault and let a broken layout reach a release.
    """

    __slots__ = ("_fields", "_fingerprint", "_layout_id", "_layout_version")

    def __init__(self, layout_id: str, layout_version: str, fields: tuple[PacsField, ...]) -> None:
        if not layout_id:
            raise ValueError("a PACS layout requires an identifier")
        if not layout_version:
            raise ValueError("a PACS layout requires a version")
        if not fields:
            raise ValueError("a PACS layout requires at least one field")

        names = [field.name for field in fields]
        if len(set(names)) != len(names):
            raise ValueError("a PACS layout may not declare a field name twice")

        previous: PacsField | None = None
        for field in fields:
            if previous is not None:
                if field.start <= previous.start:
                    raise ValueError(
                        f"{field.name}: fields must be declared in ascending start order"
                    )
                if field.start <= previous.end:
                    raise ValueError(f"{field.name}: overlaps {previous.name}")
            previous = field

        self._layout_id = layout_id
        self._layout_version = layout_version
        self._fields = fields
        self._fingerprint = _fingerprint(layout_id, layout_version, fields)

    @property
    def layout_id(self) -> str:
        return self._layout_id

    @property
    def layout_version(self) -> str:
        """Read-only.

        The fingerprint is computed once at construction. A settable version
        would let a layout be relabelled after fingerprinting, so a mutated
        layout would validate and report the old approved digest beside the new
        version -- exactly the drift the fingerprint exists to detect.
        """

        return self._layout_version

    @property
    def fields(self) -> tuple[PacsField, ...]:
        return self._fields

    @property
    def fingerprint(self) -> str:
        """Lowercase SHA-256 of the canonical layout document."""

        return self._fingerprint

    @property
    def declared_width(self) -> int:
        """The greatest declared end position."""

        return self._fields[-1].end

    def slice_record(self, record: str, *, encoding: str = "utf-8") -> SlicedRecord:
        """Slice one record at 1-indexed inclusive positions.

        A field whose declared end exceeds the observed width is never emitted
        as a truncated value: when required it is reported, and when optional it
        is absent. Values are returned exactly as they appear, because trimming
        is a county rule rather than a serialization mechanic.

        `encoding` is the encoding the record was decoded from. The trailing
        region's byte length and digest describe the *source* bytes, so a county
        reading ISO-8859-1 must say so; re-encoding as UTF-8 would report two
        bytes for one accented character and digest something that never
        appeared in the file.
        """

        width = len(record)
        values: dict[str, str] = {}
        truncated: list[str] = []
        absent: list[str] = []

        for field in self._fields:
            if field.end > width:
                if field.required:
                    truncated.append(field.name)
                else:
                    absent.append(field.name)
                continue
            values[field.name] = record[field.start - 1 : field.end]

        trailing: TrailingRegion | None = None
        if width > self.declared_width:
            region = record[self.declared_width :]
            encoded = region.encode(encoding, errors="strict")
            trailing = TrailingRegion(
                byte_length=len(encoded),
                digest=hashlib.sha256(encoded).hexdigest(),
            )

        return SlicedRecord(
            values=values,
            truncated_required=tuple(truncated),
            absent_optional=tuple(absent),
            trailing=trailing,
        )


def _fingerprint(layout_id: str, layout_version: str, fields: tuple[PacsField, ...]) -> str:
    """Digest the canonical layout document.

    Versioned separately from any export-header version, so a county may accept
    a known layout against an unknown export version and record both.
    """

    document = {
        "component_contract_version": PACS_COMPONENT_CONTRACT_VERSION,
        "field_count": len(fields),
        "fields": [[field.name, field.start, field.end, field.required] for field in fields],
        "layout_id": layout_id,
        "layout_version": layout_version,
    }
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "PACS_COMPONENT_CONTRACT_VERSION",
    "PacsField",
    "PacsLayout",
    "SlicedRecord",
    "TrailingRegion",
]
