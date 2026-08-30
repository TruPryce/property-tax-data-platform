"""Attacks on owner observation, association, and allocation grain."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    ArtifactIdentity,
    DomainProvenance,
    Jurisdiction,
    MailingAddress,
    OwnerAssociation,
    OwnerObservation,
    OwnerValueAllocation,
    ReleaseIdentity,
    ReleaseKind,
    ValueKind,
)

JURISDICTION = Jurisdiction("tx", "denton", "48121")


def release(identifier: str) -> ReleaseIdentity:
    return ReleaseIdentity(JURISDICTION, 2025, ReleaseKind.CERTIFIED, identifier)


def provenance(identifier: str = "R-1") -> DomainProvenance:
    return DomainProvenance(
        release(identifier), ArtifactIdentity("a" * 64), "PROP.TXT", 1, 1, "b" * 64
    )


def snapshot(identifier: str = "R-1", account: str = "123") -> AccountSnapshot:
    return AccountSnapshot(AccountIdentity(JURISDICTION, account), provenance(identifier))


def owner(subject: AccountSnapshot, name: str = "Source Owner") -> OwnerObservation:
    return OwnerObservation(
        subject,
        name,
        subject.provenance,
        MailingAddress(street_address="1 Main", city="Denton"),
    )


def association(subject: AccountSnapshot, discriminator: str | None = None) -> OwnerAssociation:
    return OwnerAssociation(
        subject,
        owner(subject),
        subject.provenance,
        ownership_percentage=Decimal("50"),
        source_discriminator=discriminator,
    )


def test_equal_owner_text_in_two_releases_remains_two_observations() -> None:
    first = owner(snapshot("R-1"))
    second = owner(snapshot("R-2"))

    assert first != second
    assert first.owner_name == second.owner_name
    assert not hasattr(first, "identity")


def test_several_associations_survive_without_deduplication() -> None:
    subject = snapshot()
    associations = (
        association(subject, "1"),
        OwnerAssociation(
            subject,
            owner(subject),
            subject.provenance,
            Decimal("50"),
            "2",
        ),
    )

    assert len(associations) == 2
    assert associations[0] != associations[1]


def test_owner_value_allocation_is_its_own_association_scoped_record() -> None:
    subject = association(snapshot(), "1")
    allocation = OwnerValueAllocation(
        subject, ValueKind.ASSESSED, Decimal("125000.00"), subject.provenance
    )

    assert allocation.association is subject
    assert allocation.amount == Decimal("125000.00")


def test_no_owner_shape_can_hold_an_assembled_account_total() -> None:
    forbidden = {"account_total", "total", "total_value", "assembled_total"}

    for value_type in (AccountSnapshot, OwnerAssociation, OwnerValueAllocation):
        assert {field.name for field in dataclasses.fields(value_type)}.isdisjoint(forbidden)


def test_association_is_constructible_without_a_discriminator() -> None:
    assert association(snapshot()).source_discriminator is None


@pytest.mark.parametrize("percentage", [Decimal("-0.01"), Decimal("100.01"), 50.0, True])
def test_percentage_outside_its_exact_decimal_bound_is_rejected(percentage: object) -> None:
    subject = snapshot()
    with pytest.raises(ValueError):
        OwnerAssociation(
            subject,
            owner(subject),
            subject.provenance,
            ownership_percentage=percentage,  # type: ignore[arg-type]
        )


def test_association_requires_its_owner_to_belong_to_the_same_snapshot() -> None:
    first = snapshot(account="123")
    second = snapshot(account="456")

    with pytest.raises(ValueError, match="snapshot"):
        OwnerAssociation(first, owner(second), first.provenance)
