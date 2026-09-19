"""Attacks on the canonical load session, one per row of the transition table.

Every case here is named by a state component (`S0`-`S6`) or a precondition
identifier (`B1`-`B10`, `W1`-`W7`, `W9`-`W12`, `C1`-`C2`, `A1`, `G1`, and the
derived invariant `I1`).  A case that cannot
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
from typing import Protocol

import pytest
from _fake_load import (
    FakeRepository,
    FakeStore,
    LoadRefused,
    SuppressingSession,
    outcome,
    run,
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
    *,
    accepted: bool = True,
    maximum: int = 8,
    store: FakeStore | None = None,
    run_id: str = "run-1",
):
    repository = FakeRepository(store, max_batch_entries=maximum)
    return repository, repository.open_load(RELEASE, run(run_id), outcome(accepted=accepted))


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
        repository.open_load(RELEASE, run("run-1"), outcome())

    assert refusal.value.rule == "S0"


def test_two_sessions_for_one_release_and_run_both_open() -> None:
    store = FakeStore()
    repository = FakeRepository(store)

    first = repository.open_load(RELEASE, run("run-1"), outcome())
    second = repository.open_load(RELEASE, run("run-1"), outcome())

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
# W1-W7 and W9-W12: refused on write, by the session that has the history
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


def live_accounts(state: tuple[object, ...]) -> set[object]:
    """The accounts `S4` holds handles for — what `I1` constrains."""

    return {account for _, (_, account) in state[3]}


def require_i1(load: object) -> None:
    """`I1`: every live handle belongs to the account `S2` names.

    Asserted from out here rather than inside the session. A subject checking
    its own invariant proves nothing — the check and the behaviour would fail
    together and the suite would never know.
    """

    state = load.state  # type: ignore[attr-defined]
    accounts = live_accounts(state)
    assert not accounts or accounts == {state[1]}, (
        f"I1 violated: S4 holds handles of {accounts} while S2 is {state[1]}"
    )


def test_i1_holds_after_every_operation_accepted_or_refused() -> None:
    """Account scope is a derived invariant, not a reachable refusal.

    `W9` confines a retained handle to the continuing account, the success
    transition releases the rest at completion, and `W7` confines a release to
    what is live — so `S4` only ever holds the open account's handles and a
    delta has no other account's handle to name.  An earlier draft demanded a
    `W8` refusal for it, which no implementation could produce and no test could
    reach except by triggering `W9` and calling it something else.
    """

    _, load = session()
    first = snapshot()

    load.write(
        CanonicalRecordBatch(
            entries=(CorrelatedRecord(first, handle(1)),), continuing=ACCOUNT, retain=(handle(1),)
        )
    )
    require_i1(load)
    assert live_accounts(load.state) == {ACCOUNT} == {load.state[1]}

    # The reachable attempt to hold a second account's handle lands on W9.
    with pytest.raises(LoadRefused) as refusal:
        load.write(
            CanonicalRecordBatch(
                entries=(CorrelatedRecord(snapshot(OTHER_ACCOUNT), handle(2)),),
                retain=(handle(2),),
                continuing=ACCOUNT,
            )
        )
    assert refusal.value.rule == "W9"

    # I1 holds after the refusal too, which is the obligation that replaced it.
    require_i1(load)
    assert live_accounts(load.state) == {ACCOUNT}

    load.write(CanonicalRecordBatch(closing=ACCOUNT))
    assert live_accounts(load.state) == set() and load.state[1] is None


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
        require_i1(load)


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

    persisted = store.loads[(RELEASE, run("run-1"))]
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

    key = (RELEASE, run("run-1"))
    assert completion.already_complete is False
    assert store.loads[key] == (parent,)
    assert store.outcomes[key].accepted is True


def test_the_rejected_branch_records_the_outcome_and_discards_the_records() -> None:
    store = FakeStore()
    _, load = session(store=store, accepted=False)
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))

    completion = load.commit()

    key = (RELEASE, run("run-1"))
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
    assert len(store.loads[(RELEASE, run("run-1"))]) == 1


def test_a_second_distinct_run_is_a_new_load_and_both_are_retained() -> None:
    store = FakeStore()
    _, first = session(store=store, run_id="run-1")
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()

    _, second = session(store=store, run_id="run-2")
    second.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    completion = second.commit()

    assert completion.already_complete is False
    assert (RELEASE, run("run-1")) in store.loads
    assert (RELEASE, run("run-2")) in store.loads


def test_two_sessions_completing_one_pairing_yield_exactly_one_load() -> None:
    store = FakeStore()
    _, first = session(store=store)
    _, second = session(store=store)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    second.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))

    completions = (first.commit(), second.commit())

    assert [completion.already_complete for completion in completions] == [False, True]
    assert len(store.loads[(RELEASE, run("run-1"))]) == 1


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

    persisted_records = store.loads[(RELEASE, run("run-1"))]
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

    load = repository.open_load(RELEASE, run("run-1"), outcome())
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
        with repository.open_load(RELEASE, run("run-1"), outcome()) as load:
            load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
            raise RuntimeError("parse failed")

    assert store.loads == {}


def test_an_implementation_that_suppresses_the_failure_is_caught_by_the_exception() -> None:
    """The annotation is a claim; the propagation is what proves it.

    A `-> None` annotation stops nothing at runtime, so the suite has to observe
    the exception rather than read the signature.
    """

    store = FakeStore()
    suppressing = SuppressingSession(store, RELEASE, run("run-1"), outcome(), 8)

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

    persisted = store.loads[(RELEASE, run("run-1"))]
    assert len(persisted) == 5


def test_the_account_of_every_canonical_record_is_reachable_without_a_correlation_value() -> None:
    parent = snapshot()
    association = OwnerAssociation(parent, owner(parent), PROVENANCE)
    allocation = OwnerValueAllocation(association, ValueKind.MARKET, Decimal("1"), PROVENANCE)

    for record in (parent, owner(parent), association, allocation, value(parent)):
        assert account_of(record) == ACCOUNT


# --------------------------------------------------------------------------
# Retry: a rejected completion is a completion
# --------------------------------------------------------------------------


def test_a_rejected_completion_is_itself_retry_idempotent() -> None:
    """Completion is recorded, never inferred from the rows it persisted.

    The rejected branch persists no record, so a pairing judged by its rows
    would look incomplete forever: each retry would rewrite the outcome the
    first completion recorded, and with an insert-only role the second write
    would fail outright.
    """

    store = FakeStore()
    _, first = session(store=store, accepted=False)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()
    recorded = dict(store.outcomes)

    _, retry = session(store=store, accepted=False)
    completion = retry.commit()

    assert completion.already_complete is True
    assert store.outcomes == recorded, "the recorded outcome is never rewritten"
    assert (RELEASE, run()) not in store.loads


def test_a_retry_of_a_rejected_pairing_carrying_an_accepted_outcome_persists_nothing() -> None:
    """The case that manufactures a load for a run whose outcome says rejected."""

    store = FakeStore()
    _, first = session(store=store, accepted=False)
    first.commit()

    _, retry = session(store=store, accepted=True)
    retry.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    completion = retry.commit()

    assert completion.already_complete is True
    assert (RELEASE, run()) not in store.loads
    assert store.outcomes[(RELEASE, run())].accepted is False


def test_two_sessions_racing_a_rejected_pairing_yield_one_completion() -> None:
    store = FakeStore()
    _, first = session(store=store, accepted=False)
    _, second = session(store=store, accepted=False)

    completions = (first.commit(), second.commit())

    assert [completion.already_complete for completion in completions] == [False, True]
    assert len(store.outcomes) == 1


# --------------------------------------------------------------------------
# The locator carries what a locator may carry
# --------------------------------------------------------------------------


def test_the_locator_refuses_a_mutable_or_unhashable_value() -> None:
    """Opacity is not permission to carry anything.

    The store indexes candidates by these locators and a caller may put one in a
    set, so a frozen wrapper around a mutable payload is not frozen: its
    equality changes after construction and its hash raises.
    """

    for rejected_value in ([], {}, set(), (["mutable"],)):
        with pytest.raises(ValueError, match="exactly a str or an int"):
            AccountSnapshotRef(rejected_value)

    with pytest.raises(ValueError, match="must not be None"):
        AccountSnapshotRef(None)


def test_the_locator_is_held_to_the_same_rule_as_the_run_reference() -> None:
    """ "Same terms as `ProcessingRunRef`" means the same check, not a weaker one.

    It borrows the owner's rule rather than restating it: exact types, so a
    subclass overriding `__hash__` to read mutable state cannot slip through an
    `isinstance`; flat, because no key this locator names is a composite of
    composites; non-empty, because a locator that locates nothing is not one.
    """

    class SneakyStr(str):
        key = 1

        def __hash__(self) -> int:
            return hash(self.key)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, SneakyStr) and other.key == self.key

    payload = SneakyStr("ref-1")
    assert isinstance(payload, str), "it passes the check exact typing replaced"

    with pytest.raises(ValueError, match="exactly a str or an int"):
        AccountSnapshotRef(payload)
    with pytest.raises(ValueError, match="must not be an empty tuple"):
        AccountSnapshotRef(())
    with pytest.raises(ValueError, match="element must be exactly a str or an int"):
        AccountSnapshotRef((1, (2, 3)))

    for value in ("ref-1", 7, (2026, "ref-1")):
        assert AccountSnapshotRef(value).value == value


def test_the_locator_hashes_and_indexes_what_it_locates() -> None:
    first, same, other = (
        AccountSnapshotRef("ref-1"),
        AccountSnapshotRef("ref-1"),
        AccountSnapshotRef("ref-2"),
    )

    assert hash(first) == hash(same)
    assert len({first, same, other}) == 2
    assert {first: "snapshot"}[same] == "snapshot"


def test_the_run_reference_the_session_carries_is_the_owned_type() -> None:
    """No substitute: the empty protocol that accepted every object is gone."""

    import property_tax_application.canonical as canonical
    from property_tax_application.runs import ProcessingRunRef

    assert canonical.ProcessingRunRef is ProcessingRunRef
    assert not isinstance(canonical.ProcessingRunRef, type(Protocol))
    for raw in (None, 7, "raw-run-id"):
        assert not isinstance(raw, ProcessingRunRef)


# --------------------------------------------------------------------------
# The boundary refuses the raw values the owned types exist to exclude
# --------------------------------------------------------------------------


def test_open_load_refuses_a_raw_run_id_or_a_raw_outcome() -> None:
    """Not an instance check in a test — the port itself has to refuse them.

    Asserting that a raw value is not an instance of `ProcessingRunRef` says
    nothing about what `open_load` does when handed one. It used to hand back a
    session and fail much later, at the first attribute access on the outcome.
    """

    repository = FakeRepository()

    with pytest.raises(LoadRefused) as raw_run:
        repository.open_load(RELEASE, "raw-run-id", outcome())  # type: ignore[arg-type]
    assert raw_run.value.rule == "S0"

    with pytest.raises(LoadRefused) as raw_outcome:
        repository.open_load(RELEASE, run(), object())  # type: ignore[arg-type]
    assert raw_outcome.value.rule == "S0"

    for missing in (None, 7):
        with pytest.raises(LoadRefused):
            repository.open_load(RELEASE, missing, outcome())  # type: ignore[arg-type]


def test_the_completion_carrier_refuses_a_raw_run_id() -> None:
    with pytest.raises(ValueError, match="run must be a ProcessingRunRef"):
        ReleaseLoadCompletion("raw-run-id", False)  # type: ignore[arg-type]

    assert ReleaseLoadCompletion(run(), False).run == run()


# --------------------------------------------------------------------------
# The two matrix cases the first implementation left out
# --------------------------------------------------------------------------


def test_a_completion_that_fails_part_way_rolls_the_durable_write_back() -> None:
    """The proof that the completion row is atomic rather than described as such.

    The failure lands **between** the durable writes, not before them: the
    records are already in the store when it is raised. A completion that
    refused before touching anything would satisfy "leaves zero records" without
    exercising a rollback at all, which is the weaker test this replaces.
    """

    store = FakeStore()
    store.fail_after_writes = 1  # the records land, then the outcome fails
    repository = FakeRepository(store)
    load = repository.open_load(RELEASE, run(), outcome())
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    before = load.state

    with pytest.raises(LoadRefused) as refusal:
        load.commit()

    assert refusal.value.rule == "durable_write"
    assert store.partial_write_applied, "the records were written before it failed"
    assert store.loads == {}, "and rolled back, which is the property under test"
    assert store.outcomes == {} and store.completed == set()
    assert load.state == before, "S1 is still OPEN and S2-S6 are untouched"
    require_i1(load)

    # A failed completion is not terminal: the caller may still abort, and that
    # abort still leaves zero records.
    assert load.abort() is None
    assert store.loads == {}


def test_a_rejected_completion_that_fails_part_way_rolls_back_too() -> None:
    """The branch that persists no records still writes an outcome and a marker."""

    store = FakeStore()
    store.fail_after_writes = 1  # the outcome lands, then the completion marker fails
    _, load = session(store=store, accepted=False)

    with pytest.raises(LoadRefused):
        load.commit()

    assert store.partial_write_applied
    assert store.outcomes == {} and store.completed == set()


def test_a_failed_completion_can_be_retried_after_the_write_recovers() -> None:
    store = FakeStore()
    store.fail_after_writes = 1
    repository = FakeRepository(store)
    load = repository.open_load(RELEASE, run(), outcome())
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    with pytest.raises(LoadRefused):
        load.commit()

    store.fail_after_writes = None  # the durable side recovered
    completion = load.commit()

    assert completion.already_complete is False
    assert len(store.loads[(RELEASE, run())]) == 1


def test_the_session_holds_no_state_beyond_the_six_components() -> None:
    """The injection is the store's, not the session's.

    A seventh component would contradict the very contract this suite checks,
    so the knob that makes a durable write fail lives on the durable side —
    which is also where such a write actually fails.
    """

    _, load = session()

    assert not any("fail" in name for name in vars(load)), vars(load).keys()
    assert len(load.state) == 5, "S1, S2, S3, S4 and S6; S5 is the key set of S4"


def test_an_abandoned_session_leaves_an_earlier_load_untouched() -> None:
    """Neither committed nor aborted — just dropped."""

    store = FakeStore()
    _, first = session(store=store)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()
    persisted = dict(store.loads)
    recorded = dict(store.outcomes)

    _, abandoned = session(store=store)
    abandoned.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    del abandoned

    assert store.loads == persisted
    assert store.outcomes == recorded
    assert store.completed == {(RELEASE, run())}


def test_the_rollback_is_visible_through_a_reference_taken_before_it() -> None:
    """Restoring means the container, not the attribute.

    Rebinding `store.loads` to a snapshot leaves anything holding the original —
    another component, a caller, a test that captured it — looking at a
    container that still holds the failed write. The rollback would then exist
    only for whoever reaches it through the store object, which is not a
    rollback at all.
    """

    store = FakeStore()
    store.fail_after_writes = 1
    held = store.loads
    repository = FakeRepository(store)
    load = repository.open_load(RELEASE, run(), outcome())
    load.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))

    with pytest.raises(LoadRefused):
        load.commit()

    assert held is store.loads, "the container was restored, not replaced"
    assert held == {}, "and the failed write is not visible through it either"


def test_the_already_complete_branch_never_touches_the_store() -> None:
    """Branch 1 persists nothing, so a failing durable side cannot reach it.

    A store that fails on its very first write is the sharpest way to say that:
    if the branch wrote anything at all — an outcome, a completion marker, a
    no-op that still counted — this would raise instead of reporting the retry.
    """

    store = FakeStore()
    _, first = session(store=store)
    first.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    first.commit()
    persisted = dict(store.loads)

    store.fail_after_writes = 0  # any durable write now fails
    _, retry = session(store=store)
    retry.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    completion = retry.commit()

    assert completion.already_complete is True
    assert store.loads == persisted
    assert store.partial_write_applied is False


def test_partial_write_evidence_does_not_carry_across_transactions() -> None:
    """Otherwise a later assertion passes on what an earlier failure observed."""

    store = FakeStore()
    store.fail_after_writes = 1
    _, failing = session(store=store)
    failing.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    with pytest.raises(LoadRefused):
        failing.commit()
    assert store.partial_write_applied is True

    store.fail_after_writes = None
    _, succeeding = session(store=store, run_id="run-2")
    succeeding.write(CanonicalRecordBatch(entries=(CorrelatedRecord(snapshot()),)))
    succeeding.commit()

    assert store.partial_write_applied is False, "the flag belongs to one transaction"
