"""A synthetic release generated on demand, never written down.

A million rows at ninety columns is roughly a gigabyte of text. Committing it is
forbidden by the artifact policy, and staging it in a temporary file would
measure the filesystem rather than the boundary — so the reader yields envelopes
straight from a counter and keeps none of them.

Every value here is derived arithmetically from a row number. There are no
county bytes, owner values, addresses, or production rows, and nothing is
redistributed: the data does not exist until the loop runs and is gone as soon
as the processor drops it.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from types import TracebackType

from property_tax_adapters.release import (
    PreparedRelease,
    SourceRowEnvelope,
)
from property_tax_adapters.sources.contracts import (
    AppraisalSourceRecord,
    SourceNativeValue,
    SourceProvenance,
)

__all__ = ["ACCEPTANCE_COLUMNS", "ACCEPTANCE_ROWS", "SyntheticReleaseReader", "synthetic_columns"]

#: The acceptance shape issue #43 D5 fixes.
ACCEPTANCE_ROWS = 1_000_000
ACCEPTANCE_COLUMNS = 90

_JURISDICTION = "tx-synthetic"
_RELEASE = "synthetic-scale-release"
_MEMBER = "synthetic-scale.txt"
_FINGERPRINT = "5" * 64
_PARSER_VERSION = 1


def synthetic_columns(count: int = ACCEPTANCE_COLUMNS) -> tuple[str, ...]:
    """Stable column names, generated rather than taken from any county layout."""

    return tuple(f"SYNTH_FIELD_{index:03d}" for index in range(count))


class SyntheticReleaseReader:
    """A conforming `PreparedReader` over data that is computed, not stored.

    Holds a row count and a column tuple and nothing else. Nothing it has
    yielded is reachable from it afterwards, which is what lets it measure a
    boundary's memory without contributing to it — an instrument that retained
    the release would be measuring itself.
    """

    __slots__ = ("_columns", "_rows", "consumed")

    def __init__(self, rows: int, *, columns: int = ACCEPTANCE_COLUMNS) -> None:
        if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
            raise ValueError("rows must be a non-negative int")
        if isinstance(columns, bool) or not isinstance(columns, int) or columns < 1:
            raise ValueError("columns must be a positive int")
        self._rows = rows
        self._columns = synthetic_columns(columns)
        #: A counter, not a collection: it says how many rows were produced
        #: without keeping any of them.
        self.consumed = 0

    def __enter__(self) -> SyntheticReleaseReader:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def prepare(self) -> PreparedRelease:
        return PreparedRelease(
            jurisdiction_code=_JURISDICTION,
            release_identifier=_RELEASE,
            source_member_name=_MEMBER,
            layout_fingerprint=_FINGERPRINT,
            parser_contract_version=_PARSER_VERSION,
        )

    def __iter__(self) -> Iterator[SourceRowEnvelope]:
        for row in range(1, self._rows + 1):
            self.consumed += 1
            yield SourceRowEnvelope(
                physical_row_number=row,
                records=(self._record(row),),
            )

    def _record(self, row: int) -> AppraisalSourceRecord:
        return AppraisalSourceRecord(
            jurisdiction_code=_JURISDICTION,
            appraisal_year=2026,
            provenance=SourceProvenance(
                jurisdiction_code=_JURISDICTION,
                release_identifier=_RELEASE,
                source_member_name=_MEMBER,
                source_row_number=row,
                parser_contract_version=_PARSER_VERSION,
                layout_fingerprint=_FINGERPRINT,
            ),
            source_account_id=f"SYNTH-{row:09d}",
            source_native_values={
                name: SourceNativeValue(source_field=name, value=Decimal(row + index))
                for index, name in enumerate(self._columns)
            },
        )
