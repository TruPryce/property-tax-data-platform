"""Source-native exemption observations with explicit scope."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.address import _require_label
from property_tax_domain.owner import OwnerAssociation
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.value import _require_amount

__all__ = ["ExemptionObservation", "ExemptionScope"]


class ExemptionScope(StrEnum):
    """The closed grain at which an exemption was observed."""

    ACCOUNT = "account"
    OWNER_ASSOCIATION = "owner_association"


@dataclass(frozen=True, slots=True)
class ExemptionObservation:
    """One source-native exemption label at an explicit account or owner grain."""

    snapshot: AccountSnapshot
    classification: str
    scope: ExemptionScope
    provenance: DomainProvenance
    amount: Decimal | None = None
    association: OwnerAssociation | None = None

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        _require_label(self.classification, "classification")
        if not isinstance(self.scope, ExemptionScope):
            raise ValueError(f"scope must be an ExemptionScope, got {type(self.scope).__name__}")
        if self.amount is not None:
            _require_amount(self.amount)
        if self.scope is ExemptionScope.ACCOUNT:
            if self.association is not None:
                raise ValueError("an account-scoped exemption must not carry an association")
            return
        if not isinstance(self.association, OwnerAssociation):
            raise ValueError("an owner-association-scoped exemption requires an association")
        if self.association.snapshot != self.snapshot:
            raise ValueError("exemption association snapshot must equal the exemption snapshot")
        if self.association.provenance.release != self.provenance.release:
            raise ValueError("exemption and association provenance releases must agree")
