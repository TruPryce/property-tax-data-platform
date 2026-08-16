"""What a reader hands the processor: release identity, and one envelope per row.

Two shapes carry the whole traffic.  `PreparedRelease` is the identity, readable
before any record is read, which is what lets an empty release still emit a
complete progress event.  `SourceRowEnvelope` is one **physical row** — its
number, the zero or more records it produced, and whether it was rejected.

The envelope is a row rather than a record because those are different counts:
one accepted Collin row already produces one record per observed family, and a
row may produce none.  The rejected indicator is what makes a zero-record
envelope legible, since without it a row that legitimately produced nothing and
a row that was invalid look identical.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from property_tax_adapters.release.outcome import ReleaseNotice
from property_tax_adapters.sources.contracts import AppraisalSourceRecord

__all__ = [
    "MAX_CARRIER_NOTICES",
    "NoticeSet",
    "PreparedRelease",
    "SourceRowEnvelope",
    "record_disagreement",
]

#: A carrier retains at most this many notices.  It bounds what is *held*, not
#: what may be observed: raising past it would make a non-fatal notice fatal,
#: and Dallas emits one `extra_columns_present` per unknown header with no limit
#: in its accepted contract.
MAX_CARRIER_NOTICES: Final = 100

#: The bound the accepted Tarrant contract already sets for these two fields.
#: The alphabet admits no path separator, so an absolute path, a UNC path, a
#: drive-qualified path, and a traversal are unrepresentable rather than merely
#: discouraged.
_IDENTIFIER_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,128}")
_JURISDICTION_PATTERN: Final = re.compile(r"[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*")


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a str, not coerced from {type(value).__name__}")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None or value[0] in {".", "-"}:
        raise ValueError(
            f"{field_name} must be 1 to 128 characters of [A-Za-z0-9._-] not beginning "
            "with '.' or '-', so a host-local path cannot be represented"
        )


@dataclass(frozen=True, slots=True)
class NoticeSet:
    """Retained notices, the total observed, and whether the two differ.

    Built incrementally by :meth:`from_observations` rather than by trimming a
    finished sequence: a carrier that assembled a hundred and fifty entries
    before cutting to a hundred would already have held what the bound exists to
    prevent, which on a release with many unknown columns is the memory this
    boundary was written to bound.
    """

    retained: tuple[ReleaseNotice, ...] = ()
    total: int = 0
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.retained, tuple) or not all(
            isinstance(entry, ReleaseNotice) for entry in self.retained
        ):
            raise ValueError("retained must be a tuple of ReleaseNotice")
        if isinstance(self.total, bool) or not isinstance(self.total, int) or self.total < 0:
            raise ValueError("total must be a non-negative int")
        if len(self.retained) != min(self.total, MAX_CARRIER_NOTICES):
            raise ValueError(f"retained must hold min(total, {MAX_CARRIER_NOTICES}) entries")
        if self.truncated is not (self.total > MAX_CARRIER_NOTICES):
            raise ValueError("truncated must be true exactly when total exceeds the cap")

    @classmethod
    def from_observations(cls, observations: Iterable[ReleaseNotice]) -> NoticeSet:
        """Consume incrementally, retaining the first hundred and counting all."""

        retained: list[ReleaseNotice] = []
        total = 0
        for notice in observations:
            total += 1
            if len(retained) < MAX_CARRIER_NOTICES:
                retained.append(notice)
        return cls(
            retained=tuple(retained),
            total=total,
            truncated=total > MAX_CARRIER_NOTICES,
        )


@dataclass(frozen=True, slots=True)
class PreparedRelease:
    """The identity of one logical release, complete before the first record."""

    jurisdiction_code: str
    release_identifier: str
    source_member_name: str
    layout_fingerprint: str
    parser_contract_version: int
    notices: NoticeSet = field(default_factory=NoticeSet)

    def __post_init__(self) -> None:
        if _JURISDICTION_PATTERN.fullmatch(self.jurisdiction_code) is None:
            raise ValueError(
                "jurisdiction_code must be a lowercase state prefix, a hyphen, and a county slug"
            )
        _require_identifier(self.release_identifier, "release_identifier")
        _require_identifier(self.source_member_name, "source_member_name")
        if not isinstance(self.layout_fingerprint, str) or not self.layout_fingerprint.strip():
            raise ValueError("layout_fingerprint must be a non-blank str")
        if isinstance(self.parser_contract_version, bool) or not isinstance(
            self.parser_contract_version, int
        ):
            raise ValueError("parser_contract_version must be an int")
        if not isinstance(self.notices, NoticeSet):
            raise ValueError("notices must be a NoticeSet")


@dataclass(frozen=True, slots=True)
class SourceRowEnvelope:
    """One physical row: its number, its records, and whether it was rejected."""

    physical_row_number: int
    records: tuple[AppraisalSourceRecord, ...] = ()
    rejected: bool = False
    field_name: str | None = None
    notices: NoticeSet = field(default_factory=NoticeSet)

    def __post_init__(self) -> None:
        if (
            isinstance(self.physical_row_number, bool)
            or not isinstance(self.physical_row_number, int)
            or self.physical_row_number < 1
        ):
            raise ValueError("physical_row_number must be a one-based int")
        if not isinstance(self.records, tuple) or not all(
            isinstance(entry, AppraisalSourceRecord) for entry in self.records
        ):
            raise ValueError("records must be a tuple of AppraisalSourceRecord")
        if not isinstance(self.rejected, bool):
            raise ValueError("rejected must be a bool")
        if self.field_name is not None and (
            not isinstance(self.field_name, str) or not self.field_name.strip()
        ):
            raise ValueError("field_name must be a non-blank str or None")
        if not isinstance(self.notices, NoticeSet):
            raise ValueError("notices must be a NoticeSet")
        for notice in self.notices.retained:
            if notice.physical_row_number not in (None, self.physical_row_number):
                raise ValueError("a row notice may not name a row it did not come from")


def record_disagreement(
    record: AppraisalSourceRecord,
    prepared: PreparedRelease,
    envelope: SourceRowEnvelope,
) -> str | None:
    """Name the first field on which a record disagrees with where it arrived.

    A record that disagrees with its release is evidence of a reader defect, and
    staging it would attribute a row to a release or a position it did not come
    from.  Returning the field name rather than a bool lets the diagnostic say
    which one, without carrying either value.
    """

    provenance = record.provenance
    for name, arrived, expected in (
        ("jurisdiction_code", record.jurisdiction_code, prepared.jurisdiction_code),
        ("release_identifier", provenance.release_identifier, prepared.release_identifier),
        ("source_member_name", provenance.source_member_name, prepared.source_member_name),
        (
            "parser_contract_version",
            provenance.parser_contract_version,
            prepared.parser_contract_version,
        ),
        ("layout_fingerprint", provenance.layout_fingerprint, prepared.layout_fingerprint),
        ("source_row_number", provenance.source_row_number, envelope.physical_row_number),
    ):
        if arrived != expected:
            return name
    return None
