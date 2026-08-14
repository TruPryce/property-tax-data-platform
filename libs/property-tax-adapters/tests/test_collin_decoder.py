"""Contract tests for the adapter-local Collin decoder foundation."""

from __future__ import annotations

import ast
import hashlib
import operator
from dataclasses import fields, replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest
from fixtures.collin_synthetic import (
    BOUNDARY_BUFFER,
    COMPATIBLE_COLUMNS,
    COMPATIBLE_SCHEMA,
    CURRENT_ONLY_ROW,
    FIXTURE_PROVENANCE,
    NEGATIVE_BUFFER,
    NUMERIC_VECTORS,
    POSITIVE_BUFFER,
    VALID_ROW,
    YEAR_2025_BUFFER,
    YEAR_2026_BUFFER,
    ZERO_BUFFER,
)
from property_tax_adapters.sources.contracts import SourceNativeValue
from property_tax_adapters.sources.texas import collin as collin_module
from property_tax_adapters.sources.texas.collin import (
    CERTIFIED_VALUE_COLUMNS,
    COLLIN_PARSER_CONTRACT_VERSION,
    COLLIN_SOURCE,
    COLLIN_SOURCE_NATIVE_CLASSIFICATION,
    COLLIN_TABLE_NAME,
    CURRENT_VALUE_COLUMNS,
    REQUIRED_COLUMN_NAMES,
    CollinAccessPhysicalType,
    CollinAppraisalObservation,
    CollinAppraisalSourceRecord,
    CollinColumnDescriptor,
    CollinContractError,
    CollinDecodedNumeric,
    CollinDiagnostic,
    CollinDiagnosticCode,
    CollinParserInputError,
    convert_collin_observation,
    convert_collin_row,
    decode_collin_numeric,
    fingerprint_collin_schema,
    validate_collin_schema,
)
from property_tax_adapters.sources.texas.registry import source_for_county
from property_tax_domain import CountySlug

SOURCE_MEMBER = "synthetic-collin-foundation.accdb"
RELEASE_IDENTIFIER = "synthetic-release-2026"
COMPATIBLE_SCHEMA_FINGERPRINT = "".join(
    (
        "026af897",
        "167d3571",
        "4f8f4c12",
        "6e55640c",
        "14e37235",
        "508a1c1d",
        "da662f9b",
        "fc627f28",
    )
)


def validated_schema(
    columns: tuple[CollinColumnDescriptor, ...] = COMPATIBLE_COLUMNS,
) -> object:
    return validate_collin_schema({COLLIN_TABLE_NAME: columns})


def convert(
    row: dict[str, object] = VALID_ROW,
    *,
    source_row_number: int = 1,
    columns: tuple[CollinColumnDescriptor, ...] = COMPATIBLE_COLUMNS,
):
    return convert_collin_row(
        row,
        schema=validate_collin_schema({COLLIN_TABLE_NAME: columns}),
        source_member_name=SOURCE_MEMBER,
        release_identifier=RELEASE_IDENTIFIER,
        source_row_number=source_row_number,
    )


def codes(error: CollinContractError) -> tuple[CollinDiagnosticCode, ...]:
    return tuple(diagnostic.code for diagnostic in error.diagnostics)


def numeric_error(
    buffer: object,
    *,
    precision: int | None = 4,
    scale: int | None = 0,
) -> CollinContractError:
    with pytest.raises(CollinContractError) as caught:
        decode_collin_numeric(buffer, precision=precision, scale=scale)
    return caught.value


def replace_column(
    name: str,
    **changes: object,
) -> tuple[CollinColumnDescriptor, ...]:
    return tuple(
        replace(column, **changes) if column.name == name else column
        for column in COMPATIBLE_COLUMNS
    )


def schema_error(
    columns: tuple[CollinColumnDescriptor, ...],
) -> CollinContractError:
    with pytest.raises(CollinContractError) as caught:
        validate_collin_schema({COLLIN_TABLE_NAME: columns})
    return caught.value


def test_independent_numeric_vectors_have_pinned_checksums_and_provenance() -> None:
    assert {vector.name for vector in NUMERIC_VECTORS} == {
        "canonical-zero",
        "positive",
        "negative",
        "scaled",
        "signed-multiword",
        "precision-boundary",
        "year-2025",
        "year-2026",
        "monetary",
    }
    for vector in NUMERIC_VECTORS:
        assert hashlib.sha256(vector.buffer).hexdigest() == vector.sha256
        assert vector.provenance == FIXTURE_PROVENANCE
        assert len(vector.buffer) == 17


@pytest.mark.parametrize("vector", NUMERIC_VECTORS, ids=lambda vector: vector.name)
def test_independent_numeric_vectors_decode_exactly(vector) -> None:
    decoded = decode_collin_numeric(
        vector.buffer,
        precision=vector.precision,
        scale=vector.scale,
    )

    assert decoded == CollinDecodedNumeric(
        value=vector.expected,
        precision=vector.precision,
        scale=vector.scale,
    )
    assert decoded.value.as_tuple().exponent == -vector.scale


@pytest.mark.parametrize(
    "buffer",
    [None, bytearray(17), memoryview(bytes(17)), bytes(16), bytes(18), "not-bytes"],
)
def test_numeric_decoder_rejects_non_bytes_and_wrong_width(buffer: object) -> None:
    assert codes(numeric_error(buffer)) == (CollinDiagnosticCode.INVALID_NUMERIC_BUFFER,)


def test_numeric_decoder_rejects_unsupported_sign() -> None:
    buffer = bytes.fromhex("02 00000000 00000000 00000000 2a000000")

    assert codes(numeric_error(buffer)) == (CollinDiagnosticCode.INVALID_NUMERIC_SIGN,)


@pytest.mark.parametrize("precision", [None, 0, 29, True])
def test_numeric_decoder_rejects_invalid_precision(precision: int | None) -> None:
    assert codes(numeric_error(POSITIVE_BUFFER, precision=precision)) == (
        CollinDiagnosticCode.INVALID_NUMERIC_PRECISION,
    )


@pytest.mark.parametrize("scale", [None, -1, 5, True])
def test_numeric_decoder_rejects_invalid_scale(scale: int | None) -> None:
    assert codes(numeric_error(POSITIVE_BUFFER, precision=4, scale=scale)) == (
        CollinDiagnosticCode.INVALID_NUMERIC_SCALE,
    )


def test_numeric_decoder_rejects_negative_zero() -> None:
    negative_zero = b"\x01" + ZERO_BUFFER[1:]

    assert codes(numeric_error(negative_zero)) == (CollinDiagnosticCode.NEGATIVE_ZERO,)


def test_numeric_decoder_rejects_declared_precision_overflow() -> None:
    assert codes(numeric_error(POSITIVE_BUFFER, precision=1)) == (
        CollinDiagnosticCode.NUMERIC_PRECISION_OVERFLOW,
    )


def test_signed_boundary_decode_ignores_the_callers_decimal_precision() -> None:
    negative_boundary = b"\x01" + BOUNDARY_BUFFER[1:]

    with localcontext() as context:
        context.prec = 5
        decoded = decode_collin_numeric(negative_boundary, precision=28, scale=0)

    assert decoded.value == Decimal("-9999999999999999999999999999")


def test_compatible_schema_binds_every_required_column() -> None:
    schema = validate_collin_schema(COMPATIBLE_SCHEMA)

    assert tuple(schema.required_columns) == REQUIRED_COLUMN_NAMES
    assert schema.table_name == COLLIN_TABLE_NAME
    assert schema.schema_fingerprint == COMPATIBLE_SCHEMA_FINGERPRINT
    assert schema.diagnostics == ()


def test_reordered_schema_has_the_same_canonical_fingerprint() -> None:
    reversed_columns = tuple(reversed(COMPATIBLE_COLUMNS))

    assert fingerprint_collin_schema(reversed_columns) == fingerprint_collin_schema(
        COMPATIBLE_COLUMNS
    )
    assert (
        validate_collin_schema({COLLIN_TABLE_NAME: reversed_columns}).schema_fingerprint
        == COMPATIBLE_SCHEMA_FINGERPRINT
    )


def test_missing_table_fails_closed_before_rows() -> None:
    with pytest.raises(CollinContractError) as caught:
        validate_collin_schema({})

    assert CollinDiagnosticCode.MISSING_REQUIRED_TABLE in codes(caught.value)
    assert codes(caught.value)[-1] is CollinDiagnosticCode.UNSUPPORTED_SCHEMA


def test_unexpected_table_fails_closed() -> None:
    with pytest.raises(CollinContractError) as caught:
        validate_collin_schema({COLLIN_TABLE_NAME: COMPATIBLE_COLUMNS, "Synthetic_Extra": ()})

    assert codes(caught.value) == (
        CollinDiagnosticCode.UNEXPECTED_TABLE,
        CollinDiagnosticCode.UNSUPPORTED_SCHEMA,
    )
    assert caught.value.diagnostics[0].table_name == "Synthetic_Extra"


def test_missing_and_case_changed_required_names_do_not_bind() -> None:
    missing = tuple(column for column in COMPATIBLE_COLUMNS if column.name != "curr_val_yr")
    renamed = tuple(
        replace(column, name="PROP_ID") if column.name == "prop_id" else column
        for column in COMPATIBLE_COLUMNS
    )

    assert CollinDiagnosticCode.MISSING_REQUIRED_COLUMN in codes(schema_error(missing))
    assert CollinDiagnosticCode.MISSING_REQUIRED_COLUMN in codes(schema_error(renamed))


def test_duplicate_exact_column_fails_closed() -> None:
    error = schema_error((*COMPATIBLE_COLUMNS, COMPATIBLE_COLUMNS[0]))

    assert CollinDiagnosticCode.DUPLICATE_COLUMN in codes(error)
    assert codes(error)[-1] is CollinDiagnosticCode.UNSUPPORTED_SCHEMA


def test_ascii_casefold_collision_fails_closed() -> None:
    collision = CollinColumnDescriptor(
        "PROP_ID", CollinAccessPhysicalType.LONG, 4, None, None, False
    )
    error = schema_error((*COMPATIBLE_COLUMNS, collision))

    assert CollinDiagnosticCode.COLUMN_NAME_COLLISION in codes(error)
    assert codes(error)[-1] is CollinDiagnosticCode.UNSUPPORTED_SCHEMA


@pytest.mark.parametrize(
    ("field_name", "changes", "expected_code"),
    [
        (
            "prop_id",
            {"physical_type": CollinAccessPhysicalType.TEXT},
            CollinDiagnosticCode.INCOMPATIBLE_PHYSICAL_TYPE,
        ),
        ("prop_id", {"width": 8}, CollinDiagnosticCode.INCOMPATIBLE_WIDTH),
        ("prop_id", {"precision": 10}, CollinDiagnosticCode.INCOMPATIBLE_PRECISION),
        ("prop_id", {"scale": 0}, CollinDiagnosticCode.INCOMPATIBLE_SCALE),
        ("geo_id", {"width": 0}, CollinDiagnosticCode.INCOMPATIBLE_WIDTH),
        ("geo_id", {"width": 256}, CollinDiagnosticCode.INCOMPATIBLE_WIDTH),
        ("geo_id", {"precision": 10}, CollinDiagnosticCode.INCOMPATIBLE_PRECISION),
        ("geo_id", {"scale": 0}, CollinDiagnosticCode.INCOMPATIBLE_SCALE),
        ("curr_val_yr", {"width": 16}, CollinDiagnosticCode.INCOMPATIBLE_WIDTH),
        ("curr_val_yr", {"precision": 29}, CollinDiagnosticCode.INCOMPATIBLE_PRECISION),
        ("curr_val_yr", {"scale": 1}, CollinDiagnosticCode.INCOMPATIBLE_SCALE),
        (
            "curr_market",
            {"scale": 5},
            CollinDiagnosticCode.INCOMPATIBLE_SCALE,
        ),
        (
            "curr_val_yr",
            {"nullable": True},
            CollinDiagnosticCode.INCOMPATIBLE_NULLABILITY,
        ),
        (
            "cert_val_yr",
            {"nullable": False},
            CollinDiagnosticCode.INCOMPATIBLE_NULLABILITY,
        ),
    ],
)
def test_incompatible_required_descriptors_fail_with_stable_codes(
    field_name: str,
    changes: dict[str, object],
    expected_code: CollinDiagnosticCode,
) -> None:
    error = schema_error(replace_column(field_name, **changes))

    assert expected_code in codes(error)
    assert codes(error)[-1] is CollinDiagnosticCode.UNSUPPORTED_SCHEMA


def test_metadata_only_extra_column_warns_and_changes_fingerprint() -> None:
    extra = CollinColumnDescriptor(
        "synthetic_extra", CollinAccessPhysicalType.TEXT, 20, None, None, True
    )
    schema = validate_collin_schema({COLLIN_TABLE_NAME: (*COMPATIBLE_COLUMNS, extra)})

    assert schema.schema_fingerprint != COMPATIBLE_SCHEMA_FINGERPRINT
    assert schema.diagnostics == (
        CollinDiagnostic(
            CollinDiagnosticCode.EXTRA_COLUMNS_PRESENT,
            field_name="synthetic_extra",
            schema_fingerprint=schema.schema_fingerprint,
        ),
    )
    assert "synthetic_extra" not in schema.required_columns


def test_non_ascii_metadata_name_is_unsupported() -> None:
    extra = CollinColumnDescriptor(
        "synthetic_é", CollinAccessPhysicalType.TEXT, 20, None, None, True
    )

    assert CollinDiagnosticCode.UNSUPPORTED_SCHEMA in codes(
        schema_error((*COMPATIBLE_COLUMNS, extra))
    )


def test_valid_row_emits_typed_record_and_separate_observations() -> None:
    result = convert()

    assert isinstance(result.source_record, CollinAppraisalSourceRecord)
    assert all(isinstance(item, CollinAppraisalObservation) for item in result.observations)
    assert result.source_record.prop_id == 101
    assert result.source_record.geo_id == "000-SYNTHETIC-A"
    assert result.source_record.current_value_year == 2026
    assert result.source_record.certified_value_year == 2025
    assert [item.source_family for item in result.observations] == ["current", "certified"]
    assert [item.source_year for item in result.observations] == [2026, 2025]
    assert [item.classification for item in result.observations] == [
        "Preliminary",
        "Certified",
    ]


def test_source_values_retain_exact_columns_metadata_and_semantics() -> None:
    source_record = convert().source_record

    assert tuple(source_record.current_values) == CURRENT_VALUE_COLUMNS
    assert tuple(source_record.certified_values) == CERTIFIED_VALUE_COLUMNS
    assert source_record.current_values["curr_market"] == SourceNativeValue(
        value=Decimal("123456789.01"),
        precision=28,
        scale=2,
        source_field="curr_market",
    )
    assert source_record.certified_values["cert_market"] == SourceNativeValue(
        value=Decimal("0.42"),
        precision=28,
        scale=2,
        source_field="cert_market",
    )
    assert (
        source_record.current_values["curr_market"].classification
        == COLLIN_SOURCE_NATIVE_CLASSIFICATION
    )


def test_current_and_certified_provenance_remains_distinct() -> None:
    current, certified = convert().observations

    assert current.provenance.shared.source_member_name == SOURCE_MEMBER
    assert current.provenance.shared.release_identifier == RELEASE_IDENTIFIER
    assert current.provenance.shared.table_name == COLLIN_TABLE_NAME
    assert current.provenance.shared.source_row_number == 1
    assert current.provenance.shared.parser_contract_version == COLLIN_PARSER_CONTRACT_VERSION
    # Same digest, mapped onto the shared vocabulary rather than duplicated.
    assert current.provenance.schema_fingerprint == COMPATIBLE_SCHEMA_FINGERPRINT
    assert current.provenance.shared.layout_fingerprint == COMPATIBLE_SCHEMA_FINGERPRINT
    assert current.provenance.source_family == "current"
    assert current.provenance.source_year == 2026
    assert current.provenance.property_status == "Preliminary"
    assert "curr_market" in current.provenance.value_source_columns
    assert certified.provenance.source_family == "certified"
    assert certified.provenance.source_year == 2025
    assert certified.provenance.property_status == "Preliminary"
    assert "cert_market" in certified.provenance.value_source_columns
    assert not set(current.values) & set(certified.values)


def test_matching_family_years_and_values_do_not_merge() -> None:
    row = {**VALID_ROW, "cert_val_yr": YEAR_2026_BUFFER, "cert_market": VALID_ROW["curr_market"]}
    result = convert(row)

    assert len(result.observations) == 2
    assert [item.source_family for item in result.observations] == ["current", "certified"]
    assert [item.source_year for item in result.observations] == [2026, 2026]


def test_absent_certified_family_is_not_synthesized() -> None:
    result = convert(CURRENT_ONLY_ROW)

    assert result.source_record.certified_value_year is None
    assert tuple(item.source_family for item in result.observations) == ("current",)


def test_certified_year_without_values_does_not_emit_an_observation() -> None:
    row = {**CURRENT_ONLY_ROW, "cert_val_yr": YEAR_2025_BUFFER}
    result = convert(row)

    assert result.source_record.certified_value_year == 2025
    assert tuple(item.source_family for item in result.observations) == ("current",)


def test_repeated_identifiers_remain_at_physical_row_grain() -> None:
    first = convert(source_row_number=7)
    second = convert(source_row_number=8)

    records = (first.source_record, second.source_record)
    assert [record.prop_id for record in records] == [101, 101]
    assert [record.geo_id for record in records] == [
        "000-SYNTHETIC-A",
        "000-SYNTHETIC-A",
    ]
    assert [record.provenance.source_row_number for record in records] == [7, 8]


def test_row_and_observation_value_mappings_are_immutable() -> None:
    result = convert()

    with pytest.raises(TypeError):
        operator.setitem(result.source_record.current_values, "curr_market", None)
    with pytest.raises(TypeError):
        operator.setitem(result.observations[0].values, "curr_market", None)


@pytest.mark.parametrize("prop_id", [True, False, None, "101", 0, -1, 2_147_483_648])
def test_invalid_prop_id_fails_without_exposing_its_value(prop_id: object) -> None:
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "prop_id": prop_id})

    assert codes(caught.value) == (CollinDiagnosticCode.INVALID_PROP_ID,)
    assert caught.value.diagnostics[0].field_name == "prop_id"


@pytest.mark.parametrize(
    "geo_id",
    [None, 17, "", " \t\r\n", "A\x00B", "A\tB", "\ud800", "x" * 256],
)
def test_invalid_geo_id_fails_without_exposing_its_value(geo_id: object) -> None:
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "geo_id": geo_id})

    assert codes(caught.value) == (CollinDiagnosticCode.INVALID_GEO_ID,)
    if isinstance(geo_id, str) and len(geo_id) >= 3:
        assert geo_id not in repr(caught.value.diagnostics)


@pytest.mark.parametrize("status", [None, "", "preliminary", "Final", "Certified\tState"])
def test_invalid_property_status_fails_closed(status: object) -> None:
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "property_status": status})

    assert codes(caught.value) == (CollinDiagnosticCode.INVALID_PROPERTY_STATUS,)


@pytest.mark.parametrize(
    "year_buffer",
    [
        bytes.fromhex("00 00000000 00000000 00000000 6b070000"),
        bytes.fromhex("00 00000000 00000000 00000000 35080000"),
    ],
)
def test_out_of_range_value_year_fails_closed(year_buffer: bytes) -> None:
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "curr_val_yr": year_buffer})

    assert codes(caught.value) == (CollinDiagnosticCode.INVALID_VALUE_YEAR,)


def test_negative_appraisal_value_fails_after_exact_signed_decode() -> None:
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "curr_market": NEGATIVE_BUFFER})

    assert codes(caught.value) == (CollinDiagnosticCode.INVALID_MONETARY_VALUE,)


def test_inconsistent_certified_family_fails_without_current_filling() -> None:
    row = {**CURRENT_ONLY_ROW, "cert_market": POSITIVE_BUFFER}

    with pytest.raises(CollinContractError) as caught:
        convert(row)

    assert codes(caught.value) == (CollinDiagnosticCode.INCONSISTENT_CERTIFIED_FAMILY,)


def test_malformed_non_null_numeric_never_becomes_none() -> None:
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "curr_market": b"malformed"})

    assert codes(caught.value) == (CollinDiagnosticCode.INVALID_NUMERIC_BUFFER,)


def test_missing_required_row_field_fails_atomically() -> None:
    row = dict(VALID_ROW)
    del row["curr_market"]

    with pytest.raises(CollinContractError) as caught:
        convert(row)

    assert codes(caught.value) == (CollinDiagnosticCode.UNSUPPORTED_SCHEMA,)


@pytest.mark.parametrize(
    ("source_member_name", "release_identifier", "source_row_number", "field_name"),
    [
        ("", RELEASE_IDENTIFIER, 1, "source_member_name"),
        (SOURCE_MEMBER, " ", 1, "release_identifier"),
        (SOURCE_MEMBER, RELEASE_IDENTIFIER, 0, "source_row_number"),
        (SOURCE_MEMBER, RELEASE_IDENTIFIER, True, "source_row_number"),
    ],
)
def test_caller_supplied_provenance_is_required(
    source_member_name: str,
    release_identifier: str,
    source_row_number: int,
    field_name: str,
) -> None:
    with pytest.raises(CollinParserInputError) as caught:
        convert_collin_row(
            VALID_ROW,
            schema=validate_collin_schema(COMPATIBLE_SCHEMA),
            source_member_name=source_member_name,
            release_identifier=release_identifier,
            source_row_number=source_row_number,
        )

    assert caught.value.field_name == field_name


def test_extra_row_value_is_never_requested_or_retained() -> None:
    class ExtraValueTrap(dict[str, object]):
        def __getitem__(self, key: str) -> object:
            if key == "synthetic_extra":
                raise AssertionError("metadata-only extra value was read")
            return super().__getitem__(key)

    extra = CollinColumnDescriptor(
        "synthetic_extra", CollinAccessPhysicalType.TEXT, 20, None, None, True
    )
    schema = validate_collin_schema({COLLIN_TABLE_NAME: (*COMPATIBLE_COLUMNS, extra)})
    row = ExtraValueTrap({**VALID_ROW, "synthetic_extra": "PROHIBITED_EXTRA_SENTINEL"})

    result = convert_collin_row(
        row,
        schema=schema,
        source_member_name=SOURCE_MEMBER,
        release_identifier=RELEASE_IDENTIFIER,
        source_row_number=1,
    )

    assert result.diagnostics[0].code is CollinDiagnosticCode.EXTRA_COLUMNS_PRESENT
    assert "synthetic_extra" not in result.source_record.current_values
    assert "PROHIBITED_EXTRA_SENTINEL" not in repr(result)


def test_diagnostics_have_only_the_bounded_fields_and_redact_sentinels() -> None:
    sentinel = "PROHIBITED-ID-CREDENTIAL-HOST-PATH"
    with pytest.raises(CollinContractError) as caught:
        convert({**VALID_ROW, "geo_id": f"{sentinel}\x00"})

    assert {field.name for field in fields(CollinDiagnostic)} == {
        "code",
        "field_name",
        "table_name",
        "source_row_number",
        "schema_fingerprint",
    }
    assert sentinel not in repr(caught.value.diagnostics)
    assert caught.value.diagnostics[0].source_row_number == 1
    assert caught.value.diagnostics[0].schema_fingerprint == COMPATIBLE_SCHEMA_FINGERPRINT


def test_diagnostic_vocabulary_is_closed() -> None:
    assert {code.value for code in CollinDiagnosticCode} == {
        "missing_required_table",
        "unexpected_table",
        "missing_required_column",
        "duplicate_column",
        "column_name_collision",
        "incompatible_physical_type",
        "incompatible_width",
        "incompatible_precision",
        "incompatible_scale",
        "incompatible_nullability",
        "unsupported_schema",
        "invalid_numeric_buffer",
        "invalid_numeric_sign",
        "invalid_numeric_precision",
        "invalid_numeric_scale",
        "numeric_precision_overflow",
        "negative_zero",
        "invalid_prop_id",
        "invalid_geo_id",
        "invalid_property_status",
        "invalid_value_year",
        "invalid_monetary_value",
        "inconsistent_certified_family",
        "extra_columns_present",
    }


def test_existing_collin_registry_surface_is_preserved() -> None:
    assert source_for_county(CountySlug.COLLIN) is COLLIN_SOURCE


def test_collin_records_remain_adapter_local() -> None:
    assert CollinAppraisalSourceRecord.__module__.startswith("property_tax_adapters.")
    assert CollinAppraisalObservation.__module__.startswith("property_tax_adapters.")
    assert SourceNativeValue.__module__.startswith("property_tax_adapters.")


def test_foundation_imports_no_access_network_or_runtime_dependency() -> None:
    module_path = Path(
        "libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not imported_roots & {
        "adodbapi",
        "httpx",
        "pyodbc",
        "requests",
        "subprocess",
        "urllib",
    }


def test_fixture_module_contains_no_owner_or_address_fields() -> None:
    fixture_source = Path(
        "libs/property-tax-adapters/tests/fixtures/collin_synthetic.py"
    ).read_text(encoding="utf-8")

    assert not {
        "owner_name",
        "dba_name",
        "mailing_address",
        "situs_address",
    } & set(fixture_source.casefold().split())


# --------------------------------------------------------------------------
# Shared-contract migration
# --------------------------------------------------------------------------


def test_collin_defines_no_copy_of_a_shared_contract() -> None:
    """The duplication the shared module exists to remove."""

    import ast
    import pathlib

    module = ast.parse(
        pathlib.Path(collin_module.__file__).read_text(encoding="utf-8"),
        type_comments=False,
    )
    defined = {node.name for node in ast.walk(module) if isinstance(node, ast.ClassDef)}
    assert not defined & {
        "SourceNativeValue",
        "SourceProvenance",
        "AppraisalSourceRecord",
        "CollinSourceNativeValue",
        "CollinSourceProvenance",
    }
    # County-native records and observation lineage stay, per issue #43 D7.
    assert {
        "CollinAppraisalSourceRecord",
        "CollinAppraisalObservation",
        "CollinObservationProvenance",
    } <= defined


def test_neither_candidate_identifier_is_promoted_to_an_account_key() -> None:
    """Collin approves no account key, so the shared field stays None.

    `prop_id` must not be declared a unique or canonical account key, and
    `geo_id` must not be equated with it.
    """

    for observation in convert().observations:
        record = convert_collin_observation(observation)
        assert record.source_account_id is None
        assert record.source_native_identifiers["prop_id"] == str(observation.prop_id)
        assert record.source_native_identifiers["geo_id"] == observation.geo_id
        assert (
            record.source_native_identifiers["prop_id"]
            != record.source_native_identifiers["geo_id"]
        )


def test_one_shared_record_per_family_without_collapse() -> None:
    """Two observations of one account stay two records, sharing nothing."""

    current, certified = convert().observations
    first = convert_collin_observation(current)
    second = convert_collin_observation(certified)

    assert first.source_family == "current"
    assert second.source_family == "certified"
    assert first.appraisal_year != second.appraisal_year
    assert first.source_native_identifiers == second.source_native_identifiers
    assert not set(first.source_native_values) & set(second.source_native_values)


def test_declared_precision_and_scale_survive_on_the_shared_value() -> None:
    """Collin's accepted contract requires them preserved; D7 approves them shared."""

    record = convert_collin_observation(convert().observations[0])
    value = record.source_native_values["curr_market"]
    assert value.precision > 0
    assert value.scale >= 0
    # The 17-byte wrapper is binary, so there is no original text.
    assert value.lexical_text is None
    assert value.source_field == "curr_market"


def test_an_absent_value_is_an_omitted_entry() -> None:
    """Not a value that holds no value.

    The previous version guarded with `... or True`, which is unconditional, so
    it asserted nothing about absence at all.  This names the columns that are
    genuinely `None` in the fixture and requires each to be gone.
    """

    observation = convert().observations[0]
    absent = {name for name, value in observation.values.items() if value is None}
    present = {name for name, value in observation.values.items() if value is not None}
    assert absent, "fixture no longer exercises absence"
    assert present, "fixture no longer exercises presence"

    record = convert_collin_observation(observation)

    assert absent & set(record.source_native_values) == set()
    assert present <= set(record.source_native_values)
    assert set(record.source_native_values) == present
    assert all(value is not None for value in record.source_native_values.values())
