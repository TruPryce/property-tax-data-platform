"""Attacks on the provenance boundary.

The enforceable property is that no field exists whose purpose is to accept
whatever a caller has. It is deliberately *not* asserted that a bounded string
cannot receive identifying data — a `source_member_name` can be handed
`JOHN_DOE`, and a test claiming otherwise would be false.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest
from property_tax_domain import (
    ArtifactIdentity,
    DomainProvenance,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
)

COLLIN = Jurisdiction(state_code="tx", county_slug="collin", county_fips="48085")
RELEASE = ReleaseIdentity(
    jurisdiction=COLLIN,
    tax_year=2025,
    release_kind=ReleaseKind.CERTIFIED,
    release_identifier="COLLIN-2025-CERT",
)
ARTIFACT = ArtifactIdentity(sha256="a" * 64)


def provenance(**overrides: object) -> DomainProvenance:
    fields: dict[str, object] = {
        "release": RELEASE,
        "artifact": ARTIFACT,
        "source_member_name": "PROP.TXT",
        "parser_contract_version": 1,
        "source_row_number": 1,
        "layout_fingerprint": "b" * 64,
    }
    fields.update(overrides)
    return DomainProvenance(**fields)  # type: ignore[arg-type]


def test_the_field_set_is_exactly_the_specified_six() -> None:
    names = {field.name for field in dataclasses.fields(DomainProvenance)}

    assert names == {
        "release",
        "artifact",
        "source_member_name",
        "parser_contract_version",
        "source_row_number",
        "layout_fingerprint",
    }


def test_no_field_is_a_general_purpose_carrier() -> None:
    """No payload, no mapping, no sequence of arbitrary values."""

    hints = typing.get_type_hints(DomainProvenance)
    for field in dataclasses.fields(DomainProvenance):
        assert field.name not in {
            "details",
            "detail",
            "extra",
            "metadata",
            "payload",
            "annotations",
        }
        rendered = str(hints[field.name])
        for carrier in ("Mapping", "dict", "list", "tuple", "set", "Any", "object"):
            assert carrier not in rendered, f"{field.name}: {rendered}"


def test_adapter_vocabulary_is_absent() -> None:
    names = {field.name for field in dataclasses.fields(DomainProvenance)}

    assert names.isdisjoint(
        {
            "table_name",
            "source_family",
            "source_status",
            "observed_fields",
            "normalized_fields",
        }
    )


def test_release_components_are_reachable_only_through_the_release_identity() -> None:
    """One copy of a fact, not two that have to agree."""

    names = {field.name for field in dataclasses.fields(DomainProvenance)}

    assert names.isdisjoint(
        {"jurisdiction", "tax_year", "release_kind", "release_identifier", "county_fips"}
    )
    subject = provenance()
    assert subject.release.jurisdiction == COLLIN
    assert subject.release.tax_year == 2025
    assert subject.release.release_kind is ReleaseKind.CERTIFIED
    assert subject.release.release_identifier == "COLLIN-2025-CERT"


def test_provenance_identifies_its_evidence_without_an_adapter() -> None:
    subject = provenance()

    assert subject.release.jurisdiction.rendered == "tx-collin"
    assert subject.artifact.sha256 == "a" * 64
    assert subject.source_member_name == "PROP.TXT"
    assert subject.source_row_number == 1
    assert subject.parser_contract_version == 1
    assert subject.layout_fingerprint == "b" * 64


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("member name over length", {"source_member_name": "a" * 129}),
        ("member name with a separator", {"source_member_name": "a/b"}),
        ("member name with whitespace", {"source_member_name": " PROP.TXT"}),
        ("member name leading dot", {"source_member_name": ".hidden"}),
        ("member name empty", {"source_member_name": ""}),
        ("row number zero", {"source_row_number": 0}),
        ("row number negative", {"source_row_number": -1}),
        ("row number bool", {"source_row_number": True}),
        ("row number string", {"source_row_number": "1"}),
        ("parser version zero", {"parser_contract_version": 0}),
        ("parser version bool", {"parser_contract_version": True}),
        ("fingerprint too short", {"layout_fingerprint": "b" * 63}),
        ("fingerprint uppercase", {"layout_fingerprint": "B" * 64}),
        ("fingerprint non-hex", {"layout_fingerprint": "z" * 64}),
        ("release is a string", {"release": "tx-collin/2025/certified/X"}),
        ("artifact is a digest string", {"artifact": "a" * 64}),
    ],
)
def test_a_value_outside_its_bound_is_rejected_not_coerced(
    label: str, overrides: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        provenance(**overrides)


def test_absence_is_none_and_never_a_placeholder() -> None:
    absent = provenance(source_row_number=None, layout_fingerprint=None)

    assert absent.source_row_number is None
    assert absent.layout_fingerprint is None
    # The placeholders that would read as data while meaning "we had none".
    with pytest.raises(ValueError):
        provenance(layout_fingerprint="0" * 64 + "0")
    with pytest.raises(ValueError):
        provenance(source_row_number=0)
    with pytest.raises(ValueError):
        provenance(source_member_name="")


def test_a_bounded_lineage_string_is_not_claimed_to_reject_a_name() -> None:
    """Stating the guarantee honestly.

    Structure prevents a field whose purpose is to accept anything. It does not
    make a name unrepresentable, and a test asserting that it did would be
    false — so this asserts the true thing instead.
    """

    assert provenance(source_member_name="JOHN_DOE").source_member_name == "JOHN_DOE"
