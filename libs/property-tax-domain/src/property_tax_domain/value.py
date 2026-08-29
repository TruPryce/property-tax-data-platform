"""Canonical appraisal and taxing-unit value observations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.address import _require_label
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.taxing_unit import TaxingUnitObservation

__all__ = ["AppraisalValueObservation", "TaxableValueObservation", "ValueKind"]


class ValueKind(StrEnum):
    """The closed canonical account-level appraisal value vocabulary."""

    MARKET = "market"
    APPRAISED = "appraised"
    ASSESSED = "assessed"


def _require_amount(value: object, name: str = "amount") -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError(f"{name} must be a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class AppraisalValueObservation:
    """One canonical market, appraised, or assessed value."""

    snapshot: AccountSnapshot
    kind: ValueKind
    amount: Decimal
    provenance: DomainProvenance

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        if not isinstance(self.kind, ValueKind):
            raise ValueError(f"kind must be a ValueKind, got {type(self.kind).__name__}")
        _require_amount(self.amount)


@dataclass(frozen=True, slots=True)
class TaxableValueObservation:
    """One taxable value qualified by the source taxing unit and basis."""

    snapshot: AccountSnapshot
    taxing_unit: TaxingUnitObservation
    amount: Decimal
    basis: str
    provenance: DomainProvenance

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        if not isinstance(self.taxing_unit, TaxingUnitObservation):
            raise ValueError(
                "taxing_unit must be a TaxingUnitObservation, "
                f"got {type(self.taxing_unit).__name__}"
            )
        if self.taxing_unit.snapshot != self.snapshot:
            raise ValueError("taxing unit snapshot must equal the taxable value snapshot")
        if self.taxing_unit.provenance.release != self.provenance.release:
            raise ValueError("taxing unit and taxable value provenance releases must agree")
        _require_amount(self.amount)
        _require_label(self.basis, "basis")
