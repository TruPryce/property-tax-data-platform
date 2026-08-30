"""Canonical account identity and release-scoped account snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from property_tax_domain.address import LegalDescription, SitusAddress
from property_tax_domain.jurisdiction import Jurisdiction
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import ReleaseIdentity, require_identifier

__all__ = ["AccountIdentity", "AccountSnapshot"]


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    """A county-qualified source account identifier."""

    jurisdiction: Jurisdiction
    source_account_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.jurisdiction, Jurisdiction):
            raise ValueError(
                f"jurisdiction must be a Jurisdiction, got {type(self.jurisdiction).__name__}"
            )
        require_identifier(self.source_account_id, "source_account_id")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """One account as one logical release observed it."""

    identity: AccountIdentity
    provenance: DomainProvenance
    source_as_of: datetime | None = field(default=None, compare=False)
    situs: SitusAddress | None = None
    legal_description: LegalDescription | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, AccountIdentity):
            raise ValueError(
                f"identity must be an AccountIdentity, got {type(self.identity).__name__}"
            )
        _require_provenance(self.provenance)
        if self.identity.jurisdiction != self.provenance.release.jurisdiction:
            raise ValueError("identity jurisdiction must equal the provenance release jurisdiction")
        if self.source_as_of is not None:
            if not isinstance(self.source_as_of, datetime):
                raise ValueError(
                    f"source_as_of must be a datetime, got {type(self.source_as_of).__name__}"
                )
            if self.source_as_of.tzinfo is None or self.source_as_of.utcoffset() is None:
                raise ValueError("source_as_of must be timezone-aware")
        if self.situs is not None and not isinstance(self.situs, SitusAddress):
            raise ValueError(f"situs must be a SitusAddress, got {type(self.situs).__name__}")
        if self.legal_description is not None and not isinstance(
            self.legal_description, LegalDescription
        ):
            raise ValueError(
                "legal_description must be a LegalDescription, "
                f"got {type(self.legal_description).__name__}"
            )

    @property
    def grain(self) -> tuple[AccountIdentity, ReleaseIdentity]:
        """The account identity and logical release, in the published order."""

        return self.identity, self.provenance.release


def _require_provenance(value: object) -> DomainProvenance:
    if not isinstance(value, DomainProvenance):
        raise ValueError(f"provenance must be a DomainProvenance, got {type(value).__name__}")
    return value


def _require_snapshot(value: object) -> AccountSnapshot:
    if not isinstance(value, AccountSnapshot):
        raise ValueError(f"snapshot must be an AccountSnapshot, got {type(value).__name__}")
    return value


def _require_snapshot_release(snapshot: object, provenance: object) -> None:
    parent = _require_snapshot(snapshot)
    lineage = _require_provenance(provenance)
    if lineage.release != parent.provenance.release:
        raise ValueError("provenance release must equal the parent snapshot release")
