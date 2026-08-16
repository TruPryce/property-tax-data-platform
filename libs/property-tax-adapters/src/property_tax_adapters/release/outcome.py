"""The bounded result of processing one logical release.

Everything here is what a caller is allowed to learn about a release: stable
codes, counts, and contract versions.  Nothing carries a row, a source value, or
an exception message, and there is nowhere to put one — the types have no
untyped attribute, no extras mapping, and no free-form payload.

Two channels, deliberately separate.  A **diagnostic** is a failure, and a
release is accepted exactly when it produced none.  A **notice** is a warning
that does not reject: the accepted Dallas contract requires unknown columns to
be *accepted* and reported, so one channel would have forced a conforming reader
to refuse a valid layout or discard a required warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "BOUNDARY_CONTRACT_VERSION",
    "DIAGNOSTIC_RETENTION_LIMIT",
    "DuplicateRecordKey",
    "ReleaseDiagnostic",
    "ReleaseDiagnosticCode",
    "ReleaseDisposition",
    "ReleaseNotice",
    "ReleaseOutcome",
]

#: The contract this boundary implements.  Pinned rather than merely positive:
#: a version whose initial value is unstated cannot tell a consumer which
#: contract they are looking at, which is the only thing a version is for.
BOUNDARY_CONTRACT_VERSION: Final = 1

#: At most this many diagnostics or notices are retained; the total is preserved.
DIAGNOSTIC_RETENTION_LIMIT: Final = 100

#: A notice code is county vocabulary, closed by that county's own contract, so
#: this boundary enumerates none.  The bound is what stops free text arriving
#: where a code belongs.
_NOTICE_CODE_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")


class DuplicateRecordKey(Exception):  # noqa: N818 - the accepted contract fixes this name
    """Raised by a stage whose index refuses a repeated key.

    Typed rather than textual because the processor must tell a duplicate from
    an ordinary write failure, and reading an exception message to do it is both
    forbidden by the privacy rules and unreliable across implementations.

    A stage may raise this from `write`, where an eager index detects the
    collision, or from `finalize`, where a deferred one does.
    """


class ReleaseDisposition(StrEnum):
    """Exactly two states, so a third cannot be invented."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ReleaseDiagnosticCode(StrEnum):
    """The closed boundary vocabulary: twelve codes, no thirteenth.

    Issue #43 D5 names eight as a minimum.  Four more exist because the boundary
    can genuinely reach them — opening a source, entering a stage, aborting one,
    and closing a reader — and a failure with no code would have to borrow one
    that names a different phase.
    """

    SOURCE_OPEN_FAILED = "source_open_failed"
    LAYOUT_REJECTED = "layout_rejected"
    RECORD_REJECTED = "record_rejected"
    DUPLICATE_RECORD_KEY = "duplicate_record_key"
    STAGE_OPEN_FAILED = "stage_open_failed"
    STAGE_WRITE_FAILED = "stage_write_failed"
    STAGE_FINALIZE_FAILED = "stage_finalize_failed"
    STAGE_COMMIT_FAILED = "stage_commit_failed"
    STAGE_ABORT_FAILED = "stage_abort_failed"
    SOURCE_CLOSE_FAILED = "source_close_failed"
    PROGRESS_CALLBACK_FAILED = "progress_callback_failed"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"


def _require_optional_name(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank str or None")


def _require_optional_row(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an int or None")
    if value < 1:
        raise ValueError(f"{field_name} must be one-based, got {value}")


@dataclass(frozen=True, slots=True)
class ReleaseDiagnostic:
    """One failure, named by a stable code.

    Four fields and no fifth: there is nowhere to put a complete row, an
    arbitrary source value, exception text, a credential, an identity, an
    address, or a host-local path.
    """

    code: ReleaseDiagnosticCode
    field_name: str | None = None
    physical_row_number: int | None = None
    layout_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, ReleaseDiagnosticCode):
            raise ValueError("code must be a ReleaseDiagnosticCode")
        _require_optional_name(self.field_name, "field_name")
        _require_optional_row(self.physical_row_number, "physical_row_number")
        _require_optional_name(self.layout_fingerprint, "layout_fingerprint")


@dataclass(frozen=True, slots=True)
class ReleaseNotice:
    """One non-fatal observation about a release or a row.

    Three fields.  It carries no layout fingerprint: every carrier exists only
    after preparation returned, so the fingerprint belongs to the release and
    the outcome already carries it once.  Repeating it here would invent a
    disagreement to check and a `None` to interpret.
    """

    code: str
    field_name: str | None = None
    physical_row_number: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _NOTICE_CODE_PATTERN.fullmatch(self.code) is None:
            raise ValueError(
                "code must be 1 to 64 characters matching [a-z][a-z0-9_]*, "
                "so free text cannot arrive where a code belongs"
            )
        _require_optional_name(self.field_name, "field_name")
        _require_optional_row(self.physical_row_number, "physical_row_number")


@dataclass(frozen=True, slots=True)
class ReleaseOutcome:
    """What a caller learns about one logical release.

    Fourteen fields, with the invariants stated rather than implied: an
    underspecified outcome is one every implementation renders differently,
    which is the opposite of a contract.
    """

    disposition: ReleaseDisposition
    boundary_contract_version: int = BOUNDARY_CONTRACT_VERSION
    parser_contract_version: int | None = None
    layout_fingerprint: str | None = None
    diagnostics: tuple[ReleaseDiagnostic, ...] = ()
    total_diagnostic_count: int = 0
    diagnostics_truncated: bool = False
    notices: tuple[ReleaseNotice, ...] = ()
    total_notice_count: int = 0
    notices_truncated: bool = False
    physical_rows_processed: int = 0
    staged_record_count: int = 0
    committed_record_count: int = 0
    rejected_row_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ReleaseDisposition):
            raise ValueError("disposition must be a ReleaseDisposition")
        if self.boundary_contract_version != BOUNDARY_CONTRACT_VERSION:
            raise ValueError(f"boundary_contract_version must be {BOUNDARY_CONTRACT_VERSION}")

        # The two prepared fields come from one `PreparedRelease`, so they are
        # set together or not at all.  A half-populated outcome would describe a
        # preparation that both did and did not complete.
        prepared = (self.parser_contract_version, self.layout_fingerprint)
        if (prepared[0] is None) != (prepared[1] is None):
            raise ValueError(
                "parser_contract_version and layout_fingerprint are set together or not at all"
            )

        for name in ("total_diagnostic_count", "total_notice_count"):
            self._require_count(name)
        for name in (
            "physical_rows_processed",
            "staged_record_count",
            "committed_record_count",
            "rejected_row_count",
        ):
            self._require_count(name)

        self._require_retention(
            "diagnostics", "total_diagnostic_count", "diagnostics_truncated", ReleaseDiagnostic
        )
        self._require_retention("notices", "total_notice_count", "notices_truncated", ReleaseNotice)

        accepted = self.disposition is ReleaseDisposition.ACCEPTED
        # Every diagnostic code is a failure code, so acceptance and diagnostics
        # are not independent.  Notices deliberately are.
        if accepted != (self.total_diagnostic_count == 0):
            raise ValueError("a release is accepted exactly when it produced no diagnostic")
        if not accepted and self.committed_record_count != 0:
            raise ValueError("a rejected release commits no record")
        if accepted and self.committed_record_count != self.staged_record_count:
            raise ValueError("an accepted release commits what it staged")
        if accepted and self.rejected_row_count != 0:
            raise ValueError("an accepted release rejected no row")

    def _require_count(self, name: str) -> None:
        value = getattr(self, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative int")

    def _require_retention(
        self, retained: str, total: str, truncated: str, entry_type: type
    ) -> None:
        entries = getattr(self, retained)
        # The element type is the carrier.  A tuple of the right length whose
        # entries are strings would satisfy every count here while carrying
        # exactly the free text these types exist to make unrepresentable.
        if not isinstance(entries, tuple) or not all(
            isinstance(entry, entry_type) for entry in entries
        ):
            raise ValueError(f"{retained} must be a tuple of {entry_type.__name__}")
        observed, flag = getattr(self, total), getattr(self, truncated)
        if len(entries) != min(observed, DIAGNOSTIC_RETENTION_LIMIT):
            raise ValueError(
                f"{retained} must hold min({total}, {DIAGNOSTIC_RETENTION_LIMIT}) entries, "
                "so nothing is dropped below the cap"
            )
        if flag is not (observed > DIAGNOSTIC_RETENTION_LIMIT):
            raise ValueError(f"{truncated} must be true exactly when {total} exceeds the cap")
