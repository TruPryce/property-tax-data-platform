"""Attacks on lineage, classification, and permission boundaries."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from property_tax_domain import (
    RECORD_CLASSIFICATIONS,
    AccountIdentity,
    AccountSnapshot,
    AppraisalValueObservation,
    ArtifactIdentity,
    DomainProvenance,
    ExemptionObservation,
    ExemptionScope,
    GeometryEncoding,
    GeometryObservation,
    ImprovementObservation,
    Jurisdiction,
    LandObservation,
    LegalDescription,
    MailingAddress,
    OwnerAssociation,
    OwnerObservation,
    OwnerValueAllocation,
    RecordClassification,
    ReleaseIdentity,
    ReleaseKind,
    SitusAddress,
    TaxableValueObservation,
    TaxingUnitObservation,
    ValueKind,
)

COLLIN = Jurisdiction("tx", "collin", "48085")
DALLAS = Jurisdiction("tx", "dallas", "48113")


def release(identifier: str = "R-1", jurisdiction: Jurisdiction = COLLIN) -> ReleaseIdentity:
    return ReleaseIdentity(jurisdiction, 2025, ReleaseKind.CERTIFIED, identifier)


def provenance(
    subject_release: ReleaseIdentity | None = None,
    *,
    artifact: str = "a",
    member: str = "PROP.TXT",
    row: int = 1,
    layout: str = "b",
) -> DomainProvenance:
    return DomainProvenance(
        subject_release or release(),
        ArtifactIdentity(artifact * 64),
        member,
        1,
        row,
        layout * 64,
    )


def snapshot(
    lineage: DomainProvenance | None = None,
    *,
    account: str = "123",
    situs: SitusAddress | None = None,
    legal: LegalDescription | None = None,
) -> AccountSnapshot:
    evidence = lineage or provenance()
    return AccountSnapshot(
        AccountIdentity(evidence.release.jurisdiction, account),
        evidence,
        situs=situs,
        legal_description=legal,
    )


def records(subject: AccountSnapshot) -> tuple[object, ...]:
    observed_owner = OwnerObservation(subject, "Source Owner", subject.provenance)
    association = OwnerAssociation(subject, observed_owner, subject.provenance)
    taxing_unit = TaxingUnitObservation(subject, "ISD", subject.provenance)
    return (
        subject,
        observed_owner,
        association,
        OwnerValueAllocation(association, ValueKind.ASSESSED, Decimal("1"), subject.provenance),
        AppraisalValueObservation(subject, ValueKind.APPRAISED, Decimal("1"), subject.provenance),
        taxing_unit,
        TaxableValueObservation(
            subject, taxing_unit, Decimal("1"), "source basis", subject.provenance
        ),
        ExemptionObservation(subject, "source label", ExemptionScope.ACCOUNT, subject.provenance),
        LandObservation(subject, subject.provenance),
        ImprovementObservation(subject, subject.provenance),
        GeometryObservation(
            subject, GeometryEncoding.WKB, b"opaque", "SOURCE-CRS", subject.provenance
        ),
    )


def test_provenance_attaches_to_every_observed_record_and_not_to_values() -> None:
    subject = snapshot()

    for record in records(subject):
        assert isinstance(record.provenance, DomainProvenance)  # type: ignore[attr-defined]
    for value in (
        subject.identity,
        SitusAddress(city="Collin"),
        MailingAddress(city="Collin"),
        LegalDescription("Lot 1"),
    ):
        assert "provenance" not in {field.name for field in dataclasses.fields(value)}


def test_empty_composed_address_values_are_rejected() -> None:
    for value_type in (SitusAddress, MailingAddress):
        with pytest.raises(ValueError, match="at least one"):
            value_type()


def test_address_components_enforce_their_bound_without_rewriting() -> None:
    preserved = " Mixed Case "

    assert SitusAddress(city=preserved).city == preserved
    assert SitusAddress(city="x" * 128).city == "x" * 128
    for value in ("x" * 129, "   ", "city\x00name"):
        with pytest.raises(ValueError):
            SitusAddress(city=value)


def test_legal_description_uses_the_label_bound_and_preserves_text() -> None:
    preserved = " Lot 1, Block A "

    assert LegalDescription(preserved).text == preserved
    assert len(LegalDescription("x" * 256).text) == 256
    for value in ("", "x" * 257, "   ", "lot\n1"):
        with pytest.raises(ValueError):
            LegalDescription(value)


def test_child_examined_alone_keeps_full_lineage() -> None:
    child = LandObservation(snapshot(), provenance())
    lineage = child.provenance

    assert lineage.release.jurisdiction == COLLIN
    assert lineage.release.tax_year == 2025
    assert lineage.artifact.sha256 == "a" * 64
    assert lineage.source_member_name == "PROP.TXT"
    assert lineage.source_row_number == 1
    assert lineage.parser_contract_version == 1
    assert lineage.layout_fingerprint == "b" * 64


@pytest.mark.parametrize(
    "build",
    [
        lambda parent, other: OwnerObservation(parent, "Owner", other),
        lambda parent, other: OwnerAssociation(
            parent, OwnerObservation(parent, "Owner", parent.provenance), other
        ),
        lambda parent, other: OwnerValueAllocation(
            OwnerAssociation(
                parent, OwnerObservation(parent, "Owner", parent.provenance), parent.provenance
            ),
            ValueKind.MARKET,
            Decimal("1"),
            other,
        ),
        lambda parent, other: AppraisalValueObservation(
            parent, ValueKind.MARKET, Decimal("1"), other
        ),
        lambda parent, other: TaxingUnitObservation(parent, "ISD", other),
        lambda parent, other: TaxableValueObservation(
            parent,
            TaxingUnitObservation(parent, "ISD", parent.provenance),
            Decimal("1"),
            "basis",
            other,
        ),
        lambda parent, other: ExemptionObservation(parent, "label", ExemptionScope.ACCOUNT, other),
        lambda parent, other: LandObservation(parent, other),
        lambda parent, other: ImprovementObservation(parent, other),
        lambda parent, other: GeometryObservation(parent, GeometryEncoding.WKB, b"x", "CRS", other),
    ],
)
def test_every_parented_record_rejects_another_release(build) -> None:  # noqa: ANN001
    parent = snapshot(provenance(release("R-1")))
    other = provenance(release("R-2"))

    with pytest.raises(ValueError, match="release"):
        build(parent, other)


def test_no_observed_record_carries_a_second_release_identity() -> None:
    for record in records(snapshot()):
        assert "release" not in {field.name for field in dataclasses.fields(record)}
        assert record.provenance.release == release()  # type: ignore[attr-defined]


def test_equal_grain_preserves_different_evidence_and_composed_values() -> None:
    base = snapshot(provenance())
    variants = (
        snapshot(provenance(artifact="c")),
        snapshot(provenance(member="OTHER.TXT")),
        snapshot(provenance(row=2)),
        snapshot(provenance(layout="d")),
        snapshot(provenance(), situs=SitusAddress(city="Collin")),
        snapshot(provenance(), legal=LegalDescription("Lot 1")),
    )

    assert all(candidate.grain == base.grain for candidate in variants)
    assert all(candidate != base for candidate in variants)


def test_source_as_of_remains_outside_equality() -> None:
    evidence = provenance()
    identity = AccountIdentity(COLLIN, "123")

    assert AccountSnapshot(identity, evidence) == AccountSnapshot(
        identity, evidence, source_as_of=datetime(2025, 1, 1, tzinfo=UTC)
    )


def test_snapshot_root_rejects_another_jurisdiction() -> None:
    with pytest.raises(ValueError, match="jurisdiction"):
        AccountSnapshot(AccountIdentity(DALLAS, "123"), provenance())


def test_record_classification_is_exact_complete_and_read_only() -> None:
    expected = {
        AccountIdentity: RecordClassification.STABLE_IDENTITY,
        AccountSnapshot: RecordClassification.RELEASE_SNAPSHOT,
        OwnerObservation: RecordClassification.CHILD_OBSERVATION,
        OwnerAssociation: RecordClassification.ASSOCIATION,
        OwnerValueAllocation: RecordClassification.ASSOCIATION,
        AppraisalValueObservation: RecordClassification.CHILD_OBSERVATION,
        TaxingUnitObservation: RecordClassification.CHILD_OBSERVATION,
        TaxableValueObservation: RecordClassification.CHILD_OBSERVATION,
        ExemptionObservation: RecordClassification.CHILD_OBSERVATION,
        LandObservation: RecordClassification.CHILD_OBSERVATION,
        ImprovementObservation: RecordClassification.CHILD_OBSERVATION,
        GeometryObservation: RecordClassification.ENRICHMENT,
    }

    assert dict(RECORD_CLASSIFICATIONS) == expected
    for value_type in (SitusAddress, MailingAddress, LegalDescription):
        assert value_type not in RECORD_CLASSIFICATIONS
    with pytest.raises(TypeError):
        RECORD_CLASSIFICATIONS[AccountIdentity] = RecordClassification.ENRICHMENT  # type: ignore[index]
    with pytest.raises(TypeError):
        del RECORD_CLASSIFICATIONS[AccountIdentity]  # type: ignore[attr-defined]
    # Replacement and deletion are not the whole surface: a mapping that refuses
    # both while accepting a new key is still editable, and a classification a
    # consumer can extend is not the published one.
    with pytest.raises(TypeError):
        RECORD_CLASSIFICATIONS[SitusAddress] = RecordClassification.CHILD_OBSERVATION  # type: ignore[index]
    assert SitusAddress not in RECORD_CLASSIFICATIONS


def test_no_record_carries_publication_or_visibility_permission() -> None:
    forbidden = {"publishable", "publication", "permission", "visibility", "redaction_override"}

    for value_type in RECORD_CLASSIFICATIONS:
        assert {field.name for field in dataclasses.fields(value_type)}.isdisjoint(forbidden)
