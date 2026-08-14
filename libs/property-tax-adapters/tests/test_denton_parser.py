"""Component, contract, privacy, and boundary tests for the Denton foundation.

Every expectation is authored from the accepted OpenSpec change
``add-denton-cad-pacs-parser-foundation`` rather than from the parser's output.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from fixtures import denton_synthetic as synthetic
from property_tax_adapters.sources.pacs import (
    PACS_COMPONENT_CONTRACT_VERSION,
    PacsField,
    PacsLayout,
)
from property_tax_adapters.sources.texas.denton import (
    DENTON_CHILD_LAYOUT,
    DENTON_CORE_CHILD_TABLES,
    DENTON_DIAGNOSTIC_RETENTION_LIMIT,
    DENTON_LEGAL_CHILD_TABLES,
    DENTON_PROPERTY_LAYOUT,
    DENTON_SENSITIVE_FIELDS,
    DENTON_SOURCE,
    DentonDiagnostic,
    DentonDiagnosticCode,
    DentonValidationReport,
    validate_child_member,
    validate_property_member,
)

IDENTITY = {
    "release_identifier": synthetic.RELEASE_IDENTIFIER,
    "source_member_name": synthetic.SOURCE_MEMBER_NAME,
    "expected_tax_year": synthetic.EXPECTED_TAX_YEAR,
}


def _validate(data: bytes | str, **overrides: object) -> DentonValidationReport:
    return validate_property_member(data, **{**IDENTITY, **overrides})  # type: ignore[arg-type]


def _codes(report: DentonValidationReport) -> list[str]:
    return [entry.code.value for entry in report.diagnostics]


# --------------------------------------------------------------------------
# The shared PACS component
# --------------------------------------------------------------------------


def test_positions_are_one_indexed_and_inclusive() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 6)))
    sliced = layout.slice_record("ABCDEF")
    assert sliced.values == {"a": "ABC", "b": "DEF"}
    assert layout.fields[0].length == 3
    assert layout.declared_width == 6


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ((PacsField("b", 4, 6), PacsField("a", 1, 3)), "descending order"),
        ((PacsField("a", 1, 5), PacsField("b", 4, 8)), "overlap"),
        ((PacsField("a", 1, 3), PacsField("a", 4, 6)), "duplicate name"),
        ((), "no fields"),
    ],
    ids=["order", "overlap", "duplicate-name", "empty"],
)
def test_a_layout_defect_raises_rather_than_diagnosing(
    fields: tuple[PacsField, ...], reason: str
) -> None:
    """A layout is trusted repository code, so a defect in one is an authoring
    mistake rather than something a source file did."""

    del reason
    with pytest.raises(ValueError):
        PacsLayout("t", "v1", fields)


@pytest.mark.parametrize(
    ("start", "end"), [(0, 3), (-1, 3), (5, 4)], ids=["zero", "negative", "reversed"]
)
def test_an_invalid_field_position_raises(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        PacsField("a", start, end)


def test_the_layout_fingerprint_matches_the_specified_document() -> None:
    """Recomputed from the spec's five keys rather than from the component."""

    fields = (PacsField("a", 1, 3), PacsField("b", 4, 6, required=False))
    payload = json.dumps(
        {
            "component_contract_version": PACS_COMPONENT_CONTRACT_VERSION,
            "field_count": 2,
            "fields": [["a", 1, 3, True], ["b", 4, 6, False]],
            "layout_id": "t",
            "layout_version": "v1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert PacsLayout("t", "v1", fields).fingerprint == expected
    assert expected == expected.lower()
    assert len(expected) == 64


@pytest.mark.parametrize(
    "mutation",
    ["layout_id", "layout_version", "name", "start", "end", "required", "field_count"],
)
def test_every_declared_attribute_changes_the_fingerprint(mutation: str) -> None:
    base = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 6)))
    variants = {
        "layout_id": PacsLayout("u", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 6))),
        "layout_version": PacsLayout("t", "v2", (PacsField("a", 1, 3), PacsField("b", 4, 6))),
        "name": PacsLayout("t", "v1", (PacsField("z", 1, 3), PacsField("b", 4, 6))),
        "start": PacsLayout("t", "v1", (PacsField("a", 2, 3), PacsField("b", 4, 6))),
        "end": PacsLayout("t", "v1", (PacsField("a", 1, 2), PacsField("b", 4, 6))),
        "required": PacsLayout(
            "t", "v1", (PacsField("a", 1, 3, required=False), PacsField("b", 4, 6))
        ),
        "field_count": PacsLayout("t", "v1", (PacsField("a", 1, 3),)),
    }
    assert variants[mutation].fingerprint != base.fingerprint


def test_a_truncated_required_field_is_never_emitted_as_a_value() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 10)))
    sliced = layout.slice_record("ABCDE")
    assert sliced.values == {"a": "ABC"}
    assert sliced.truncated_required == ("b",)
    assert "DE" not in sliced.values.values()


def test_a_truncated_optional_field_is_absent_rather_than_partial() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3), PacsField("b", 4, 10, required=False)))
    sliced = layout.slice_record("ABCDE")
    assert sliced.truncated_required == ()
    assert sliced.absent_optional == ("b",)
    assert "b" not in sliced.values


def test_a_trailing_region_is_fingerprinted_and_never_carried() -> None:
    layout = PacsLayout("t", "v1", (PacsField("a", 1, 3),))
    sliced = layout.slice_record("ABC" + "SECRET-TRAILING")
    assert sliced.trailing is not None
    assert sliced.trailing.byte_length == len("SECRET-TRAILING")
    assert sliced.trailing.digest == hashlib.sha256(b"SECRET-TRAILING").hexdigest()
    assert "SECRET-TRAILING" not in repr(sliced.trailing)


def test_the_component_names_no_county_in_its_code() -> None:
    """A component that knew a county field could not be bound by another.

    Read from the parsed code rather than the file text: the module docstring
    legitimately explains *why* Ellis binds rather than forks, and a naive grep
    would fail on that explanation while missing nothing real.
    """

    import ast

    from property_tax_adapters.sources import pacs

    tree = ast.parse(Path(inspect.getfile(pacs)).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value.value = ""  # drop docstrings, keeping the code shape
    code = ast.unparse(tree).casefold()

    for county in ("denton", "ellis", "tarrant", "dallas", "collin", "rockwall"):
        assert county not in code, county
    for county_field in ("prop_id", "owner_sequence", "ten_percent_cap"):
        assert county_field not in code, county_field


# --------------------------------------------------------------------------
# Denton physical layer
# --------------------------------------------------------------------------


def test_the_declared_layout_matches_the_documented_widths() -> None:
    assert DENTON_PROPERTY_LAYOUT.declared_width == synthetic.EXPECTED_PROPERTY_WIDTH
    assert DENTON_CHILD_LAYOUT.declared_width == synthetic.EXPECTED_CHILD_WIDTH
    assert len(synthetic.property_row()) == synthetic.EXPECTED_PROPERTY_WIDTH


@pytest.mark.parametrize(
    "member",
    [synthetic.VALID_LF, synthetic.VALID_CRLF, synthetic.VALID_NO_TRAILING_NEWLINE],
    ids=["lf", "crlf", "no-trailing-newline"],
)
def test_a_valid_member_is_accepted(member: bytes) -> None:
    report = _validate(member)
    assert report.release_accepted is True
    assert report.accepted_row_count == 1
    assert report.owner_row_count == 1
    assert report.diagnostics == ()
    assert report.parser_contract_version == 1


def test_text_outside_the_approved_encoding_is_refused() -> None:
    report = _validate("—" * synthetic.EXPECTED_PROPERTY_WIDTH)
    assert _codes(report) == ["invalid_encoding"]


@pytest.mark.parametrize(
    "member", [synthetic.UTF8_BOM, synthetic.UTF16_LE_BOM], ids=["utf-8", "utf-16-le"]
)
def test_a_byte_order_mark_is_refused(member: bytes) -> None:
    assert _codes(_validate(member)) == ["unexpected_bom"]


def test_records_of_disagreeing_width_are_refused() -> None:
    """Width is a member-level property: PACS records carry no delimiter, so a
    differing width is evidence the member is not the declared layout."""

    report = _validate(synthetic.WIDTH_MISMATCH)
    assert _codes(report) == ["record_width_mismatch"]
    assert report.diagnostics[0].physical_row_number == 2
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_a_truncated_required_field_blocks_the_release() -> None:
    report = _validate(synthetic.TRUNCATED_REQUIRED)
    assert "truncated_required_field" in _codes(report)
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_a_trailing_region_warns_once_and_is_not_carried() -> None:
    report = _validate(synthetic.WITH_TRAILING_REGION)
    assert _codes(report) == ["undocumented_trailing_region"]
    assert report.release_accepted is True
    assert report.trailing_region_bytes == len(synthetic.TRAILING_REGION_TEXT)
    assert synthetic.TRAILING_REGION_TEXT not in repr(report)


def test_a_bare_cr_is_not_a_record_boundary_and_does_not_pass_as_one_record() -> None:
    """A bare CR is not a boundary, so two records become one over-wide record.

    Accepting that as a valid record with a trailing region would silently read
    two records as one, so an embedded control character is refused outright.
    """

    member = (synthetic.property_row() + "\r" + synthetic.property_row()).encode("iso-8859-1")
    report = _validate(member)
    assert _codes(report) == ["invalid_source_text"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_an_over_wide_fixture_value_is_refused_by_the_fixture() -> None:
    """The four-character owner sequence cannot hold five digits, so the bound
    is structural. The fixture refuses rather than silently clipping."""

    with pytest.raises(ValueError):
        synthetic.property_row(owner_sequence="12345")


# --------------------------------------------------------------------------
# Lexical rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("prop_id", "", "blank_required_key"),
        ("owner_sequence", "", "blank_required_key"),
        ("owner_sequence", "abcd", "invalid_owner_sequence"),
        ("tax_year", "999", "invalid_tax_year"),
        ("tax_year", "1899", "invalid_tax_year"),
        ("tax_year", "2024", "tax_year_mismatch"),
        ("ownership_percentage", "101", "invalid_ownership_percentage"),
        ("ownership_percentage", "-1", "invalid_ownership_percentage"),
        ("market_value", "1,250.00", "invalid_monetary_value"),
        ("market_value", "-1", "invalid_monetary_value"),
        ("market_value", "1.234", "invalid_monetary_value"),
        ("market_value", "", "blank_required_key"),
        ("ten_percent_cap", "abc", "invalid_monetary_value"),
    ],
)
def test_an_unapproved_value_is_refused(field: str, value: str, code: str) -> None:
    report = _validate(synthetic.member(synthetic.property_row(**{field: value})))
    assert code in _codes(report), _codes(report)
    assert report.release_accepted is False


@pytest.mark.parametrize("value", ["0", "100", "50.5", "33.333333"])
def test_an_approved_ownership_percentage_is_accepted(value: str) -> None:
    report = _validate(synthetic.member(synthetic.property_row(ownership_percentage=value)))
    assert report.release_accepted is True


def test_optional_monetary_fields_may_be_blank_as_source_absence() -> None:
    report = _validate(
        synthetic.member(
            synthetic.property_row(land_value="", improvement_value="", ten_percent_cap="")
        )
    )
    assert report.release_accepted is True


def test_an_account_identifier_is_compared_as_text() -> None:
    """`000123` and `123` are two accounts, not one."""

    report = _validate(synthetic.LEADING_ZERO_ACCOUNTS)
    assert report.release_accepted is True
    assert report.accepted_row_count == 2
    assert report.owner_row_count == 2


# --------------------------------------------------------------------------
# Owner-row grain
# --------------------------------------------------------------------------


def test_an_undivided_interest_allocation_is_preserved() -> None:
    report = _validate(synthetic.OWNER_ALLOCATION)
    assert report.release_accepted is True
    assert report.accepted_row_count == 3
    assert report.owner_row_count == 3
    # No account-level total is derived from the three rows.
    assert not hasattr(report, "account_total")


def test_a_repeated_owner_row_is_refused() -> None:
    report = _validate(synthetic.DUPLICATE_OWNER_ROW)
    assert "duplicate_owner_row" in _codes(report)
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_conflicting_account_facts_are_refused() -> None:
    report = _validate(synthetic.CONFLICTING_ACCOUNT_FACTS)
    assert "conflicting_account_facts" in _codes(report)
    assert report.diagnostics[0].field_name == "market_value"
    assert report.release_accepted is False


def test_ten_percent_cap_is_carried_without_interpretation() -> None:
    report = _validate(
        synthetic.member(
            synthetic.property_row(ten_percent_cap="20000.00", market_value="250000.00")
        )
    )
    assert report.release_accepted is True
    for derived in ("capped_value", "assessed_after_cap", "taxable_value"):
        assert not hasattr(report, derived)


# --------------------------------------------------------------------------
# Child relationships
# --------------------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(DENTON_CORE_CHILD_TABLES))
def test_a_core_appraisal_orphan_blocks(table: str) -> None:
    report = validate_child_member(
        synthetic.CHILD_ORPHANED,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        child_table=table,
        accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
    )
    assert _codes(report) == ["core_child_orphaned"]
    assert report.release_accepted is False


@pytest.mark.parametrize("table", sorted(DENTON_LEGAL_CHILD_TABLES))
def test_a_legal_orphan_warns_without_blocking(table: str) -> None:
    report = validate_child_member(
        synthetic.CHILD_ORPHANED,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        child_table=table,
        accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
    )
    assert _codes(report) == ["legal_child_orphaned"]
    assert report.release_accepted is True


def test_a_resolved_child_is_accepted() -> None:
    report = validate_child_member(
        synthetic.CHILD_RESOLVED,
        release_identifier=synthetic.RELEASE_IDENTIFIER,
        source_member_name=synthetic.SOURCE_MEMBER_NAME,
        child_table="land",
        accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
    )
    assert report.release_accepted is True
    assert report.accepted_row_count == 1


def test_an_unapproved_child_table_raises() -> None:
    with pytest.raises(ValueError):
        validate_child_member(
            synthetic.CHILD_RESOLVED,
            release_identifier=synthetic.RELEASE_IDENTIFIER,
            source_member_name=synthetic.SOURCE_MEMBER_NAME,
            child_table="not_a_table",
            accepted_account_ids=synthetic.ACCEPTED_ACCOUNT_IDS,
        )


# --------------------------------------------------------------------------
# Diagnostics, atomicity, caller identity
# --------------------------------------------------------------------------


def test_the_diagnostic_vocabulary_is_closed() -> None:
    observed = {code.value for code in DentonDiagnosticCode}
    assert len(observed) == synthetic.EXPECTED_DIAGNOSTIC_CODE_COUNT
    assert observed == {
        "invalid_encoding",
        "unexpected_bom",
        "record_width_mismatch",
        "truncated_required_field",
        "unsupported_layout_fingerprint",
        "undocumented_trailing_region",
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


def test_a_diagnostic_carries_only_the_four_permitted_fields() -> None:
    assert list(DentonDiagnostic.__dataclass_fields__) == [
        "code",
        "field_name",
        "physical_row_number",
        "layout_fingerprint",
    ]


def test_one_failing_record_among_many_returns_nothing() -> None:
    rows = [synthetic.property_row(prop_id=f"ACC-{index:04d}") for index in range(40)]
    rows[21] = synthetic.property_row(prop_id="ACC-0021", market_value="-1")
    report = _validate(synthetic.member(*rows))
    assert "invalid_monetary_value" in _codes(report)
    assert report.diagnostics[0].physical_row_number == 22
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_diagnostics_truncate_deterministically_while_preserving_the_total() -> None:
    rows = [
        synthetic.property_row(prop_id=f"ACC-{index:04d}", market_value="-1")
        for index in range(130)
    ]
    member = synthetic.member(*rows)
    report = _validate(member)
    assert len(report.diagnostics) == DENTON_DIAGNOSTIC_RETENTION_LIMIT
    assert report.total_diagnostic_count == 130
    assert report.diagnostics_truncated is True
    assert _validate(member).diagnostics == report.diagnostics


@pytest.mark.parametrize(
    "override",
    [
        {"release_identifier": ""},
        {"release_identifier": "a" * 129},
        {"source_member_name": "/var/tmp/denton.txt"},
        {"source_member_name": "../denton.txt"},
        {"expected_tax_year": 1899},
        {"expected_tax_year": True},
        {"expected_tax_year": "2025"},
        {"release_identifier": b"denton"},
    ],
    ids=["empty", "too-long", "path", "traversal", "year-low", "bool", "str-year", "bytes"],
)
def test_an_out_of_contract_caller_argument_raises(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _validate(synthetic.VALID_LF, **override)


# --------------------------------------------------------------------------
# Privacy and boundaries
# --------------------------------------------------------------------------


def test_owner_and_address_values_never_reach_the_report() -> None:
    report = _validate(synthetic.VALID_LF)
    rendered = repr(report)
    for placeholder in (
        synthetic.OWNER_PLACEHOLDER,
        synthetic.ADDRESS_PLACEHOLDER,
        synthetic.SITUS_PLACEHOLDER,
    ):
        assert placeholder not in rendered


def test_the_sensitive_field_inventory_matches_the_contract() -> None:
    assert DENTON_SENSITIVE_FIELDS == {"owner_name", "owner_address", "situs_address"}
    assert len(DENTON_SENSITIVE_FIELDS) == synthetic.EXPECTED_SENSITIVE_FIELD_COUNT


def test_the_report_carries_no_row_payload() -> None:
    fields = set(DentonValidationReport.__dataclass_fields__)
    assert fields == {
        "parser_contract_version",
        "release_accepted",
        "layout_fingerprint",
        "layout_version",
        "accepted_row_count",
        "owner_row_count",
        "trailing_region_bytes",
        "diagnostics",
        "total_diagnostic_count",
        "diagnostics_truncated",
    }
    assert not fields & {"rows", "records", "values", "source_records"}


def _denton_source() -> str:
    from property_tax_adapters.sources.texas import denton

    return Path(inspect.getfile(denton)).read_text(encoding="utf-8")


def test_no_county_local_shared_contract_is_defined() -> None:
    """Issue #43 owns these three; a fourth local copy is what this avoids."""

    source = _denton_source()
    for forbidden in (
        "class SourceNativeValue",
        "class SourceProvenance",
        "class AppraisalSourceRecord",
        "class DentonSourceNativeValue",
        "class DentonAppraisalSourceRecord",
    ):
        assert forbidden not in source, forbidden
    assert "sources.contracts" not in source


def test_the_domain_and_application_packages_gain_no_parser_vocabulary() -> None:
    """`DENTON_SOURCE` legitimately imports both, so absence is not the claim."""

    source = _denton_source()
    assert "from property_tax_application import" in source
    assert "from property_tax_domain import" in source
    assert DENTON_SOURCE.parser_id == "texas.denton.pacs-fixed-width-v1"

    vocabulary = (
        "DentonDiagnostic",
        "DentonValidationReport",
        "validate_property_member",
        "PacsLayout",
        "PacsField",
        "ten_percent_cap",
        "owner_sequence",
    )
    repo_root = Path(__file__).resolve().parents[3]
    for package in ("property-tax-domain", "property-tax-application"):
        for path in (repo_root / "libs" / package / "src").rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            leaked = [name for name in vocabulary if name in body]
            assert leaked == [], (path, leaked)


def test_no_acquisition_network_or_persistence_behavior_is_present() -> None:
    for source in (_denton_source(), _pacs_source()):
        for forbidden in (
            "import requests",
            "import httpx",
            "urllib",
            "socket",
            "zipfile",
            "sqlalchemy",
            "boto3",
            "open(",
        ):
            assert forbidden not in source, forbidden


def _pacs_source() -> str:
    from property_tax_adapters.sources import pacs

    return Path(inspect.getfile(pacs)).read_text(encoding="utf-8")


def test_the_foundation_adds_no_dependency_outside_the_standard_library() -> None:
    for source in (_denton_source(), _pacs_source()):
        imported = {
            line.split()[1].split(".")[0]
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "property_tax" not in line
        }
        assert imported <= {
            "__future__",
            "hashlib",
            "json",
            "re",
            "collections",
            "dataclasses",
            "decimal",
            "enum",
            "typing",
        }, imported
