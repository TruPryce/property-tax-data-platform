"""Owner observations, account associations, and owner-scoped allocations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from property_tax_domain.account import AccountSnapshot, _require_snapshot_release
from property_tax_domain.address import MailingAddress, _require_label
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import require_identifier
from property_tax_domain.value import ValueKind, _require_amount

__all__ = ["OwnerAssociation", "OwnerObservation", "OwnerValueAllocation"]


@dataclass(frozen=True, slots=True)
class OwnerObservation:
    """One release's observation of an owner, without person identity."""

    snapshot: AccountSnapshot
    owner_name: str
    provenance: DomainProvenance
    mailing_address: MailingAddress | None = None

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        _require_label(self.owner_name, "owner_name")
        if self.mailing_address is not None and not isinstance(
            self.mailing_address, MailingAddress
        ):
            raise ValueError(
                "mailing_address must be a MailingAddress, "
                f"got {type(self.mailing_address).__name__}"
            )


@dataclass(frozen=True, slots=True)
class OwnerAssociation:
    """One source-observed relationship between an account and an owner row."""

    snapshot: AccountSnapshot
    owner: OwnerObservation
    provenance: DomainProvenance
    ownership_percentage: Decimal | None = None
    source_discriminator: str | None = None

    def __post_init__(self) -> None:
        _require_snapshot_release(self.snapshot, self.provenance)
        if not isinstance(self.owner, OwnerObservation):
            raise ValueError(f"owner must be an OwnerObservation, got {type(self.owner).__name__}")
        if self.owner.snapshot != self.snapshot:
            raise ValueError("owner observation snapshot must equal the association snapshot")
        if self.owner.provenance.release != self.provenance.release:
            raise ValueError("owner and association provenance releases must agree")
        if self.ownership_percentage is not None:
            _require_percentage(self.ownership_percentage)
        if self.source_discriminator is not None:
            require_identifier(self.source_discriminator, "source_discriminator")


@dataclass(frozen=True, slots=True)
class OwnerValueAllocation:
    """One owner-association-scoped canonical value allocation."""

    association: OwnerAssociation
    kind: ValueKind
    amount: Decimal
    provenance: DomainProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.association, OwnerAssociation):
            raise ValueError(
                f"association must be an OwnerAssociation, got {type(self.association).__name__}"
            )
        if not isinstance(self.provenance, DomainProvenance):
            raise ValueError(
                f"provenance must be a DomainProvenance, got {type(self.provenance).__name__}"
            )
        if self.provenance.release != self.association.provenance.release:
            raise ValueError("allocation and association provenance releases must agree")
        if not isinstance(self.kind, ValueKind):
            raise ValueError(f"kind must be a ValueKind, got {type(self.kind).__name__}")
        _require_amount(self.amount)


def _require_percentage(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError(f"ownership_percentage must be a Decimal, got {type(value).__name__}")
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(100):
        raise ValueError("ownership_percentage must be finite and from 0 through 100")
    return value
