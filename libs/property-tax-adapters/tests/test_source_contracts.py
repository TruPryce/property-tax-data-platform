"""Contract tests for the vendor-neutral source contracts.

Issue #43 decision D7 approves these three types field by field, so the field
names and their annotations are asserted against that list: a field silently
retyped later fails here rather than at whichever county notices first.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import fields
from decimal import Decimal
from typing import get_type_hints

import pytest
from property_tax_adapters.sources import contracts
from property_tax_adapters.sources.contracts import (
    AppraisalSourceRecord,
    SourceNativeValue,
    SourceProvenance,
)

COUNTIES = ("collin", "dallas", "denton", "ellis", "rockwall", "tarrant")


def provenance(**overrides: object) -> SourceProvenance:
    return SourceProvenance(
        **{
            "jurisdiction_code": "tx-dallas",
            "release_identifier": "synthetic-release-2026",
            "source_member_name": "synthetic-member.txt",
            "source_row_number": 1,
            "parser_contract_version": 1,
            "layout_fingerprint": "0" * 64,
            **overrides,
        }  # type: ignore[arg-type]
    )


def value(**overrides: object) -> SourceNativeValue:
    return SourceNativeValue(
        **{"source_field": "TOT_VAL", "value": Decimal("1.20"), **overrides}  # type: ignore[arg-type]
    )


def record(**overrides: object) -> AppraisalSourceRecord:
    return AppraisalSourceRecord(
        **{
            "jurisdiction_code": "tx-dallas",
            "appraisal_year": 2026,
            "provenance": provenance(),
            **overrides,
        }  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# The approved D7 field list
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (
            SourceNativeValue,
            {
                "source_field": "str",
                "value": "str | int | Decimal",
                "lexical_text": "str | None",
                "precision": "int | None",
                "scale": "int | None",
                "classification": "Literal['source-native']",
            },
        ),
        (
            SourceProvenance,
            {
                "jurisdiction_code": "str",
                "release_identifier": "str",
                "source_member_name": "str",
                "source_row_number": "int",
                "parser_contract_version": "int",
                "layout_fingerprint": "str",
                "table_name": "str | None",
                "source_family": "str | None",
                "source_year": "int | None",
                "source_status": "str | None",
                "observed_fields": "tuple[str, ...] | None",
                "normalized_fields": "tuple[str, ...] | None",
            },
        ),
        (
            AppraisalSourceRecord,
            {
                "jurisdiction_code": "str",
                "appraisal_year": "int",
                "provenance": "SourceProvenance",
                "source_account_id": "str | None",
                "source_family": "str | None",
                "source_status": "str | None",
                "parcel_reference": "str | None",
                "source_native_identifiers": "Mapping[str, str]",
                "source_native_values": "Mapping[str, SourceNativeValue]",
            },
        ),
    ],
)
def test_declared_fields_match_the_approved_list(cls: type, expected: dict[str, str]) -> None:
    """Names and annotations, not names alone."""

    declared = {declared.name: declared.type for declared in fields(cls)}
    assert set(declared) == set(expected)
    for name, annotation in expected.items():
        assert declared[name].replace('"', "'") == annotation, name


def test_provenance_carries_no_field_beyond_the_approved_list() -> None:
    """D7 lists six required and six optional fields. Twelve, and no thirteenth."""

    assert len(fields(SourceProvenance)) == 12


# --------------------------------------------------------------------------
# SourceNativeValue
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_value_must_name_its_source(blank: str) -> None:
    with pytest.raises(ValueError, match="source_field"):
        value(source_field=blank)


def test_value_admits_no_none_member() -> None:
    """Absence is an omitted entry, not a value that holds no value."""

    with pytest.raises(ValueError, match="omit the entry"):
        value(value=None)
    assert "None" not in get_type_hints(SourceNativeValue)["value"].__str__()


@pytest.mark.parametrize("accepted", ["text", 17, Decimal("-001.20")])
def test_value_accepts_each_declared_member(accepted: object) -> None:
    assert value(value=accepted).value == accepted


def test_an_observed_empty_text_stays_an_empty_text() -> None:
    """`""` is a text. One county emits it today for an empty extra column."""

    assert value(value="", lexical_text="").lexical_text == ""
    assert value(lexical_text="   ").lexical_text == "   "


def test_a_binary_source_has_no_lexical_text() -> None:
    """A 17-byte NUMERIC wrapper carries no original text to preserve."""

    assert value(lexical_text=None).lexical_text is None


def test_precision_and_scale_travel_together() -> None:
    assert value(precision=9, scale=2).scale == 2
    with pytest.raises(ValueError, match="together"):
        value(precision=9)
    with pytest.raises(ValueError, match="together"):
        value(scale=2)


def test_classification_is_fixed() -> None:
    assert value().classification == "source-native"
    with pytest.raises(TypeError):
        SourceNativeValue(source_field="A", value="1", classification="other")  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# SourceProvenance
# --------------------------------------------------------------------------


@pytest.mark.parametrize("row", [0, -1])
def test_a_physical_row_is_one_based(row: int) -> None:
    with pytest.raises(ValueError, match="source_row_number"):
        provenance(source_row_number=row)


def test_a_bool_is_not_a_row_number() -> None:
    """`bool` subclasses `int`, and `True` is not row one."""

    with pytest.raises(ValueError, match="source_row_number"):
        provenance(source_row_number=True)


@pytest.mark.parametrize("code", ["TX_Dallas", "tx dallas", "TX-DALLAS", "dallas", "", "  "])
def test_a_malformed_jurisdiction_is_rejected(code: str) -> None:
    with pytest.raises(ValueError, match="jurisdiction_code"):
        provenance(jurisdiction_code=code)


@pytest.mark.parametrize("code", ["tx-dallas", "tx-collin", "tx-el-paso"])
def test_a_well_formed_jurisdiction_is_accepted(code: str) -> None:
    assert provenance(jurisdiction_code=code).jurisdiction_code == code


def test_a_field_vector_distinguishes_absent_from_empty() -> None:
    """`None` means the county records no vector; `()` means it recorded none."""

    assert provenance().observed_fields is None
    assert provenance(observed_fields=()).observed_fields == ()
    assert provenance(observed_fields=()).observed_fields is not None


@pytest.mark.parametrize("optional", ["table_name", "source_family", "source_status"])
def test_optional_metadata_rejects_a_string_that_only_looks_empty(optional: str) -> None:
    assert getattr(provenance(), optional) is None
    for blank in ("", "   "):
        with pytest.raises(ValueError, match=optional):
            provenance(**{optional: blank})


# --------------------------------------------------------------------------
# AppraisalSourceRecord
# --------------------------------------------------------------------------


def test_a_record_cannot_be_constructed_without_provenance() -> None:
    """A source-native record whose origin is unknown is not evidence."""

    with pytest.raises(TypeError):
        AppraisalSourceRecord(jurisdiction_code="tx-dallas", appraisal_year=2026)  # type: ignore[call-arg]


def test_leading_zeroes_remain_meaningful() -> None:
    """One accepted contract requires `000123` and `123` to stay distinct."""

    assert record(source_account_id="000123") != record(source_account_id="123")
    assert record(source_account_id="000123").source_account_id == "000123"


@pytest.mark.parametrize(
    "nullable", ["source_account_id", "source_family", "source_status", "parcel_reference"]
)
def test_absence_is_none_and_never_a_string_that_looks_empty(nullable: str) -> None:
    assert getattr(record(), nullable) is None
    for blank in ("", "   "):
        with pytest.raises(ValueError, match=nullable):
            record(**{nullable: blank})


def test_a_county_with_no_approved_account_key_promotes_neither_candidate() -> None:
    held = record(
        jurisdiction_code="tx-collin",
        provenance=provenance(jurisdiction_code="tx-collin"),
        source_native_identifiers={"prop_id": "17", "geo_id": "Parcel-0007"},
    )
    assert held.source_account_id is None
    assert held.source_native_identifiers["prop_id"] == "17"
    assert held.source_native_identifiers["geo_id"] == "Parcel-0007"


def test_a_value_map_key_must_equal_its_source_field() -> None:
    """Otherwise one of the two is lying and there is no way to tell which."""

    with pytest.raises(ValueError, match="does not equal its source_field"):
        record(source_native_values={"LAND_VAL": value(source_field="TOT_VAL")})


def test_a_record_jurisdiction_must_agree_with_its_provenance() -> None:
    with pytest.raises(ValueError, match="provenance jurisdiction_code"):
        record(jurisdiction_code="tx-ellis")


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------


@pytest.mark.parametrize("attribute", ["jurisdiction_code", "appraisal_year", "_anything"])
def test_a_constructed_record_refuses_assignment(attribute: str) -> None:
    held = record()
    with pytest.raises((AttributeError, TypeError)):
        setattr(held, attribute, "mutated")
    assert held.jurisdiction_code == "tx-dallas"


def test_a_constructed_record_refuses_deletion() -> None:
    held = record()
    with pytest.raises((AttributeError, TypeError)):
        del held.jurisdiction_code


@pytest.mark.parametrize("mapping_name", ["source_native_identifiers", "source_native_values"])
def test_a_callers_mapping_cannot_reach_inside_a_record(mapping_name: str) -> None:
    """Copy then wrap. Either alone leaves a hole."""

    supplied: dict[str, object] = (
        {"prop_id": "17"} if mapping_name == "source_native_identifiers" else {"TOT_VAL": value()}
    )
    held = record(**{mapping_name: supplied})
    supplied["ADDED"] = "later" if mapping_name == "source_native_identifiers" else value()
    assert "ADDED" not in getattr(held, mapping_name)

    with pytest.raises(TypeError):
        getattr(held, mapping_name)["THROUGH_THE_RECORD"] = supplied["ADDED"]


# --------------------------------------------------------------------------
# Privacy: exactly what decision D6 claims, and no more
# --------------------------------------------------------------------------


def test_no_named_identity_field_and_no_open_payload() -> None:
    forbidden = ("owner", "mailing", "situs", "address", "name_", "payload", "extras", "metadata")
    for cls in (SourceNativeValue, SourceProvenance, AppraisalSourceRecord):
        for declared in fields(cls):
            assert not any(token in declared.name.lower() for token in forbidden), declared.name
            assert "Any" not in str(declared.type), declared.name


def test_the_weaker_privacy_guarantee_is_not_overstated() -> None:
    """Deliberately documents the property these types do NOT hold.

    `source_native_values` is keyed by county-chosen source fields, and one
    accepted county contract requires retaining unknown source columns.  A
    shared allowlist would contradict it, so bounding columns stays a county
    obligation.  Issue #78 tracks that for the county concerned.  Without this
    test a later reader could mistake the weaker property for the stronger one.
    """

    held = record(source_native_values={"OWNER_NAME": value(source_field="OWNER_NAME")})
    assert "OWNER_NAME" in held.source_native_values


def test_no_canonical_vocabulary_is_introduced() -> None:
    source = pathlib.Path(contracts.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    _strip_docstrings(tree)
    text = ast.unparse(tree).lower()
    for token in (
        "market_value",
        "appraised_value",
        "assessed_value",
        "taxable_value",
        "tax_amount",
        "exemption",
        "replacement",
    ):
        assert token not in text, token


# --------------------------------------------------------------------------
# Architecture
# --------------------------------------------------------------------------


def _strip_docstrings(tree: ast.AST) -> None:
    """A docstring may legitimately name a county; code may not."""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]


def _module_tree() -> ast.Module:
    tree = ast.parse(pathlib.Path(contracts.__file__).read_text(encoding="utf-8"))
    _strip_docstrings(tree)
    return tree


def test_the_shared_module_imports_no_county_and_no_third_party() -> None:
    permitted = {"re", "collections.abc", "dataclasses", "decimal", "types", "typing", "__future__"}
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in permitted, alias.name
        elif isinstance(node, ast.ImportFrom):
            assert node.module in permitted, node.module


def test_no_county_name_appears_in_code() -> None:
    text = ast.unparse(_module_tree()).lower()
    for county in COUNTIES:
        assert county not in text, county


def test_the_shared_module_touches_neither_domain_nor_application() -> None:
    text = ast.unparse(_module_tree())
    assert "property_tax_domain" not in text
    assert "property_tax_application" not in text


def test_no_network_archive_or_persistence_behaviour() -> None:
    text = ast.unparse(_module_tree()).lower()
    for token in ("http", "socket", "urllib", "requests", "zipfile", "sqlite", "open("):
        assert token not in text, token
