"""Land child observations without invented business identity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.address import _require_label
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import require_identifier

__all__ = ["LandObservation"]


@dataclass(frozen=True, slots=True)
class LandObservation:
    """One source land row attached to an account snapshot."""

    snapshot: AccountSnapshot
    provenance: DomainProvenance
    source_discriminator: str | None = None
    classification: str | None = None
    area: Decimal | None = None
    area_unit: str | None = None

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        _validate_child_fields(
            self.source_discriminator,
            self.classification,
            self.area,
            self.area_unit,
        )


def _validate_child_fields(
    source_discriminator: object,
    classification: object,
    area: object,
    area_unit: object,
) -> None:
    if source_discriminator is not None:
        require_identifier(source_discriminator, "source_discriminator")
    if classification is not None:
        _require_label(classification, "classification")
    if (area is None) != (area_unit is None):
        raise ValueError("area and area_unit must be present or absent together")
    if area is not None:
        _require_magnitude(area, "area")
        _require_label(area_unit, "area_unit")


def _require_magnitude(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite and not negative")
    return value
