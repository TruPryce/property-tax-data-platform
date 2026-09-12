"""Attacks on the canonical load session, one per row of the transition table.

Every case here is named by a state component (`S0`-`S6`) or a precondition
identifier (`B1`-`B10`, `W1`-`W12`, `C1`-`C2`, `A1`, `G1`).  A case that cannot
be named in those terms is a case this capability does not have, and belongs in
the spec's table before it belongs here.

Two properties this suite exists for, neither asserted indirectly: every `B`
refusal happens at construction, with no session in sight; and after every
refusal the whole state is what it was, proven by retrying the rejected batch's
own handles and by completing to find none of its records.
"""

from __future__ import annotations

import inspect
import typing
from decimal import Decimal

import pytest
from _fake_load import (
    FakeOutcome,
    FakeRepository,
    FakeRun,
    FakeStore,
    LoadRefused,
    SuppressingSession,
)
from property_tax_application.canonical import (
    AccountSnapshotRef,
    AdoptableSnapshot,
    AdoptableSnapshotMismatch,
    AdoptedParent,
    CanonicalRecordBatch,
    CanonicalReleaseRepository,
    CorrelatedRecord,
    CorrelationHandle,
    ReleaseLoadCompletion,
    ReleaseLoadSession,
    UnknownAccountSnapshot,
    account_of,
)
from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    AppraisalValueObservation,
    ArtifactIdentity,
    DomainProvenance,
    Jurisdiction,
    LegalDescription,
    OwnerAssociation,
    OwnerObservation,
    OwnerValueAllocation,
    ReleaseIdentity,
    ReleaseKind,
    ValueKind,
)

JURISDICTION = Jurisdiction("tx", "rockwall", "48397")
RELEASE = ReleaseIdentity(JURISDICTION, 2025, ReleaseKind.CURRENT, "R-1")
OTHER_RELEASE = ReleaseIdentity(JURISDICTION, 2025, ReleaseKind.CERTIFIED, "R-9")
ARTIFACT = ArtifactIdentity("a" * 64)
PROVENANCE = DomainProvenance(RELEASE, ARTIFACT, "ACCOUNT.DAT", 1, 1)
SECOND_PROVENANCE = DomainProvenance(RELEASE, ArtifactIdentity("b" * 64), "GIS.DAT", 1, 1)
ACCOUNT = AccountIdentity(JURISDICTION, "100")
OTHER_ACCOUNT = AccountIdentity(JURISDICTION, "200")


def snapshot(account: AccountIdentity = ACCOUNT, **kwargs: object) -> AccountSnapshot:
    return AccountSnapshot(account, kwargs.pop("provenance", PROVENANCE), **kwargs)  # type: ignore[arg-type]


def owner(parent: AccountSnapshot, name: str = "OWNER") -> OwnerObservation:
    return OwnerObservation(parent, name, PROVENANCE)


def value(parent: AccountSnapshot, amount: str = "100") -> AppraisalValueObservation:
    return AppraisalValueObservation(parent, ValueKind.MARKET, Decimal(amount), PROVENANCE)


def handle(number: int) -> CorrelationHandle:
    return CorrelationHandle(number)


def session(
    *, accepted: bool = True, maximum: int = 8, store: FakeStore | None = None, run: str = "run-1"
):
    repository = FakeRepository(store, max_batch_entries=maximum)
    return repository, repository.open_load(RELEASE, FakeRun(run), FakeOutcome(accepted))


# --------------------------------------------------------------------------
# The state machine: S0, the initial state, and the operations
# --------------------------------------------------------------------------


def test_a_session_opens_in_the_initial_state() -> None:
    _, load = session()

    status, open_account, staged, mappings, high_water = load.state
    assert status == "OPEN"
    assert open_account is None
    assert staged == ()
    assert mappings == ()
    assert high_water is None
    assert load.max_batch_entries == 8
    # The first handle a session sees is judged on its own merits, not against
    # an implied zero.
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot(), handle(1)),)))


def test_the_state_is_exactly_six_components_and_live_is_the_key_set_of_mappings() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )

    assert load.live == frozenset({handle(1)})
    assert {key for key, _ in load.state[3]} == load.live


def test_opening_is_refused_when_the_context_cannot_be_completed() -> None:
    repository = FakeRepository(max_batch_entries=0)

    with pytest.raises(LoadRefused) as refusal:
        repository.open_load(RELEASE, FakeRun("run-1"), FakeOutcome())

    assert refusal.value.rule == "S0"


def test_two_sessions_for_one_release_and_run_both_open() -> None:
    store = FakeStore()
    repository = FakeRepository(store)

    first = repository.open_load(RELEASE, FakeRun("run-1"), FakeOutcome())
    second = repository.open_load(RELEASE, FakeRun("run-1"), FakeOutcome())

    assert first is not second


def test_every_operation_after_a_terminal_one_is_refused() -> None:
    for ending in ("commit", "abort"):
        _, load = session()
        getattr(load, ending)()
        for operation in ("write", "commit", "abort"):
            with pytest.raises(LoadRefused) as refusal:
                if operation == "write":
                    load.write(CanonicalRecordBatch())
                else:
                    getattr(load, operation)()
            assert refusal.value.rule == "G1"


# --------------------------------------------------------------------------
# B1-B10: refused at construction, with no session in sight
# --------------------------------------------------------------------------


def test_b1_refuses_an_entry_that_is_not_a_canonical_record() -> None:
    with pytest.raises(ValueError, match="canonical record"):
        CorrelatedRecord("not a record")  # type: ignore[arg-type]


def test_b1_does_not_refuse_two_entries_carrying_equal_records() -> None:
    # The no-key rule: refusing the second would be deduplication over observed
    # values, which this boundary forbids.
    first, second = snapshot(), snapshot()
    assert first == second and first is not second

    batch = CanonicalRecordBatch(
        entries=(CorrelatedRecord(first), CorrelatedRecord(second)), closing=None
    )

    assert len(batch.entries) == 2


def test_b2_refuses_a_handle_introduced_twice_across_entries_and_adoptions() -> None:
    parent = snapshot()
    with pytest.raises(ValueError, match="introduced twice"):
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)), CorrelatedRecord(snapshot(), handle(1)))
        )

    adopted = AdoptableSnapshot(AccountSnapshotRef("ref-1"), snapshot())
    with pytest.raises(ValueError, match="introduced twice"):
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),),
            adoptions=(AdoptedParent(adopted, handle(1)),),
        )


def test_b3_refuses_a_delta_that_names_one_handle_twice() -> None:
    for delta in ("retain", "release"):
        with pytest.raises(ValueError, match="more than once"):
            CanonicalRecordBatch(**{delta: (handle(1), handle(1))})


def test_b4_refuses_a_handle_named_in_both_deltas() -> None:
    with pytest.raises(ValueError, match="both deltas"):
        CanonicalRecordBatch(retain=(handle(1),), release=(handle(1),))


def test_b5_refuses_releasing_a_handle_the_batch_introduces() -> None:
    with pytest.raises(ValueError, match="introduced and released"):
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(snapshot(), handle(1)),), release=(handle(1),)
        )


def test_b6_refuses_an_entry_naming_its_own_handle_as_its_parent() -> None:
    with pytest.raises(ValueError, match="own handle"):
        CorrelatedRecord(snapshot(), handle(1), handle(1))


def test_b6_accepts_a_parent_handle_the_batch_does_not_introduce() -> None:
    # The companion case: a rule that refused these would forbid naming a parent
    # from an earlier batch at all, which is what W5 exists to decide.
    parent = snapshot()
    batch = CanonicalRecordBatch(entries=(CorrelatedRecord(owner(parent), None, handle(7)),))

    assert batch.entries[0].parent == handle(7)


def test_b7_refuses_an_in_batch_parent_that_denotes_another_record() -> None:
    first, second = snapshot(), snapshot(OTHER_ACCOUNT)
    with pytest.raises(ValueError, match="does not hold"):
        CanonicalRecordBatch(
            entries=(
                CorrelatedRecord(first, handle(1)),
                CorrelatedRecord(second, handle(2)),
                CorrelatedRecord(owner(first), None, handle(2)),
            )
        )


def test_b7_compares_by_identity_and_not_by_value() -> None:
    first, second = snapshot(), snapshot()
    assert first == second

    with pytest.raises(ValueError, match="does not hold"):
        CanonicalRecordBatch(
            entries=(
                CorrelatedRecord(first, handle(1)),
                CorrelatedRecord(owner(second), None, handle(1)),
            )
        )


def test_b9_refuses_a_child_holding_a_snapshot_the_adoption_does_not_carry() -> None:
    adopted, equal = snapshot(), snapshot()
    candidate = AdoptableSnapshot(AccountSnapshotRef("ref-1"), adopted)

    with pytest.raises(ValueError, match="does not hold"):
        CanonicalRecordBatch(
            adoptions=(AdoptedParent(candidate, handle(1)),),
            entries=(CorrelatedRecord(owner(equal), None, handle(1)),),
        )


def test_b10_refuses_one_account_named_as_both_continuing_and_closing() -> None:
    with pytest.raises(ValueError, match="both continuing and closing"):
        CanonicalRecordBatch(continuing=ACCOUNT, closing=ACCOUNT)


def test_a_correlation_handle_is_an_integer_that_is_not_a_bool() -> None:
    for rejected in (True, False, 0, -1, 1.0, "1"):
        with pytest.raises(ValueError):
            CorrelationHandle(rejected)  # type: ignore[arg-type]
    assert CorrelationHandle(1).value == 1


# --------------------------------------------------------------------------
# W1-W12: refused on write, by the session that has the history
# --------------------------------------------------------------------------


def test_w2_refuses_a_batch_larger_than_the_stated_maximum() -> None:
    _, load = session(maximum=2)
    parent = snapshot()
    batch = CanonicalRecordBatch(
        entries=(CorrelatedRecord(parent, handle(1)), CorrelatedRecord(owner(parent))),
        retain=(handle(1),),
        continuing=ACCOUNT,
    )
    assert batch.size == 3

    with pytest.raises(LoadRefused) as refusal:
        load.write(batch)

    assert refusal.value.rule == "W2"


def test_the_caller_reads_the_maximum_before_building_a_batch() -> None:
    _, load = session(maximum=3)

    assert load.max_batch_entries == 3
    assert isinstance(load.max_batch_entries, int) and not isinstance(load.max_batch_entries, bool)


def test_w3_refuses_a_handle_that_does_not_exceed_the_high_water_mark() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(5)),), continuing=ACCOUNT, retain=(handle(5),)
        )
    )

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(owner(parent), handle(3)),), continuing=ACCOUNT
            )
        )

    assert refusal.value.rule == "W3"


def test_w3_refuses_a_handle_already_live() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(5)),), continuing=ACCOUNT, retain=(handle(5),)
        )
    )

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(owner(parent), handle(5)),), continuing=ACCOUNT
            )
        )

    assert refusal.value.rule == "W3"


def test_w5_refuses_a_parent_that_was_never_introduced() -> None:
    _, load = session()

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(entries=(CorrelatedRecord(owner(snapshot()), None, handle(9)),))
        )

    assert refusal.value.rule == "W5"


def test_w5_refuses_a_parent_whose_account_has_completed() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(owner(parent)),)))  # completes it

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(entries=(CorrelatedRecord(owner(parent), None, handle(1)),))
        )

    assert refusal.value.rule == "W5"


def test_w5_refuses_a_live_handle_that_denotes_another_record() -> None:
    _, load = session()
    first = snapshot()
    other = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(first, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(owner(other), None, handle(1)),), continuing=ACCOUNT
            )
        )

    assert refusal.value.rule == "W5"


def test_w6_and_w7_refuse_deltas_naming_handles_that_are_neither_live_nor_introduced() -> None:
    _, load = session()
    parent = snapshot()

    with pytest.raises(LoadRefused) as retained:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(parent, handle(1)),),
                retain=(handle(4),),
                continuing=ACCOUNT,
            )
        )
    assert retained.value.rule == "W6"

    with pytest.raises(LoadRefused) as released:
        load.write(CanonicalRecordBatch(release=(handle(4),)))
    assert released.value.rule == "W7"


def test_w8_holds_as_an_invariant_a_caller_cannot_reach_through_the_surface() -> None:
    """Every live handle belongs to the open account, so a delta cannot name another's.

    W8 says an account is open in a batch by what the batch *carries*, never by
    what its deltas name — the rule that stops a delta being its own evidence.
    Its direct violation turns out to be unreachable while W9 holds: W9 confines
    every retained handle to the continuing account, the success transition
    sweeps the rest at completion, so S4 only ever holds the open account's
    handles, and W7 confines a release to S4.  The reachable attempt lands on
    W9, and what is proven here is the invariant W8 guards rather than a refusal
    it cannot produce.
    """

    _, load = session()
    first = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(first, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    assert {account for _, (_, account) in load.state[3]} == {ACCOUNT} == {load.state[1]}

    # Trying to open a second account's handles by naming them is refused before
    # W8 can be reached: the batch would have to retain a handle of an account it
    # does not carry onward.
    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(snapshot(OTHER_ACCOUNT), handle(2)),),
                retain=(handle(2),),
                continuing=ACCOUNT,
            )
        )
    assert refusal.value.rule == "W9"

    # And the invariant still holds afterwards, the refusal having changed nothing.
    assert {account for _, (_, account) in load.state[3]} == {ACCOUNT}


def test_w9_refuses_retaining_a_handle_of_an_account_the_batch_completes() -> None:
    _, load = session()
    parent = snapshot()

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(parent, handle(1)),), retain=(handle(1),)
            )
        )

    assert refusal.value.rule == "W9"


def test_w10_is_satisfied_by_carrying_the_open_account() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )

    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(owner(parent)),)))

    assert load.state[1] is None  # the account completed with that batch
    assert load.live == frozenset()


def test_w10_is_satisfied_by_a_delta_alone_which_is_why_it_needs_s4() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )

    # No entry of the account at all: only S4 says the released handle is its.
    load.write(CanonicalRecordBatch(release=(handle(1),)))

    assert load.state[1] is None


def test_w10_is_satisfied_by_carrying_the_account_onward() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )

    load.write(CanonicalRecordBatch(continuing=ACCOUNT))

    assert load.state[1] == ACCOUNT
    assert load.live == frozenset({handle(1)})


def test_w10_is_satisfied_by_an_empty_batch_that_declares_the_account_closing() -> None:
    """The only satisfier available to an account with too many live handles."""

    _, load = session(maximum=2)
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(owner(parent), handle(2)),),
            continuing=ACCOUNT,
            retain=(handle(2),),
        )
    )
    assert len(load.live) == 2 == load.max_batch_entries

    empty = CanonicalRecordBatch(closing=ACCOUNT)
    assert empty.size == 0
    load.write(empty)

    assert load.live == frozenset()
    assert load.state[1] is None
    assert load.commit().already_complete is False


def test_w10_refuses_a_batch_that_abandons_the_open_account() -> None:
    _, load = session()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(snapshot(), handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )

    with pytest.raises(LoadRefused) as refusal:
        load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot(OTHER_ACCOUNT)),)))

    assert refusal.value.rule == "W10"


def test_w11_refuses_continuing_an_account_nothing_has_begun() -> None:
    _, load = session()

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(snapshot(), handle(1)),), continuing=OTHER_ACCOUNT
            )
        )

    assert refusal.value.rule == "W11"


def test_w11_permits_carrying_the_open_account_onward_while_carrying_none_of_it() -> None:
    _, load = session()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(snapshot(), handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )

    load.write(CanonicalRecordBatch(continuing=ACCOUNT))

    assert load.state[1] == ACCOUNT


def test_w12_refuses_closing_an_account_that_is_not_the_open_one() -> None:
    _, load = session()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(snapshot(), handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )

    with pytest.raises(LoadRefused) as refusal:
        load.write(CanonicalRecordBatch(closing=OTHER_ACCOUNT, continuing=ACCOUNT))

    assert refusal.value.rule == "W12"


# --------------------------------------------------------------------------
# The failure rows: every refusal leaves the whole state as it was
# --------------------------------------------------------------------------


def test_every_refusal_leaves_all_six_components_exactly_as_they_were() -> None:
    _, load = session(maximum=3)
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    before = load.state

    refusals = (
        CanonicalRecordBatch(  # W2
            entries=(
                CorrelatedRecord(owner(parent), handle(2)),
                CorrelatedRecord(owner(parent, "B"), handle(3)),
            ),
            retain=(handle(2), handle(3)),
            continuing=ACCOUNT,
        ),
        CanonicalRecordBatch(  # W3
            entries=(CorrelatedRecord(owner(parent), handle(1)),), continuing=ACCOUNT
        ),
        CanonicalRecordBatch(  # W5
            entries=(CorrelatedRecord(owner(parent), None, handle(99)),), continuing=ACCOUNT
        ),
        CanonicalRecordBatch(release=(handle(42),), continuing=ACCOUNT),  # W7
        CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot(OTHER_ACCOUNT)),)),  # W10
    )
    for batch in refusals:
        with pytest.raises(LoadRefused):
            load.write(batch)
        assert load.state == before


def test_a_corrected_retry_reuses_the_handles_its_rejected_attempt_introduced() -> None:
    _, load = session(maximum=2)
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )

    oversized = CanonicalRecordBatch(
        entries=(
            CorrelatedRecord(owner(parent), handle(7)),
            CorrelatedRecord(owner(parent, "B"), handle(8)),
        ),
        retain=(handle(7), handle(8)),
        continuing=ACCOUNT,
    )
    with pytest.raises(LoadRefused):
        load.write(oversized)

    # The high-water mark did not move, so the very same handles are still free.
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(owner(parent), handle(7)),), continuing=ACCOUNT
        )
    )
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(owner(parent, "B"), handle(8)),)))

    assert load.commit().already_complete is False


def test_a_refused_batch_contributes_no_records_to_the_completed_load() -> None:
    store = FakeStore()
    _, load = session(store=store)
    parent = snapshot()
    kept = owner(parent, "KEPT")
    rejected = owner(parent, "REJECTED")

    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    with pytest.raises(LoadRefused):
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(rejected, handle(1)),), continuing=ACCOUNT
            )
        )
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(kept),)))
    load.commit()

    persisted = store.loads[(RELEASE, FakeRun("run-1"))]
    assert kept in persisted
    assert rejected not in persisted


def test_a_refused_batch_carrying_adoptions_adopts_nothing() -> None:
    store = FakeStore()
    persisted = snapshot()
    candidate = store.persist_snapshot(AccountSnapshotRef("ref-1"), RELEASE, persisted)
    _, load = session(store=store, maximum=1)
    before = load.state

    with pytest.raises(LoadRefused):
        load.write(
            CanonicalRecordBatch(
                adoptions=(AdoptedParent(candidate, handle(1)),),
                entries=(CorrelatedRecord(owner(persisted)),),
                continuing=ACCOUNT,
                retain=(handle(1),),
            )
        )

    assert load.state == before


# --------------------------------------------------------------------------
# The success row, applied together and at the batch boundary
# --------------------------------------------------------------------------


def test_a_released_handle_resolves_for_every_record_of_its_own_batch() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )

    # The release is declared by the same batch whose records name the handle,
    # and records sit on both sides of it.
    load.write(
        CanonicalRecordBatch(
            entries=(
                CorrelatedRecord(owner(parent), None, handle(1)),
                CorrelatedRecord(value(parent), None, handle(1)),
            ),
            release=(handle(1),),
            continuing=ACCOUNT,
        )
    )
    assert load.live == frozenset()

    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(owner(parent), None, handle(1)),), continuing=ACCOUNT
            )
        )
    assert refusal.value.rule == "W5"


def test_a_handle_introduced_and_not_retained_never_enters_the_mappings() -> None:
    _, load = session()
    parent = snapshot()

    load.write(
        CanonicalRecordBatch(
            entries=(
                CorrelatedRecord(parent, handle(1)),
                CorrelatedRecord(owner(parent), None, handle(1)),
            ),
            continuing=ACCOUNT,
        )
    )

    assert load.live == frozenset()


def test_an_account_spans_several_batches_without_re_declaring_its_parents() -> None:
    _, load = session()
    parent = snapshot()
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(parent, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    for index in range(3):
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(owner(parent, f"OWNER-{index}"), None, handle(1)),),
                continuing=ACCOUNT,
            )
        )

    assert load.live == frozenset({handle(1)})


# --------------------------------------------------------------------------
# C1, C2 and the three completion branches
# --------------------------------------------------------------------------


def test_c2_refuses_a_completion_with_an_account_still_open_and_the_close_repairs_it() -> None:
    store = FakeStore()
    _, load = session(store=store)
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(snapshot(), handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )

    with pytest.raises(LoadRefused) as refusal:
        load.commit()
    assert refusal.value.rule == "C2"

    load.write(CanonicalRecordBatch(closing=ACCOUNT))
    assert load.commit().already_complete is False


def test_the_accepted_branch_makes_records_and_outcome_durable_together() -> None:
    store = FakeStore()
    _, load = session(store=store)
    parent = snapshot()
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(parent),)))

    completion = load.commit()

    key = (RELEASE, FakeRun("run-1"))
    assert completion.already_complete is False
    assert store.loads[key] == (parent,)
    assert store.outcomes[key].accepted is True


def test_the_rejected_branch_records_the_outcome_and_discards_the_records() -> None:
    store = FakeStore()
    _, load = session(store=store, accepted=False)
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))

    completion = load.commit()

    key = (RELEASE, FakeRun("run-1"))
    assert completion.already_complete is False
    assert key not in store.loads
    assert store.outcomes[key].accepted is False


def test_the_already_complete_branch_wins_over_the_rejected_one() -> None:
    """Both conditions hold; only the first may apply.

    Overwriting the earlier completion's outcome would make the retry key a lie:
    the pairing already recorded one.
    """

    store = FakeStore()
    _, first = session(store=store)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()
    before = dict(store.outcomes)

    _, retry = session(store=store, accepted=False)
    retry.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    completion = retry.commit()

    assert completion.already_complete is True
    assert store.outcomes == before
    assert len(store.loads[(RELEASE, FakeRun("run-1"))]) == 1


def test_a_second_distinct_run_is_a_new_load_and_both_are_retained() -> None:
    store = FakeStore()
    _, first = session(store=store, run="run-1")
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()

    _, second = session(store=store, run="run-2")
    second.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    completion = second.commit()

    assert completion.already_complete is False
    assert (RELEASE, FakeRun("run-1")) in store.loads
    assert (RELEASE, FakeRun("run-2")) in store.loads


def test_two_sessions_completing_one_pairing_yield_exactly_one_load() -> None:
    store = FakeStore()
    _, first = session(store=store)
    _, second = session(store=store)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    second.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))

    completions = (first.commit(), second.commit())

    assert [completion.already_complete for completion in completions] == [False, True]
    assert len(store.loads[(RELEASE, FakeRun("run-1"))]) == 1


def test_an_abort_leaves_an_earlier_sessions_durable_records_untouched() -> None:
    store = FakeStore()
    _, first = session(store=store)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()
    persisted = dict(store.loads)

    _, retry = session(store=store)
    retry.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    retry.abort()

    assert store.loads == persisted


def test_an_abort_succeeds_with_an_account_open_and_leaves_zero_records() -> None:
    store = FakeStore()
    _, load = session(store=store)
    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(snapshot(), handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )

    assert load.abort() is None
    assert store.loads == {}


# --------------------------------------------------------------------------
# Adoption, carried by the batch
# --------------------------------------------------------------------------


def test_an_adopted_parent_states_its_binding_rather_than_implying_it() -> None:
    store = FakeStore()
    first = snapshot()
    second = snapshot(provenance=SECOND_PROVENANCE)
    one = store.persist_snapshot(AccountSnapshotRef("ref-1"), RELEASE, first)
    two = store.persist_snapshot(AccountSnapshotRef("ref-2"), RELEASE, second)

    # Reordering the adoptions changes nothing: the pairing is in the value.
    forwards = CanonicalRecordBatch(
        adoptions=(AdoptedParent(one, handle(1)), AdoptedParent(two, handle(2)))
    )
    backwards = CanonicalRecordBatch(
        adoptions=(AdoptedParent(two, handle(2)), AdoptedParent(one, handle(1)))
    )

    def binding(batch: CanonicalRecordBatch) -> dict[CorrelationHandle, object]:
        return {adoption.handle: adoption.candidate.snapshot for adoption in batch.adoptions}

    assert binding(forwards) == binding(backwards)
    assert binding(forwards)[handle(1)] is first


def test_an_adopted_handle_is_an_introduced_handle_under_every_rule() -> None:
    store = FakeStore()
    persisted = snapshot()
    candidate = store.persist_snapshot(AccountSnapshotRef("ref-1"), RELEASE, persisted)
    _, load = session(store=store)

    # B2 counts it, the success transition retains it, and a child names it.
    load.write(
        CanonicalRecordBatch(
            adoptions=(AdoptedParent(candidate, handle(1)),),
            entries=(CorrelatedRecord(owner(persisted), None, handle(1)),),
            continuing=ACCOUNT,
            retain=(handle(1),),
        )
    )
    assert load.live == frozenset({handle(1)})

    # W3 judges it like any other: it moved the high-water mark.
    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(owner(persisted), handle(1)),), continuing=ACCOUNT
            )
        )
    assert refusal.value.rule == "W3"

    # And it is released by the completion of its account, like any other.
    load.write(CanonicalRecordBatch(closing=ACCOUNT))
    assert load.live == frozenset()


def test_adoption_creates_no_observation_and_the_child_keeps_its_own_lineage() -> None:
    store = FakeStore()
    persisted = snapshot()
    candidate = store.persist_snapshot(AccountSnapshotRef("ref-1"), RELEASE, persisted)
    _, load = session(store=store)
    child = OwnerObservation(persisted, "ENRICHED", SECOND_PROVENANCE)

    load.write(
        CanonicalRecordBatch(
            adoptions=(AdoptedParent(candidate, handle(1)),),
            entries=(CorrelatedRecord(child, None, handle(1)),),
        )
    )
    load.commit()

    persisted_records = store.loads[(RELEASE, FakeRun("run-1"))]
    assert persisted_records == (child,)
    assert child.provenance is SECOND_PROVENANCE
    assert child.snapshot is persisted


def test_w4_refuses_a_locator_that_resolves_to_nothing_or_to_another_release() -> None:
    store = FakeStore()
    _, load = session(store=store)
    unknown = AdoptableSnapshot(AccountSnapshotRef("missing"), snapshot())
    with pytest.raises(UnknownAccountSnapshot):
        load.write(CanonicalRecordBatch(adoptions=(AdoptedParent(unknown, handle(1)),)))

    elsewhere = snapshot()
    store.persist_snapshot(AccountSnapshotRef("ref-other"), OTHER_RELEASE, elsewhere)
    with pytest.raises(UnknownAccountSnapshot):
        load.write(
            CanonicalRecordBatch(
                adoptions=(
                    AdoptedParent(
                        AdoptableSnapshot(AccountSnapshotRef("ref-other"), elsewhere), handle(1)
                    ),
                ),
            )
        )


def test_w4_refuses_a_candidate_whose_halves_disagree() -> None:
    store = FakeStore()
    located = snapshot()
    store.persist_snapshot(AccountSnapshotRef("ref-1"), RELEASE, located)
    _, load = session(store=store)
    assembled = AdoptableSnapshot(AccountSnapshotRef("ref-1"), snapshot())  # equal, not the same

    with pytest.raises(AdoptableSnapshotMismatch):
        load.write(CanonicalRecordBatch(adoptions=(AdoptedParent(assembled, handle(1)),)))


def test_two_candidates_sharing_a_provenance_are_distinct_and_adopting_one_picks_it() -> None:
    store = FakeStore()
    first = AccountSnapshot(ACCOUNT, PROVENANCE, legal_description=LegalDescription("LOT 1"))
    second = AccountSnapshot(ACCOUNT, PROVENANCE, legal_description=LegalDescription("LOT 2"))
    store.persist_snapshot(AccountSnapshotRef("ref-1"), RELEASE, first)
    store.persist_snapshot(AccountSnapshotRef("ref-2"), RELEASE, second)
    repository = FakeRepository(store)

    candidates = list(repository.adoptable_snapshots(ACCOUNT, RELEASE))
    assert len(candidates) == 2
    chosen = next(one for one in candidates if one.snapshot is second)

    load = repository.open_load(RELEASE, FakeRun("run-1"), FakeOutcome())
    child = OwnerObservation(second, "OWNER", SECOND_PROVENANCE)
    load.write(
        CanonicalRecordBatch(
            adoptions=(AdoptedParent(chosen, handle(1)),),
            entries=(CorrelatedRecord(child, None, handle(1)),),
        )
    )

    assert child.snapshot is second


def test_candidates_are_drawn_lazily() -> None:
    store = FakeStore()
    for index in range(5):
        store.persist_snapshot(
            AccountSnapshotRef(f"ref-{index}"),
            RELEASE,
            AccountSnapshot(
                ACCOUNT, PROVENANCE, legal_description=LegalDescription(f"LOT {index}")
            ),
        )
    repository = FakeRepository(store)

    candidates = repository.adoptable_snapshots(ACCOUNT, RELEASE)
    assert store.candidates_drawn == 0
    next(candidates)

    assert store.candidates_drawn == 1


def test_a_parent_that_is_not_an_account_snapshot_is_not_adoptable() -> None:
    with pytest.raises(ValueError, match="AccountSnapshot"):
        AdoptableSnapshot(AccountSnapshotRef("ref-1"), owner(snapshot()))  # type: ignore[arg-type]


def test_the_locator_carries_equality_and_no_ordering() -> None:
    assert AccountSnapshotRef("ref-1") == AccountSnapshotRef("ref-1")
    assert AccountSnapshotRef("ref-1") != AccountSnapshotRef("ref-2")
    with pytest.raises(TypeError, match="no ordering"):
        _ = AccountSnapshotRef("ref-1") < AccountSnapshotRef("ref-2")


# --------------------------------------------------------------------------
# The signatures, and suppression as a behaviour
# --------------------------------------------------------------------------


def test_the_protocol_signatures_are_what_the_table_requires() -> None:
    hints = typing.get_type_hints(ReleaseLoadSession.__exit__)
    assert hints["return"] is type(None)
    assert typing.get_type_hints(ReleaseLoadSession.write)["return"] is type(None)
    assert typing.get_type_hints(ReleaseLoadSession.abort)["return"] is type(None)
    assert typing.get_type_hints(ReleaseLoadSession.commit)["return"] is ReleaseLoadCompletion
    assert isinstance(inspect.getattr_static(ReleaseLoadSession, "max_batch_entries"), property)
    assert typing.get_type_hints(ReleaseLoadSession.__enter__)["return"] is ReleaseLoadSession
    assert set(inspect.signature(CanonicalReleaseRepository.open_load).parameters) == {
        "self",
        "release",
        "run",
        "outcome",
    }


def test_write_raises_rather_than_returning_a_refusal() -> None:
    _, load = session(maximum=1)
    accepted = load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))

    assert accepted is None
    with pytest.raises(LoadRefused):
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(snapshot()), CorrelatedRecord(snapshot()))
            )
        )


def test_commit_returns_a_completion_for_a_retry_rather_than_raising() -> None:
    store = FakeStore()
    _, first = session(store=store)
    first.commit()

    _, retry = session(store=store)
    completion = retry.commit()

    assert isinstance(completion, ReleaseLoadCompletion)
    assert completion.already_complete is True


def test_an_exception_inside_the_block_reaches_the_caller_and_leaves_no_records() -> None:
    store = FakeStore()
    repository = FakeRepository(store)

    with pytest.raises(RuntimeError, match="parse failed"):
        with repository.open_load(RELEASE, FakeRun("run-1"), FakeOutcome()) as load:
            load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
            raise RuntimeError("parse failed")

    assert store.loads == {}


def test_an_implementation_that_suppresses_the_failure_is_caught_by_the_exception() -> None:
    """The annotation is a claim; the propagation is what proves it.

    A `-> None` annotation stops nothing at runtime, so the suite has to observe
    the exception rather than read the signature.
    """

    store = FakeStore()
    suppressing = SuppressingSession(store, RELEASE, FakeRun("run-1"), FakeOutcome(), 8)

    escaped = True
    try:
        with suppressing:
            raise RuntimeError("parse failed")
    except RuntimeError:
        escaped = False

    assert escaped, "the exception was swallowed, which is the violation this test names"


def test_the_no_key_rule_retains_what_the_model_admits() -> None:
    store = FakeStore()
    _, load = session(store=store)
    parent = snapshot()
    first_child = owner(parent, "A")
    second_child = owner(parent, "B")
    twin_a, twin_b = value(parent), value(parent)
    assert twin_a == twin_b and twin_a is not twin_b

    load.write(
        CanonicalRecordBatch(
            entries=(
                CorrelatedRecord(parent),
                CorrelatedRecord(first_child),
                CorrelatedRecord(second_child),
                CorrelatedRecord(twin_a),
                CorrelatedRecord(twin_b),
            )
        )
    )
    load.commit()

    persisted = store.loads[(RELEASE, FakeRun("run-1"))]
    assert len(persisted) == 5


def test_the_account_of_every_canonical_record_is_reachable_without_a_correlation_value() -> None:
    parent = snapshot()
    association = OwnerAssociation(parent, owner(parent), PROVENANCE)
    allocation = OwnerValueAllocation(association, ValueKind.MARKET, Decimal("1"), PROVENANCE)

    for record in (parent, owner(parent), association, allocation, value(parent)):
        assert account_of(record) == ACCOUNT
