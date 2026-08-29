"""Opaque geometry enrichment without a geospatial dependency."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.address import _require_bounded_text
from property_tax_domain.provenance import DomainProvenance

__all__ = ["GeometryEncoding", "GeometryObservation"]

_MAX_GEOMETRY_BYTES: Final = 8 * 1024 * 1024


class GeometryEncoding(StrEnum):
    """The closed opaque geometry encodings."""

    WKB = "wkb"
    WKT = "wkt"


@dataclass(frozen=True, slots=True)
class GeometryObservation:
    """One opaque geometry payload with its source-stated CRS."""

    snapshot: AccountSnapshot
    encoding: GeometryEncoding
    payload: bytes | str
    crs: str
    provenance: DomainProvenance

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        if not isinstance(self.encoding, GeometryEncoding):
            raise ValueError(
                f"encoding must be a GeometryEncoding, got {type(self.encoding).__name__}"
            )
        if self.encoding is GeometryEncoding.WKB:
            if not isinstance(self.payload, bytes):
                raise ValueError("wkb geometry payload must be bytes")
            size = len(self.payload)
        else:
            if not isinstance(self.payload, str):
                raise ValueError("wkt geometry payload must be str")
            size = len(self.payload.encode("utf-8"))
        if not 1 <= size <= _MAX_GEOMETRY_BYTES:
            raise ValueError(f"geometry payload must be 1 through {_MAX_GEOMETRY_BYTES} bytes")
        _require_bounded_text(self.crs, "crs", 64)
