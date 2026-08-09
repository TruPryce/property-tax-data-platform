"""Independent, identity-free literals for the Collin foundation contract."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from property_tax_adapters.sources.texas.collin import (
    CERTIFIED_VALUE_COLUMNS,
    COLLIN_TABLE_NAME,
    CURRENT_VALUE_COLUMNS,
    CollinAccessPhysicalType,
    CollinColumnDescriptor,
)

FIXTURE_PROVENANCE = (
    "Independently authored project synthetic; reviewed coefficient arithmetic; "
    "not produced by the decoder, an encoder, Access, or county data."
)


def hex_digest(*chunks: str) -> str:
    return "".join(chunks)


ZERO_BUFFER = bytes.fromhex("00 00000000 00000000 00000000 00000000")
POSITIVE_BUFFER = bytes.fromhex("00 00000000 00000000 00000000 2a000000")
NEGATIVE_BUFFER = bytes.fromhex("01 00000000 00000000 00000000 2a000000")
SCALED_BUFFER = bytes.fromhex("00 00000000 00000000 00000000 39300000")
MULTIWORD_BUFFER = bytes.fromhex("01 00000000 00000000 01000000 01000000")
BOUNDARY_BUFFER = bytes.fromhex("00 00000000 5ece4f20 6102253e ffffff0f")
YEAR_2025_BUFFER = bytes.fromhex("00 00000000 00000000 00000000 e9070000")
YEAR_2026_BUFFER = bytes.fromhex("00 00000000 00000000 00000000 ea070000")
MONETARY_BUFFER = bytes.fromhex("00 00000000 00000000 02000000 351cdcdf")


@dataclass(frozen=True, slots=True)
class CollinNumericVector:
    """Reviewed literal with external metadata and an independent answer."""

    name: str
    buffer: bytes
    precision: int
    scale: int
    expected: Decimal
    sha256: str
    provenance: str = FIXTURE_PROVENANCE


NUMERIC_VECTORS = (
    CollinNumericVector(
        "canonical-zero",
        ZERO_BUFFER,
        1,
        0,
        Decimal("0"),
        hex_digest(
            "0a881118",
            "52095cae",
            "045340ea",
            "1f0b2799",
            "44b2a756",
            "a213d9b5",
            "0107d748",
            "9771e159",
        ),
    ),
    CollinNumericVector(
        "positive",
        POSITIVE_BUFFER,
        2,
        0,
        Decimal("42"),
        hex_digest(
            "43ac6b9f",
            "15759a71",
            "8ae1b237",
            "3f475c27",
            "37151df0",
            "f7d2c918",
            "d79d6702",
            "099e7eec",
        ),
    ),
    CollinNumericVector(
        "negative",
        NEGATIVE_BUFFER,
        2,
        0,
        Decimal("-42"),
        hex_digest(
            "34dd3285",
            "888cd652",
            "c14d67f7",
            "f156ffc0",
            "5e3420ee",
            "6aabea0a",
            "3ed9231b",
            "799fc7c0",
        ),
    ),
    CollinNumericVector(
        "scaled",
        SCALED_BUFFER,
        5,
        2,
        Decimal("123.45"),
        hex_digest(
            "9df5aac6",
            "a59a1f66",
            "86d07510",
            "be85c17e",
            "bdcf2120",
            "faae6271",
            "8ce5f7bd",
            "f3e4e1ba",
        ),
    ),
    CollinNumericVector(
        "signed-multiword",
        MULTIWORD_BUFFER,
        10,
        2,
        Decimal("-42949672.97"),
        hex_digest(
            "207f111c",
            "18514966",
            "47dfe54d",
            "67f289c9",
            "6653fbc0",
            "5e57ba92",
            "b5a694c4",
            "aac142e3",
        ),
    ),
    CollinNumericVector(
        "precision-boundary",
        BOUNDARY_BUFFER,
        28,
        0,
        Decimal("9999999999999999999999999999"),
        hex_digest(
            "f8226000",
            "e2da3fc8",
            "7cd61c88",
            "c5bf10ec",
            "7225bfdf",
            "678f0685",
            "c179cffe",
            "a74b3f23",
        ),
    ),
    CollinNumericVector(
        "year-2025",
        YEAR_2025_BUFFER,
        4,
        0,
        Decimal("2025"),
        hex_digest(
            "1263de25",
            "765aba4c",
            "7e551b2a",
            "3e8642dd",
            "722ac071",
            "fd7e2809",
            "6040f689",
            "5a4e7070",
        ),
    ),
    CollinNumericVector(
        "year-2026",
        YEAR_2026_BUFFER,
        4,
        0,
        Decimal("2026"),
        hex_digest(
            "4927b4ef",
            "6ae8b2bc",
            "7d7a1b83",
            "6c2b0604",
            "4ebe11cb",
            "a8f51ef0",
            "1d2ae9c0",
            "fa5dc61b",
        ),
    ),
    CollinNumericVector(
        "monetary",
        MONETARY_BUFFER,
        13,
        2,
        Decimal("123456789.01"),
        hex_digest(
            "942a886f",
            "9e86c8b0",
            "42d692d6",
            "f3737566",
            "f4e399b2",
            "a1a27ea7",
            "ac1d6b42",
            "93885419",
        ),
    ),
)

COMPATIBLE_COLUMNS = (
    CollinColumnDescriptor("prop_id", CollinAccessPhysicalType.LONG, 4, None, None, False),
    CollinColumnDescriptor("geo_id", CollinAccessPhysicalType.TEXT, 64, None, None, False),
    CollinColumnDescriptor("property_status", CollinAccessPhysicalType.TEXT, 32, None, None, False),
    CollinColumnDescriptor("curr_val_yr", CollinAccessPhysicalType.NUMERIC, 17, 4, 0, False),
    CollinColumnDescriptor("cert_val_yr", CollinAccessPhysicalType.NUMERIC, 17, 4, 0, True),
    *tuple(
        CollinColumnDescriptor(name, CollinAccessPhysicalType.NUMERIC, 17, 28, 2, True)
        for name in (*CURRENT_VALUE_COLUMNS, *CERTIFIED_VALUE_COLUMNS)
    ),
)

COMPATIBLE_SCHEMA = {COLLIN_TABLE_NAME: COMPATIBLE_COLUMNS}

VALID_ROW: dict[str, object] = {
    "prop_id": 101,
    "geo_id": "  000-SYNTHETIC-A  ",
    "property_status": " Preliminary ",
    "curr_val_yr": YEAR_2026_BUFFER,
    "cert_val_yr": YEAR_2025_BUFFER,
    **{name: None for name in (*CURRENT_VALUE_COLUMNS, *CERTIFIED_VALUE_COLUMNS)},
    "curr_market": MONETARY_BUFFER,
    "curr_appraised_val": SCALED_BUFFER,
    "curr_assessed_val": POSITIVE_BUFFER,
    "cert_market": POSITIVE_BUFFER,
    "cert_appraised_val": SCALED_BUFFER,
    "cert_assessed_val": MONETARY_BUFFER,
}

CURRENT_ONLY_ROW = {
    **VALID_ROW,
    "cert_val_yr": None,
    **{name: None for name in CERTIFIED_VALUE_COLUMNS},
}

__all__ = [
    "BOUNDARY_BUFFER",
    "COMPATIBLE_COLUMNS",
    "COMPATIBLE_SCHEMA",
    "CURRENT_ONLY_ROW",
    "FIXTURE_PROVENANCE",
    "MONETARY_BUFFER",
    "MULTIWORD_BUFFER",
    "NEGATIVE_BUFFER",
    "NUMERIC_VECTORS",
    "POSITIVE_BUFFER",
    "SCALED_BUFFER",
    "VALID_ROW",
    "YEAR_2025_BUFFER",
    "YEAR_2026_BUFFER",
    "ZERO_BUFFER",
    "CollinNumericVector",
]
