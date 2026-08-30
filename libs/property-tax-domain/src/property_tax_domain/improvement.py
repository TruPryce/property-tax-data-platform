"""Improvement child observations without invented business identity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.land import _validate_child_fields
from property_tax_domain.provenance import DomainProvenance

__all__ = ["ImprovementObservation"]


@dataclass(frozen=True, slots=True)
class ImprovementObservation:
    """One source improvement row attached to an account snapshot."""

    snapshot: AccountSnapshot
    provenance: DomainProvenance
    source_discriminator: str | None = None
    classification: str | None = None
    area: Decimal | None = None
    area_unit: str | None = None
    year_built: int | None = None

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        _validate_child_fields(
            self.source_discriminator,
            self.classification,
            self.area,
            self.area_unit,
        )
        if self.year_built is not None:
            if isinstance(self.year_built, bool) or not isinstance(self.year_built, int):
                raise ValueError(f"year_built must be an int, got {type(self.year_built).__name__}")
            if not 1600 <= self.year_built <= 2200:
                raise ValueError("year_built must be from 1600 through 2200")
