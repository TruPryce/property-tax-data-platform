"""Attacks on the serialization contract.

The compact rendering's reversibility is proved against the accepted alphabet
rather than asserted, by discovering the alphabet from the validator itself. If
the alphabet is later widened to admit the separator, these fail rather than the
rendering quietly becoming ambiguous.
"""

from __future__ import annotations

import json
import string

import pytest
from property_tax_domain import (
    ArtifactIdentity,
    ArtifactReleaseBinding,
    DomainProvenance,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
)
from property_tax_domain import serialization as s
from property_tax_domain.release import IDENTIFIER_MAX_CHARS, require_identifier

COLLIN = Jurisdiction(state_code="tx", county_slug="collin", county_fips="48085")
DALLAS = Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113")
ARTIFACT = ArtifactIdentity(sha256="a" * 64)


def release(identifier: str = "COLLIN-2025-CERT-01", **overrides: object) -> ReleaseIdentity:
    fields: dict[str, object] = {
        "jurisdiction": COLLIN,
        "tax_year": 2025,
        "release_kind": ReleaseKind.CERTIFIED,
        "release_identifier": identifier,
    }
    fields.update(overrides)
    return ReleaseIdentity(**fields)  # type: ignore[arg-type]


def provenance(**overrides: object) -> DomainProvenance:
    fields: dict[str, object] = {
        "release": release(),
        "artifact": ARTIFACT,
        "source_member_name": "PROP.TXT",
        "parser_contract_version": 1,
        "source_row_number": 1,
        "layout_fingerprint": "b" * 64,
    }
    fields.update(overrides)
    return DomainProvenance(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The alphabet, discovered rather than copied
# --------------------------------------------------------------------------


def accepted_alphabet() -> set[str]:
    """Every ASCII character the identifier validator admits.

    Probed in a non-leading position, because `.` and `-` are inside the
    alphabet but may not begin an identifier — two different rules that a single
    probe would conflate.
    """

    admitted: set[str] = set()
    for code in range(128):
        character = chr(code)
        try:
            require_identifier(f"a{character}", "probe")
        except ValueError:
            continue
        admitted.add(character)
    return admitted


def test_the_separator_is_outside_the_accepted_alphabet() -> None:
    """This is why the compact rendering needs no escaping.

    It is a property of the alphabets, not of the renderer, so it is checked
    against the validator rather than restated from a comment.
    """

    assert s.COMPACT_RELEASE_SEPARATOR not in accepted_alphabet()
    assert s.COMPACT_RELEASE_SEPARATOR not in string.ascii_letters + string.digits + "._-"


def test_the_compact_rendering_reverses_for_every_admissible_character() -> None:
    alphabet = accepted_alphabet()
    assert alphabet, "the probe found no admissible character; it is broken"

    for character in sorted(alphabet):
        for identifier in (
            f"a{character}",
            f"{character}a" if character.isalnum() else f"a{character}a",
        ):
            try:
                require_identifier(identifier, "probe")
            except ValueError:
                continue
            subject = release(identifier)
            assert s.parse_compact_release(subject.rendered) == subject
            assert s.parse_compact_release(subject.rendered).release_identifier == identifier


def test_the_compact_rendering_reverses_at_the_length_boundaries() -> None:
    for identifier in ("a", "a" * IDENTIFIER_MAX_CHARS, "A.b-c_d", "DCAD2025_CURRENT"):
        subject = release(identifier)
        assert s.parse_compact_release(subject.rendered) == subject


def test_no_two_distinct_identities_render_alike() -> None:
    identities = [
        release("A-1"),
        release("a-1"),
        release("A-2"),
        release("A-1", tax_year=2024),
        release("A-1", release_kind=ReleaseKind.CURRENT),
        release("A-1", jurisdiction=DALLAS),
    ]
    rendered = [identity.rendered for identity in identities]

    assert len(set(rendered)) == len(identities)
    for identity in identities:
        assert s.parse_compact_release(identity.rendered) == identity


@pytest.mark.parametrize(
    ("label", "rendered"),
    [
        ("too few components", "tx-collin/2025/certified"),
        ("too many components", "tx-collin/2025/certified/a/b"),
        ("jurisdiction is not state-and-slug", "txcollin/2025/certified/A"),
        ("year is not digits", "tx-collin/twenty/certified/A"),
        ("kind outside the vocabulary", "tx-collin/2025/preliminary/A"),
        ("unknown slug", "tx-harris/2025/certified/A"),
    ],
)
def test_a_malformed_compact_rendering_is_refused(label: str, rendered: str) -> None:
    with pytest.raises(ValueError):
        s.parse_compact_release(rendered)


# --------------------------------------------------------------------------
# Named-field JSON
# --------------------------------------------------------------------------


def test_equal_values_serialize_byte_identically() -> None:
    first = release()
    second = release()

    assert first == second
    assert s.to_json(s.release_document(first)) == s.to_json(s.release_document(second))


def test_key_order_is_the_declared_order() -> None:
    assert list(s.jurisdiction_document(COLLIN)) == ["state_code", "county_slug"]
    assert list(s.artifact_document(ARTIFACT)) == ["sha256"]
    assert list(s.release_document(release())) == [
        "jurisdiction",
        "tax_year",
        "release_kind",
        "release_identifier",
    ]
    assert list(
        s.binding_document(ArtifactReleaseBinding(artifact=ARTIFACT, release=release()))
    ) == [
        "artifact",
        "release",
    ]
    assert list(s.provenance_document(provenance())) == [
        "release",
        "artifact",
        "source_member_name",
        "source_row_number",
        "parser_contract_version",
        "layout_fingerprint",
    ]
    assert list(s.jurisdiction_registry_document(COLLIN)) == ["jurisdiction", "county_fips"]


def test_the_jurisdiction_identity_document_carries_identity_only() -> None:
    document = s.jurisdiction_document(COLLIN)

    assert document == {"state_code": "tx", "county_slug": "collin"}
    assert "county_fips" not in document


def test_identities_nest_as_objects_not_pre_rendered_strings() -> None:
    document = s.release_document(release())

    assert isinstance(document["jurisdiction"], dict)
    assert document["jurisdiction"] == {"state_code": "tx", "county_slug": "collin"}


def test_an_absent_optional_is_null_rather_than_omitted() -> None:
    """Absence and an older schema must stay distinguishable."""

    document = s.provenance_document(provenance(source_row_number=None, layout_fingerprint=None))

    assert "source_row_number" in document and document["source_row_number"] is None
    assert "layout_fingerprint" in document and document["layout_fingerprint"] is None
    assert '"source_row_number":null' in s.to_json(document)


def test_a_provenance_document_missing_an_optional_key_is_refused() -> None:
    document = s.provenance_document(provenance())
    del document["layout_fingerprint"]

    with pytest.raises(ValueError, match="null"):
        s.parse_provenance_document(document)


@pytest.mark.parametrize(
    ("label", "value", "serialize", "parse"),
    [
        ("artifact", ARTIFACT, s.artifact_document, s.parse_artifact_document),
        ("release", release(), s.release_document, s.parse_release_document),
        (
            "binding",
            ArtifactReleaseBinding(artifact=ARTIFACT, release=release()),
            s.binding_document,
            s.parse_binding_document,
        ),
        ("provenance", provenance(), s.provenance_document, s.parse_provenance_document),
        (
            "provenance with absences",
            provenance(source_row_number=None, layout_fingerprint=None),
            s.provenance_document,
            s.parse_provenance_document,
        ),
    ],
)
def test_every_value_round_trips_unaltered(label, value, serialize, parse) -> None:  # noqa: ANN001
    assert parse(json.loads(s.to_json(serialize(value)))) == value


def test_a_jurisdiction_identity_document_round_trips_its_identity() -> None:
    """Identity survives; metadata is not being round-tripped, because it is not
    in there."""

    parsed = s.parse_jurisdiction_document(s.jurisdiction_document(COLLIN))

    assert parsed == COLLIN
    assert (parsed.state_code, parsed.county_slug) == ("tx", "collin")
    assert parsed.county_fips == "48085", "resolved from the registry, not from the document"


def test_an_identity_document_naming_an_unregistered_slug_fails_to_parse() -> None:
    with pytest.raises(ValueError, match="registry"):
        s.parse_jurisdiction_document({"state_code": "tx", "county_slug": "harris"})


def test_the_registry_document_is_where_a_disagreement_is_detectable() -> None:
    document = s.jurisdiction_registry_document(COLLIN)
    document["county_fips"] = "48113"

    with pytest.raises(ValueError, match="disagrees"):
        s.parse_jurisdiction_registry_document(document)


def test_the_registry_document_parser_returns_the_recorded_value() -> None:
    jurisdiction, recorded = s.parse_jurisdiction_registry_document(
        s.jurisdiction_registry_document(COLLIN)
    )

    assert jurisdiction == COLLIN
    assert recorded == "48085"


def test_a_release_document_with_a_kind_outside_the_vocabulary_is_refused() -> None:
    document = s.release_document(release())
    document["release_kind"] = "preliminary"

    with pytest.raises(ValueError, match="vocabulary"):
        s.parse_release_document(document)


def test_a_release_document_with_a_bool_tax_year_is_refused() -> None:
    document = s.release_document(release())
    document["tax_year"] = True

    with pytest.raises(ValueError):
        s.parse_release_document(document)
