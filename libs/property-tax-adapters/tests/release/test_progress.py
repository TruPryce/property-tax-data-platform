"""The progress contract and the resource-guard checkpoints.

Both are about *when* something happens, so both are tested by recording the
sequence rather than by inspecting the code that produces it.
"""

from __future__ import annotations

from property_tax_adapters.release import (
    BOUNDARY_CONTRACT_VERSION,
    PROGRESS_CONTRACT_VERSION,
    PROGRESS_ROW_INTERVAL,
    ReleaseDisposition,
    process_release,
)

from release.support import (
    FINGERPRINT,
    JURISDICTION,
    MEMBER,
    RELEASE,
    Reader,
    RecordingProgress,
    RecordingStage,
    envelopes,
)

# 100,000 rows per interval is the contract; the tests run at a scaled interval
# by generating exactly that many envelopes only where the boundary case needs
# it, and otherwise assert on the schedule the processor followed.


def test_an_empty_release_emits_one_complete_final_event() -> None:
    progress = RecordingProgress()

    outcome = process_release(reader=Reader([]), stage=RecordingStage(), progress=progress)

    assert len(progress.events) == 1
    event = progress.events[0]
    assert event.final is True
    assert event.physical_rows_processed == 0
    assert event.staged_record_count == 0
    assert event.sequence_number == 0
    # Identity comes from the prepared release, which is why an empty release
    # still has one at all.
    assert event.jurisdiction_code == JURISDICTION
    assert event.release_identifier == RELEASE
    assert event.source_member_name == MEMBER
    assert event.layout_fingerprint == FINGERPRINT
    assert outcome.disposition is ReleaseDisposition.ACCEPTED


def test_an_exact_multiple_emits_a_boundary_event_and_one_final() -> None:
    progress = RecordingProgress()

    process_release(
        reader=Reader(envelopes(PROGRESS_ROW_INTERVAL)),
        stage=RecordingStage(),
        progress=progress,
    )

    assert [event.final for event in progress.events] == [False, True]
    assert [event.sequence_number for event in progress.events] == [0, 1]
    assert progress.events[0].physical_rows_processed == PROGRESS_ROW_INTERVAL
    assert progress.events[-1].physical_rows_processed == PROGRESS_ROW_INTERVAL


def test_sequence_numbers_are_gapless_from_zero() -> None:
    progress = RecordingProgress()

    process_release(reader=Reader(envelopes(3)), stage=RecordingStage(), progress=progress)

    assert [event.sequence_number for event in progress.events] == list(range(len(progress.events)))


def test_a_failing_final_callback_prevents_the_commit() -> None:
    """The case that distinguishes a contract able to prevent a commit."""

    stage = RecordingStage()
    progress = RecordingProgress(raise_on_final=True)

    outcome = process_release(reader=Reader(envelopes(2)), stage=stage, progress=progress)

    assert [entry.code.value for entry in outcome.diagnostics] == ["progress_callback_failed"]
    assert "finalize" not in stage.calls
    assert "commit" not in stage.calls
    assert "abort" in stage.calls
    assert outcome.committed_record_count == 0


def test_no_callback_exception_text_is_retained() -> None:
    outcome = process_release(
        reader=Reader(envelopes(2)),
        stage=RecordingStage(),
        progress=RecordingProgress(raise_on_final=True),
    )

    assert "SECRET-CALLBACK" not in repr(outcome)


def test_both_contract_versions_are_pinned() -> None:
    assert BOUNDARY_CONTRACT_VERSION == 1
    assert PROGRESS_CONTRACT_VERSION == 1

    progress = RecordingProgress()
    outcome = process_release(reader=Reader([]), stage=RecordingStage(), progress=progress)

    assert outcome.boundary_contract_version == 1
    assert progress.events[0].progress_contract_version == 1


def test_a_callback_raising_on_a_non_final_event_rejects_the_release() -> None:
    """The boundary event, not the last one: reading continues past it."""

    stage = RecordingStage()
    progress = RecordingProgress(raise_on_index=0)

    outcome = process_release(
        reader=Reader(envelopes(PROGRESS_ROW_INTERVAL + 5)),
        stage=stage,
        progress=progress,
    )

    assert [entry.code.value for entry in outcome.diagnostics] == ["progress_callback_failed"]
    assert len(progress.events) == 1, "events continued after the callback failed"
    assert progress.events[0].final is False
    assert outcome.physical_rows_processed == PROGRESS_ROW_INTERVAL, (
        "the rejection was not raised at the boundary event"
    )
    assert "commit" not in stage.calls
    assert "abort" in stage.calls
    assert outcome.committed_record_count == 0
