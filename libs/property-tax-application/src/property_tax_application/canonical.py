"""The canonical load session: one logical release load as a closed state machine.

The `canonical-load-session` capability spec is the authority for everything in
this module.  It defines the fixed context `S0`, the six state components
`S1`-`S6`, the three operations, and every precondition by identifier: `B1`-`B10`
are intrinsic to a batch and enforced here, in `CanonicalRecordBatch`; `W1`-`W12`,
`C1`-`C2`, `A1` and the general rule `G1` need session history and belong to an
implementation of `ReleaseLoadSession`.

Nothing here performs I/O, and nothing names a schema, table, cursor, connection,
transaction, bulk-load mechanism, conflict clause, or surrogate key.  The port is
what an adapter implements and what a use case reads; how a handle becomes a
generated key is the adapter's to choose, subject to the table.

Two names this module uses are **cited, not owned**: `ProcessingRunRef` and
`ReleaseProcessingOutcome` belong to the `processing-run` capability, which is
planned in the sibling change `add-application-port-boundary` and not yet
implemented.  They appear here as the narrow structural protocols this port
actually requires — a run it carries opaquely, and an outcome whose disposition
selects a completion branch — and are deliberately absent from the package's
public surface, so the concrete types replace them without a name collision.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, runtime_checkable

from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    AppraisalValueObservation,
    ExemptionObservation,
    GeometryObservation,
    ImprovementObservation,
    LandObservation,
    OwnerAssociation,
    OwnerObservation,
    OwnerValueAllocation,
    ReleaseIdentity,
    TaxableValueObservation,
    TaxingUnitObservation,
)

__all__ = [
    "AccountSnapshotRef",
    "AdoptableSnapshot",
    "AdoptableSnapshotMismatch",
    "AdoptedParent",
    "CanonicalRecord",
    "CanonicalRecordBatch",
    "CanonicalReleaseRepository",
    "CorrelatedRecord",
    "CorrelationHandle",
    "ReleaseLoadCompletion",
    "ReleaseLoadSession",
    "UnknownAccountSnapshot",
    "account_of",
]

#: Every canonical record the boundary accepts.  A union rather than a base
#: class: the domain model has no common ancestor, and inventing one here would
#: put a persistence concern into the vocabulary.
CanonicalRecord = (
    AccountSnapshot
    | OwnerObservation
    | OwnerAssociation
    | OwnerValueAllocation
    | AppraisalValueObservation
    | TaxableValueObservation
    | ExemptionObservation
    | GeometryObservation
    | ImprovementObservation
    | LandObservation
    | TaxingUnitObservation
)

_CANONICAL_RECORD_TYPES = (
    AccountSnapshot,
    OwnerObservation,
    OwnerAssociation,
    OwnerValueAllocation,
    AppraisalValueObservation,
    TaxableValueObservation,
    ExemptionObservation,
    GeometryObservation,
    ImprovementObservation,
    LandObservation,
    TaxingUnitObservation,
)


def account_of(record: CanonicalRecord) -> AccountIdentity:
    """The account a canonical record belongs to.

    Which account a batch *carries* is settled from its records alone, never from
    its deltas — the spec's `W8` turns on that, because a rule that permits a
    delta may not take the delta as its evidence.  Every record reaches its
    account by the parent it already holds, so no correlation value is consulted
    and no new key is invented.
    """

    if isinstance(record, AccountSnapshot):
        return record.identity
    if isinstance(record, OwnerValueAllocation):
        return record.association.snapshot.identity
    if isinstance(record, _CANONICAL_RECORD_TYPES):
        return record.snapshot.identity
    raise ValueError(f"not a canonical record: {type(record).__name__}")


class UnknownAccountSnapshot(Exception):  # noqa: N818 - the accepted plan fixes this name
    """An adoption's locator resolves to no snapshot of the release being loaded.

    Distinct from `AdoptableSnapshotMismatch` because they are different facts: a
    caller that cannot separate them cannot tell a stale locator from an assembly
    mistake.
    """


class AdoptableSnapshotMismatch(Exception):  # noqa: N818 - the accepted plan fixes this name
    """An adoption's locator resolves to a snapshot other than the one it carries."""


def _require_handle_value(value: object, field: str) -> int:
    # A boolean is an `int` in Python, so `True` would otherwise pass as a
    # handle equal to one.  The guard is the one `archives.py` already writes.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an int that is not a bool, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{field} must be at least 1, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class CorrelationHandle:
    """A session-local name for a parent, and nothing else.

    Neither domain identity nor persistence identity: it exists only so a record
    written in a later batch can name a parent written in an earlier one, it
    appears in no stored row, and it stops resolving once its account completes.
    Unique within one session and strictly increasing, so a value released by a
    completed account cannot be minted again and silently retargeted.
    """

    value: int

    def __post_init__(self) -> None:
        _require_handle_value(self.value, "value")


@dataclass(frozen=True, slots=True)
class CorrelatedRecord:
    """One canonical record, the handle it may be named by, and its parent's.

    Correlation rides on the batch rather than on the record: the canonical
    types hold their parents directly and gain no correlation field.
    """

    record: CanonicalRecord
    handle: CorrelationHandle | None = None
    parent: CorrelationHandle | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.record, _CANONICAL_RECORD_TYPES):
            raise ValueError(f"record must be a canonical record, got {type(self.record).__name__}")
        if self.handle is not None and not isinstance(self.handle, CorrelationHandle):
            raise ValueError(
                f"handle must be a CorrelationHandle, got {type(self.handle).__name__}"
            )
        if self.parent is not None and not isinstance(self.parent, CorrelationHandle):
            raise ValueError(
                f"parent must be a CorrelationHandle, got {type(self.parent).__name__}"
            )
        if self.handle is not None and self.handle == self.parent:
            # B6.  A record cannot be its own parent, and this is the only thing
            # about parents a batch can settle without the session: a parent
            # handle the batch does not introduce is left to `W5`, because a
            # batch cannot know whether one is live.
            raise ValueError("an entry may not name its own handle as its parent")


@dataclass(frozen=True, slots=True)
class AccountSnapshotRef:
    """An opaque locator for a persisted account snapshot.

    Opaque on the same terms as any persistence-generated handle: it supports
    equality and carries no ordering, no structure a caller may parse, and no
    meaning outside the implementation that produced it.
    """

    value: object

    def __post_init__(self) -> None:
        if self.value is None:
            raise ValueError("value must not be None")

    def __lt__(self, other: object) -> bool:
        raise TypeError("AccountSnapshotRef carries no ordering")

    def __le__(self, other: object) -> bool:
        raise TypeError("AccountSnapshotRef carries no ordering")

    def __gt__(self, other: object) -> bool:
        raise TypeError("AccountSnapshotRef carries no ordering")

    def __ge__(self, other: object) -> bool:
        raise TypeError("AccountSnapshotRef carries no ordering")


@dataclass(frozen=True, slots=True)
class AdoptableSnapshot:
    """A locator paired with the snapshot it locates.

    The pair, never the locator alone: a child naming an adopted parent is held
    to the same object-identity check an in-batch parent gets, and that needs the
    object.  Never the grain and never provenance alone either — the accepted
    persistence contract makes the grain deliberately non-unique and retains two
    snapshots that share a load, release and provenance while differing only in a
    composed situs or legal value, so each of those names more than one snapshot.
    """

    ref: AccountSnapshotRef
    snapshot: AccountSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.ref, AccountSnapshotRef):
            raise ValueError(f"ref must be an AccountSnapshotRef, got {type(self.ref).__name__}")
        if not isinstance(self.snapshot, AccountSnapshot):
            raise ValueError(
                f"snapshot must be an AccountSnapshot, got {type(self.snapshot).__name__}"
            )


@dataclass(frozen=True, slots=True)
class AdoptedParent:
    """One candidate and the one handle a batch binds to it.

    The binding is carried rather than inferred.  Parallel sequences of
    candidates and handles would make it positional, and a reader of one batch
    could not say which handle denotes which snapshot without counting.
    """

    candidate: AdoptableSnapshot
    handle: CorrelationHandle

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, AdoptableSnapshot):
            raise ValueError(
                f"candidate must be an AdoptableSnapshot, got {type(self.candidate).__name__}"
            )
        if not isinstance(self.handle, CorrelationHandle):
            raise ValueError(
                f"handle must be a CorrelationHandle, got {type(self.handle).__name__}"
            )


@dataclass(frozen=True, slots=True)
class CanonicalRecordBatch:
    """A bounded batch of correlated records, and how it leaves the open account.

    Validates exactly `B1`-`B10` — everything a frozen value that knows only
    itself can settle.  It judges neither `S4`, nor `S6`, nor its own size
    against `max_batch_entries`, knowing none of them: those are `W` rules, and a
    rule a party cannot enforce is worse than none.
    """

    entries: tuple[CorrelatedRecord, ...] = ()
    adoptions: tuple[AdoptedParent, ...] = ()
    continuing: AccountIdentity | None = None
    closing: AccountIdentity | None = None
    retain: tuple[CorrelationHandle, ...] = ()
    release: tuple[CorrelationHandle, ...] = ()

    def __post_init__(self) -> None:
        self._require_shapes()
        introduced = self._introduced_handles()  # B2
        self._require_no_repetition()  # B3
        self._require_no_contradiction()  # B4
        self._require_no_release_of_introduced(introduced)  # B5
        self._require_in_batch_parents_denote_their_records()  # B7, B9
        self._require_one_continuation()  # B8, B10

    # B1: every entry is well-formed.  Deliberately no rule about records being
    # distinct — two entries carrying equal canonical records are two records and
    # both persist, because refusing the second would be a deduplication rule
    # over observed values, which this boundary forbids.
    def _require_shapes(self) -> None:
        for name, value, item_type in (
            ("entries", self.entries, CorrelatedRecord),
            ("adoptions", self.adoptions, AdoptedParent),
            ("retain", self.retain, CorrelationHandle),
            ("release", self.release, CorrelationHandle),
        ):
            if not isinstance(value, tuple):
                raise ValueError(f"{name} must be a tuple, got {type(value).__name__}")
            for item in value:
                if not isinstance(item, item_type):
                    raise ValueError(
                        f"{name} must contain {item_type.__name__}, got {type(item).__name__}"
                    )
        for name, account in (("continuing", self.continuing), ("closing", self.closing)):
            if account is not None and not isinstance(account, AccountIdentity):
                raise ValueError(f"{name} must be an AccountIdentity, got {type(account).__name__}")

    def _introduced_handles(self) -> frozenset[CorrelationHandle]:
        """B2: no handle is introduced twice, entries and adoptions together.

        An adoption's handle is introduced by this batch for every purpose the
        table names, so it shares this rule rather than acquiring one of its own.
        """

        seen: set[CorrelationHandle] = set()
        for handle in self.introduced:
            if handle in seen:
                raise ValueError(f"handle introduced twice within the batch: {handle.value}")
            seen.add(handle)
        return frozenset(seen)

    def _require_no_repetition(self) -> None:
        # B3.  Refused rather than counted twice against `max_batch_entries` or
        # quietly collapsed, for the reason a handle introduced twice is.
        for name, delta in (("retain", self.retain), ("release", self.release)):
            if len(set(delta)) != len(delta):
                raise ValueError(f"{name} names one handle more than once")

    def _require_no_contradiction(self) -> None:
        # B4.  There is no correct order to pick: retain-then-release and
        # release-then-retain give opposite results for the same batch.
        both = set(self.retain) & set(self.release)
        if both:
            value = sorted(handle.value for handle in both)[0]
            raise ValueError(f"handle {value} is named in both deltas")

    def _require_no_release_of_introduced(self, introduced: frozenset[CorrelationHandle]) -> None:
        # B5.  Redundant rather than permitted: an introduced handle the batch
        # does not retain is released at the end of it anyway.
        redundant = introduced & set(self.release)
        if redundant:
            value = sorted(handle.value for handle in redundant)[0]
            raise ValueError(f"handle {value} is introduced and released by the same batch")

    def _require_in_batch_parents_denote_their_records(self) -> None:
        """B7 and B9: an in-batch parent must be the very object the child holds.

        Requiring a parent merely to *resolve* would let a child naming one
        observation be persisted under another of the same kind, and no database
        constraint catches that, because both parents are legitimate.  Compared
        by identity, never by value: two equal snapshots are two observations.
        """

        by_handle: dict[CorrelationHandle, object] = {}
        for entry in self.entries:
            if entry.handle is not None:
                by_handle[entry.handle] = entry.record
        for adoption in self.adoptions:
            by_handle[adoption.handle] = adoption.candidate.snapshot

        for entry in self.entries:
            if entry.parent is None or entry.parent not in by_handle:
                # A parent this batch does not introduce is not the batch's to
                # judge; `W5` decides whether it is live and what it denotes.
                continue
            held = _parent_object_of(entry.record)
            if held is None:
                raise ValueError(
                    f"{type(entry.record).__name__} holds no parent to check a handle against"
                )
            if held is not by_handle[entry.parent]:
                raise ValueError(
                    f"handle {entry.parent.value} denotes a record this entry does not hold"
                )

    def _require_one_continuation(self) -> None:
        # B8: at most one account continues, so at most one is ever open across a
        # batch boundary.  B10: an account is not both continued and closed —
        # the batch sees that contradiction without any history.
        if self.continuing is not None and self.continuing == self.closing:
            raise ValueError("one account is named as both continuing and closing")

    @property
    def introduced(self) -> tuple[CorrelationHandle, ...]:
        """Every handle this batch introduces, entry handles and adoptions alike."""

        return tuple(entry.handle for entry in self.entries if entry.handle is not None) + tuple(
            adoption.handle for adoption in self.adoptions
        )

    @property
    def size(self) -> int:
        """What `W2` measures: entries plus adoptions plus each delta's values."""

        return len(self.entries) + len(self.adoptions) + len(self.retain) + len(self.release)

    def carries(self, account: AccountIdentity) -> bool:
        """Whether the batch holds a record or an adoption of `account`.

        Settled from records alone.  A batch that merely names one of an
        account's handles in a delta does not carry it, which is what keeps `W8`
        from taking a delta as the evidence for that same delta.
        """

        return account in self.carried_accounts

    @property
    def carried_accounts(self) -> frozenset[AccountIdentity]:
        """The accounts this batch carries, from its records and adoptions."""

        accounts = {account_of(entry.record) for entry in self.entries}
        accounts |= {adoption.candidate.snapshot.identity for adoption in self.adoptions}
        return frozenset(accounts)


def _parent_object_of(record: CanonicalRecord) -> object | None:
    """The parent a canonical record already holds, or None for a snapshot."""

    if isinstance(record, AccountSnapshot):
        return None
    if isinstance(record, OwnerValueAllocation):
        return record.association
    if isinstance(record, OwnerAssociation):
        # An association holds two parents; the snapshot is the one a handle
        # names, and the owner is reached through the association itself.
        return record.snapshot
    return record.snapshot


@runtime_checkable
class ProcessingRunRef(Protocol):
    """The run this load belongs to, carried opaquely.

    Cited, not owned: `processing-run` defines the concrete value, and this port
    requires nothing of it but that it exist and compare by equality.  Stated as
    a protocol so the session can be written and proven before that capability
    lands, and kept out of the package's public surface so the concrete type
    replaces it without a name collision.
    """


@runtime_checkable
class ReleaseProcessingOutcome(Protocol):
    """The run's outcome, whose disposition selects a completion branch.

    Cited, not owned, like `ProcessingRunRef`.  The session needs exactly one
    thing from it — whether the release was accepted — because the completion
    persists a rejected run's outcome and discards its records.
    """

    @property
    def accepted(self) -> bool:
        """Whether this outcome accepted the release."""


@dataclass(frozen=True, slots=True)
class ReleaseLoadCompletion:
    """What a completion reports: the run, and whether the load already happened.

    Deliberately no locator per account.  A caller wanting to name a snapshot it
    just wrote uses the handle it already has, and a result that handed back one
    locator per account would grow with the release.
    """

    run: ProcessingRunRef
    already_complete: bool

    def __post_init__(self) -> None:
        if isinstance(self.already_complete, bool) is False:
            raise ValueError(
                f"already_complete must be a bool, got {type(self.already_complete).__name__}"
            )


@runtime_checkable
class ReleaseLoadSession(Protocol):
    """One logical release load, as the transition table defines it.

    Three operations and no more.  There is no operation that adopts a parent —
    adoption is carried by a batch, so a refused batch adopts nothing — and none
    that declares an account complete, which `continuing` and `closing` already
    settle inside the batch that carries them.

    Every failure leaves the whole state unchanged: `S1`-`S6` are each exactly
    what they were, staged records and the high-water mark included.  A refusal
    is raised rather than returned, so a caller cannot walk past one by
    discarding a result.
    """

    @property
    def max_batch_entries(self) -> int:
        """What one batch may carry: entries plus adoptions plus each delta's values.

        An integer of at least one that is not a boolean, fixed for the session,
        and readable so a caller sizes what it builds rather than discovering the
        bound by being refused.
        """

    def write(self, batch: CanonicalRecordBatch) -> None:
        """Accept one batch, or refuse it and change nothing.

        Enforces `W1`-`W12` against session history.  Nothing becomes durable
        here whatever is accepted.
        """

    def commit(self) -> ReleaseLoadCompletion:
        """End the load, taking the first completion branch that applies.

        Already loaded by this release and run, and nothing is persisted at all,
        not even the outcome; otherwise rejected, and the outcome is recorded
        while the records are discarded; otherwise the records and the outcome
        become durable together.  Refused by `C2` while an account is still open.
        """

    def abort(self) -> None:
        """End the load, leaving zero canonical records of its own."""

    def __enter__(self) -> ReleaseLoadSession:
        """Enter the load, returning the session itself."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Leave the load without suppressing anything.

        Annotated `-> None` rather than `-> bool` so the type says what the
        contract requires, and required to *behave* that way: an exception raised
        inside the block reaches the caller, because an implementation returning
        a truthy value would swallow it whatever the annotation said.
        """


@runtime_checkable
class CanonicalReleaseRepository(Protocol):
    """Where a canonical load begins, and where adoptable parents are found."""

    def open_load(
        self,
        release: ReleaseIdentity,
        run: ProcessingRunRef,
        outcome: ReleaseProcessingOutcome,
    ) -> ReleaseLoadSession:
        """Open a session for one release, run and outcome.

        Refused rather than opened when that context cannot be completed, a
        maximum that is not a usable count included, so a refused open leaves no
        session and nothing to abort.  Two sessions for one release and run both
        open: the retry key decides between them at completion, not here.
        """

    def adoptable_snapshots(
        self, account: AccountIdentity, release: ReleaseIdentity
    ) -> Iterator[AdoptableSnapshot]:
        """The snapshots an account and release already offer for adoption.

        An iterator, and lazily drawn: one acquisition may persist several
        snapshots at one grain, so no accepted contract bounds how many there
        are, and an implementation must not draw them all before the caller
        consumes the first.
        """
