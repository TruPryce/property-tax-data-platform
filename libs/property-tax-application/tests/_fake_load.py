"""An in-memory `ReleaseLoadSession`, written to be falsified.

The transition table in the `canonical-load-session` spec is the specification
this implements: `S0`-`S6`, `G1`, `W1`-`W12`, `C1`-`C2`, `A1`.  It exists so the
contract can be attacked without a database, and it is deliberately the simplest
thing that can honour every row — a real adapter chooses staging and merge
mechanics the port says nothing about.

Every refusal computes before it mutates.  That is not a style choice: the
failure row of each transition requires `S1`-`S6` to be exactly what they were,
and an implementation that applied as it validated could not offer that.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType

from property_tax_application.canonical import (
    AccountSnapshotRef,
    AdoptableSnapshot,
    AdoptableSnapshotMismatch,
    CanonicalRecordBatch,
    CorrelationHandle,
    ReleaseLoadCompletion,
    UnknownAccountSnapshot,
    account_of,
)
from property_tax_domain import AccountIdentity, AccountSnapshot, ReleaseIdentity


class LoadRefused(Exception):  # noqa: N818 - named for the rule it carries
    """A refusal carrying the precondition identifier that produced it."""

    def __init__(self, rule: str, detail: str = "") -> None:
        super().__init__(f"{rule}: {detail}" if detail else rule)
        self.rule = rule


@dataclass(frozen=True, slots=True)
class FakeRun:
    """Stands in for `ProcessingRunRef` until `processing-run` lands."""

    value: str


@dataclass(frozen=True, slots=True)
class FakeOutcome:
    """Stands in for `ReleaseProcessingOutcome`; only its disposition is used."""

    accepted: bool = True


class FakeStore:
    """What survives a session: durable loads, outcomes, and persisted snapshots."""

    def __init__(self) -> None:
        self.loads: dict[tuple[ReleaseIdentity, FakeRun], tuple[object, ...]] = {}
        self.outcomes: dict[tuple[ReleaseIdentity, FakeRun], FakeOutcome] = {}
        self._snapshots: dict[AccountSnapshotRef, tuple[ReleaseIdentity, AccountSnapshot]] = {}
        self.candidates_drawn = 0

    def persist_snapshot(
        self, ref: AccountSnapshotRef, release: ReleaseIdentity, snapshot: AccountSnapshot
    ) -> AdoptableSnapshot:
        self._snapshots[ref] = (release, snapshot)
        return AdoptableSnapshot(ref, snapshot)

    def resolve(self, ref: AccountSnapshotRef) -> tuple[ReleaseIdentity, AccountSnapshot] | None:
        return self._snapshots.get(ref)

    def candidates(
        self, account: AccountIdentity, release: ReleaseIdentity
    ) -> Iterator[AdoptableSnapshot]:
        for ref, (persisted_release, snapshot) in self._snapshots.items():
            if persisted_release == release and snapshot.identity == account:
                self.candidates_drawn += 1
                yield AdoptableSnapshot(ref, snapshot)


class FakeRepository:
    """Opens sessions, and answers which parents an account already offers."""

    def __init__(self, store: FakeStore | None = None, *, max_batch_entries: int = 8) -> None:
        self.store = store if store is not None else FakeStore()
        self._max_batch_entries = max_batch_entries

    def open_load(
        self, release: ReleaseIdentity, run: FakeRun, outcome: FakeOutcome
    ) -> FakeSession:
        # `S0` must be complete, and a refused open leaves no session at all.
        if not isinstance(release, ReleaseIdentity):
            raise LoadRefused("S0", "release")
        if run is None:
            raise LoadRefused("S0", "run")
        if outcome is None:
            raise LoadRefused("S0", "outcome")
        maximum = self._max_batch_entries
        if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
            raise LoadRefused("S0", "max_batch_entries")
        return FakeSession(self.store, release, run, outcome, maximum)

    def adoptable_snapshots(
        self, account: AccountIdentity, release: ReleaseIdentity
    ) -> Iterator[AdoptableSnapshot]:
        return self.store.candidates(account, release)


class FakeSession:
    """`S1`-`S6` over a fixed `S0`, and the three operations."""

    def __init__(
        self,
        store: FakeStore,
        release: ReleaseIdentity,
        run: FakeRun,
        outcome: FakeOutcome,
        max_batch_entries: int,
    ) -> None:
        self._store = store
        self._release = release  # S0
        self._run = run  # S0
        self._outcome = outcome  # S0
        self._max_batch_entries = max_batch_entries  # S0
        self._status = "OPEN"  # S1
        self._open_account: AccountIdentity | None = None  # S2
        self._staged: list[object] = []  # S3
        self._mappings: dict[CorrelationHandle, tuple[object, AccountIdentity]] = {}  # S4
        self._high_water: int | None = None  # S6

    # -- the state, readable so a test can compare it byte for byte ----------

    @property
    def max_batch_entries(self) -> int:
        return self._max_batch_entries

    @property
    def state(self) -> tuple[object, ...]:
        return (
            self._status,
            self._open_account,
            tuple(self._staged),
            tuple(sorted(self._mappings.items(), key=lambda item: item[0].value)),
            self._high_water,
        )

    @property
    def live(self) -> frozenset[CorrelationHandle]:
        """`S5`: the key set of `S4`, never a second structure."""

        return frozenset(self._mappings)

    # -- write ---------------------------------------------------------------

    def write(self, batch: CanonicalRecordBatch) -> None:
        if self._status != "OPEN":
            raise LoadRefused("G1", self._status)  # W1
        if batch.size > self._max_batch_entries:
            raise LoadRefused("W2", f"{batch.size} > {self._max_batch_entries}")

        introduced = batch.introduced
        for handle in introduced:
            if self._high_water is not None and handle.value <= self._high_water:
                raise LoadRefused("W3", f"{handle.value} <= {self._high_water}")
            if handle in self._mappings:
                raise LoadRefused("W3", f"{handle.value} is live")

        for adoption in batch.adoptions:  # W4
            located = self._store.resolve(adoption.candidate.ref)
            if located is None or located[0] != self._release:
                raise UnknownAccountSnapshot(str(adoption.candidate.ref.value))
            if located[1] is not adoption.candidate.snapshot:
                raise AdoptableSnapshotMismatch(str(adoption.candidate.ref.value))

        in_batch = {handle: index for index, handle in enumerate(introduced)}
        for entry in batch.entries:  # W5
            if entry.parent is None or entry.parent in in_batch:
                continue
            if entry.parent not in self._mappings:
                raise LoadRefused("W5", f"{entry.parent.value} is not live")
            denoted, _ = self._mappings[entry.parent]
            if _held_parent(entry.record) is not denoted:
                raise LoadRefused("W5", f"{entry.parent.value} denotes another record")

        introduced_set = frozenset(introduced)
        for handle in batch.retain:  # W6
            if handle not in introduced_set and handle not in self._mappings:
                raise LoadRefused("W6", str(handle.value))
        for handle in batch.release:  # W7
            if handle not in self._mappings:
                raise LoadRefused("W7", str(handle.value))

        accounts = self._accounts_of_batch(batch)
        carried = batch.carried_accounts
        open_here = carried | ({self._open_account} if self._open_account else frozenset())
        for handle in batch.retain + batch.release:  # W8
            if accounts[handle] not in open_here:
                raise LoadRefused("W8", str(handle.value))
        for handle in batch.retain:  # W9
            if batch.continuing is None or accounts[handle] != batch.continuing:
                raise LoadRefused("W9", str(handle.value))

        if self._open_account is not None:  # W10
            touched = self._open_account in carried or any(
                accounts[handle] == self._open_account for handle in batch.retain + batch.release
            )
            if not (
                batch.continuing == self._open_account
                or batch.closing == self._open_account
                or touched
            ):
                raise LoadRefused("W10", str(self._open_account.source_account_id))
        if batch.continuing is not None and batch.continuing not in open_here:  # W11
            raise LoadRefused("W11", str(batch.continuing.source_account_id))
        if batch.closing is not None and batch.closing != self._open_account:  # W12
            raise LoadRefused("W12", str(batch.closing.source_account_id))

        self._apply(batch, accounts, carried)

    def _apply(
        self,
        batch: CanonicalRecordBatch,
        accounts: dict[CorrelationHandle, AccountIdentity],
        carried: frozenset[AccountIdentity],
    ) -> None:
        """The success row, applied together and at the batch boundary."""

        denoted = _denoted_by(batch)
        self._staged.extend(entry.record for entry in batch.entries)
        introduced = batch.introduced
        if introduced:
            self._high_water = max(handle.value for handle in introduced)

        for handle in batch.retain:
            self._mappings[handle] = (
                denoted.get(handle, self._mappings.get(handle, (None,))[0]),
                accounts[handle],
            )
        for handle in batch.release:
            self._mappings.pop(handle, None)

        completing = set(carried)
        if self._open_account is not None:
            completing.add(self._open_account)
        if batch.closing is not None:
            completing.add(batch.closing)
        completing.discard(batch.continuing)
        for handle, (_, account) in list(self._mappings.items()):
            if account in completing:
                del self._mappings[handle]

        self._open_account = batch.continuing

    def _accounts_of_batch(
        self, batch: CanonicalRecordBatch
    ) -> dict[CorrelationHandle, AccountIdentity]:
        accounts: dict[CorrelationHandle, AccountIdentity] = {}
        for entry in batch.entries:
            if entry.handle is not None:
                accounts[entry.handle] = account_of(entry.record)
        for adoption in batch.adoptions:
            accounts[adoption.handle] = adoption.candidate.snapshot.identity
        for handle, (_, account) in self._mappings.items():
            accounts.setdefault(handle, account)
        return accounts

    # -- commit and abort ----------------------------------------------------

    def commit(self) -> ReleaseLoadCompletion:
        if self._status != "OPEN":
            raise LoadRefused("G1", self._status)  # C1
        if self._open_account is not None:
            raise LoadRefused("C2", str(self._open_account.source_account_id))

        key = (self._release, self._run)
        if key in self._store.loads:  # branch 1
            completion = ReleaseLoadCompletion(self._run, True)
        elif not self._outcome.accepted:  # branch 2
            self._store.outcomes[key] = self._outcome
            completion = ReleaseLoadCompletion(self._run, False)
        else:  # branch 3
            self._store.loads[key] = tuple(self._staged)
            self._store.outcomes[key] = self._outcome
            completion = ReleaseLoadCompletion(self._run, False)

        self._status = "COMMITTED"
        self._clear()
        return completion

    def abort(self) -> None:
        if self._status != "OPEN":
            raise LoadRefused("G1", self._status)  # A1
        self._status = "ABORTED"
        self._clear()

    def _clear(self) -> None:
        self._open_account = None
        self._staged.clear()
        self._mappings.clear()

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._status == "OPEN":
            self.abort()


class SuppressingSession(FakeSession):
    """A session that swallows the failure, so a test can catch it doing so."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:  # type: ignore[override]
        if self._status == "OPEN":
            self.abort()
        return True


def _held_parent(record: object) -> object | None:
    from property_tax_domain import OwnerValueAllocation

    if isinstance(record, AccountSnapshot):
        return None
    if isinstance(record, OwnerValueAllocation):
        return record.association
    return getattr(record, "snapshot", None)


def _denoted_by(batch: CanonicalRecordBatch) -> dict[CorrelationHandle, object]:
    denoted: dict[CorrelationHandle, object] = {}
    for entry in batch.entries:
        if entry.handle is not None:
            denoted[entry.handle] = entry.record
    for adoption in batch.adoptions:
        denoted[adoption.handle] = adoption.candidate.snapshot
    return denoted
