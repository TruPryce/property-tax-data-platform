"""The processing-run vocabulary the application owns: a reference, and an outcome.

Values only. Starting a run, holding it, resuming an abandoned one, finishing it
and the repository that does all four belong to the `processing-run` capability
and are not here — this module is what that lifecycle and the canonical load
session both carry, and neither may redefine.

Two rules in this module are enforced twice, once here and once by a database
constraint, and the whole point is that the two agree. A value this boundary
accepts must be a value that can be recorded: the evidence seal below runs at
COMMIT in `ingestion.assert_outcome_evidence_agrees`, and an outcome that
satisfies every field-level rule while failing the seal would abort the canonical
transaction after its records were written. So the seal is part of the value.

The application cannot import `property_tax_adapters` — the dependency direction
forbids it — so it holds its own copy of the boundary contract version and its
own disposition. The architecture test asserts the copy equals the adapters',
because a copy that drifts is worse than no copy at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "BOUNDARY_CONTRACT_VERSION",
    "DIAGNOSTIC_CODES",
    "DIAGNOSTIC_RETENTION_LIMIT",
    "ProcessingRunRef",
    "ReleaseDiagnosticRecord",
    "ReleaseDisposition",
    "ReleaseNoticeRecord",
    "ReleaseProcessingOutcome",
]

#: The contract this boundary implements, pinned so a consumer can tell which.
#: Mirrors the adapters' constant, which the application may not import; the
#: architecture test asserts the two are equal so the mirror cannot drift.
BOUNDARY_CONTRACT_VERSION: Final = 1

#: At most this many diagnostics or notices are retained; the total is preserved.
DIAGNOSTIC_RETENTION_LIMIT: Final = 100

#: The closed diagnostic vocabulary, as a frozen set rather than a second enum.
#: The bounded-processing boundary declares these codes and keeps the authority
#: for them; restating them as an enum here would make two places able to
#: disagree about what a diagnostic may say, and `ingestion.release_diagnostic`
#: carries `CHECK (code IN (...))`, so the database would settle the argument at
#: the write rather than at the port.
DIAGNOSTIC_CODES: Final[frozenset[str]] = frozenset(
    {
        "source_open_failed",
        "layout_rejected",
        "record_rejected",
        "duplicate_record_key",
        "stage_open_failed",
        "stage_write_failed",
        "stage_finalize_failed",
        "stage_commit_failed",
        "stage_abort_failed",
        "source_close_failed",
        "progress_callback_failed",
        "resource_limit_exceeded",
    }
)

#: A notice code is county vocabulary, open where the diagnostic vocabulary is
#: closed. `ingestion.release_notice` carries `CHECK (code ~ '^[a-z][a-z0-9_]
#: {0,63}$')`, so the rule is a grammar and not a set: checking a notice against
#: `DIAGNOSTIC_CODES` would refuse codes the database accepts, and checking a
#: diagnostic against this pattern would accept codes it refuses.
_NOTICE_CODE_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]{0,63}")

#: A bounded field, so a hostile or careless producer cannot make an outcome
#: large by answering with a megabyte where a name belongs.
MAX_FIELD_CHARS: Final = 256


def _require_optional_name(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty str or None")
    if len(value) > MAX_FIELD_CHARS:
        raise ValueError(f"{field_name} must be at most {MAX_FIELD_CHARS} characters")


def _require_optional_row(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an int or None")
    if value < 1:
        raise ValueError(f"{field_name} must be one-based, got {value}")


@dataclass(frozen=True, slots=True)
class ProcessingRunRef:
    """An opaque locator for one processing run.

    Comparable for equality, hashable, and carrying no ordering, no freshness or
    precedence meaning, and never canonical identity. The value inside is
    produced where the run is recorded — `ingestion.run.run_id` is
    `GENERATED ALWAYS AS IDENTITY` — and this type exists so no caller has to
    invent one: a port that accepted the bare value would let a number a caller
    made up name a run that was never recorded, and nothing in the signature
    would say so.

    Ordering raises rather than being merely absent. The wrapped value really is
    ascending in practice, so sorting by it is the tempting mistake, and a
    `TypeError` from somewhere else does not say why it is wrong.
    """

    value: object

    def __post_init__(self) -> None:
        if self.value is None:
            raise ValueError("value must not be None")
        try:
            hash(self.value)
        except TypeError as error:
            # A frozen wrapper around a mutable payload is not frozen: its
            # equality changes after construction, and it cannot be a key in the
            # mapping every implementation tracking runs keeps.
            raise ValueError(
                f"value must be immutable and hashable, got {type(self.value).__name__}"
            ) from error

    def _no_ordering(self, other: object) -> bool:
        raise TypeError(
            "ProcessingRunRef carries no ordering: it is an opaque locator, and a "
            "caller sorting by it would be reading a persistence detail as a fact"
        )

    __lt__ = _no_ordering
    __le__ = _no_ordering
    __gt__ = _no_ordering
    __ge__ = _no_ordering


class ReleaseDisposition(StrEnum):
    """Exactly two states, so a third cannot be invented.

    The application's own, because the dependency direction forbids importing
    the adapters'. The mapping between the two is total in both directions: a
    partial mapping would mean a release that processed successfully and then
    could not be described at this boundary.
    """

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReleaseDiagnosticRecord:
    """One failure, named by a code the closed vocabulary admits.

    Four fields and no fifth: there is nowhere to put a complete row, an
    arbitrary source value, exception text, a credential, an identity, an
    address, or a host-local path.
    """

    code: str
    field_name: str | None = None
    physical_row_number: int | None = None
    layout_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or self.code not in DIAGNOSTIC_CODES:
            raise ValueError(
                "code must be one the closed diagnostic vocabulary admits, "
                "because the database checks it against exactly that list"
            )
        _require_optional_name(self.field_name, "field_name")
        _require_optional_row(self.physical_row_number, "physical_row_number")
        _require_optional_name(self.layout_fingerprint, "layout_fingerprint")


@dataclass(frozen=True, slots=True)
class ReleaseNoticeRecord:
    """One non-fatal observation, named by a code the grammar admits.

    Three fields. It carries no layout fingerprint: a notice exists only after
    preparation returned, so the fingerprint belongs to the release and the
    outcome already carries it once. Repeating it here would invent a
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
class ReleaseProcessingOutcome:
    """What the boundary carries about one logical release, losslessly.

    Fourteen fields, and every invariant the accepted outcome record enforces
    enforced here too — including the evidence seal the database checks at
    COMMIT. An outcome that declares one diagnostic and retains none satisfies
    every field-level rule and aborts the canonical transaction, after the
    records were written, in a transaction that then has to be undone. Refusing
    it here costs a caller one exception; refusing it there costs a load.
    """

    disposition: ReleaseDisposition
    boundary_contract_version: int = BOUNDARY_CONTRACT_VERSION
    parser_contract_version: int | None = None
    layout_fingerprint: str | None = None
    diagnostics: tuple[ReleaseDiagnosticRecord, ...] = ()
    total_diagnostic_count: int = 0
    diagnostics_truncated: bool = False
    notices: tuple[ReleaseNoticeRecord, ...] = ()
    total_notice_count: int = 0
    notices_truncated: bool = False
    physical_rows_processed: int = 0
    staged_record_count: int = 0
    committed_record_count: int = 0
    rejected_row_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ReleaseDisposition):
            raise ValueError("disposition must be a ReleaseDisposition")
        # `True == 1` in Python, so equality alone would admit a bool as the
        # contract version, and `!=` alone never looks at the type at all.
        if (
            isinstance(self.boundary_contract_version, bool)
            or not isinstance(self.boundary_contract_version, int)
            or self.boundary_contract_version != BOUNDARY_CONTRACT_VERSION
        ):
            raise ValueError(
                f"boundary_contract_version must be the int {BOUNDARY_CONTRACT_VERSION}"
            )

        if self.parser_contract_version is not None and (
            isinstance(self.parser_contract_version, bool)
            or not isinstance(self.parser_contract_version, int)
        ):
            raise ValueError("parser_contract_version must be an int or None")
        _require_optional_name(self.layout_fingerprint, "layout_fingerprint")

        for name in ("diagnostics_truncated", "notices_truncated"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")

        # The two prepared fields come from one prepared release, so they are set
        # together or not at all. A half-populated outcome would describe a
        # preparation that both did and did not complete.
        prepared = (self.parser_contract_version, self.layout_fingerprint)
        if (prepared[0] is None) != (prepared[1] is None):
            raise ValueError(
                "parser_contract_version and layout_fingerprint are set together or not at all"
            )

        for name in (
            "total_diagnostic_count",
            "total_notice_count",
            "physical_rows_processed",
            "staged_record_count",
            "committed_record_count",
            "rejected_row_count",
        ):
            self._require_count(name)

        self._require_seal(
            "diagnostics",
            "total_diagnostic_count",
            "diagnostics_truncated",
            ReleaseDiagnosticRecord,
        )
        self._require_seal(
            "notices", "total_notice_count", "notices_truncated", ReleaseNoticeRecord
        )

        # One release has one layout, so a diagnostic naming a different
        # fingerprint than the outcome it arrived in describes a release that did
        # not happen. Checking each carrier alone can never catch it: both values
        # are individually valid, and only their disagreement is the defect. A
        # notice needs no such rule — it carries no fingerprint at all.
        for entry in self.diagnostics:
            if entry.layout_fingerprint != self.layout_fingerprint:
                raise ValueError(
                    "a diagnostic may not carry a layout fingerprint the outcome does not, "
                    "since one release has one layout"
                )

        accepted = self.disposition is ReleaseDisposition.ACCEPTED
        # Every diagnostic code is a failure code, so acceptance and diagnostics
        # are not independent. Notices deliberately are.
        if accepted != (self.total_diagnostic_count == 0):
            raise ValueError("a release is accepted exactly when it produced no diagnostic")
        if not accepted and self.committed_record_count != 0:
            raise ValueError("a rejected release commits no record")
        if accepted and self.committed_record_count != self.staged_record_count:
            raise ValueError("an accepted release commits what it staged")
        if accepted and self.rejected_row_count != 0:
            raise ValueError("an accepted release rejected no row")

    @property
    def accepted(self) -> bool:
        """Whether this outcome accepted the release.

        The one thing a canonical load session reads from an outcome, and it
        reads it here rather than comparing enum members at a call site.
        """

        return self.disposition is ReleaseDisposition.ACCEPTED

    def _require_count(self, name: str) -> None:
        value = getattr(self, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative int")

    def _require_seal(self, retained: str, total: str, truncated: str, entry_type: type) -> None:
        """The evidence seal, in the value rather than at COMMIT."""

        entries = getattr(self, retained)
        # The element type is the carrier. A tuple of the right length holding
        # strings would satisfy every count here while carrying exactly the free
        # text these types exist to make unrepresentable.
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
