"""Attacks on land, improvement, and geometry observation boundaries."""

from __future__ import annotations

from decimal import Decimal

import pytest
from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    ArtifactIdentity,
    DomainProvenance,
    GeometryEncoding,
    GeometryObservation,
    ImprovementObservation,
    Jurisdiction,
    LandObservation,
    ReleaseIdentity,
    ReleaseKind,
)

MAX_GEOMETRY_BYTES = 8 * 1024 * 1024
JURISDICTION = Jurisdiction("tx", "rockwall", "48397")
RELEASE = ReleaseIdentity(JURISDICTION, 2025, ReleaseKind.CURRENT, "R-1")
PROVENANCE = DomainProvenance(RELEASE, ArtifactIdentity("a" * 64), "GIS.DAT", 1, 1)
SNAPSHOT = AccountSnapshot(AccountIdentity(JURISDICTION, "123"), PROVENANCE)


def test_several_land_and_improvement_rows_survive_at_child_grain() -> None:
    lands = (
        LandObservation(SNAPSHOT, PROVENANCE, "1", "residential", Decimal("1"), "acre"),
        LandObservation(SNAPSHOT, PROVENANCE, "2", "commercial", Decimal("2"), "acre"),
    )
    improvements = (
        ImprovementObservation(SNAPSHOT, PROVENANCE, "1", "house", Decimal("1000"), "sqft", 1990),
        ImprovementObservation(SNAPSHOT, PROVENANCE, "2", "garage", Decimal("400"), "sqft", 2000),
    )

    assert len(set(lands)) == 2
    assert len(set(improvements)) == 2
    assert not hasattr(SNAPSHOT, "land")
    assert not hasattr(SNAPSHOT, "improvements")


def test_unresolved_child_key_is_represented_by_absence_not_invented_identity() -> None:
    child = LandObservation(SNAPSHOT, PROVENANCE, area=Decimal("0"), area_unit="acre")

    assert child.source_discriminator is None
    assert not hasattr(child, "identity")


@pytest.mark.parametrize(
    ("area", "unit"),
    [(Decimal("1"), None), (None, "acre")],
)
def test_area_and_unit_must_be_present_or_absent_together(
    area: Decimal | None, unit: str | None
) -> None:
    with pytest.raises(ValueError, match="together"):
        LandObservation(SNAPSHOT, PROVENANCE, area=area, area_unit=unit)


def test_magnitude_rejects_negative_and_accepts_zero_and_positive() -> None:
    with pytest.raises(ValueError, match="not negative"):
        LandObservation(SNAPSHOT, PROVENANCE, area=Decimal("-0.01"), area_unit="acre")

    for area in (Decimal("0"), Decimal("0.01")):
        assert LandObservation(SNAPSHOT, PROVENANCE, area=area, area_unit="acre").area == area


@pytest.mark.parametrize("year", [1599, 2201, True, 2000.0])
def test_year_built_enforces_the_closed_integer_range(year: object) -> None:
    with pytest.raises(ValueError):
        ImprovementObservation(SNAPSHOT, PROVENANCE, year_built=year)  # type: ignore[arg-type]


def test_geometry_requires_a_nonblank_coordinate_reference() -> None:
    for crs in ("", "   "):
        with pytest.raises(ValueError):
            GeometryObservation(SNAPSHOT, GeometryEncoding.WKB, b"x", crs, PROVENANCE)


def test_geometry_payload_bound_counts_utf8_bytes() -> None:
    binary = b"x" * MAX_GEOMETRY_BYTES
    text = "é" * (MAX_GEOMETRY_BYTES // 2)

    assert (
        GeometryObservation(SNAPSHOT, GeometryEncoding.WKB, binary, "EPSG:2276", PROVENANCE).payload
        is binary
    )
    assert (
        GeometryObservation(SNAPSHOT, GeometryEncoding.WKT, text, "EPSG:2276", PROVENANCE).payload
        is text
    )
    with pytest.raises(ValueError):
        GeometryObservation(SNAPSHOT, GeometryEncoding.WKB, binary + b"x", "EPSG:2276", PROVENANCE)
    with pytest.raises(ValueError):
        GeometryObservation(SNAPSHOT, GeometryEncoding.WKT, text + "x", "EPSG:2276", PROVENANCE)


@pytest.mark.parametrize(
    ("encoding", "payload"),
    [(GeometryEncoding.WKB, "POINT (1 2)"), (GeometryEncoding.WKT, b"point")],
)
def test_geometry_payload_type_must_agree_with_its_encoding(
    encoding: GeometryEncoding, payload: bytes | str
) -> None:
    with pytest.raises(ValueError):
        GeometryObservation(SNAPSHOT, encoding, payload, "EPSG:2276", PROVENANCE)


def test_geometry_is_retained_opaquely_without_interpretation() -> None:
    malformed_but_opaque = b"not valid geometry"
    subject = GeometryObservation(
        SNAPSHOT, GeometryEncoding.WKB, malformed_but_opaque, "SOURCE-CRS", PROVENANCE
    )

    assert subject.payload == malformed_but_opaque
    assert subject.crs == "SOURCE-CRS"
