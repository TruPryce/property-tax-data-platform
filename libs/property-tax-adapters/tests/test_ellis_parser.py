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


def test_an_undocumented_trailing_region_fails_closed() -> None:
    """The governing issue requires unknown trailing bytes to be rejected."""

    report = _validate(synthetic.WITH_TRAILING_REGION)
    assert _codes(report) == ["undocumented_trailing_region"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0
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
        "blank_required_key",
        "invalid_account_id",
        "invalid_owner_sequence",
        "invalid_child_sequence",
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
    """Tasks 6.1 to 6.3 end the wait; they do not license a copy.

    Before the shared module existed this also asserted that nothing referenced
    it, because waiting was the only correct behaviour.  The prohibition is now
    expressed as a check on what this module *defines* rather than what it
    imports.
    """

    import ast

    source = _ellis_source()
    assert "from property_tax_adapters.sources.contracts import" in source

    defined = {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ClassDef)}
    assert not defined & {
        "SourceNativeValue",
        "SourceProvenance",
        "AppraisalSourceRecord",
        "EllisSourceNativeValue",
        "EllisAppraisalSourceRecord",
    }


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
        "types",
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
        synthetic.ZERO_DECLARED_SIZE,
        synthetic.MISMATCHED_DECLARED_SIZES,
    ],
    ids=[
        "marker-without-header",
        "deflated-mimetype",
        "wrong-name-length",
        "zero-declared-size",
        "mismatched-declared-sizes",
    ],
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


def test_every_declared_ellis_code_is_actually_emitted() -> None:
    """Named for a property the previous version did not check.

    Comparing the enum against a literal set proves the two agree, not that any
    input produces each code. `unrecognised_layout_package` passed that test for
    three rounds while nothing could emit it. This drives real inputs through
    the public entry points and collects what comes back, so a code with no
    producing path fails here.
    """

    emitted: set[str] = set()

    def collect(report: EllisValidationReport) -> None:
        emitted.update(entry.code.value for entry in report.diagnostics)

    row = synthetic.property_row
    collect(_validate("\u2014" * synthetic.EXPECTED_PROPERTY_WIDTH))
    collect(_validate(synthetic.UTF8_BOM))
    collect(_validate(synthetic.WIDTH_MISMATCH))
    collect(_validate(synthetic.VALID_LF, expected_layout_fingerprint="0" * 64))
    collect(_validate(synthetic.WITH_TRAILING_REGION))
    collect(_validate(synthetic.VALID_LF, release_label="mineral-only"))
    collect(_validate(synthetic.member(row(prop_id=""))))
    collect(_validate(synthetic.member(row(prop_id="a b"))))
    collect(_validate(synthetic.member(row(owner_sequence="abcd"))))
    collect(_validate(synthetic.member(row(market_value="-1"))))
    collect(_validate(synthetic.member(row(ownership_percentage="101"))))
    collect(_validate(synthetic.member(row(tax_year="1899"))))
    collect(_validate(synthetic.member(row(tax_year="2024"))))
    collect(_validate((row() + "\r" + row()).encode("iso-8859-1")))
    collect(_validate(synthetic.DUPLICATE_OWNER_ROW))
    collect(_validate(synthetic.CONFLICTING_ACCOUNT_FACTS))
    collect(_validate_child(synthetic.CHILD_ORPHANED))
    collect(_validate_child(synthetic.CHILD_ORPHANED, child_table="arb"))
    collect(_validate_child(synthetic.member(synthetic.child_row(sequence="abcd"))))

    declared = {code.value for code in EllisDiagnosticCode}
    assert declared - emitted == set(), f"declared but never emitted: {sorted(declared - emitted)}"


def test_the_declared_vocabulary_matches_the_contract() -> None:
    """No code is declared that no path can emit."""

    assert {code.value for code in EllisDiagnosticCode} == {
        "invalid_encoding",
        "unexpected_bom",
        "record_width_mismatch",
        "unsupported_layout_fingerprint",
        "undocumented_trailing_region",
        "unsupported_scenario_label",
        "blank_required_key",
        "invalid_account_id",
        "invalid_owner_sequence",
        "invalid_child_sequence",
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


def test_a_fingerprinted_layout_cannot_be_relabelled() -> None:
    """A settable version let a mutated layout report the old approved digest."""

    from property_tax_adapters.sources.pacs import PacsField, PacsLayout

    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3),))
    before = layout.fingerprint
    for attribute, value in (("layout_version", "mutated-v2"), ("layout_id", "other")):
        with pytest.raises(AttributeError):
            setattr(layout, attribute, value)
    assert layout.fingerprint == before
    assert layout.layout_version == "v1"


# --------------------------------------------------------------------------
# Automated review findings
# --------------------------------------------------------------------------


def test_repository_drift_fails_even_when_the_caller_supplies_the_live_digest() -> None:
    """The gate compared the caller's value against the live layout digest.

    That made the pinned constant decorative: if the mapping drifted, the live
    digest drifted with it, so a caller passing the current value passed the
    gate while the approved constant still held the old one.
    """

    from property_tax_adapters.sources.pacs import PacsLayout
    from property_tax_adapters.sources.texas.ellis import _assert_layout_approved

    drifted = PacsLayout("ellis.property", "v1", tuple(ELLIS_PROPERTY_LAYOUT.fields[:-1]))
    assert drifted.fingerprint != ELLIS_EXPECTED_LAYOUT_FINGERPRINT
    # The caller supplies the drifted layout's own digest: both sides agree, and
    # both are wrong. That is the bypass.
    assert not _assert_layout_approved(
        drifted, drifted.fingerprint, ELLIS_EXPECTED_LAYOUT_FINGERPRINT
    )
    assert _assert_layout_approved(
        ELLIS_PROPERTY_LAYOUT,
        ELLIS_EXPECTED_LAYOUT_FINGERPRINT,
        ELLIS_EXPECTED_LAYOUT_FINGERPRINT,
    )


def test_a_uniformly_wide_child_member_is_refused() -> None:
    """The child path ignored trailing regions the property path rejects."""

    wide = synthetic.member(
        synthetic.child_row() + "EXTRA-TRAILING",
        synthetic.child_row(prop_id="000124") + "EXTRA-TRAILING",
    )
    report = _validate_child(wide, accepted_account_ids=("000123", "000124"))
    assert _codes(report) == ["undocumented_trailing_region"]
    assert report.release_accepted is False
    assert report.trailing_region_bytes == len("EXTRA-TRAILING")


def test_classification_reports_through_its_own_type() -> None:
    """`unrecognised_layout_package` was declared and unemittable for three rounds."""

    assert "unrecognised_layout_package" not in {code.value for code in EllisDiagnosticCode}
    assert classify_layout_package(synthetic.NOT_A_PACKAGE) is LayoutPackageKind.UNRECOGNISED


# --------------------------------------------------------------------------
# Tasks 6.1, 6.2, 6.3
# --------------------------------------------------------------------------


def _materialize(data: bytes | str = None, **overrides: object):  # type: ignore[assignment]
    from property_tax_adapters.sources.texas.ellis import materialize_property_member

    payload = synthetic.VALID_LF if data is None else data
    return materialize_property_member(payload, **{**IDENTITY, **overrides})  # type: ignore[arg-type]


def _materialize_child(data: bytes = None, **overrides: object):  # type: ignore[assignment]
    from property_tax_adapters.sources.texas.ellis import materialize_child_member

    payload = synthetic.CHILD_RESOLVED if data is None else data
    return materialize_child_member(
        payload,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        release_label=overrides.pop("release_label", synthetic.CERTIFIED_LABEL),  # type: ignore[arg-type]
        child_table=overrides.pop("child_table", "land"),  # type: ignore[arg-type]
        accepted_account_ids=overrides.pop("accepted_account_ids", synthetic.ACCEPTED_ACCOUNT_IDS),  # type: ignore[arg-type]
    )


def test_materialization_reuses_validation_rather_than_repeating_it() -> None:
    """Contract: a row-materialization entry point that reuses the existing validation."""

    validated = _validate(synthetic.VALID_LF)
    result = _materialize(synthetic.VALID_LF)

    assert result.report == validated
    assert len(result.records) == validated.accepted_row_count


def test_the_report_stays_valid_and_record_free() -> None:
    """Contract: keep EllisValidationReport valid and record-free."""

    from dataclasses import fields as dataclass_fields

    declared = {field.name for field in dataclass_fields(EllisValidationReport)}
    assert not declared & {"records", "rows", "values", "source_native_values"}


def test_a_record_carries_the_owner_grain_and_the_release_label() -> None:
    """Contract: provenance carries jurisdiction, release label, tax year, and positions."""

    from property_tax_adapters.sources.contracts import SourceProvenance
    from property_tax_adapters.sources.texas.ellis import ELLIS_PROPERTY_LAYOUT

    record = _materialize().records[0]
    provenance = record.provenance

    assert record.prop_id
    assert record.owner_sequence
    assert provenance.jurisdiction_code == "tx-ellis"
    assert provenance.release_label == synthetic.CERTIFIED_LABEL
    assert provenance.tax_year == synthetic.EXPECTED_TAX_YEAR
    assert provenance.layout_fingerprint == ELLIS_PROPERTY_LAYOUT.fingerprint
    assert provenance.layout_version == ELLIS_PROPERTY_LAYOUT.layout_version
    assert provenance.physical_row_number == 1
    assert isinstance(provenance.shared, SourceProvenance)
    assert provenance.field_positions["prop_id"] == (1, 12)

    for name, value in record.source_native_values.items():
        assert value.source_field == name
        assert value.lexical_text == value.lexical_text.strip()


def test_no_sensitive_field_position_or_value_reaches_a_record() -> None:
    """Contract: sensitive values MUST NOT enter any output."""

    record = _materialize().records[0]

    assert not set(record.source_native_values) & ELLIS_SENSITIVE_FIELDS
    assert not set(record.provenance.field_positions) & ELLIS_SENSITIVE_FIELDS


def test_a_rejected_release_materializes_nothing() -> None:
    """Release-level atomicity, with a valid row present to actually discard."""

    mixed = synthetic.member(
        synthetic.property_row(),
        synthetic.property_row(prop_id="000124", tax_year="1899"),
    )
    result = _materialize(mixed)

    assert result.report.release_accepted is False
    assert result.records == ()


def test_a_scenario_roll_materializes_nothing() -> None:
    """The label gate runs before any record is read, so no row escapes it."""

    result = _materialize(synthetic.VALID_LF, release_label="mineral-only")

    assert result.report.release_accepted is False
    assert result.records == ()


def test_a_stored_shared_provenance_may_not_disagree_with_its_county_fields() -> None:
    from dataclasses import replace

    from property_tax_adapters.sources.texas.ellis import EllisSourceProvenance

    provenance = _materialize().records[0].provenance
    with pytest.raises(ValueError, match="disagrees with Ellis provenance"):
        EllisSourceProvenance(
            jurisdiction_code=provenance.jurisdiction_code,
            release_identifier=provenance.release_identifier,
            source_member_name=provenance.source_member_name,
            release_label=provenance.release_label,
            tax_year=provenance.tax_year,
            layout_fingerprint=provenance.layout_fingerprint,
            layout_version=provenance.layout_version,
            field_positions=provenance.field_positions,
            physical_row_number=provenance.physical_row_number,
            parser_contract_version=provenance.parser_contract_version,
            shared=replace(provenance.shared, source_row_number=99),
        )


def test_conversion_uses_prop_id_and_preserves_the_owner_grain() -> None:
    """Contract: prop_id as source account ID; preserve owner-row grain, no roll-up."""

    from property_tax_adapters.sources.texas.ellis import convert_ellis_record

    allocation = synthetic.member(
        synthetic.property_row(owner_sequence="1"),
        synthetic.property_row(owner_sequence="2"),
    )
    records = _materialize(allocation).records
    assert len(records) == 2

    converted = [convert_ellis_record(record) for record in records]
    assert len(converted) == 2
    assert {shared.source_account_id for shared in converted} == {records[0].prop_id}
    assert {shared.source_native_identifiers["owner_sequence"] for shared in converted} == {
        "1",
        "2",
    }
    for shared, native in zip(converted, records, strict=True):
        assert shared.jurisdiction_code == "tx-ellis"
        assert shared.provenance is native.provenance.shared
        assert shared.parcel_reference is None


def test_conversion_normalizes_only_documented_facts() -> None:
    """Contract: normalize only the documented Ellis facts to matching types."""

    from decimal import Decimal

    from property_tax_adapters.sources.texas.ellis import (
        ELLIS_MONETARY_FIELDS,
        convert_ellis_record,
    )

    shared = convert_ellis_record(_materialize().records[0])
    for name, value in shared.source_native_values.items():
        if name in ELLIS_MONETARY_FIELDS or name == "ownership_percentage":
            assert isinstance(value.value, Decimal), name
        elif name == "tax_year":
            assert isinstance(value.value, int), name
        else:
            assert isinstance(value.value, str), name


def test_conversion_populates_no_canonical_field() -> None:
    """Contract: populate no canonical semantic field.

    The Ellis *field names* are market_value and the rest, and they travel as
    source-native values keyed by the county's own name.  The prohibition is
    about the record growing a canonical attribute, so that is what is checked.
    """

    from dataclasses import fields as dataclass_fields

    from property_tax_adapters.sources.contracts import AppraisalSourceRecord

    declared = {field.name for field in dataclass_fields(AppraisalSourceRecord)}
    assert not declared & {
        "market_value",
        "appraised_value",
        "assessed_value",
        "taxable_value",
        "tax_amount",
        "exemption_entitlement",
    }


def test_a_child_record_carries_its_measured_grain_and_label() -> None:
    """Contract: child provenance carries the child table, release label, fingerprint,
    version, and the one-based physical row number."""

    from decimal import Decimal

    from property_tax_adapters.sources.texas.ellis import ELLIS_CHILD_LAYOUT

    record = _materialize_child().records[0]

    assert record.prop_id == "000123"
    assert record.child_sequence == "1"
    assert record.child_value is not None
    assert record.child_value.value == Decimal("1000.00")
    assert record.provenance.child_table == "land"
    assert record.provenance.release_label == synthetic.CERTIFIED_LABEL
    assert record.provenance.layout_fingerprint == ELLIS_CHILD_LAYOUT.fingerprint
    assert record.provenance.layout_version == ELLIS_CHILD_LAYOUT.layout_version
    assert record.provenance.physical_row_number == 1


@pytest.mark.parametrize(
    ("sequence", "code"),
    [
        ("", "blank_required_key"),
        ("   ", "blank_required_key"),
        ("abcd", "invalid_child_sequence"),
        ("1.2", "invalid_child_sequence"),
        ("-1", "invalid_child_sequence"),
    ],
    ids=["blank", "whitespace", "letters", "decimal", "negative"],
)
def test_a_child_sequence_outside_the_d5_bounds_is_rejected(sequence: str, code: str) -> None:
    """Contract: child_sequence SHALL be required and one to four ASCII digits."""

    member = synthetic.member(synthetic.child_row(prop_id="000123", sequence=sequence))
    result = _materialize_child(member)

    assert _codes(result.report) == [code]
    assert result.report.release_accepted is False
    assert result.records == ()


@pytest.mark.parametrize(
    "value",
    ["-1.00", "1.000", "1,000.00", "$100", "1e5", "100.", "abc"],
    ids=["negative", "three-decimals", "grouped", "currency", "exponent", "trailing-point", "text"],
)
def test_a_child_value_outside_the_d5_grammar_is_rejected(value: str) -> None:
    """Contract: a nonblank child_value SHALL match the property monetary grammar."""

    member = synthetic.member(synthetic.child_row(prop_id="000123", value=value))
    result = _materialize_child(member)

    assert _codes(result.report) == ["invalid_monetary_value"]
    assert result.report.release_accepted is False
    assert result.records == ()


def test_whitespace_only_child_value_is_absence_not_a_malformed_amount() -> None:
    """Contract: empty text after trimming SHALL be the only null."""

    member = synthetic.member(synthetic.child_row(prop_id="000123", value="   "))
    result = _materialize_child(member)

    assert result.report.release_accepted is True
    assert result.records[0].child_value is None


def test_a_core_orphan_blocks_and_a_legal_orphan_warns_without_blocking() -> None:
    """Contract: keep the core-blocking and legal-warning classification intact.

    A legal orphan warns and is kept -- counted and materialized -- because a
    warning must not delete the row it warns about.  A core orphan blocks, and a
    blocked release publishes nothing at all.
    """

    core = _materialize_child(synthetic.CHILD_ORPHANED)
    assert core.report.release_accepted is False
    assert _codes(core.report) == ["core_child_orphaned"]
    assert core.records == ()

    legal = _materialize_child(synthetic.CHILD_ORPHANED, child_table="arb")
    assert legal.report.release_accepted is True
    assert _codes(legal.report) == ["legal_child_orphaned"]
    assert legal.report.accepted_row_count == 1
    assert len(legal.records) == 1


def test_children_are_not_rolled_up_to_the_parent_account() -> None:
    """Contract: preserve each child at its measured source grain, derive no roll-up."""

    two = synthetic.member(
        synthetic.child_row(prop_id="000123", sequence="1", value="1000.00"),
        synthetic.child_row(prop_id="000123", sequence="2", value="2500.00"),
    )
    records = _materialize_child(two).records

    assert len(records) == 2
    assert {record.child_sequence for record in records} == {"1", "2"}
    assert not any(hasattr(record, "total") for record in records)


def test_only_the_legal_orphan_code_is_non_fatal() -> None:
    """The invariant the child path relies on to zero a core orphan's output."""

    from property_tax_adapters.sources.texas.ellis import _NONFATAL_CODES

    assert _NONFATAL_CODES == frozenset({EllisDiagnosticCode.LEGAL_CHILD_ORPHANED})
    assert EllisDiagnosticCode.CORE_CHILD_ORPHANED not in _NONFATAL_CODES


def test_the_public_surface_declares_the_record_layer() -> None:
    """A name absent from `__all__` is not part of the module's contract."""

    from property_tax_adapters.sources.texas import ellis

    assert {
        "EllisSourceRecord",
        "EllisSourceProvenance",
        "EllisChildRecord",
        "EllisChildProvenance",
        "EllisMaterializationResult",
        "EllisChildMaterializationResult",
        "materialize_property_member",
        "materialize_child_member",
        "convert_ellis_record",
    } <= set(ellis.__all__)
    for name in ellis.__all__:
        assert hasattr(ellis, name), name
