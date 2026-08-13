"""Contract, failure, privacy, atomicity, and architecture tests for Tarrant.

Every expectation is authored from the accepted OpenSpec change
``add-tarrant-cad-parser-foundation`` rather than from the parser's own output.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from fixtures import tarrant_synthetic as synthetic
from property_tax_adapters.sources.texas.tarrant import (
    TARRANT_DIAGNOSTIC_RETENTION_LIMIT,
    TARRANT_REQUIRED_HEADERS,
    TARRANT_SENSITIVE_HEADERS,
    TARRANT_SOURCE,
    TarrantDiagnostic,
    TarrantDiagnosticCode,
    TarrantValidationReport,
    layout_fingerprint,
    validate_certified_member,
)

IDENTITY = {
    "release_identifier": synthetic.RELEASE_IDENTIFIER,
    "source_member_name": synthetic.SOURCE_MEMBER_NAME,
    "expected_source_year": synthetic.EXPECTED_SOURCE_YEAR,
}


def _validate(data: bytes | str, **overrides: object) -> TarrantValidationReport:
    return validate_certified_member(data, **{**IDENTITY, **overrides})  # type: ignore[arg-type]


def _codes(report: TarrantValidationReport) -> list[str]:
    return [diagnostic.code.value for diagnostic in report.diagnostics]


# --------------------------------------------------------------------------
# Declared contracts
# --------------------------------------------------------------------------


def test_the_required_header_projection_is_the_approved_sixteen() -> None:
    assert len(TARRANT_REQUIRED_HEADERS) == synthetic.EXPECTED_REQUIRED_HEADER_COUNT
    assert TARRANT_REQUIRED_HEADERS == (
        "RP",
        "Appraisal_Year",
        "Account_Num",
        "PIDN",
        "GIS_Link",
        "Property_Class",
        "State_Use_Code",
        "Exemption_Code",
        "Land_Value",
        "Improvement_Value",
        "Total_Value",
        "Appraised_Value",
        "Ag_Value",
        "Deed_Date",
        "Notice_Date",
        "Appraisal_Date",
    )


def test_the_diagnostic_vocabulary_is_closed_at_the_approved_codes() -> None:
    observed = {code.value for code in TarrantDiagnosticCode}
    assert len(observed) == synthetic.EXPECTED_DIAGNOSTIC_CODE_COUNT
    assert observed == {
        "invalid_encoding",
        "unexpected_bom",
        "malformed_delimited_record",
        "multiline_record_unsupported",
        "blank_header",
        "duplicate_header",
        "header_name_collision",
        "missing_required_header",
        "row_width_mismatch",
        "unsupported_layout",
        "extra_columns_present",
        "blank_required_value",
        "invalid_division",
        "invalid_appraisal_year",
        "appraisal_year_mismatch",
        "invalid_account_num",
        "invalid_source_identifier",
        "invalid_source_text",
        "invalid_monetary_value",
        "invalid_source_date",
        "duplicate_account_num",
    }


def test_the_existing_registry_definition_is_preserved() -> None:
    assert TARRANT_SOURCE.parser_id == "texas.tarrant.fixed-width-v1"
    assert TARRANT_SOURCE.official_url == "https://www.tad.org/"


# --------------------------------------------------------------------------
# Physical format
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member",
    [synthetic.VALID_LF, synthetic.VALID_CRLF, synthetic.VALID_NO_TRAILING_NEWLINE],
    ids=["lf", "crlf", "no-trailing-newline"],
)
def test_a_valid_member_is_accepted(member: bytes) -> None:
    report = _validate(member)
    assert report.release_accepted is True
    assert report.accepted_row_count == synthetic.EXPECTED_VALID_ACCEPTED_ROWS
    assert report.diagnostics == ()
    assert report.parser_contract_version == 1


def test_a_string_input_round_trips_through_the_approved_encoding() -> None:
    report = _validate(synthetic.VALID_LF.decode("iso-8859-1"))
    assert report.release_accepted is True


def test_text_outside_the_approved_encoding_is_refused() -> None:
    report = _validate("RP|Appraisal_Year\u2014\n")
    assert _codes(report) == ["invalid_encoding"]
    assert report.release_accepted is False


@pytest.mark.parametrize(
    "member", [synthetic.UTF8_BOM, synthetic.UTF16_LE_BOM], ids=["utf-8", "utf-16-le"]
)
def test_a_byte_order_mark_is_refused(member: bytes) -> None:
    report = _validate(member)
    assert _codes(report) == ["unexpected_bom"]
    assert report.accepted_row_count == 0


def test_a_quoted_delimiter_does_not_split_the_row() -> None:
    """If the pipe were read as a delimiter the row would fail on width."""

    report = _validate(synthetic.QUOTED_DELIMITER)
    assert report.release_accepted is True
    assert report.accepted_row_count == 1
    assert "row_width_mismatch" not in _codes(report)


def test_a_doubled_quote_is_reduced_rather_than_closing_the_field() -> None:
    """`"a""|b"` holds a literal quote and a literal pipe in one field."""

    report = _validate(synthetic.QUOTED_DOUBLED_QUOTE)
    assert report.release_accepted is True
    assert report.accepted_row_count == 1
    assert "malformed_delimited_record" not in _codes(report)
    assert "row_width_mismatch" not in _codes(report)


def test_an_unbalanced_quote_is_refused() -> None:
    report = _validate(synthetic.UNBALANCED_QUOTE)
    assert "malformed_delimited_record" in _codes(report)
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_a_record_spanning_two_physical_lines_reports_the_multiline_code() -> None:
    """Asserting only rejection hid a real defect.

    Splitting on newlines before parsing quotes made a spanning record look like
    two malformed ones, so the release was refused for the wrong reason and the
    row number pointed at the wrong place. The code itself is the assertion.
    """

    report = _validate(synthetic.MULTILINE_RECORD)
    assert _codes(report) == ["multiline_record_unsupported"]
    assert report.release_accepted is False
    assert report.accepted_row_count == 0
    assert report.diagnostics[0].physical_row_number == 2


def test_a_spanning_record_does_not_leak_a_second_diagnostic() -> None:
    """Its continuation belongs to the same rejected record."""

    report = _validate(synthetic.MULTILINE_RECORD_THEN_VALID)
    assert _codes(report) == ["multiline_record_unsupported"]
    assert report.total_diagnostic_count == 1
    # The valid row after the spanning record still numbers correctly.
    assert report.accepted_row_count == 0


def test_a_crlf_inside_a_quoted_field_is_also_a_spanning_record() -> None:
    report = _validate(synthetic.MULTILINE_RECORD_CRLF)
    assert _codes(report) == ["multiline_record_unsupported"]


def test_an_empty_member_is_an_unsupported_layout() -> None:
    report = _validate(synthetic.EMPTY_MEMBER)
    assert _codes(report) == ["unsupported_layout"]


# --------------------------------------------------------------------------
# Header binding
# --------------------------------------------------------------------------


def test_reordered_required_headers_bind_by_exact_name() -> None:
    report = _validate(synthetic.VALID_REORDERED)
    assert report.release_accepted is True
    assert report.accepted_row_count == 1


def test_one_metadata_extra_is_nonfatal_and_unnamed() -> None:
    report = _validate(synthetic.EXTRA_COLUMN)
    assert report.release_accepted is True
    assert _codes(report) == ["extra_columns_present"]
    # The extra header's own name is never echoed.
    assert all(diagnostic.field_name is None for diagnostic in report.diagnostics)


@pytest.mark.parametrize(
    ("member", "code"),
    [
        (synthetic.BLANK_HEADER, "blank_header"),
        (synthetic.PADDED_HEADER, "unsupported_layout"),
        (synthetic.DUPLICATE_HEADER, "duplicate_header"),
        (synthetic.CASE_FOLD_COLLISION, "header_name_collision"),
        (synthetic.MISSING_REQUIRED_HEADER, "missing_required_header"),
        (synthetic.ROW_WIDTH_MISMATCH, "row_width_mismatch"),
    ],
    ids=["blank", "padded", "duplicate", "case-fold", "missing", "row-width"],
)
def test_a_defective_layout_is_refused_with_its_own_code(member: bytes, code: str) -> None:
    report = _validate(member)
    assert code in _codes(report)
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_header_collision_folds_ascii_only() -> None:
    """`casefold()` maps 'SS' and 'ß' together; D1 says ASCII folding.

    Two extra headers that differ only outside ASCII are distinct names, so the
    release is accepted rather than reported as colliding.
    """

    report = _validate(synthetic.NON_ASCII_DISTINCT_EXTRAS)
    assert "header_name_collision" not in _codes(report)
    assert report.release_accepted is True

    # An actual ASCII collision is still caught.
    collision = _validate(synthetic.CASE_FOLD_COLLISION)
    assert "header_name_collision" in _codes(collision)


def test_a_row_width_mismatch_carries_its_physical_row_number() -> None:
    report = _validate(synthetic.ROW_WIDTH_MISMATCH)
    mismatch = next(d for d in report.diagnostics if d.code.value == "row_width_mismatch")
    assert mismatch.physical_row_number == 2


# --------------------------------------------------------------------------
# Layout fingerprint
# --------------------------------------------------------------------------


def test_the_fingerprint_matches_the_specified_document_byte_for_byte() -> None:
    """Recomputed from the spec's five keys rather than from the implementation."""

    headers = tuple(synthetic.HEADER.split("|"))
    payload = json.dumps(
        {
            "column_count": 16,
            "dialect": "pipe-delimited-double-quote-v1",
            "encoding": "iso-8859-1",
            "headers_sorted": sorted(headers),
            "parser_contract_version": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert layout_fingerprint(headers) == expected
    assert expected == expected.lower()
    assert len(expected) == 64


def test_reordering_headers_does_not_change_the_fingerprint() -> None:
    ordered = tuple(synthetic.HEADER.split("|"))
    reordered = tuple(synthetic.HEADER_REORDERED.split("|"))
    assert sorted(ordered) == sorted(reordered)
    assert layout_fingerprint(ordered) == layout_fingerprint(reordered)


def test_each_report_keeps_its_own_observed_header_order() -> None:
    first = _validate(synthetic.VALID_LF)
    second = _validate(synthetic.VALID_REORDERED)
    assert first.observed_headers == tuple(synthetic.HEADER.split("|"))
    assert second.observed_headers == tuple(synthetic.HEADER_REORDERED.split("|"))
    assert first.observed_headers != second.observed_headers
    assert first.layout_fingerprint == second.layout_fingerprint


def test_layout_validation_does_not_depend_on_the_fingerprint() -> None:
    report = _validate(synthetic.MISSING_REQUIRED_HEADER)
    assert "missing_required_header" in _codes(report)
    assert report.layout_fingerprint is not None


# --------------------------------------------------------------------------
# Lexical grammars
# --------------------------------------------------------------------------


@pytest.mark.parametrize("division", ["R", "C", "M", "P"])
def test_every_approved_division_is_accepted(division: str) -> None:
    report = _validate(synthetic.member(synthetic.row(RP=division)))
    assert report.release_accepted is True


@pytest.mark.parametrize("division", ["r", "X", "", " R", "RC"])
def test_an_unapproved_division_is_refused(division: str) -> None:
    report = _validate(synthetic.member(synthetic.row(RP=division)))
    assert "invalid_division" in _codes(report)


@pytest.mark.parametrize(
    ("year", "code"),
    [
        ("999", "invalid_appraisal_year"),
        ("20255", "invalid_appraisal_year"),
        ("1899", "invalid_appraisal_year"),
        ("2024", "appraisal_year_mismatch"),
        ("", "blank_required_value"),
    ],
)
def test_an_unapproved_appraisal_year_is_refused(year: str, code: str) -> None:
    report = _validate(synthetic.member(synthetic.row(Appraisal_Year=year)))
    assert code in _codes(report)


def test_an_account_is_preserved_as_text_rather_than_parsed_numerically() -> None:
    """`00123` and `123` are two accounts, which only holds under text comparison."""

    report = _validate(
        synthetic.member(
            synthetic.row(Account_Num="00123"),
            synthetic.row(Account_Num="123"),
        )
    )
    assert report.release_accepted is True
    assert report.accepted_row_count == 2
    assert "duplicate_account_num" not in _codes(report)


@pytest.mark.parametrize(
    ("account", "code"),
    [
        ("", "blank_required_value"),
        ("a" * 65, "invalid_account_num"),
        ("has space", "invalid_account_num"),
    ],
)
def test_an_unapproved_account_is_refused(account: str, code: str) -> None:
    report = _validate(synthetic.member(synthetic.row(Account_Num=account)))
    assert code in _codes(report)


@pytest.mark.parametrize("value", ["0", "1000", "3500.50", "0.0001", "9" * 28])
def test_an_approved_monetary_value_is_accepted(value: str) -> None:
    report = _validate(synthetic.member(synthetic.row(Total_Value=value, Appraised_Value=value)))
    assert report.release_accepted is True


@pytest.mark.parametrize(
    "value", ["-1", "1,250.00", "$100", "1e5", "100.", "1.00000", "10" + "0" * 28]
)
def test_an_unapproved_monetary_value_is_refused(value: str) -> None:
    report = _validate(synthetic.member(synthetic.row(Total_Value=value)))
    assert "invalid_monetary_value" in _codes(report)


def test_a_required_monetary_blank_is_refused_as_a_blank_required_value() -> None:
    report = _validate(synthetic.member(synthetic.row(Total_Value="")))
    assert "blank_required_value" in _codes(report)


def test_empty_text_is_the_only_null() -> None:
    accepted = _validate(synthetic.member(synthetic.row(Land_Value="")))
    assert accepted.release_accepted is True
    sentinel = _validate(synthetic.member(synthetic.row(Land_Value="NULL")))
    assert "invalid_monetary_value" in _codes(sentinel)
    assert sentinel.accepted_row_count == 0


def test_an_unequal_appraised_and_total_pair_is_accepted() -> None:
    """D2 forbids enforcing that inequality as a row-validity rule."""

    report = _validate(synthetic.member(synthetic.row(Total_Value="1000", Appraised_Value="2000")))
    assert report.release_accepted is True


@pytest.mark.parametrize("value", ["3/14/2025", "03/14/2025", "12/1/1998", "1/1/1900"])
def test_an_approved_date_is_accepted(value: str) -> None:
    report = _validate(synthetic.member(synthetic.row(Deed_Date=value)))
    assert report.release_accepted is True


@pytest.mark.parametrize(
    "value",
    [
        "2025-03-14",
        "3-14-2025",
        "3/14/25",
        "13/1/2025",
        "2/30/2025",
        "4/31/2025",
        "3/14/1899",
        "3/14/2101",
    ],
)
def test_an_unapproved_date_is_refused(value: str) -> None:
    report = _validate(synthetic.member(synthetic.row(Deed_Date=value)))
    assert "invalid_source_date" in _codes(report)


@pytest.mark.parametrize(
    ("codepoint", "label"),
    [(0x00, "nul"), (0x1F, "unit-separator"), (0x7F, "del"), (0x85, "nel"), (0x9F, "apc")],
)
def test_a_control_character_is_refused_in_source_text(codepoint: int, label: str) -> None:
    """ISO-8859-1 can represent C1 controls, so excluding only C0 and DEL let
    U+0080 through U+009F into supposedly non-control text."""

    del label
    value = f"A{chr(codepoint)}B"
    report = _validate(synthetic.member(synthetic.row(Property_Class=value)))
    assert "invalid_source_text" in _codes(report)


@pytest.mark.parametrize("codepoint", [0x00, 0x1F, 0x7F, 0x85, 0x9F])
def test_a_control_character_is_refused_in_a_header(codepoint: int) -> None:
    header = f"{synthetic.HEADER}|Note{chr(codepoint)}"
    member = synthetic.member(f"{synthetic.VALID_ROW}|x", header=header)
    report = _validate(member)
    assert "unsupported_layout" in _codes(report)


def test_an_optional_identifier_and_text_bound_are_enforced() -> None:
    long_identifier = _validate(synthetic.member(synthetic.row(PIDN="p" * 513)))
    assert "invalid_source_identifier" in _codes(long_identifier)
    long_text = _validate(synthetic.member(synthetic.row(Property_Class="c" * 129)))
    assert "invalid_source_text" in _codes(long_text)


# --------------------------------------------------------------------------
# Uniqueness and atomicity
# --------------------------------------------------------------------------


def test_a_repeated_account_rejects_the_release() -> None:
    report = _validate(
        synthetic.member(
            synthetic.row(Account_Num="ACC-1", RP="R"),
            synthetic.row(Account_Num="ACC-1", RP="C"),
        )
    )
    assert "duplicate_account_num" in _codes(report)
    assert report.release_accepted is False
    assert report.accepted_row_count == 0


def test_one_account_across_two_identified_releases_is_not_a_duplicate() -> None:
    member = synthetic.member(synthetic.row(Account_Num="ACC-1"))
    first = _validate(member, release_identifier="tarrant-2024-synthetic")
    second = _validate(member, release_identifier="tarrant-2025-synthetic")
    for report in (first, second):
        assert report.release_accepted is True
        assert report.accepted_row_count == 1
        assert "duplicate_account_num" not in _codes(report)


def test_one_failing_row_among_many_returns_nothing() -> None:
    rows = [synthetic.row(Account_Num=f"ACC-{index}") for index in range(50)]
    rows[36] = synthetic.row(Account_Num="ACC-36", RP="X")
    report = _validate(synthetic.member(*rows))
    assert report.release_accepted is False
    assert report.accepted_row_count == 0
    invalid = next(d for d in report.diagnostics if d.code.value == "invalid_division")
    assert invalid.physical_row_number == 38


def test_a_nonfatal_diagnostic_alone_still_accepts_every_row() -> None:
    rows = [synthetic.row(Account_Num=f"ACC-{index}") for index in range(3)]
    report = _validate(synthetic.member(*rows, header=synthetic.HEADER_WITH_EXTRA))
    assert report.release_accepted is False  # rows are now narrower than the header
    widened = synthetic.member(*[f"{row}|note" for row in rows], header=synthetic.HEADER_WITH_EXTRA)
    accepted = _validate(widened)
    assert accepted.release_accepted is True
    assert _codes(accepted) == ["extra_columns_present"]
    assert accepted.accepted_row_count == 3


def test_diagnostics_truncate_deterministically_while_preserving_the_total() -> None:
    rows = [synthetic.row(Account_Num=f"ACC-{index}", RP="X") for index in range(140)]
    member = synthetic.member(*rows)
    report = _validate(member)
    assert len(report.diagnostics) == TARRANT_DIAGNOSTIC_RETENTION_LIMIT
    assert report.total_diagnostic_count == 140
    assert report.diagnostics_truncated is True
    assert _validate(member).diagnostics == report.diagnostics


def test_an_untruncated_report_reports_its_exact_total() -> None:
    report = _validate(synthetic.VALID_LF)
    assert report.total_diagnostic_count == 0
    assert report.diagnostics_truncated is False


# --------------------------------------------------------------------------
# Caller identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"release_identifier": ""},
        {"release_identifier": "a" * 129},
        {"release_identifier": ".hidden"},
        {"release_identifier": "-leading"},
        {"source_member_name": "/var/tmp/tarrant/2025.txt"},
        {"source_member_name": "C:\\data\\2025.txt"},
        {"source_member_name": "../2025.txt"},
        {"source_member_name": "has space.txt"},
        {"expected_source_year": 1899},
        {"expected_source_year": 2101},
    ],
    ids=[
        "empty",
        "too-long",
        "leading-dot",
        "leading-dash",
        "absolute-path",
        "drive-path",
        "traversal",
        "whitespace",
        "year-low",
        "year-high",
    ],
)
def test_an_out_of_contract_caller_argument_raises(override: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _validate(synthetic.VALID_LF, **override)


@pytest.mark.parametrize(
    "override",
    [
        {"release_identifier": b"tarrant-2025"},
        {"release_identifier": None},
        {"source_member_name": 42},
        {"expected_source_year": "2025"},
        {"expected_source_year": 2025.0},
        {"expected_source_year": True},
    ],
    ids=["bytes", "none", "int-name", "str-year", "float-year", "bool-year"],
)
def test_a_caller_argument_of_the_wrong_type_raises_rather_than_coercing(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _validate(synthetic.VALID_LF, **override)


def test_a_caller_contract_violation_produces_no_report_and_no_diagnostic() -> None:
    """The closed vocabulary describes the source, never the caller."""

    with pytest.raises(ValueError) as raised:
        _validate(synthetic.VALID_LF, source_member_name="/etc/passwd")
    assert not isinstance(raised.value, TarrantValidationReport)
    assert "passwd" not in str(raised.value)


# --------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------


def test_a_sensitive_column_name_may_appear_while_its_value_never_does() -> None:
    report = _validate(synthetic.SENSITIVE_COLUMNS)
    assert "Owner_Name" in report.observed_headers
    assert "Situs_Address" in report.observed_headers
    rendered = repr(report)
    for placeholder in synthetic.SENSITIVE_PLACEHOLDERS:
        assert placeholder not in rendered


def test_an_unknown_column_value_is_absent_from_the_report() -> None:
    report = _validate(synthetic.EXTRA_COLUMN)
    assert "synthetic-note" not in repr(report)


def test_a_rejected_value_is_absent_from_its_diagnostic() -> None:
    report = _validate(synthetic.member(synthetic.row(Total_Value="1,250.00")))
    assert "invalid_monetary_value" in _codes(report)
    assert "1,250.00" not in repr(report)


def test_a_diagnostic_carries_only_the_four_permitted_fields() -> None:
    assert [field.name for field in TarrantDiagnostic.__dataclass_fields__.values()] == [
        "code",
        "field_name",
        "physical_row_number",
        "layout_fingerprint",
    ]


def test_the_report_carries_no_row_payload() -> None:
    fields = set(TarrantValidationReport.__dataclass_fields__)
    assert fields == {
        "parser_contract_version",
        "release_accepted",
        "layout_fingerprint",
        "observed_headers",
        "accepted_row_count",
        "diagnostics",
        "total_diagnostic_count",
        "diagnostics_truncated",
    }
    assert not fields & {"rows", "records", "values", "fields", "source_records"}


def test_the_sensitive_header_inventory_matches_the_approved_list() -> None:
    assert TARRANT_SENSITIVE_HEADERS == frozenset(
        {
            "Owner_Name",
            "Owner_Address",
            "Owner_CityState",
            "Owner_Zip",
            "Owner_Zip4",
            "Owner_CRRT",
            "Situs_Address",
            "LegalDescription",
        }
    )


# --------------------------------------------------------------------------
# Architecture and boundaries
# --------------------------------------------------------------------------


def _module_source() -> str:
    from property_tax_adapters.sources.texas import tarrant

    return Path(inspect.getfile(tarrant)).read_text(encoding="utf-8")


def test_no_shared_issue_43_contract_is_imported_or_substituted() -> None:
    """The record layer waits on Issue #43, and no county-local stand-in exists."""

    source = _module_source()
    assert "sources.contracts" not in source
    assert "AppraisalSourceRecord" not in source
    assert "class SourceNativeValue" not in source
    assert "class SourceProvenance" not in source
    assert "TarrantCertifiedSourceRecord" not in source


def test_the_domain_and_application_packages_gain_no_tarrant_vocabulary() -> None:
    """`TARRANT_SOURCE` legitimately imports both, so absence is not the claim.

    Nor is the absence of the word "Tarrant": `CountySlug.TARRANT` and the
    county registry entry predate this work and are county vocabulary, not the
    parser's. The claim is narrower and checkable -- no name this parser
    introduces appears in either package.
    """

    source = _module_source()
    assert "from property_tax_application import" in source
    assert "from property_tax_domain import" in source

    parser_vocabulary = (
        "TarrantDiagnostic",
        "TarrantValidationReport",
        "validate_certified_member",
        "layout_fingerprint",
        "TARRANT_REQUIRED_HEADERS",
        "TARRANT_SENSITIVE_HEADERS",
        "TARRANT_PARSER_CONTRACT_VERSION",
        "certified-core",
    )
    repo_root = Path(__file__).resolve().parents[3]
    for package in ("property-tax-domain", "property-tax-application"):
        for path in (repo_root / "libs" / package / "src").rglob("*.py"):
            body = path.read_text(encoding="utf-8")
            leaked = [name for name in parser_vocabulary if name in body]
            assert leaked == [], (path, leaked)


def test_no_acquisition_network_or_persistence_behavior_is_present() -> None:
    source = _module_source()
    for forbidden in (
        "import requests",
        "import httpx",
        "urllib",
        "socket",
        "zipfile",
        "sqlalchemy",
        "boto3",
        "open(",
        "Path(",
    ):
        assert forbidden not in source, forbidden


def test_the_parser_adds_no_dependency_outside_the_standard_library() -> None:
    source = _module_source()
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
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "typing",
    }, imported
