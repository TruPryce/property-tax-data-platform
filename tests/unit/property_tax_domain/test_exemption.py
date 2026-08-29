"""Attacks on exemptions and taxing-unit observations."""

from __future__ import annotations

from decimal import Decimal

import property_tax_domain as domain
import property_tax_domain.exemption as exemption_module
import pytest
from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    ArtifactIdentity,
    DomainProvenance,
    ExemptionObservation,
    ExemptionScope,
    Jurisdiction,
    OwnerAssociation,
    OwnerObservation,
    ReleaseIdentity,
    ReleaseKind,
    TaxingUnitObservation,
)

JURISDICTION = Jurisdiction("tx", "ellis", "48139")
RELEASE = ReleaseIdentity(JURISDICTION, 2025, ReleaseKind.CERTIFIED, "R-1")
PROVENANCE = DomainProvenance(RELEASE, ArtifactIdentity("a" * 64), "PROP.TXT", 1, 1)


def snapshot(account: str = "123") -> AccountSnapshot:
    return AccountSnapshot(AccountIdentity(JURISDICTION, account), PROVENANCE)


def association(subject: AccountSnapshot) -> OwnerAssociation:
    observed = OwnerObservation(subject, "Source Owner", subject.provenance)
    return OwnerAssociation(subject, observed, subject.provenance)


def test_unknown_county_label_is_retained_verbatim_without_widening_a_vocabulary() -> None:
    subject = snapshot()
    exemption = ExemptionObservation(
        subject,
        "County Label X",
        ExemptionScope.ACCOUNT,
        PROVENANCE,
        Decimal("0"),
    )

    assert exemption.classification == "County Label X"
    assert not hasattr(domain, "ExemptionKind")
    assert not hasattr(exemption_module, "ExemptionKind")


@pytest.mark.parametrize(
    ("scope", "include_association"),
    [(ExemptionScope.ACCOUNT, True), (ExemptionScope.OWNER_ASSOCIATION, False)],
)
def test_scope_is_explicit_and_must_agree_with_the_association(
    scope: ExemptionScope, include_association: bool
) -> None:
    subject = snapshot()
    with pytest.raises(ValueError):
        ExemptionObservation(
            subject,
            "Label",
            scope,
            PROVENANCE,
            association=association(subject) if include_association else None,
        )


def test_exemption_refuses_an_association_from_another_snapshot() -> None:
    subject = snapshot("123")
    other = snapshot("456")

    with pytest.raises(ValueError, match="snapshot"):
        ExemptionObservation(
            subject,
            "Label",
            ExemptionScope.OWNER_ASSOCIATION,
            PROVENANCE,
            association=association(other),
        )


def test_domain_exposes_no_exemption_to_taxable_derivation() -> None:
    assert not any("taxable" in name.casefold() for name in vars(exemption_module))


def test_taxing_unit_is_not_the_canonical_jurisdiction() -> None:
    unit = TaxingUnitObservation(snapshot(), "ISD", PROVENANCE, "School District")

    assert not isinstance(unit, Jurisdiction)
    with pytest.raises(ValueError):
        TaxingUnitObservation(snapshot(), JURISDICTION, PROVENANCE)  # type: ignore[arg-type]
