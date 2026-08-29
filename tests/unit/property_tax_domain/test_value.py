"""Attacks on canonical appraisal values and taxable-value grain."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import property_tax_domain.value as value_module
import pytest
from property_tax_domain import (
    AccountIdentity,
    AccountSnapshot,
    AppraisalValueObservation,
    ArtifactIdentity,
    DomainProvenance,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
    TaxableValueObservation,
    TaxingUnitObservation,
    ValueKind,
)

JURISDICTION = Jurisdiction("tx", "dallas", "48113")
RELEASE = ReleaseIdentity(JURISDICTION, 2025, ReleaseKind.CERTIFIED, "R-1")
PROVENANCE = DomainProvenance(RELEASE, ArtifactIdentity("a" * 64), "APPRAISAL.CSV", 1, 2)
SNAPSHOT = AccountSnapshot(AccountIdentity(JURISDICTION, "123"), PROVENANCE)


def test_market_appraised_and_assessed_are_distinct_observations() -> None:
    values = tuple(
        AppraisalValueObservation(SNAPSHOT, kind, Decimal("100"), PROVENANCE) for kind in ValueKind
    )

    assert {value.kind for value in values} == set(ValueKind)
    assert len(set(values)) == 3


def test_value_vocabulary_is_exactly_three_and_has_no_source_native_extensions() -> None:
    assert {kind.value for kind in ValueKind} == {"market", "appraised", "assessed"}
    forbidden = {
        "taxable",
        "land",
        "improvement",
        "agricultural",
        "timber",
        "productivity",
        "cap",
    }
    assert {kind.value for kind in ValueKind}.isdisjoint(forbidden)
    for name in forbidden:
        with pytest.raises(ValueError):
            ValueKind(name)


def test_domain_exposes_no_source_label_mapping_callable() -> None:
    forbidden_fragments = ("canonicalize", "from_source", "map_source", "source_to")
    callables = {
        name
        for name, value in vars(value_module).items()
        if callable(value) and not name.startswith("__")
    }

    assert not any(fragment in name for name in callables for fragment in forbidden_fragments)


def test_taxable_value_has_no_constructible_form_without_a_taxing_unit() -> None:
    fields = {field.name for field in dataclasses.fields(TaxableValueObservation)}

    assert fields == {"snapshot", "taxing_unit", "amount", "basis", "provenance"}
    with pytest.raises(TypeError):
        TaxableValueObservation(  # type: ignore[call-arg]
            snapshot=SNAPSHOT,
            amount=Decimal("100"),
            basis="county basis",
            provenance=PROVENANCE,
        )


def test_several_taxable_values_each_retain_their_unit_and_basis() -> None:
    city = TaxingUnitObservation(SNAPSHOT, "CITY", PROVENANCE, "City")
    school = TaxingUnitObservation(SNAPSHOT, "ISD", PROVENANCE, "School District")
    values = (
        TaxableValueObservation(SNAPSHOT, city, Decimal("90"), "city basis", PROVENANCE),
        TaxableValueObservation(SNAPSHOT, school, Decimal("80"), "school basis", PROVENANCE),
    )

    assert [(value.taxing_unit.unit_code, value.basis) for value in values] == [
        ("CITY", "city basis"),
        ("ISD", "school basis"),
    ]


@pytest.mark.parametrize(
    "amount",
    [1.0, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_non_exact_or_non_finite_amounts_are_rejected(amount: object) -> None:
    with pytest.raises(ValueError):
        AppraisalValueObservation(
            SNAPSHOT,
            ValueKind.MARKET,
            amount,
            PROVENANCE,  # type: ignore[arg-type]
        )


def test_zero_and_negative_amounts_remain_exact_values() -> None:
    for amount in (Decimal("0"), Decimal("-1.25")):
        assert (
            AppraisalValueObservation(SNAPSHOT, ValueKind.APPRAISED, amount, PROVENANCE).amount
            == amount
        )
