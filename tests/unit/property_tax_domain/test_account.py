"""Attacks on canonical account identity and snapshot grain."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest
from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    ArtifactIdentity,
    DomainProvenance,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
)

COLLIN = Jurisdiction(state_code="tx", county_slug="collin", county_fips="48085")
DALLAS = Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113")


def release(
    jurisdiction: Jurisdiction = COLLIN,
    kind: ReleaseKind = ReleaseKind.CERTIFIED,
    identifier: str = "R-1",
) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=jurisdiction,
        tax_year=2025,
        release_kind=kind,
        release_identifier=identifier,
    )


def provenance(subject: ReleaseIdentity) -> DomainProvenance:
    return DomainProvenance(
        release=subject,
        artifact=ArtifactIdentity("a" * 64),
        source_member_name="PROP.TXT",
        parser_contract_version=1,
        source_row_number=2,
        layout_fingerprint="b" * 64,
    )


def test_equal_source_identifiers_in_two_jurisdictions_are_unequal_accounts() -> None:
    assert AccountIdentity(COLLIN, "123") != AccountIdentity(DALLAS, "123")


def test_one_account_in_two_releases_is_one_identity_and_two_snapshots() -> None:
    identity = AccountIdentity(COLLIN, "123")
    proposed = release(kind=ReleaseKind.PROPOSED, identifier="PROPOSED")
    certified = release(kind=ReleaseKind.CERTIFIED, identifier="CERTIFIED")
    first = AccountSnapshot(identity, provenance(proposed))
    second = AccountSnapshot(identity, provenance(certified))

    assert first.identity == second.identity
    assert first != second
    assert first.grain == (identity, proposed)
    assert second.grain == (identity, certified)


def test_snapshot_has_one_release_authority_reached_through_provenance() -> None:
    fields = {field.name for field in dataclasses.fields(AccountSnapshot)}
    subject_release = release()
    subject = AccountSnapshot(AccountIdentity(COLLIN, "123"), provenance(subject_release))

    assert fields == {"identity", "provenance", "source_as_of", "situs", "legal_description"}
    assert "release" not in fields
    assert subject.provenance.release is subject_release


def test_source_as_of_is_timezone_aware_and_excluded_from_equality_and_hashing() -> None:
    identity = AccountIdentity(COLLIN, "123")
    lineage = provenance(release())
    first = AccountSnapshot(identity, lineage, source_as_of=datetime(2025, 1, 1, tzinfo=UTC))
    second = AccountSnapshot(
        identity,
        lineage,
        source_as_of=datetime(2025, 1, 2, tzinfo=timezone(timedelta(hours=-6))),
    )

    assert first == second
    assert hash(first) == hash(second)
    with pytest.raises(ValueError, match="timezone-aware"):
        AccountSnapshot(identity, lineage, source_as_of=datetime(2025, 1, 1))


def test_account_identity_has_no_nullable_or_provisional_form() -> None:
    fields = dataclasses.fields(AccountIdentity)

    assert [(field.name, field.default) for field in fields] == [
        ("jurisdiction", dataclasses.MISSING),
        ("source_account_id", dataclasses.MISSING),
    ]
    with pytest.raises(TypeError):
        AccountIdentity(COLLIN)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "identifier",
    ["", ".abc", "-abc", "a" * 129, "a b", "a/b", "a\\b", "a:b", "a\nb"],
)
def test_every_identifier_bound_is_enforced_without_coercion(identifier: str) -> None:
    with pytest.raises(ValueError):
        AccountIdentity(COLLIN, identifier)


def test_domain_validates_lexically_without_claiming_account_key_approval() -> None:
    """County adapters own approval under county-appraisal-normalization."""

    assert AccountIdentity(COLLIN, "123").source_account_id == "123"


def test_cross_jurisdiction_identity_and_release_fail_at_the_snapshot_root() -> None:
    with pytest.raises(ValueError, match="jurisdiction"):
        AccountSnapshot(AccountIdentity(DALLAS, "123"), provenance(release(COLLIN)))
