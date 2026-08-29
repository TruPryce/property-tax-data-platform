"""Source-native taxing-unit observations."""

from __future__ import annotations

from dataclasses import dataclass

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.address import _require_label
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import require_identifier

__all__ = ["TaxingUnitObservation"]


@dataclass(frozen=True, slots=True)
class TaxingUnitObservation:
    """A source taxing entity applying to one account snapshot."""

    snapshot: AccountSnapshot
    unit_code: str
    provenance: DomainProvenance
    unit_name: str | None = None

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        require_identifier(self.unit_code, "unit_code")
        if self.unit_name is not None:
            _require_label(self.unit_name, "unit_name")
