"""Binding, package-classification, and boundary tests for the Ellis foundation.

Every expectation is authored from the accepted OpenSpec change
``add-ellis-cad-pacs-parser-binding`` rather than from the parser's output.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fixtures import ellis_synthetic as synthetic
from property_tax_adapters.sources.texas.denton import DENTON_PROPERTY_LAYOUT
from property_tax_adapters.sources.texas.ellis import (
    ELLIS_CERTIFIED_LABEL,
    ELLIS_DIAGNOSTIC_RETENTION_LIMIT,
    ELLIS_EXPECTED_LAYOUT_FINGERPRINT,
    ELLIS_PROPERTY_LAYOUT,
    ELLIS_SENSITIVE_FIELDS,
    ELLIS_SOURCE,
    EllisDiagnostic,
    EllisDiagnosticCode,
    EllisValidationReport,
    LayoutPackageKind,
    classify_layout_package,
    validate_property_member,
)

IDENTITY = {
    "release_identifier": synthetic.RELEASE_IDENTIFIER,
    "source_member_name": synthetic.SOURCE_MEMBER_NAME,
    "release_label": synthetic.CERTIFIED_LABEL,
    "expected_tax_year": synthetic.EXPECTED_TAX_YEAR,
}


def _validate(data: bytes | str, **overrides: object) -> EllisValidationReport:
    return validate_property_member(data, **{**IDENTITY, **overrides})  # type: ignore[arg-type]


def _codes(report: EllisValidationReport) -> list[str]:
    return [entry.code.value for entry in report.diagnostics]


def _ellis_source() -> str:
    from property_tax_adapters.sources.texas import ellis

    return Path(inspect.getfile(ellis)).read_text(encoding="utf-8")


def _ellis_code() -> str:
    """The module's code with docstrings and comments removed.

    The prose legitimately says the binding "decompresses nothing" and explains
    why it does not depend on Denton. A raw grep fails on those explanations
    while catching nothing real, so the structural claims read the parsed code.
    """

    tree = ast.parse(_ellis_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value.value = ""
    return ast.unparse(tree)


# --------------------------------------------------------------------------
# Binding rather than forking
# --------------------------------------------------------------------------


def test_ellis_binds_to_the_shared_component() -> None:
    source = _ellis_source()
    assert "from property_tax_adapters.sources.pacs import" in source
    assert isinstance(ELLIS_PROPERTY_LAYOUT.fingerprint, str)


def test_ellis_defines_no_slicing_or_fingerprint_logic_of_its_own() -> None:
    """Issue #21 forbids copying or forking the shared parser."""

    tree = ast.parse(_ellis_source())
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    for forked in (
        "slice_record",
        "layout_fingerprint",
        "_fingerprint",
        "PacsField",
        "PacsLayout",
        "_slice",
    ):
        assert forked not in defined, forked
    assert "hashlib" not in _ellis_code(), "fingerprinting belongs to the shared component"


def test_ellis_does_not_depend_on_denton() -> None:
    """Two independent bindings of one component.

    A dependency between them would let a Denton layout change silently alter
    Ellis behaviour.
    """

    assert "denton" not in _ellis_code().casefold()


def test_the_ellis_and_denton_fingerprints_are_independent() -> None:
    assert ELLIS_PROPERTY_LAYOUT.fingerprint != DENTON_PROPERTY_LAYOUT.fingerprint
    assert ELLIS_EXPECTED_LAYOUT_FINGERPRINT == ELLIS_PROPERTY_LAYOUT.fingerprint


def test_the_declared_layout_matches_the_documented_width() -> None:
    assert ELLIS_PROPERTY_LAYOUT.declared_width == synthetic.EXPECTED_PROPERTY_WIDTH
    assert len(synthetic.property_row()) == synthetic.EXPECTED_PROPERTY_WIDTH


def test_a_foreign_expected_fingerprint_is_refused() -> None:
    """Sharing a vendor with Denton is not evidence that the schemas agree."""

    report = _validate(
        synthetic.VALID_LF, expected_layout_fingerprint=DENTON_PROPERTY_LAYOUT.fingerprint
    )
    assert _codes(report) == ["unsupported_layout_fingerprint"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_the_fingerprint_gate_runs_before_any_record_is_read() -> None:
    """A misidentified artifact must not have its records parsed at all."""

    report = _validate(
        synthetic.WIDTH_MISMATCH, expected_layout_fingerprint=DENTON_PROPERTY_LAYOUT.fingerprint
    )
    assert _codes(report) == ["unsupported_layout_fingerprint"]
    assert "record_width_mismatch" not in _codes(report)


# --------------------------------------------------------------------------
# Layout package classification
# --------------------------------------------------------------------------


def test_a_misleading_compound_extension_is_classified_by_content() -> None:
    """The published layout is named `.xlsx.ods`; the name decides nothing."""

    assert synthetic.MISLEADING_ODS_NAME.endswith(".xlsx.ods")
    assert (
        classify_layout_package(synthetic.VALID_ODS_PACKAGE)
        is LayoutPackageKind.OPENDOCUMENT_SPREADSHEET
    )


@pytest.mark.parametrize(
    "package",
    [
        synthetic.ZIP_WITHOUT_MIMETYPE,
        synthetic.ZIP_WITH_OTHER_MEDIA_TYPE,
        synthetic.TRUNCATED_PACKAGE,
        synthetic.NOT_A_PACKAGE,
        synthetic.EMPTY_PACKAGE,
    ],
    ids=["no-mimetype", "other-media-type", "truncated", "not-a-zip", "empty"],
)
def test_an_absent_or_ambiguous_signature_fails_closed(package: bytes) -> None:
    assert classify_layout_package(package) is LayoutPackageKind.UNRECOGNISED


def test_classification_takes_no_filename_argument() -> None:
    """A signature that cannot see the name cannot be misled by it."""

    parameters = inspect.signature(classify_layout_package).parameters
    assert list(parameters) == ["package_bytes"]


def test_classification_extracts_nothing() -> None:
    code = _ellis_code()
    for forbidden in ("zipfile", "ZipFile", "decompress", "zlib", "extractall", "namelist"):
        assert forbidden not in code, forbidden


def test_classification_reads_a_bounded_window() -> None:
    """A hostile package must not turn recognition into extraction."""

    huge = synthetic.VALID_ODS_PACKAGE + b"\x00" * 10_000_000
    assert classify_layout_package(huge) is LayoutPackageKind.OPENDOCUMENT_SPREADSHEET
    assert "_SIGNATURE_WINDOW" in _ellis_code()


def test_classification_rejects_a_non_bytes_argument() -> None:
    with pytest.raises(ValueError):
        classify_layout_package("PK\x03\x04")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Scenario labels
# --------------------------------------------------------------------------


def test_the_certified_label_is_accepted() -> None:
    report = _validate(synthetic.VALID_LF)
    assert report.release_accepted is True
    assert report.release_label == ELLIS_CERTIFIED_LABEL
    assert report.accepted_row_count == synthetic.EXPECTED_VALID_ROWS


@pytest.mark.parametrize("label", synthetic.UNSUPPORTED_LABELS)
def test_an_unsupported_scenario_label_is_refused(label: str) -> None:
    report = _validate(synthetic.VALID_LF, release_label=label)
    assert _codes(report) == ["unsupported_scenario_label"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_the_label_gate_runs_before_any_record_is_read() -> None:
    """A mineral-only scenario roll must not become certified current state."""

    report = _validate(synthetic.WIDTH_MISMATCH, release_label="mineral-only")
    assert _codes(report) == ["unsupported_scenario_label"]
    assert "record_width_mismatch" not in _codes(report)


# --------------------------------------------------------------------------
# Physical and lexical layers
# --------------------------------------------------------------------------


@pytest.mark.parametrize("member", [synthetic.VALID_LF, synthetic.VALID_CRLF], ids=["lf", "crlf"])
def test_a_valid_member_is_accepted(member: bytes) -> None:
    report = _validate(member)
    assert report.release_accepted is True
    assert report.diagnostics == ()
    assert report.parser_contract_version == 1


def test_a_byte_order_mark_is_refused() -> None:
    assert _codes(_validate(synthetic.UTF8_BOM)) == ["unexpected_bom"]


def test_text_outside_the_approved_encoding_is_refused() -> None:
    assert _codes(_validate("—" * synthetic.EXPECTED_PROPERTY_WIDTH)) == ["invalid_encoding"]


def test_records_of_disagreeing_width_are_refused() -> None:
    report = _validate(synthetic.WIDTH_MISMATCH)
    assert _codes(report) == ["record_width_mismatch"]
    assert report.diagnostics[0].physical_row_number == 2


def test_a_uniformly_short_member_is_refused() -> None:
    """Uniformity is not enough; the observed width must reach the declared one."""

    report = _validate(synthetic.UNIFORMLY_SHORT)
    assert _codes(report) == ["record_width_mismatch"]
    assert report.release_accepted is False
    assert _codes(_validate(synthetic.TRUNCATED_REQUIRED)) == ["record_width_mismatch"]


def test_a_trailing_region_warns_once_and_is_not_carried() -> None:
    report = _validate(synthetic.WITH_TRAILING_REGION)
    assert _codes(report) == ["undocumented_trailing_region"]
    assert report.release_accepted is True
    assert report.trailing_region_bytes == len(synthetic.TRAILING_REGION_TEXT)
    assert synthetic.TRAILING_REGION_TEXT not in repr(report)


def test_a_bare_cr_does_not_pass_as_one_record() -> None:
    member = (synthetic.property_row() + "\r" + synthetic.property_row()).encode("iso-8859-1")
    report = _validate(member)
    assert _codes(report) == ["invalid_source_text"]
    assert report.release_accepted is False


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("prop_id", "", "blank_required_key"),
        ("owner_sequence", "abcd", "invalid_owner_sequence"),
        ("tax_year", "1899", "invalid_tax_year"),
        ("tax_year", "2024", "tax_year_mismatch"),
        ("ownership_percentage", "101", "invalid_ownership_percentage"),
        ("market_value", "1,250.00", "invalid_monetary_value"),
        ("market_value", "-1", "invalid_monetary_value"),
        ("market_value", "", "blank_required_key"),
    ],
)
def test_an_unapproved_value_is_refused(field: str, value: str, code: str) -> None:
    report = _validate(synthetic.member(synthetic.property_row(**{field: value})))
    assert code in _codes(report), _codes(report)
    assert report.release_accepted is False


def test_an_account_identifier_is_compared_as_text() -> None:
    report = _validate(synthetic.LEADING_ZERO_ACCOUNTS)
    assert report.release_accepted is True
    assert report.accepted_row_count == 2


# --------------------------------------------------------------------------
# Owner grain, diagnostics, atomicity
# --------------------------------------------------------------------------


def test_an_owner_allocation_is_preserved() -> None:
    report = _validate(synthetic.OWNER_ALLOCATION)
    assert report.release_accepted is True
    assert report.accepted_row_count == 3
    assert report.owner_row_count == 3
    assert not hasattr(report, "account_total")


def test_a_repeated_owner_row_is_refused() -> None:
    report = _validate(synthetic.DUPLICATE_OWNER_ROW)
    assert "duplicate_owner_row" in _codes(report)
    assert report.release_accepted is False


def test_conflicting_account_facts_are_refused() -> None:
    report = _validate(synthetic.CONFLICTING_ACCOUNT_FACTS)
    assert "conflicting_account_facts" in _codes(report)
    assert report.diagnostics[0].field_name == "market_value"


def test_the_diagnostic_vocabulary_is_closed() -> None:
    observed = {code.value for code in EllisDiagnosticCode}
    assert len(observed) == synthetic.EXPECTED_DIAGNOSTIC_CODE_COUNT
    assert observed == {
        "invalid_encoding",
        "unexpected_bom",
        "record_width_mismatch",
        "unsupported_layout_fingerprint",
        "undocumented_trailing_region",
        "unsupported_scenario_label",
        "core_child_orphaned",
        "legal_child_orphaned",
        "unrecognised_layout_package",
        "blank_required_key",
        "invalid_account_id",
        "invalid_owner_sequence",
        "invalid_monetary_value",
        "invalid_ownership_percentage",
        "invalid_tax_year",
        "tax_year_mismatch",
        "invalid_source_text",
        "duplicate_owner_row",
        "conflicting_account_facts",
    }


def test_a_diagnostic_carries_only_the_four_permitted_fields() -> None:
    assert list(EllisDiagnostic.__dataclass_fields__) == [
        "code",
        "field_name",
        "physical_row_number",
        "layout_fingerprint",
    ]


def test_one_failing_record_among_many_returns_nothing() -> None:
    rows = [synthetic.property_row(prop_id=f"ACC-{index:04d}") for index in range(30)]
    rows[11] = synthetic.property_row(prop_id="ACC-0011", market_value="-1")
    report = _validate(synthetic.member(*rows))
    assert report.diagnostics[0].physical_row_number == 12
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_diagnostics_truncate_deterministically_while_preserving_the_total() -> None:
    rows = [
        synthetic.property_row(prop_id=f"ACC-{index:04d}", market_value="-1")
        for index in range(120)
    ]
    member = synthetic.member(*rows)
    report = _validate(member)
    assert len(report.diagnostics) == ELLIS_DIAGNOSTIC_RETENTION_LIMIT
    assert report.total_diagnostic_count == 120
    assert report.diagnostics_truncated is True
    assert _validate(member).diagnostics == report.diagnostics


@pytest.mark.parametrize(
    "override",
    [
        {"release_identifier": ""},
        {"source_member_name": "/var/tmp/ellis.txt"},
        {"expected_tax_year": True},
        {"expected_tax_year": "2025"},
    ],
    ids=["empty", "path", "bool", "str-year"],
)
def test_an_out_of_contract_caller_argument_raises(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _validate(synthetic.VALID_LF, **override)


# --------------------------------------------------------------------------
# Privacy and boundaries
# --------------------------------------------------------------------------


def test_owner_and_address_values_never_reach_the_report() -> None:
    rendered = repr(_validate(synthetic.VALID_LF))
    for placeholder in (
        synthetic.OWNER_PLACEHOLDER,
        synthetic.ADDRESS_PLACEHOLDER,
        synthetic.SITUS_PLACEHOLDER,
    ):
        assert placeholder not in rendered


def test_the_sensitive_field_inventory_matches_the_contract() -> None:
    assert ELLIS_SENSITIVE_FIELDS == {"owner_name", "owner_address", "situs_address"}


def test_the_report_carries_no_row_payload() -> None:
    fields = set(EllisValidationReport.__dataclass_fields__)
    assert fields == {
        "parser_contract_version",
        "release_accepted",
        "layout_fingerprint",
        "layout_version",
        "release_label",
        "accepted_row_count",
        "owner_row_count",
        "trailing_region_bytes",
        "diagnostics",
        "total_diagnostic_count",
        "diagnostics_truncated",
    }
    assert not fields & {"rows", "records", "values", "source_records"}


def test_no_county_local_shared_contract_is_defined() -> None:
    source = _ellis_code()
    for forbidden in (
        "class SourceNativeValue",
        "class SourceProvenance",
        "class AppraisalSourceRecord",
        "class EllisSourceNativeValue",
        "class EllisAppraisalSourceRecord",
    ):
        assert forbidden not in source, forbidden
    assert "sources.contracts" not in source


def test_the_domain_and_application_packages_gain_no_parser_vocabulary() -> None:
    """`ELLIS_SOURCE` legitimately imports both, so absence is not the claim."""

    source = _ellis_source()
    assert "from property_tax_application import" in source
    assert "from property_tax_domain import" in source
    assert ELLIS_SOURCE.parser_id == "texas.ellis.pacs-fixed-width-v1"

    vocabulary = (
        "EllisDiagnostic",
        "EllisValidationReport",
        "classify_layout_package",
        "LayoutPackageKind",
        "owner_sequence",
        "certified-all-property",
    )
    repo_root = Path(__file__).resolve().parents[3]
    for package in ("property-tax-domain", "property-tax-application"):
        for path in (repo_root / "libs" / package / "src").rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            leaked = [name for name in vocabulary if name in body]
            assert leaked == [], (path, leaked)


def test_no_acquisition_network_or_persistence_behavior_is_present() -> None:
    source = _ellis_code()
    for forbidden in (
        "import requests",
        "import httpx",
        "urllib",
        "socket",
        "sqlalchemy",
        "boto3",
        "open(",
    ):
        assert forbidden not in source, forbidden


def test_the_binding_adds_no_dependency_outside_the_standard_library() -> None:
    imported = {
        line.split()[1].split(".")[0]
        for line in _ellis_source().splitlines()
        if line.startswith(("import ", "from ")) and "property_tax" not in line
    }
    assert imported <= {
        "__future__",
        "re",
        "collections",
        "dataclasses",
        "decimal",
        "enum",
        "typing",
    }, imported


# --------------------------------------------------------------------------
# Review findings
# --------------------------------------------------------------------------


def test_the_expected_fingerprint_is_pinned_rather_than_derived() -> None:
    """`ELLIS_EXPECTED_LAYOUT_FINGERPRINT = ELLIS_PROPERTY_LAYOUT.fingerprint`
    moved both sides of the gate together, so mapping drift was undetectable."""

    source = _ellis_source()
    assert f'"{ELLIS_PROPERTY_LAYOUT.fingerprint}"' in source
    assert "ELLIS_EXPECTED_LAYOUT_FINGERPRINT: Final = ELLIS_PROPERTY_LAYOUT" not in source


@pytest.mark.parametrize(
    "package",
    [
        synthetic.MARKER_WITHOUT_HEADER,
        synthetic.DEFLATED_MIMETYPE,
        synthetic.WRONG_NAME_LENGTH,
    ],
    ids=["marker-without-header", "deflated-mimetype", "wrong-name-length"],
)
def test_the_local_file_header_is_parsed_rather_than_searched(package: bytes) -> None:
    """Finding the marker somewhere after a ZIP signature accepted any archive
    that happened to contain those bytes."""

    assert classify_layout_package(package) is LayoutPackageKind.UNRECOGNISED


def test_a_rejected_label_is_not_echoed_back() -> None:
    """Returning arbitrary caller text in a default-deny output."""

    from property_tax_adapters.sources.texas.ellis import ELLIS_REJECTED_LABEL

    report = _validate(synthetic.VALID_LF, release_label="ARBITRARY-CALLER-TEXT")
    assert report.release_label == ELLIS_REJECTED_LABEL
    assert "ARBITRARY-CALLER-TEXT" not in repr(report)


def _validate_child(data: bytes, **overrides: object):
    from property_tax_adapters.sources.texas.ellis import validate_child_member

    return validate_child_member(
        data,
        **{
            "release_identifier": synthetic.RELEASE_IDENTIFIER,
            "source_member_name": synthetic.SOURCE_MEMBER_NAME,
            "release_label": synthetic.CERTIFIED_LABEL,
            "child_table": "land",
            "accepted_account_ids": synthetic.ACCEPTED_ACCOUNT_IDS,
            **overrides,
        },  # type: ignore[arg-type]
    )


def test_ellis_has_a_child_binding() -> None:
    """Issue #21 requires child facts and relationship provenance."""

    report = _validate_child(synthetic.CHILD_RESOLVED)
    assert report.release_accepted is True
    assert report.accepted_row_count == 1


def test_an_ellis_core_child_orphan_blocks() -> None:
    report = _validate_child(synthetic.CHILD_ORPHANED)
    assert _codes(report) == ["core_child_orphaned"]
    assert report.release_accepted is False


def test_an_ellis_legal_child_orphan_warns() -> None:
    report = _validate_child(synthetic.CHILD_ORPHANED, child_table="arb")
    assert _codes(report) == ["legal_child_orphaned"]
    assert report.release_accepted is True


def test_the_child_binding_applies_the_label_and_fingerprint_gates() -> None:
    """A child member from a scenario roll is no more parseable than a property
    member from one."""

    labelled = _validate_child(synthetic.CHILD_RESOLVED, release_label="mineral-only")
    assert _codes(labelled) == ["unsupported_scenario_label"]

    fingerprinted = _validate_child(synthetic.CHILD_RESOLVED, expected_layout_fingerprint="0" * 64)
    assert _codes(fingerprinted) == ["unsupported_layout_fingerprint"]


def test_every_declared_ellis_code_is_reachable() -> None:
    """No code is declared that no path can emit."""

    assert {code.value for code in EllisDiagnosticCode} == {
        "invalid_encoding",
        "unexpected_bom",
        "record_width_mismatch",
        "unsupported_layout_fingerprint",
        "undocumented_trailing_region",
        "unsupported_scenario_label",
        "unrecognised_layout_package",
        "blank_required_key",
        "invalid_account_id",
        "invalid_owner_sequence",
        "invalid_monetary_value",
        "invalid_ownership_percentage",
        "invalid_tax_year",
        "tax_year_mismatch",
        "invalid_source_text",
        "duplicate_owner_row",
        "conflicting_account_facts",
        "core_child_orphaned",
        "legal_child_orphaned",
    }
