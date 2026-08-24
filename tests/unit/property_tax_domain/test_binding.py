"""Attacks on the artifact-release association.

The relationship is many-to-many in both directions, and recording another
binding must change neither identity.
"""

from __future__ import annotations

import dataclasses

import pytest
from property_tax_domain import (
    ArtifactIdentity,
    ArtifactReleaseBinding,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
)

COLLIN = Jurisdiction(state_code="tx", county_slug="collin", county_fips="48085")


def release(year: int, kind: ReleaseKind, identifier: str) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=COLLIN, tax_year=year, release_kind=kind, release_identifier=identifier
    )


def test_one_artifact_carries_several_logical_releases() -> None:
    """The measured Collin case: one archive, current for one year and certified
    for another."""

    artifact = ArtifactIdentity(sha256="c" * 64)
    current = release(2026, ReleaseKind.CURRENT, "COLLIN-2026-CURR")
    certified = release(2025, ReleaseKind.CERTIFIED, "COLLIN-2025-CERT")

    first = ArtifactReleaseBinding(artifact=artifact, release=current)
    second = ArtifactReleaseBinding(artifact=artifact, release=certified)

    assert first != second
    assert first.artifact == second.artifact == artifact
    assert first.release != second.release


def test_one_release_is_observed_in_several_artifacts() -> None:
    """Bronze divergence: one identity, different bytes, both kept and flagged."""

    subject = release(2025, ReleaseKind.CERTIFIED, "COLLIN-2025-CERT")
    first = ArtifactReleaseBinding(artifact=ArtifactIdentity(sha256="1" * 64), release=subject)
    second = ArtifactReleaseBinding(artifact=ArtifactIdentity(sha256="2" * 64), release=subject)

    assert first.artifact != second.artifact
    assert first.release == second.release == subject


def test_recording_another_binding_mutates_neither_identity() -> None:
    """Binding is an association, not a collection on either side."""

    artifact = ArtifactIdentity(sha256="d" * 64)
    subject = release(2025, ReleaseKind.CERTIFIED, "R-1")
    before_artifact, before_release = artifact, subject

    ArtifactReleaseBinding(artifact=artifact, release=subject)
    ArtifactReleaseBinding(artifact=ArtifactIdentity(sha256="e" * 64), release=subject)

    assert artifact == before_artifact
    assert subject == before_release
    for value_type in (ArtifactIdentity, ReleaseIdentity):
        for field in dataclasses.fields(value_type):
            assert "binding" not in field.name
            assert not str(field.type).startswith(("list", "tuple", "set", "frozenset"))


def test_a_binding_is_immutable() -> None:
    binding = ArtifactReleaseBinding(
        artifact=ArtifactIdentity(sha256="f" * 64),
        release=release(2025, ReleaseKind.CERTIFIED, "R-1"),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        binding.artifact = ArtifactIdentity(sha256="0" * 64)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("label", "artifact", "release_value"),
    [
        ("artifact is a bare digest", "f" * 64, None),
        ("release is a bare string", None, "tx-collin/2025/certified/R-1"),
    ],
)
def test_a_binding_refuses_anything_but_the_two_identities(
    label: str, artifact: object, release_value: object
) -> None:
    with pytest.raises(ValueError):
        ArtifactReleaseBinding(
            artifact=artifact if artifact is not None else ArtifactIdentity(sha256="f" * 64),
            release=release_value
            if release_value is not None
            else release(2025, ReleaseKind.CERTIFIED, "R-1"),
        )


def test_the_domain_constructor_does_not_judge_whether_an_identifier_was_approved() -> None:
    """The Tarrant refusal is not this layer's to make.

    A well-formed identifier is accepted here because the domain sees four
    syntactically valid components and cannot know whether a county contract
    authorized that discriminator. The county-aware mapping boundary owns that
    refusal, and asserting it here would put a fact about Tarrant's contract
    inside a package that must not import one.
    """

    tarrant = Jurisdiction(state_code="tx", county_slug="tarrant", county_fips="48439")
    accepted = ReleaseIdentity(
        jurisdiction=tarrant,
        tax_year=2025,
        release_kind=ReleaseKind.CURRENT,
        release_identifier="TARRANT-2025-01",
    )

    assert accepted.release_identifier == "TARRANT-2025-01"
    with pytest.raises(ValueError):
        ReleaseIdentity(
            jurisdiction=tarrant,
            tax_year=2025,
            release_kind=ReleaseKind.CURRENT,
            release_identifier="",
        )
