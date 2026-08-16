"""Lifecycle, atomicity, agreement, and the failure-to-code mapping.

The order is proved by construction rather than by inspection: each test hands
the processor a stage or reader that records what happened to it, so a claim
about ordering is an observation rather than a reading of the source.
"""

from __future__ import annotations

import pytest
from property_tax_adapters.release import (
    DIAGNOSTIC_RETENTION_LIMIT,
    DuplicateRecordKey,
    ReleaseDiagnosticCode,
    ReleaseDisposition,
    SourceRowEnvelope,
    process_release,
)

from release.support import (
    FINGERPRINT,
    Reader,
    RecordingStage,
    envelopes,
    prepared,
    record,
)


def codes(outcome) -> list[str]:  # noqa: ANN001 - a local reader for terseness
    return [entry.code.value for entry in outcome.diagnostics]


# --------------------------------------------------------------------------
# Lifecycle order
# --------------------------------------------------------------------------


def test_an_accepted_release_runs_the_declared_order() -> None:
    stage = RecordingStage()
    reader = Reader(envelopes(3))

    outcome = process_release(reader=reader, stage=stage)

    assert stage.calls == ["enter", "write", "write", "write", "finalize", "commit", "exit"]
    assert reader.exited is True
    assert outcome.disposition is ReleaseDisposition.ACCEPTED
    assert outcome.committed_record_count == outcome.staged_record_count == 3


def test_a_layout_failure_never_enters_a_stage() -> None:
    """The stage records whether it was entered, so this is observed not read."""

    stage = RecordingStage()
    outcome = process_release(reader=Reader([], fail_on_prepare=True), stage=stage)

    assert codes(outcome) == ["layout_rejected"]
    assert stage.entered is False
    assert stage.calls == []
    assert "abort" not in stage.calls


def test_a_reader_that_fails_to_open_is_not_a_layout_failure() -> None:
    stage = RecordingStage()
    outcome = process_release(reader=Reader([], fail_on_enter=True), stage=stage)

    assert codes(outcome) == ["source_open_failed"]
    assert stage.entered is False


def test_the_reader_is_closed_before_the_commit() -> None:
    """A reader failing on close must still reject while nothing is visible."""

    stage = RecordingStage()
    outcome = process_release(reader=Reader(envelopes(2), fail_on_exit=True), stage=stage)

    assert codes(outcome) == ["source_close_failed"]
    assert "commit" not in stage.calls
    assert stage.calls[-2:] == ["abort", "exit"]
    assert outcome.committed_record_count == 0


# --------------------------------------------------------------------------
# Atomicity
# --------------------------------------------------------------------------


def test_writing_stops_at_the_first_rejection_but_reading_does_not() -> None:
    stage = RecordingStage()
    outcome = process_release(reader=Reader(envelopes(5, rejected=[2])), stage=stage)

    assert stage.calls.count("write") == 1, "writing continued past the rejection"
    assert outcome.physical_rows_processed == 5, "reading stopped at the rejection"
    assert "abort" in stage.calls
    assert "finalize" not in stage.calls and "commit" not in stage.calls
    assert outcome.committed_record_count == 0


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"finalize_error": RuntimeError("SECRET")}, "stage_finalize_failed"),
        ({"commit_error": RuntimeError("SECRET")}, "stage_commit_failed"),
        ({"write_error": RuntimeError("SECRET")}, "stage_write_failed"),
        ({"write_error": DuplicateRecordKey()}, "duplicate_record_key"),
        ({"finalize_error": DuplicateRecordKey()}, "duplicate_record_key"),
        ({"fail_on_enter": True}, "stage_open_failed"),
    ],
    ids=["finalize", "commit", "write", "duplicate-write", "duplicate-finalize", "enter"],
)
def test_each_stage_phase_maps_to_its_own_code(kwargs: dict, expected: str) -> None:
    outcome = process_release(reader=Reader(envelopes(2)), stage=RecordingStage(**kwargs))

    assert codes(outcome) == [expected]
    assert outcome.committed_record_count == 0


def test_a_failing_abort_does_not_hide_the_original_failure() -> None:
    stage = RecordingStage(abort_error=RuntimeError("SECRET-ABORT"))
    outcome = process_release(reader=Reader(envelopes(3, rejected=[2])), stage=stage)

    assert codes(outcome) == ["record_rejected", "stage_abort_failed"]
    assert outcome.disposition is ReleaseDisposition.REJECTED


def test_reader_iteration_failure_is_a_row_rejection() -> None:
    outcome = process_release(
        reader=Reader(envelopes(2), fail_on_iteration=True), stage=RecordingStage()
    )

    assert codes(outcome) == ["record_rejected"]


# --------------------------------------------------------------------------
# Agreement
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"release_identifier": "another-release"},
        {"source_member_name": "another-member.txt"},
        {"layout_fingerprint": "a" * 64},
        {"parser_contract_version": 2},
        {"source_row_number": 6},
    ],
    ids=["release", "member", "fingerprint", "parser-version", "row"],
)
def test_a_record_disagreeing_with_its_release_is_refused(override: dict) -> None:
    envelope = SourceRowEnvelope(physical_row_number=7, records=(record(7, **override),))
    stage = RecordingStage()

    outcome = process_release(reader=Reader([envelope]), stage=stage)

    assert codes(outcome) == ["record_rejected"]
    assert stage.staged == [], "a disagreeing record was staged"
    assert outcome.rejected_row_count == 1


# --------------------------------------------------------------------------
# Counts, rows, and the retention cap
# --------------------------------------------------------------------------


def test_rows_and_records_are_counted_independently() -> None:
    mixed = [
        SourceRowEnvelope(physical_row_number=1),
        SourceRowEnvelope(physical_row_number=2, records=(record(2),)),
        SourceRowEnvelope(
            physical_row_number=3,
            records=(record(3, account="A"), record(3, account="B")),
        ),
    ]

    outcome = process_release(reader=Reader(mixed), stage=RecordingStage())

    assert outcome.physical_rows_processed == 3
    assert outcome.staged_record_count == 3
    assert outcome.committed_record_count == 3


def test_many_rejected_rows_reach_the_retention_cap_deterministically() -> None:
    rows = 150
    reader = Reader(envelopes(rows, rejected=range(1, rows + 1)))

    outcome = process_release(reader=reader, stage=RecordingStage())

    assert outcome.physical_rows_processed == rows, "iteration stopped at the first rejection"
    assert len(outcome.diagnostics) == DIAGNOSTIC_RETENTION_LIMIT
    assert outcome.total_diagnostic_count == rows
    assert outcome.diagnostics_truncated is True
    assert [entry.physical_row_number for entry in outcome.diagnostics] == list(range(1, 101))


def test_an_accepted_outcome_carries_no_diagnostic() -> None:
    accepted = process_release(reader=Reader(envelopes(2)), stage=RecordingStage())
    rejected = process_release(reader=Reader(envelopes(2, rejected=[1])), stage=RecordingStage())

    assert accepted.total_diagnostic_count == 0
    assert accepted.rejected_row_count == 0
    assert rejected.total_diagnostic_count >= 1
    assert rejected.disposition is ReleaseDisposition.REJECTED


def test_a_pre_preparation_failure_reports_neither_prepared_field() -> None:
    outcome = process_release(reader=Reader([], fail_on_enter=True), stage=RecordingStage())

    assert outcome.layout_fingerprint is None
    assert outcome.parser_contract_version is None
    assert outcome.boundary_contract_version == 1


def test_a_later_failure_does_not_clear_prepared_values() -> None:
    outcome = process_release(reader=Reader(envelopes(2, rejected=[2])), stage=RecordingStage())

    assert outcome.layout_fingerprint == FINGERPRINT
    assert outcome.parser_contract_version == 1


def test_a_diagnostic_after_preparation_carries_the_fingerprint() -> None:
    outcome = process_release(reader=Reader(envelopes(2, rejected=[1])), stage=RecordingStage())
    before = process_release(reader=Reader([], fail_on_enter=True), stage=RecordingStage())

    assert outcome.diagnostics[0].layout_fingerprint == FINGERPRINT
    assert before.diagnostics[0].layout_fingerprint is None


def test_the_vocabulary_is_exactly_twelve_codes() -> None:
    assert len(ReleaseDiagnosticCode) == 12


def test_an_empty_release_is_accepted() -> None:
    outcome = process_release(reader=Reader([], release=prepared()), stage=RecordingStage())

    assert outcome.disposition is ReleaseDisposition.ACCEPTED
    assert outcome.physical_rows_processed == 0
    assert outcome.committed_record_count == 0
