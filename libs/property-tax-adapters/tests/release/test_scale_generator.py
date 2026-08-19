"""The generator's shape, and that it does not hold the release it measures.

Small sizes only. The acceptance run belongs to the benchmark's own target.
"""

from __future__ import annotations

import pathlib
import sys

import pytest
from property_tax_adapters.release import NoticeSet, PreparedRelease, SourceRowEnvelope

from release.scale import (
    ACCEPTANCE_COLUMNS,
    ACCEPTANCE_ROWS,
    SyntheticReleaseReader,
    synthetic_columns,
)
from release.support import prepared  # noqa: F401 - kept for parity with the suite's helpers


def test_the_acceptance_shape_is_what_the_decision_fixed() -> None:
    assert ACCEPTANCE_ROWS == 1_000_000
    assert ACCEPTANCE_COLUMNS >= 90


def test_it_produces_the_requested_rows() -> None:
    for rows in (0, 1, 37, 500):
        with SyntheticReleaseReader(rows) as reader:
            reader.prepare()
            assert sum(1 for _ in reader) == rows


def test_every_row_carries_at_least_ninety_source_columns() -> None:
    with SyntheticReleaseReader(20) as reader:
        reader.prepare()
        for envelope in reader:
            for record in envelope.records:
                assert len(record.source_native_values) >= 90


def test_every_envelope_is_well_formed_against_the_accepted_contract() -> None:
    with SyntheticReleaseReader(50) as reader:
        release = reader.prepare()
        assert isinstance(release, PreparedRelease)
        for expected_row, envelope in enumerate(reader, start=1):
            assert isinstance(envelope, SourceRowEnvelope)
            assert envelope.physical_row_number == expected_row
            assert envelope.rejected is False
            # A NoticeSet that is empty rather than absent.
            assert isinstance(envelope.notices, NoticeSet)
            assert envelope.notices.total == 0
            for record in envelope.records:
                assert record.jurisdiction_code == release.jurisdiction_code
                assert record.provenance.release_identifier == release.release_identifier
                assert record.provenance.source_member_name == release.source_member_name
                assert record.provenance.layout_fingerprint == release.layout_fingerprint
                assert record.provenance.parser_contract_version == release.parser_contract_version
                assert record.provenance.source_row_number == envelope.physical_row_number


def test_its_own_footprint_does_not_grow_with_the_rows_produced() -> None:
    """Driven to exhaustion at two sizes, the reader's retained state is identical.

    An instrument that accumulated what it yielded would measure itself.
    """

    def retained(rows: int) -> int:
        reader = SyntheticReleaseReader(rows)
        with reader as opened:
            opened.prepare()
            for _ in opened:
                pass
        held = [getattr(reader, name) for name in reader.__slots__]
        return sum(sys.getsizeof(item) for item in held)

    assert retained(100) == retained(5_000)


def test_it_holds_no_collection_that_could_grow() -> None:
    reader = SyntheticReleaseReader(200)
    with reader as opened:
        opened.prepare()
        for _ in opened:
            pass

    for name in reader.__slots__:
        value = getattr(reader, name)
        assert not isinstance(value, list | dict | set), f"{name} is a growable container"
    assert reader.consumed == 200, "the counter is a count, not a collection"


def test_it_writes_no_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Staging a gigabyte of text would measure the filesystem, not the boundary."""

    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.rglob("*"))

    with SyntheticReleaseReader(1_000) as reader:
        reader.prepare()
        for _ in reader:
            pass

    assert set(tmp_path.rglob("*")) == before


def test_the_source_names_no_county_and_no_real_identifier() -> None:
    text = pathlib.Path(__file__).with_name("scale.py").read_text(encoding="utf-8").casefold()

    for county in ("collin", "dallas", "denton", "ellis", "rockwall", "tarrant"):
        assert county not in text, county


def test_the_columns_are_generated_not_taken_from_a_layout() -> None:
    columns = synthetic_columns(90)

    assert len(columns) == 90
    assert len(set(columns)) == 90
    assert all(name.startswith("SYNTH_FIELD_") for name in columns)


@pytest.mark.parametrize(
    ("rows", "columns"),
    [(-1, 90), (True, 90), (10, 0), (10, True)],
    ids=["neg", "bool", "zero-col", "bool-col"],
)
def test_an_unusable_shape_is_refused(rows: object, columns: object) -> None:
    with pytest.raises(ValueError):
        SyntheticReleaseReader(rows, columns=columns)  # type: ignore[arg-type]
