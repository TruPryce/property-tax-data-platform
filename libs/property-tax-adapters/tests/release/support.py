"""Shared fixtures for the boundary tests: a conforming reader and a recording stage."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from decimal import Decimal
from types import TracebackType

from property_tax_adapters.release import (
    NoticeSet,
    PreparedRelease,
    ReleaseProgressEvent,
    SourceRowEnvelope,
)
from property_tax_adapters.sources.contracts import (
    AppraisalSourceRecord,
    SourceNativeValue,
    SourceProvenance,
)

JURISDICTION = "tx-dallas"
RELEASE = "synthetic-release-2026"
MEMBER = "synthetic-member.txt"
FINGERPRINT = "f" * 64
PARSER_VERSION = 1


def prepared(**overrides: object) -> PreparedRelease:
    return PreparedRelease(
        **{
            "jurisdiction_code": JURISDICTION,
            "release_identifier": RELEASE,
            "source_member_name": MEMBER,
            "layout_fingerprint": FINGERPRINT,
            "parser_contract_version": PARSER_VERSION,
            **overrides,
        }  # type: ignore[arg-type]
    )


def record(row: int, *, account: str | None = None, **provenance: object) -> AppraisalSourceRecord:
    origin = SourceProvenance(
        **{
            "jurisdiction_code": JURISDICTION,
            "release_identifier": RELEASE,
            "source_member_name": MEMBER,
            "source_row_number": row,
            "parser_contract_version": PARSER_VERSION,
            "layout_fingerprint": FINGERPRINT,
            **provenance,
        }  # type: ignore[arg-type]
    )
    return AppraisalSourceRecord(
        jurisdiction_code=str(provenance.get("jurisdiction_code", JURISDICTION)),
        appraisal_year=2026,
        provenance=origin,
        source_account_id=account or f"ACCOUNT-{row:06d}",
        source_native_values={
            "TOT_VAL": SourceNativeValue(source_field="TOT_VAL", value=Decimal(row))
        },
    )


class Reader:
    """A conforming single-pass reader over a supplied list of envelopes."""

    def __init__(
        self,
        envelopes: Sequence[SourceRowEnvelope],
        *,
        release: PreparedRelease | None = None,
        fail_on_enter: bool = False,
        fail_on_prepare: bool = False,
        fail_on_exit: bool = False,
        fail_on_iteration: bool = False,
    ) -> None:
        self._envelopes = list(envelopes)
        self._release = release or prepared()
        self._fail_on_enter = fail_on_enter
        self._fail_on_prepare = fail_on_prepare
        self._fail_on_exit = fail_on_exit
        self._fail_on_iteration = fail_on_iteration
        self.exited = False

    def __enter__(self) -> Reader:
        if self._fail_on_enter:
            raise RuntimeError("SECRET-ENTER")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True
        if self._fail_on_exit:
            raise RuntimeError("SECRET-EXIT")

    def prepare(self) -> PreparedRelease:
        if self._fail_on_prepare:
            raise RuntimeError("SECRET-PREPARE")
        return self._release

    def __iter__(self) -> Iterator[SourceRowEnvelope]:
        yield from self._envelopes
        if self._fail_on_iteration:
            raise RuntimeError("SECRET-ITERATION")


class RecordingStage:
    """Records the order of every lifecycle call, and what is visible when."""

    def __init__(
        self,
        *,
        fail_on_enter: bool = False,
        write_error: BaseException | None = None,
        finalize_error: BaseException | None = None,
        commit_error: BaseException | None = None,
        abort_error: BaseException | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.staged: list[AppraisalSourceRecord] = []
        self.visible: list[AppraisalSourceRecord] = []
        self.entered = False
        self._fail_on_enter = fail_on_enter
        self._write_error = write_error
        self._finalize_error = finalize_error
        self._commit_error = commit_error
        self._abort_error = abort_error

    def __enter__(self) -> RecordingStage:
        if self._fail_on_enter:
            raise RuntimeError("SECRET-STAGE-ENTER")
        self.entered = True
        self.calls.append("enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.calls.append("exit")

    def write(self, records: Sequence[AppraisalSourceRecord]) -> None:
        self.calls.append("write")
        if self._write_error is not None:
            raise self._write_error
        self.staged.extend(records)

    def finalize(self) -> None:
        self.calls.append("finalize")
        if self._finalize_error is not None:
            raise self._finalize_error

    def abort(self) -> None:
        self.calls.append("abort")
        self.staged.clear()
        if self._abort_error is not None:
            raise self._abort_error

    def commit(self) -> None:
        self.calls.append("commit")
        if self._commit_error is not None:
            raise self._commit_error
        self.visible.extend(self.staged)


class RecordingProgress:
    """Collects events, optionally raising on one of them."""

    def __init__(self, *, raise_on_final: bool = False, raise_on_index: int | None = None) -> None:
        self.events: list[ReleaseProgressEvent] = []
        self._raise_on_final = raise_on_final
        self._raise_on_index = raise_on_index

    def __call__(self, event: ReleaseProgressEvent) -> None:
        self.events.append(event)
        if self._raise_on_final and event.final:
            raise RuntimeError("SECRET-CALLBACK")
        if self._raise_on_index is not None and len(self.events) - 1 == self._raise_on_index:
            raise RuntimeError("SECRET-CALLBACK")


class RecordingGuard:
    """Records each checkpoint, optionally raising on the nth call."""

    def __init__(self, *, raise_on_call: int | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self._raise_on_call = raise_on_call

    def check(self, physical_rows_processed: int, staged_record_count: int) -> None:
        self.calls.append((physical_rows_processed, staged_record_count))
        if self._raise_on_call is not None and len(self.calls) == self._raise_on_call:
            raise RuntimeError("SECRET-GUARD")


def envelopes(count: int, *, rejected: Sequence[int] = ()) -> list[SourceRowEnvelope]:
    """`count` well-formed envelopes, with the named rows marked rejected."""

    marked = set(rejected)
    return [
        SourceRowEnvelope(
            physical_row_number=row,
            records=() if row in marked else (record(row),),
            rejected=row in marked,
        )
        for row in range(1, count + 1)
    ]


def notice_set(total: int, *, row: int | None = None) -> NoticeSet:
    """A set built from `total` observations, exercising incremental retention."""

    from property_tax_adapters.release import ReleaseNotice

    return NoticeSet.from_observations(
        ReleaseNotice(code="extra_columns_present", physical_row_number=row) for _ in range(total)
    )
