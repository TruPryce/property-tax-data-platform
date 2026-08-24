"""Attacks on the identity contract.

These are not demonstrations of what the implementation happens to do. Each one
states a rule the accepted capability fixes and tries to break it.
"""

from __future__ import annotations

import dataclasses

import pytest
from property_tax_domain import (
    ARTIFACT_IDENTITY_HEX_LENGTH,
    ArtifactIdentity,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
)

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def collin() -> Jurisdiction:
    return Jurisdiction(state_code="tx", county_slug="collin", county_fips="48085")


def dallas() -> Jurisdiction:
    return Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113")


# --------------------------------------------------------------------------
# Jurisdiction
# --------------------------------------------------------------------------


def test_equal_state_and_slug_are_one_jurisdiction() -> None:
    assert collin() == collin()
    assert hash(collin()) == hash(collin())


def test_different_counties_are_different_jurisdictions() -> None:
    assert collin() != dallas()


def test_the_equality_basis_is_exactly_state_and_slug() -> None:
    """Assertable directly, rather than gestured at.

    Saying equality holds "regardless of any other attribute" would be
    unfalsifiable here: registry validation makes a jurisdiction whose FIPS
    differs from its slug's registered value unconstructible, so the
    counterexample cannot be built. The enumerable set can be checked instead.
    """

    participating = {field.name for field in dataclasses.fields(Jurisdiction) if field.compare}

    assert participating == {"state_code", "county_slug"}


def test_a_slug_paired_with_another_countys_fips_is_unconstructible() -> None:
    with pytest.raises(ValueError, match="registry"):
        Jurisdiction(state_code="tx", county_slug="collin", county_fips="48113")


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("uppercase state", {"state_code": "TX", "county_slug": "collin", "county_fips": "48085"}),
        ("mixed-case state", {"state_code": "Tx", "county_slug": "collin", "county_fips": "48085"}),
        ("uppercase slug", {"state_code": "tx", "county_slug": "Collin", "county_fips": "48085"}),
        (
            "three-letter state",
            {"state_code": "tex", "county_slug": "collin", "county_fips": "48085"},
        ),
        ("four-digit fips", {"state_code": "tx", "county_slug": "collin", "county_fips": "4808"}),
        ("non-digit fips", {"state_code": "tx", "county_slug": "collin", "county_fips": "4808a"}),
        (
            "slug with underscore",
            {"state_code": "tx", "county_slug": "col_lin", "county_fips": "48085"},
        ),
        (
            "slug leading hyphen",
            {"state_code": "tx", "county_slug": "-collin", "county_fips": "48085"},
        ),
        ("unknown slug", {"state_code": "tx", "county_slug": "harris", "county_fips": "48201"}),
    ],
)
def test_malformed_jurisdiction_input_is_rejected_not_repaired(
    label: str, kwargs: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        Jurisdiction(**kwargs)


def test_the_registry_keeps_its_uppercase_state_code() -> None:
    """The case fold happens on the registry side, not on caller identity."""

    from property_tax_domain import county_by_slug

    assert county_by_slug("collin").state_code == "TX"
    assert collin().state_code == "tx"


def test_a_jurisdiction_renders_as_the_stored_code() -> None:
    assert collin().rendered == "tx-collin"


# --------------------------------------------------------------------------
# ArtifactIdentity
# --------------------------------------------------------------------------


def test_the_published_digest_length_is_the_enforced_bound() -> None:
    assert ARTIFACT_IDENTITY_HEX_LENGTH == 64
    with pytest.raises(ValueError):
        ArtifactIdentity(sha256="a" * (ARTIFACT_IDENTITY_HEX_LENGTH - 1))
    ArtifactIdentity(sha256="a" * ARTIFACT_IDENTITY_HEX_LENGTH)


def test_the_same_bytes_are_one_artifact_wherever_they_were_found() -> None:
    """Identity is content. A URL and a filename are not part of it."""

    assert ArtifactIdentity(sha256=DIGEST) == ArtifactIdentity(sha256=DIGEST)
    assert hash(ArtifactIdentity(sha256=DIGEST)) == hash(ArtifactIdentity(sha256=DIGEST))


def test_different_bytes_under_one_name_are_different_artifacts() -> None:
    assert ArtifactIdentity(sha256=DIGEST) != ArtifactIdentity(sha256=OTHER_DIGEST)


def test_artifact_identity_carries_nothing_but_the_digest() -> None:
    assert [field.name for field in dataclasses.fields(ArtifactIdentity)] == ["sha256"]


@pytest.mark.parametrize(
    ("label", "digest"),
    [
        ("uppercase hex", "A" * 64),
        ("too short", "a" * 63),
        ("too long", "a" * 65),
        ("non-hex character", "g" * 64),
        ("surrounding whitespace", " " + "a" * 63),
        ("empty", ""),
    ],
)
def test_a_malformed_digest_is_rejected_not_coerced(label: str, digest: str) -> None:
    with pytest.raises(ValueError):
        ArtifactIdentity(sha256=digest)


# --------------------------------------------------------------------------
# ReleaseKind
# --------------------------------------------------------------------------


def test_the_release_kind_vocabulary_is_closed() -> None:
    assert {kind.value for kind in ReleaseKind} == {
        "proposed",
        "certified",
        "supplemental",
        "current",
    }


def test_a_kind_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(ValueError):
        ReleaseKind("preliminary")


def test_the_kind_vocabulary_names_no_county() -> None:
    """County-native labels stay at the adapter boundary."""

    text = " ".join(kind.value for kind in ReleaseKind)
    for county in ("dallas", "collin", "tarrant", "denton", "rockwall", "ellis"):
        assert county not in text


# --------------------------------------------------------------------------
# ReleaseIdentity
# --------------------------------------------------------------------------


def release(**overrides: object) -> ReleaseIdentity:
    fields: dict[str, object] = {
        "jurisdiction": collin(),
        "tax_year": 2025,
        "release_kind": ReleaseKind.CERTIFIED,
        "release_identifier": "COLLIN-2025-CERT-01",
    }
    fields.update(overrides)
    return ReleaseIdentity(**fields)  # type: ignore[arg-type]


def test_two_counties_may_reuse_one_source_label() -> None:
    """The label is namespaced by the jurisdiction, so neither is renamed."""

    shared = "2025-CERT"
    first = release(jurisdiction=dallas(), release_identifier=shared)
    second = release(jurisdiction=collin(), release_identifier=shared)

    assert first != second
    assert first.release_identifier == second.release_identifier == shared


def test_one_county_may_issue_two_releases_of_one_kind_in_one_year() -> None:
    assert release(release_identifier="A-1") != release(release_identifier="A-2")


def test_identifiers_differing_only_by_case_are_both_valid_and_unequal() -> None:
    """Both letter cases are inside the accepted alphabet.

    Rejecting one would invalidate half that alphabet or impose an unstated
    canonical case, so case is preserved and significant.
    """

    upper = release(release_identifier="ABC")
    lower = release(release_identifier="abc")

    assert upper != lower
    assert upper.release_identifier == "ABC"
    assert lower.release_identifier == "abc"


@pytest.mark.parametrize(
    ("label", "identifier"),
    [
        ("surrounding whitespace", " ABC "),
        ("inner space", "A BC"),
        ("path separator", "a/b"),
        ("windows separator", "a\\b"),
        ("leading dot", ".abc"),
        ("leading hyphen", "-abc"),
        ("empty", ""),
        ("over length", "a" * 129),
        ("colon", "a:b"),
        ("newline", "a\nb"),
    ],
)
def test_an_identifier_outside_the_grammar_is_rejected_not_repaired(
    label: str, identifier: str
) -> None:
    with pytest.raises(ValueError):
        release(release_identifier=identifier)


def test_the_length_boundaries_are_inclusive() -> None:
    assert release(release_identifier="a").release_identifier == "a"
    assert len(release(release_identifier="a" * 128).release_identifier) == 128


@pytest.mark.parametrize(
    ("label", "year"),
    [
        ("below the floor", 1899),
        ("above the ceiling", 2201),
        ("a bool", True),
        ("a string", "2025"),
        ("a float", 2025.0),
    ],
)
def test_a_tax_year_outside_the_bound_is_rejected(label: str, year: object) -> None:
    with pytest.raises(ValueError):
        release(tax_year=year)


def test_the_tax_year_boundaries_are_inclusive() -> None:
    assert release(tax_year=1900).tax_year == 1900
    assert release(tax_year=2200).tax_year == 2200


def test_release_identity_carries_no_artifact() -> None:
    names = {field.name for field in dataclasses.fields(ReleaseIdentity)}

    assert names == {"jurisdiction", "tax_year", "release_kind", "release_identifier"}
    assert not any("artifact" in name or "sha" in name for name in names)


def test_no_infrastructure_identifier_participates_in_equality() -> None:
    """A location, a name, a surrogate key, or a timestamp is not identity."""

    forbidden = ("uri", "url", "key", "bucket", "path", "filename", "etag", "id", "timestamp", "at")
    for value_type in (Jurisdiction, ArtifactIdentity, ReleaseIdentity):
        for field in dataclasses.fields(value_type):
            if not field.compare:
                continue
            assert not any(token == field.name for token in forbidden), field.name
