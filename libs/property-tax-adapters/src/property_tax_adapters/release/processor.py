"""Drive one logical release from a reader into a stage, atomically.

The order is the whole design.  Layout validation precedes opening a stage, so a
misidentified member never opens one.  The final progress event precedes
finalize and commit, so a callback that raises can still reject while zero
records are visible.  The reader is closed before the commit, so no reader
failure can occur after records become visible — nothing failable follows the
only step that changes visibility.

`process_release` is a function, not an object.  Nothing survives a call, so no
release state can leak into the next one, and the caller keeps the lifetime of
both resources it supplied.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Final

from property_tax_adapters.release.outcome import (
    BOUNDARY_CONTRACT_VERSION,
    DIAGNOSTIC_RETENTION_LIMIT,
    DuplicateRecordKey,
    ReleaseDiagnostic,
    ReleaseDiagnosticCode,
    ReleaseDisposition,
    ReleaseNotice,
    ReleaseOutcome,
)
from property_tax_adapters.release.progress import (
    PROGRESS_ROW_INTERVAL,
    ReleaseProgressEvent,
)
from property_tax_adapters.release.protocols import (
    PreparedReader,
    ProgressCallback,
    ReleaseStage,
    ResourceGuard,
)
from property_tax_adapters.release.records import (
    PreparedRelease,
    SourceRowEnvelope,
    record_disagreement,
)
from property_tax_adapters.sources.contracts import AppraisalSourceRecord

__all__ = ["process_release"]

_CODE: Final = ReleaseDiagnosticCode


class _Rejected(Exception):  # noqa: N818 - control flow, never surfaced
    """Internal signal carrying the code a phase failed with."""

    def __init__(self, code: ReleaseDiagnosticCode) -> None:
        self.code = code
        super().__init__()


class _Recorder:
    """Bounded accumulation of diagnostics and notices.

    Retains the first hundred of each in encounter order and counts the rest, so
    two runs over one member agree and neither list grows with the release.
    """

    __slots__ = ("diagnostics", "notices", "total_diagnostics", "total_notices")

    def __init__(self) -> None:
        self.diagnostics: list[ReleaseDiagnostic] = []
        self.notices: list[ReleaseNotice] = []
        self.total_diagnostics = 0
        self.total_notices = 0

    def fail(
        self,
        code: ReleaseDiagnosticCode,
        *,
        field_name: str | None = None,
        row: int | None = None,
        fingerprint: str | None = None,
    ) -> None:
        self.total_diagnostics += 1
        if len(self.diagnostics) < DIAGNOSTIC_RETENTION_LIMIT:
            self.diagnostics.append(
                ReleaseDiagnostic(
                    code=code,
                    field_name=field_name,
                    physical_row_number=row,
                    layout_fingerprint=fingerprint,
                )
            )

    def note(self, notices: tuple[ReleaseNotice, ...], total: int) -> None:
        self.total_notices += total
        for notice in notices:
            if len(self.notices) < DIAGNOSTIC_RETENTION_LIMIT:
                self.notices.append(notice)


def process_release(
    *,
    reader: PreparedReader,
    stage: ReleaseStage,
    progress: ProgressCallback | None = None,
    guard: ResourceGuard | None = None,
) -> ReleaseOutcome:
    """Process one logical release and return a bounded outcome.

    Keyword-only, so a caller cannot transpose the reader and the stage: both are
    protocols, and a positional signature would let that mistake type-check.
    """

    recorder = _Recorder()
    prepared: PreparedRelease | None = None
    rows = staged = rejected_rows = 0
    sequence = 0
    reader_entered = reader_closed = stage_entered = False
    writing = True

    def emit(final: bool) -> None:
        nonlocal sequence
        if progress is None or prepared is None:
            sequence += 1
            return
        event = ReleaseProgressEvent(
            jurisdiction_code=prepared.jurisdiction_code,
            release_identifier=prepared.release_identifier,
            source_member_name=prepared.source_member_name,
            parser_contract_version=prepared.parser_contract_version,
            layout_fingerprint=prepared.layout_fingerprint,
            physical_rows_processed=rows,
            staged_record_count=staged,
            sequence_number=sequence,
            final=final,
        )
        sequence += 1
        try:
            progress(event)
        except Exception as error:  # noqa: BLE001 - mapped to a code, text discarded
            raise _Rejected(_CODE.PROGRESS_CALLBACK_FAILED) from error

    def close_reader() -> None:
        """Close the reader exactly once, and only if it ever opened.

        A reader that failed to open has no resource to release, and one already
        closed may not be closed again: `__exit__` is a lifecycle call, not an
        idempotent cleanup hook, and calling it twice is a defect this boundary
        would otherwise introduce into every conforming reader.
        """

        nonlocal reader_closed
        if not reader_entered or reader_closed:
            return
        reader_closed = True
        try:
            reader.__exit__(None, None, None)
        except Exception as error:  # noqa: BLE001 - mapped to a code, text discarded
            raise _Rejected(_CODE.SOURCE_CLOSE_FAILED) from error

    def ask_guard() -> None:
        if guard is None:
            return
        try:
            guard.check(rows, staged)
        except Exception as error:  # noqa: BLE001 - mapped to a code, text discarded
            raise _Rejected(_CODE.RESOURCE_LIMIT_EXCEEDED) from error

    try:
        try:
            reader.__enter__()
        except Exception as error:  # noqa: BLE001
            raise _Rejected(_CODE.SOURCE_OPEN_FAILED) from error
        reader_entered = True

        try:
            prepared = reader.prepare()
        except Exception as error:  # noqa: BLE001
            raise _Rejected(_CODE.LAYOUT_REJECTED) from error
        recorder.note(prepared.notices.retained, prepared.notices.total)

        try:
            stage.__enter__()
        except Exception as error:  # noqa: BLE001
            raise _Rejected(_CODE.STAGE_OPEN_FAILED) from error
        stage_entered = True

        ask_guard()

        for envelope in _iterate(reader):
            rows += 1
            recorder.note(envelope.notices.retained, envelope.notices.total)

            if envelope.rejected:
                rejected_rows += 1
                writing = False
                recorder.fail(
                    _CODE.RECORD_REJECTED,
                    field_name=envelope.field_name,
                    row=envelope.physical_row_number,
                    fingerprint=prepared.layout_fingerprint,
                )
            else:
                disagreement = next(
                    (
                        name
                        for record in envelope.records
                        if (name := record_disagreement(record, prepared, envelope)) is not None
                    ),
                    None,
                )
                if disagreement is not None:
                    rejected_rows += 1
                    writing = False
                    recorder.fail(
                        _CODE.RECORD_REJECTED,
                        field_name=disagreement,
                        row=envelope.physical_row_number,
                        fingerprint=prepared.layout_fingerprint,
                    )
                elif writing and envelope.records:
                    _write(stage, envelope.records)
                    staged += len(envelope.records)

            if rows % PROGRESS_ROW_INTERVAL == 0:
                ask_guard()
                emit(final=False)

        ask_guard()
        emit(final=True)

        close_reader()

        if recorder.total_diagnostics:
            raise _Rejected(_CODE.RECORD_REJECTED)

        try:
            stage.finalize()
        except DuplicateRecordKey as error:
            raise _Rejected(_CODE.DUPLICATE_RECORD_KEY) from error
        except Exception as error:  # noqa: BLE001
            raise _Rejected(_CODE.STAGE_FINALIZE_FAILED) from error

        try:
            stage.commit()
        except Exception as error:  # noqa: BLE001
            raise _Rejected(_CODE.STAGE_COMMIT_FAILED) from error

    except _Rejected as rejection:
        # A row rejection already recorded its own diagnostic; re-recording the
        # marker code would double-count it.
        if rejection.code is not _CODE.RECORD_REJECTED or recorder.total_diagnostics == 0:
            recorder.fail(
                rejection.code,
                fingerprint=None if prepared is None else prepared.layout_fingerprint,
            )
        if stage_entered:
            try:
                stage.abort()
            except Exception:  # noqa: BLE001
                recorder.fail(
                    _CODE.STAGE_ABORT_FAILED,
                    fingerprint=None if prepared is None else prepared.layout_fingerprint,
                )
        # A close that fails here is a second failure, not a detail of the
        # first.  Suppressing it would lose the only report of a source left
        # open, and `close_reader` has already returned if the close that
        # rejected us is the one being cleaned up after.
        try:
            close_reader()
        except _Rejected as close_failure:
            recorder.fail(
                close_failure.code,
                fingerprint=None if prepared is None else prepared.layout_fingerprint,
            )
        return _outcome(
            recorder,
            prepared,
            rows=rows,
            staged=staged,
            committed=0,
            rejected_rows=rejected_rows,
        )
    finally:
        if stage_entered:
            stage.__exit__(None, None, None)

    return _outcome(
        recorder,
        prepared,
        rows=rows,
        staged=staged,
        committed=staged,
        rejected_rows=rejected_rows,
    )


def _iterate(reader: PreparedReader) -> Iterator[SourceRowEnvelope]:
    """Iterate the reader, mapping any iteration failure to a row rejection."""

    iterator = iter(reader)
    while True:
        try:
            yield next(iterator)
        except StopIteration:
            return
        except Exception as error:  # noqa: BLE001
            raise _Rejected(_CODE.RECORD_REJECTED) from error


def _write(stage: ReleaseStage, records: Sequence[AppraisalSourceRecord]) -> None:
    try:
        stage.write(records)
    except DuplicateRecordKey as error:
        raise _Rejected(_CODE.DUPLICATE_RECORD_KEY) from error
    except Exception as error:  # noqa: BLE001
        raise _Rejected(_CODE.STAGE_WRITE_FAILED) from error


def _outcome(
    recorder: _Recorder,
    prepared: PreparedRelease | None,
    *,
    rows: int,
    staged: int,
    committed: int,
    rejected_rows: int,
) -> ReleaseOutcome:
    accepted = recorder.total_diagnostics == 0
    return ReleaseOutcome(
        disposition=ReleaseDisposition.ACCEPTED if accepted else ReleaseDisposition.REJECTED,
        boundary_contract_version=BOUNDARY_CONTRACT_VERSION,
        parser_contract_version=None if prepared is None else prepared.parser_contract_version,
        layout_fingerprint=None if prepared is None else prepared.layout_fingerprint,
        diagnostics=tuple(recorder.diagnostics),
        total_diagnostic_count=recorder.total_diagnostics,
        diagnostics_truncated=recorder.total_diagnostics > DIAGNOSTIC_RETENTION_LIMIT,
        notices=tuple(recorder.notices),
        total_notice_count=recorder.total_notices,
        notices_truncated=recorder.total_notices > DIAGNOSTIC_RETENTION_LIMIT,
        physical_rows_processed=rows,
        staged_record_count=staged,
        committed_record_count=committed if accepted else 0,
        rejected_row_count=rejected_rows,
    )
