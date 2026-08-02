"""Contract tests for the adapter-local Dallas parser foundation."""

from __future__ import annotations

import hashlib
from dataclasses import fields
from decimal import Decimal
from typing import get_type_hints

import pytest
from fixtures.dallas_synthetic import (
    REQUIRED_HEADER,
    VALID_BOM,
    VALID_CRLF,
    VALID_LF,
    VALID_QUOTED_EXTRA,
    VALID_REORDERED,
    VALID_ROW,
)
from property_tax_adapters.sources.texas.dallas import (
    DALLAS_PARSER_CONTRACT_VERSION,
    AppraisalSourceRecord,
    DallasAppraisalSourceRecord,
    DallasDiagnosticCode,
    DallasParseError,
    DallasParseResult,
    DallasParserInputError,
    SourceNativeDecimal,
    SourceNativeValue,
    parse_dallas_appraisal_csv,
)


def hex_digest(*chunks: str) -> str:
    return "".join(chunks)


SOURCE_MEMBER = "synthetic-dallas-foundation.txt"
RELEASE_IDENTIFIER = "synthetic-release-2026"
REQUIRED_LAYOUT_FINGERPRINT = hex_digest(
    "49546217",
    "7f0ab2b0",
    "3d6fd27a",
    "197fd73b",
    "04ac5e0b",
    "4a055653",
    "c8b2156a",
    "75d7e334",
)


def parse(content: bytes | str = VALID_LF) -> DallasParseResult:
    return parse_dallas_appraisal_csv(
        content,
        source_member_name=SOURCE_MEMBER,
        release_identifier=RELEASE_IDENTIFIER,
    )


def error_for(content: bytes | str) -> DallasParseError:
    with pytest.raises(DallasParseError) as caught:
        parse(content)
    return caught.value


def codes(error: DallasParseError) -> tuple[DallasDiagnosticCode, ...]:
    return tuple(diagnostic.code for diagnostic in error.diagnostics)


def source_with(
    *,
    header: str = REQUIRED_HEADER,
    rows: tuple[str, ...] = (VALID_ROW,),
    newline: str = "\n",
) -> bytes:
    return (newline.join((header, *rows)) + newline).encode()


def required_row(
    *,
    account_num: str = "00000000000000017",
    appraisal_year: str = "2026",
    gis_parcel_id: str = "Parcel-0007",
    tot_val: str = "-001.20",
) -> str:
    return ",".join((account_num, appraisal_year, gis_parcel_id, tot_val))


def test_valid_row_emits_typed_source_and_adapter_records() -> None:
    result = parse()

    assert len(result.source_records) == 1
    assert len(result.records) == 1
    assert result.diagnostics == ()
    assert isinstance(result.source_records[0], DallasAppraisalSourceRecord)
    assert isinstance(result.records[0], AppraisalSourceRecord)


def test_valid_row_preserves_lexical_forms_and_source_native_total() -> None:
    source_record = parse().source_records[0]

    assert source_record.account_num == "00000000000000017"
    assert source_record.appraisal_year == 2026
    assert source_record.gis_parcel_id == "Parcel-0007"
    assert source_record.tot_val == SourceNativeDecimal(
        lexical_text="-001.20",
        value=Decimal("-001.20"),
    )


def test_adapter_conversion_retains_only_source_native_total_semantics() -> None:
    record = parse().records[0]

    assert record.jurisdiction_code == "tx-dallas"
    assert record.source_account_id == "00000000000000017"
    assert record.appraisal_year == 2026
    assert record.parcel_reference == "Parcel-0007"
    assert record.source_native_values == {
        "TOT_VAL": SourceNativeValue(
            lexical_text="-001.20",
            value=Decimal("-001.20"),
        )
    }
    assert not {
        "market_value",
        "appraised_value",
        "assessed_value",
        "taxable_value",
        "tax_amount",
        "payment_status",
        "delinquency",
        "penalty",
        "interest",
    } & {field.name for field in fields(record)}


def test_reordered_columns_bind_by_name_with_the_same_fingerprint() -> None:
    original = parse()
    reordered = parse(VALID_REORDERED)

    assert reordered.source_records[0].account_num == original.source_records[0].account_num
    assert reordered.source_records[0].gis_parcel_id == original.source_records[0].gis_parcel_id
    assert (
        reordered.source_records[0].provenance.layout_fingerprint
        == original.source_records[0].provenance.layout_fingerprint
        == REQUIRED_LAYOUT_FINGERPRINT
    )


@pytest.mark.parametrize("content", [VALID_LF, VALID_CRLF, VALID_BOM])
def test_line_endings_and_optional_bom_parse_identically(content: bytes) -> None:
    result = parse(content)

    assert result.source_records[0].account_num == "00000000000000017"
    assert result.source_records[0].provenance.observed_headers[0] == "ACCOUNT_NUM"
    assert result.source_records[0].provenance.layout_fingerprint == REQUIRED_LAYOUT_FINGERPRINT


def test_standard_csv_quotes_decode_without_shifting_columns() -> None:
    result = parse(VALID_QUOTED_EXTRA)

    assert result.source_records[0].extras == {"NOTE": 'Synthetic, "quoted" note'}
    assert result.records[0].source_native_values["NOTE"].value == 'Synthetic, "quoted" note'
    assert codes_from_result(result) == (DallasDiagnosticCode.EXTRA_COLUMNS_PRESENT,)


def test_observed_headers_are_retained_before_normalization() -> None:
    content = source_with(
        header='" account_num ",APPRAISAL_YR,GIS_PARCEL_ID,TOT_VAL',
    )

    provenance = parse(content).source_records[0].provenance
    assert provenance.observed_headers[0] == " account_num "
    assert provenance.normalized_headers[0] == "ACCOUNT_NUM"


def test_missing_required_header_fails_before_rows() -> None:
    error = error_for(
        source_with(
            header="ACCOUNT_NUM,APPRAISAL_YR,GIS_PARCEL_ID",
            rows=("00000000000000017,2026,Parcel-0007",),
        )
    )

    assert codes(error) == (
        DallasDiagnosticCode.MISSING_REQUIRED_HEADER,
        DallasDiagnosticCode.UNSUPPORTED_LAYOUT,
    )
    assert error.diagnostics[0].field_name == "TOT_VAL"
    assert all(diagnostic.source_row_number == 1 for diagnostic in error.diagnostics)


def test_alias_does_not_replace_a_required_observed_header() -> None:
    error = error_for(
        source_with(
            header="ACCOUNT_NUMBER,APPRAISAL_YR,GIS_PARCEL_ID,TOT_VAL",
        )
    )

    assert DallasDiagnosticCode.MISSING_REQUIRED_HEADER in codes(error)
    assert error.diagnostics[0].field_name == "ACCOUNT_NUM"


def test_exact_duplicate_header_fails_closed() -> None:
    error = error_for(
        source_with(
            header=("ACCOUNT_NUM,ACCOUNT_NUM,APPRAISAL_YR,GIS_PARCEL_ID,TOT_VAL"),
            rows=("00000000000000017,00000000000000018,2026,Parcel-0007,1",),
        )
    )

    assert DallasDiagnosticCode.DUPLICATE_HEADER in codes(error)
    assert codes(error)[-1] is DallasDiagnosticCode.UNSUPPORTED_LAYOUT


def test_normalization_collision_fails_closed() -> None:
    error = error_for(
        source_with(
            header=('ACCOUNT_NUM," account_num ",APPRAISAL_YR,GIS_PARCEL_ID,TOT_VAL'),
            rows=("00000000000000017,00000000000000018,2026,Parcel-0007,1",),
        )
    )

    assert DallasDiagnosticCode.HEADER_NORMALIZATION_COLLISION in codes(error)
    assert codes(error)[-1] is DallasDiagnosticCode.UNSUPPORTED_LAYOUT


def test_blank_header_fails_closed() -> None:
    error = error_for(
        source_with(
            header="ACCOUNT_NUM,APPRAISAL_YR,GIS_PARCEL_ID,TOT_VAL,   ",
            rows=(f"{VALID_ROW},unused",),
        )
    )

    assert DallasDiagnosticCode.BLANK_HEADER in codes(error)
    assert codes(error)[-1] is DallasDiagnosticCode.UNSUPPORTED_LAYOUT


def test_unknown_columns_are_retained_with_deterministic_warnings() -> None:
    content = source_with(
        header=f"{REQUIRED_HEADER},ZETA,ALPHA",
        rows=(f"{VALID_ROW},last,first",),
    )
    result = parse(content)

    assert result.source_records[0].extras == {"ALPHA": "first", "ZETA": "last"}
    assert tuple(diagnostic.field_name for diagnostic in result.diagnostics) == (
        "ALPHA",
        "ZETA",
    )
    assert all(
        diagnostic.code is DallasDiagnosticCode.EXTRA_COLUMNS_PRESENT
        for diagnostic in result.diagnostics
    )
    assert result.source_records[0].provenance.layout_fingerprint != REQUIRED_LAYOUT_FINGERPRINT


def test_malformed_quoting_fails_without_partial_records() -> None:
    content = (
        f"{REQUIRED_HEADER},NOTE\n"
        f"{VALID_ROW},safe\n"
        '00000000000000018,2026,Parcel-0008,2,"unterminated\n'
    ).encode()
    error = error_for(content)

    assert codes(error) == (
        DallasDiagnosticCode.MALFORMED_CSV,
        DallasDiagnosticCode.UNSUPPORTED_LAYOUT,
    )
    assert all(diagnostic.source_row_number == 3 for diagnostic in error.diagnostics)
    assert not hasattr(error, "records")


@pytest.mark.parametrize(
    ("row", "expected_row"),
    [
        ("00000000000000017,2026,Parcel-0007", 2),
        (f"{VALID_ROW},unexpected", 2),
    ],
)
def test_short_and_long_rows_fail_closed(row: str, expected_row: int) -> None:
    error = error_for(source_with(rows=(row,)))

    assert codes(error) == (
        DallasDiagnosticCode.ROW_WIDTH_MISMATCH,
        DallasDiagnosticCode.UNSUPPORTED_LAYOUT,
    )
    assert all(diagnostic.source_row_number == expected_row for diagnostic in error.diagnostics)


def test_invalid_utf8_and_misplaced_bom_fail_at_the_physical_boundary() -> None:
    invalid_encoding = error_for(VALID_LF + b"\xff")
    misplaced_bom = error_for(VALID_LF.replace(b"Parcel", b"\xef\xbb\xbfParcel"))

    assert codes(invalid_encoding) == (DallasDiagnosticCode.INVALID_ENCODING,)
    assert codes(misplaced_bom) == (DallasDiagnosticCode.UNEXPECTED_BOM,)


@pytest.mark.parametrize(
    "account_num",
    ["", "0000000000000017", "000000000000000017", "0000000000000001A", "٠" * 17],
)
def test_invalid_account_forms_fail_deterministically(account_num: str) -> None:
    error = error_for(source_with(rows=(required_row(account_num=account_num),)))

    assert codes(error) == (DallasDiagnosticCode.INVALID_ACCOUNT_NUM,)
    assert error.diagnostics[0].field_name == "ACCOUNT_NUM"


@pytest.mark.parametrize("year", ["", "026", "02026", "٢٠٢٦", "1899", "2101"])
def test_invalid_appraisal_year_forms_fail_deterministically(year: str) -> None:
    error = error_for(source_with(rows=(required_row(appraisal_year=year),)))

    assert codes(error) == (DallasDiagnosticCode.INVALID_APPRAISAL_YEAR,)


def test_blank_ascii_trimmed_parcel_identifier_fails() -> None:
    error = error_for(source_with(rows=(required_row(gis_parcel_id=" \t\v\f"),)))

    assert codes(error) == (DallasDiagnosticCode.INVALID_GIS_PARCEL_ID,)


@pytest.mark.parametrize(
    "tot_val",
    ["", "$100", '"1,000"', "1e3", "+100", "100.", ".5", "--1", "1 00"],
)
def test_invalid_total_value_forms_fail_deterministically(tot_val: str) -> None:
    error = error_for(source_with(rows=(required_row(tot_val=tot_val),)))

    assert codes(error) == (DallasDiagnosticCode.INVALID_TOT_VAL,)
    assert error.diagnostics[0].field_name == "TOT_VAL"


def test_duplicate_parent_key_rejects_the_later_logical_row_without_key_values() -> None:
    duplicate = required_row(gis_parcel_id="Different-Parcel", tot_val="999")
    error = error_for(source_with(rows=(VALID_ROW, duplicate)))

    assert codes(error) == (DallasDiagnosticCode.DUPLICATE_PARENT_KEY,)
    diagnostic = error.diagnostics[0]
    assert diagnostic.source_row_number == 3
    assert diagnostic.field_name is None
    assert "00000000000000017" not in repr(diagnostic)
    assert "2026" not in repr(diagnostic)


def test_provenance_is_complete_and_equal_across_both_record_types() -> None:
    result = parse()
    source_provenance = result.source_records[0].provenance
    output_provenance = result.records[0].provenance

    assert source_provenance.source_member_name == SOURCE_MEMBER
    assert source_provenance.release_identifier == RELEASE_IDENTIFIER
    assert source_provenance.observed_headers == tuple(REQUIRED_HEADER.split(","))
    assert source_provenance.normalized_headers == tuple(REQUIRED_HEADER.split(","))
    assert source_provenance.layout_fingerprint == REQUIRED_LAYOUT_FINGERPRINT
    assert source_provenance.source_row_number == 2
    assert source_provenance.parser_contract_version == DALLAS_PARSER_CONTRACT_VERSION == 1
    assert output_provenance == type(output_provenance)(
        source_member_name=source_provenance.source_member_name,
        release_identifier=source_provenance.release_identifier,
        observed_headers=source_provenance.observed_headers,
        normalized_headers=source_provenance.normalized_headers,
        layout_fingerprint=source_provenance.layout_fingerprint,
        source_row_number=source_provenance.source_row_number,
        parser_contract_version=source_provenance.parser_contract_version,
    )


@pytest.mark.parametrize("field_name", ["source_member_name", "release_identifier"])
def test_source_identity_must_be_supplied_by_the_caller(field_name: str) -> None:
    arguments = {
        "source_member_name": SOURCE_MEMBER,
        "release_identifier": RELEASE_IDENTIFIER,
    }
    arguments[field_name] = ""

    with pytest.raises(DallasParserInputError) as caught:
        parse_dallas_appraisal_csv(VALID_LF, **arguments)

    assert caught.value.field_name == field_name


def test_diagnostic_vocabulary_is_closed() -> None:
    assert {code.value for code in DallasDiagnosticCode} == {
        "invalid_encoding",
        "unexpected_bom",
        "blank_header",
        "missing_required_header",
        "duplicate_header",
        "header_normalization_collision",
        "malformed_csv",
        "row_width_mismatch",
        "invalid_account_num",
        "invalid_appraisal_year",
        "invalid_gis_parcel_id",
        "invalid_tot_val",
        "duplicate_parent_key",
        "unsupported_layout",
        "extra_columns_present",
    }


def test_diagnostics_do_not_retain_arbitrary_source_values() -> None:
    protected_like_text = "SYNTHETIC_OWNER|000 Example Test Lane|not-a-secret-token"
    content = source_with(
        header=f"{REQUIRED_HEADER},UNMAPPED_TEXT",
        rows=(required_row(account_num="invalid") + f",{protected_like_text}",),
    )
    error = error_for(content)
    rendered = repr(error.diagnostics)

    assert codes(error) == (DallasDiagnosticCode.INVALID_ACCOUNT_NUM,)
    assert protected_like_text not in rendered
    assert "Example Test Lane" not in rendered
    assert "not-a-secret-token" not in rendered
    assert {field.name for field in fields(error.diagnostics[0])} == {
        "code",
        "field_name",
        "source_row_number",
        "layout_fingerprint",
    }


def test_records_and_annotations_remain_adapter_local() -> None:
    record_types = (
        DallasAppraisalSourceRecord,
        AppraisalSourceRecord,
        SourceNativeDecimal,
        SourceNativeValue,
    )

    assert all(
        record_type.__module__.startswith("property_tax_adapters.") for record_type in record_types
    )
    for record_type in record_types:
        rendered_hints = repr(get_type_hints(record_type))
        assert "property_tax_domain" not in rendered_hints
        assert "property_tax_application" not in rendered_hints


@pytest.mark.parametrize(
    ("name", "payload", "expected_sha256"),
    [
        (
            "VALID_LF",
            VALID_LF,
            hex_digest(
                "131bca3a",
                "824a4818",
                "d47f7528",
                "697bb5a3",
                "c072b45d",
                "5c4e9e48",
                "59b3b476",
                "4a936f0d",
            ),
        ),
        (
            "VALID_CRLF",
            VALID_CRLF,
            hex_digest(
                "068182b1",
                "13efeaf8",
                "64f47d7e",
                "83007437",
                "aa9fc04c",
                "9b298072",
                "891a76e7",
                "8b67fd09",
            ),
        ),
        (
            "VALID_BOM",
            VALID_BOM,
            hex_digest(
                "068c25ec",
                "c7f00d3d",
                "6754a325",
                "34e1de5f",
                "2f9eba46",
                "c0037809",
                "18f08820",
                "1209b174",
            ),
        ),
        (
            "VALID_REORDERED",
            VALID_REORDERED,
            hex_digest(
                "98990e57",
                "74608078",
                "62013c5a",
                "914f1e4f",
                "55ead5b3",
                "86a38039",
                "6a31d2da",
                "861c6eb5",
            ),
        ),
        (
            "VALID_QUOTED_EXTRA",
            VALID_QUOTED_EXTRA,
            hex_digest(
                "43f891cc",
                "e923b754",
                "0d562da2",
                "814ebd70",
                "aa6c47a9",
                "f8de6f6d",
                "1e3d1a46",
                "326614a8",
            ),
        ),
    ],
)
def test_synthetic_fixture_checksums(
    name: str,
    payload: bytes,
    expected_sha256: str,
) -> None:
    assert name.startswith("VALID_")
    assert hashlib.sha256(payload).hexdigest() == expected_sha256


def codes_from_result(result: DallasParseResult) -> tuple[DallasDiagnosticCode, ...]:
    return tuple(diagnostic.code for diagnostic in result.diagnostics)
