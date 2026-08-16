"""When the boundary asks the guard, and never what the guard measures.

The cadence is the contract. A guard called at unpredictable moments cannot
enforce a ceiling reproducibly, so these tests assert the exact checkpoint
sequence rather than that some checkpoint happened.

Nothing here reads a resident set size, a cgroup file, or an allocation counter.
The target and the measurement method belong to the resource-limits change; what
this change owes is the seam and its schedule.
"""

from __future__ import annotations

from property_tax_adapters.release import (
    PROGRESS_ROW_INTERVAL,
    ReleaseDisposition,
    process_release,
)

from release.support import (
    LazyReader,
    Reader,
    RecordingGuard,
    RecordingStage,
    envelopes,
)

#: Two and a half intervals: enough that a guard called only at the boundaries
#: and a guard called only at the end produce visibly different sequences.
LONG_RELEASE = 250_000


def test_the_checkpoint_sequence_is_exact_on_a_long_release() -> None:
    """Once after the stage opens, once per 100,000 rows, once at end-of-input."""

    guard = RecordingGuard()

    outcome = process_release(
        reader=LazyReader(LONG_RELEASE),
        stage=RecordingStage(),
        guard=guard,
    )

    assert guard.calls == [
        (0, 0),
        (PROGRESS_ROW_INTERVAL, 0),
        (2 * PROGRESS_ROW_INTERVAL, 0),
        (LONG_RELEASE, 0),
    ]
    assert outcome.physical_rows_processed == LONG_RELEASE
    assert outcome.disposition is ReleaseDisposition.ACCEPTED


def test_the_row_count_at_each_checkpoint_is_the_count_so_far() -> None:
    """A guard given the final count at every call could not act early."""

    guard = RecordingGuard()

    process_release(reader=LazyReader(LONG_RELEASE), stage=RecordingStage(), guard=guard)

    observed = [rows for rows, _ in guard.calls]
    assert observed == sorted(observed), "the row count went backwards"
    assert len(set(observed)) == len(observed), "a checkpoint repeated a count"


def test_the_guard_is_called_at_the_fixed_checkpoints_only() -> None:
    guard = RecordingGuard()

    process_release(
        reader=Reader(envelopes(PROGRESS_ROW_INTERVAL)),
        stage=RecordingStage(),
        guard=guard,
    )

    # After the stage opens, at the 100,000 boundary, and once at end-of-input.
    assert guard.calls == [
        (0, 0),
        (PROGRESS_ROW_INTERVAL, PROGRESS_ROW_INTERVAL),
        (PROGRESS_ROW_INTERVAL, PROGRESS_ROW_INTERVAL),
    ]


def test_two_runs_produce_the_same_guard_sequence() -> None:
    first, second = RecordingGuard(), RecordingGuard()

    process_release(reader=Reader(envelopes(5)), stage=RecordingStage(), guard=first)
    process_release(reader=Reader(envelopes(5)), stage=RecordingStage(), guard=second)

    assert first.calls == second.calls


def test_a_raising_guard_rejects_and_aborts() -> None:
    stage = RecordingStage()
    outcome = process_release(
        reader=Reader(envelopes(3)),
        stage=stage,
        guard=RecordingGuard(raise_on_call=1),
    )

    assert [entry.code.value for entry in outcome.diagnostics] == ["resource_limit_exceeded"]
    assert "abort" in stage.calls
    assert "commit" not in stage.calls
    assert outcome.committed_record_count == 0
    assert "SECRET-GUARD" not in repr(outcome)


def test_a_guard_raising_at_the_last_checkpoint_still_prevents_the_commit() -> None:
    """End-of-input precedes finalize, so the last checkpoint can still reject."""

    stage = RecordingStage()
    outcome = process_release(
        reader=Reader(envelopes(3)),
        stage=stage,
        guard=RecordingGuard(raise_on_call=2),
    )

    assert [entry.code.value for entry in outcome.diagnostics] == ["resource_limit_exceeded"]
    assert "finalize" not in stage.calls
    assert "commit" not in stage.calls
    assert outcome.staged_record_count == 3, "the rejection discarded the staged count"
    assert outcome.committed_record_count == 0


def test_the_absent_guard_changes_nothing() -> None:
    outcome = process_release(reader=Reader(envelopes(3)), stage=RecordingStage())

    assert outcome.disposition is ReleaseDisposition.ACCEPTED
    assert outcome.total_diagnostic_count == 0
