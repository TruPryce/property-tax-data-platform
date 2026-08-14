"""Collin CAD metadata and synthetic Access decoder foundation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Never, cast

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

from property_tax_adapters.sources.contracts import (
    AppraisalSourceRecord,
    SourceNativeValue,
    SourceProvenance,
)

COLLIN_JURISDICTION_CODE = "tx-collin"
COLLIN_PARSER_CONTRACT_VERSION = 1
COLLIN_TABLE_NAME = "AD_Public"
COLLIN_NUMERIC_BUFFER_WIDTH = 17
COLLIN_SOURCE_NATIVE_CLASSIFICATION: Literal["source-native"] = "source-native"

type CollinPropertyStatus = Literal["Preliminary", "InProgress", "Certified"]
type CollinSourceFamily = Literal["current", "certified"]

CURRENT_VALUE_COLUMNS = (
    "curr_imprv_hstd_val",
    "curr_imprv_non_hstd_val",
    "curr_land_hstd_val",
    "curr_land_non_hstd_val",
    "curr_ag_use_val",
    "curr_ag_market",
    "curr_market",
    "curr_ag_loss",
    "curr_appraised_val",
    "curr_ten_percent_cap",
    "curr_assessed_val",
)
CERTIFIED_VALUE_COLUMNS = (
    "cert_imprv_hstd_val",
    "cert_imprv_non_hstd_val",
    "cert_land_hstd_val",
    "cert_land_non_hstd_val",
    "cert_ag_use_val",
    "cert_ag_market",
    "cert_market",
    "cert_ag_loss",
    "cert_appraised_val",
    "cert_ten_percent_cap",
    "cert_assessed_val",
)
REQUIRED_COLUMN_NAMES = (
    "prop_id",
    "geo_id",
    "property_status",
    "curr_val_yr",
    "cert_val_yr",
    *CURRENT_VALUE_COLUMNS,
    *CERTIFIED_VALUE_COLUMNS,
)

COLLIN_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.COLLIN),
    official_url="https://collincad.org/open-data-portal/",
    acquisition_method=AcquisitionMethod.OPEN_DATA_API,
    parser_id="texas.collin.open-data-v1",
)


class CollinAccessPhysicalType(StrEnum):
    """Physical types accepted by the bounded synthetic schema contract."""

    LONG = "LONG"
    TEXT = "TEXT"
    NUMERIC = "NUMERIC"


class CollinDiagnosticCode(StrEnum):
    """Closed diagnostic vocabulary for the Collin foundation."""

    MISSING_REQUIRED_TABLE = "missing_required_table"
    UNEXPECTED_TABLE = "unexpected_table"
    MISSING_REQUIRED_COLUMN = "missing_required_column"
    DUPLICATE_COLUMN = "duplicate_column"
    COLUMN_NAME_COLLISION = "column_name_collision"
    INCOMPATIBLE_PHYSICAL_TYPE = "incompatible_physical_type"
    INCOMPATIBLE_WIDTH = "incompatible_width"
    INCOMPATIBLE_PRECISION = "incompatible_precision"
    INCOMPATIBLE_SCALE = "incompatible_scale"
    INCOMPATIBLE_NULLABILITY = "incompatible_nullability"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    INVALID_NUMERIC_BUFFER = "invalid_numeric_buffer"
    INVALID_NUMERIC_SIGN = "invalid_numeric_sign"
    INVALID_NUMERIC_PRECISION = "invalid_numeric_precision"
    INVALID_NUMERIC_SCALE = "invalid_numeric_scale"
    NUMERIC_PRECISION_OVERFLOW = "numeric_precision_overflow"
    NEGATIVE_ZERO = "negative_zero"
    INVALID_PROP_ID = "invalid_prop_id"
    INVALID_GEO_ID = "invalid_geo_id"
    INVALID_PROPERTY_STATUS = "invalid_property_status"
    INVALID_VALUE_YEAR = "invalid_value_year"
    INVALID_MONETARY_VALUE = "invalid_monetary_value"
    INCONSISTENT_CERTIFIED_FAMILY = "inconsistent_certified_family"
    EXTRA_COLUMNS_PRESENT = "extra_columns_present"


@dataclass(frozen=True, slots=True)
class CollinDiagnostic:
    """Bounded diagnostic that never retains source values."""

    code: CollinDiagnosticCode
    field_name: str | None = None
    table_name: str | None = None
    source_row_number: int | None = None
    schema_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class CollinColumnDescriptor:
    """One observed Access column descriptor."""

    name: str
    physical_type: CollinAccessPhysicalType | str
    width: int | None
    precision: int | None
    scale: int | None
    nullable: bool


@dataclass(frozen=True, slots=True)
class CollinDecodedNumeric:
    """Exact decoded coefficient with its external metadata."""

    value: Decimal
    precision: int
    scale: int


@dataclass(frozen=True, slots=True)
class CollinValidatedSchema:
    """Compatible required bindings plus fingerprint provenance and warnings."""

    table_name: str
    schema_fingerprint: str
    required_columns: Mapping[str, CollinColumnDescriptor]
    observed_columns: tuple[CollinColumnDescriptor, ...]
    diagnostics: tuple[CollinDiagnostic, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_columns", _immutable_mapping(self.required_columns))


@dataclass(frozen=True, slots=True)
class CollinObservationProvenance:
    """Family-specific provenance retained by one logical observation."""

    shared: SourceProvenance
    source_family: CollinSourceFamily
    source_year: int
    property_status: CollinPropertyStatus
    value_source_columns: tuple[str, ...]

    @property
    def schema_fingerprint(self) -> str:
        """Collin name for what the shared contract calls a layout fingerprint.

        The digest is the same digest; only the vocabulary differs, so it maps
        onto `layout_fingerprint` rather than becoming a second field.
        """

        return self.shared.layout_fingerprint


@dataclass(frozen=True, slots=True)
class CollinAppraisalSourceRecord:
    """One validated physical Collin row preserved without deduplication."""

    prop_id: int
    geo_id: str
    property_status: CollinPropertyStatus
    current_value_year: int
    certified_value_year: int | None
    current_values: Mapping[str, SourceNativeValue | None]
    certified_values: Mapping[str, SourceNativeValue | None]
    provenance: SourceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "current_values", _immutable_mapping(self.current_values))
        object.__setattr__(self, "certified_values", _immutable_mapping(self.certified_values))


@dataclass(frozen=True, slots=True)
class CollinAppraisalObservation:
    """One immutable current or certified logical source observation."""

    prop_id: int
    geo_id: str
    source_family: CollinSourceFamily
    source_year: int
    classification: CollinPropertyStatus
    values: Mapping[str, SourceNativeValue | None]
    provenance: CollinObservationProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", _immutable_mapping(self.values))


@dataclass(frozen=True, slots=True)
class CollinRowConversionResult:
    """Atomic physical record, logical observations, and schema warnings."""

    source_record: CollinAppraisalSourceRecord
    observations: tuple[CollinAppraisalObservation, ...]
    diagnostics: tuple[CollinDiagnostic, ...]


class CollinContractError(ValueError):
    """Raised atomically with privacy-safe Collin diagnostics."""

    def __init__(self, diagnostics: tuple[CollinDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("Collin source contract validation failed")


class CollinParserInputError(ValueError):
    """Raised when trusted caller-supplied provenance is invalid."""

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(f"required Collin parser input is invalid: {field_name}")


def decode_collin_numeric(
    buffer: object,
    *,
    precision: int | None,
    scale: int | None,
    field_name: str | None = None,
    source_row_number: int | None = None,
    schema_fingerprint: str | None = None,
) -> CollinDecodedNumeric:
    """Decode the approved reader-specific 17-byte wrapper exactly."""

    if not isinstance(buffer, bytes) or len(buffer) != COLLIN_NUMERIC_BUFFER_WIDTH:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.INVALID_NUMERIC_BUFFER,
                field_name=field_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema_fingerprint,
            )
        )
    sign = buffer[0]
    if sign not in (0x00, 0x01):
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.INVALID_NUMERIC_SIGN,
                field_name=field_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema_fingerprint,
            )
        )
    if type(precision) is not int or not 1 <= precision <= 28:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.INVALID_NUMERIC_PRECISION,
                field_name=field_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema_fingerprint,
            )
        )
    if type(scale) is not int or not 0 <= scale <= precision:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.INVALID_NUMERIC_SCALE,
                field_name=field_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema_fingerprint,
            )
        )

    magnitude = 0
    for offset in range(1, COLLIN_NUMERIC_BUFFER_WIDTH, 4):
        magnitude = (magnitude << 32) | int.from_bytes(
            buffer[offset : offset + 4], "little", signed=False
        )
    if sign == 0x01 and magnitude == 0:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.NEGATIVE_ZERO,
                field_name=field_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema_fingerprint,
            )
        )
    if len(str(magnitude)) > precision:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.NUMERIC_PRECISION_OVERFLOW,
                field_name=field_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema_fingerprint,
            )
        )

    with localcontext() as context:
        context.prec = 28
        value = Decimal(magnitude).scaleb(-scale)
        if sign == 0x01:
            value = -value
    return CollinDecodedNumeric(value=value, precision=precision, scale=scale)


def fingerprint_collin_schema(columns: Sequence[CollinColumnDescriptor]) -> str:
    """Return canonical fingerprint provenance for one observed AD_Public layout."""

    payload = json.dumps(
        {
            "columns": [
                {
                    "name": column.name,
                    "nullable": column.nullable,
                    "physical_type": str(column.physical_type),
                    "precision": column.precision,
                    "scale": column.scale,
                    "width": column.width,
                }
                for column in sorted(columns, key=lambda item: item.name)
            ],
            "parser_contract_version": COLLIN_PARSER_CONTRACT_VERSION,
            "table_name": COLLIN_TABLE_NAME,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_collin_schema(
    tables: Mapping[str, Sequence[CollinColumnDescriptor]],
) -> CollinValidatedSchema:
    """Validate the bounded AD_Public metadata before any row is read."""

    observed_columns = tuple(tables.get(COLLIN_TABLE_NAME, ()))
    schema_fingerprint = fingerprint_collin_schema(observed_columns)
    diagnostics: list[CollinDiagnostic] = []

    if COLLIN_TABLE_NAME not in tables:
        diagnostics.append(
            _diagnostic(
                CollinDiagnosticCode.MISSING_REQUIRED_TABLE,
                table_name=COLLIN_TABLE_NAME,
                schema_fingerprint=schema_fingerprint,
            )
        )
    for table_name in sorted(set(tables) - {COLLIN_TABLE_NAME}):
        diagnostics.append(
            _diagnostic(
                CollinDiagnosticCode.UNEXPECTED_TABLE,
                table_name=table_name,
                schema_fingerprint=schema_fingerprint,
            )
        )

    columns_by_name: dict[str, list[CollinColumnDescriptor]] = {}
    columns_by_folded_name: dict[str, set[str]] = {}
    for column in observed_columns:
        columns_by_name.setdefault(column.name, []).append(column)
        columns_by_folded_name.setdefault(_ascii_casefold(column.name), set()).add(column.name)

    for name in sorted(columns_by_name):
        if len(columns_by_name[name]) > 1:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.DUPLICATE_COLUMN,
                    field_name=name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
    for names in sorted(columns_by_folded_name.values(), key=lambda values: sorted(values)):
        if len(names) > 1:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.COLUMN_NAME_COLLISION,
                    field_name=sorted(names)[0],
                    schema_fingerprint=schema_fingerprint,
                )
            )

    required_bindings: dict[str, CollinColumnDescriptor] = {}
    for required_name in REQUIRED_COLUMN_NAMES:
        matches = columns_by_name.get(required_name, [])
        if not matches:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.MISSING_REQUIRED_COLUMN,
                    field_name=required_name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
            continue
        descriptor = matches[0]
        required_bindings[required_name] = descriptor
        diagnostics.extend(_descriptor_diagnostics(descriptor, schema_fingerprint))

    for column in observed_columns:
        if not column.name.isascii():
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.UNSUPPORTED_SCHEMA,
                    field_name=column.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )

    fatal_diagnostics = _deduplicate_diagnostics(diagnostics)
    if fatal_diagnostics:
        if not any(
            diagnostic.code is CollinDiagnosticCode.UNSUPPORTED_SCHEMA
            for diagnostic in fatal_diagnostics
        ):
            fatal_diagnostics = (
                *fatal_diagnostics,
                _diagnostic(
                    CollinDiagnosticCode.UNSUPPORTED_SCHEMA,
                    table_name=COLLIN_TABLE_NAME,
                    schema_fingerprint=schema_fingerprint,
                ),
            )
        raise CollinContractError(fatal_diagnostics)

    warnings = tuple(
        _diagnostic(
            CollinDiagnosticCode.EXTRA_COLUMNS_PRESENT,
            field_name=column.name,
            schema_fingerprint=schema_fingerprint,
        )
        for column in sorted(observed_columns, key=lambda item: item.name)
        if column.name not in REQUIRED_COLUMN_NAMES
    )
    return CollinValidatedSchema(
        table_name=COLLIN_TABLE_NAME,
        schema_fingerprint=schema_fingerprint,
        required_columns=required_bindings,
        observed_columns=observed_columns,
        diagnostics=warnings,
    )


def convert_collin_row(
    row: Mapping[str, object],
    *,
    schema: CollinValidatedSchema,
    source_member_name: str,
    release_identifier: str,
    source_row_number: int,
) -> CollinRowConversionResult:
    """Convert one synthetic decoded AD_Public row without reading extra values."""

    _require_parser_input(source_member_name, "source_member_name")
    _require_parser_input(release_identifier, "release_identifier")
    if type(source_row_number) is not int or source_row_number < 1:
        raise CollinParserInputError("source_row_number")
    if schema.table_name != COLLIN_TABLE_NAME:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.UNSUPPORTED_SCHEMA,
                table_name=schema.table_name,
                source_row_number=source_row_number,
                schema_fingerprint=schema.schema_fingerprint,
            )
        )

    prop_id = _validate_prop_id(
        _row_value(row, "prop_id", schema, source_row_number), schema, source_row_number
    )
    geo_id = _validate_geo_id(
        _row_value(row, "geo_id", schema, source_row_number), schema, source_row_number
    )
    property_status = _validate_property_status(
        _row_value(row, "property_status", schema, source_row_number),
        schema,
        source_row_number,
    )
    current_value_year = _decode_value_year(
        _row_value(row, "curr_val_yr", schema, source_row_number),
        schema.required_columns["curr_val_yr"],
        schema,
        source_row_number,
    )
    certified_year_value = _row_value(row, "cert_val_yr", schema, source_row_number)
    certified_value_year = (
        None
        if certified_year_value is None
        else _decode_value_year(
            certified_year_value,
            schema.required_columns["cert_val_yr"],
            schema,
            source_row_number,
        )
    )

    current_values = {
        column: _decode_monetary_value(
            _row_value(row, column, schema, source_row_number),
            schema.required_columns[column],
            schema,
            source_row_number,
        )
        for column in CURRENT_VALUE_COLUMNS
    }
    certified_values = {
        column: _decode_monetary_value(
            _row_value(row, column, schema, source_row_number),
            schema.required_columns[column],
            schema,
            source_row_number,
        )
        for column in CERTIFIED_VALUE_COLUMNS
    }
    has_certified_values = any(value is not None for value in certified_values.values())
    if certified_value_year is None and has_certified_values:
        _raise_contract_error(
            _diagnostic(
                CollinDiagnosticCode.INCONSISTENT_CERTIFIED_FAMILY,
                field_name="cert_val_yr",
                source_row_number=source_row_number,
                schema_fingerprint=schema.schema_fingerprint,
            )
        )

    source_provenance = SourceProvenance(
        jurisdiction_code=COLLIN_JURISDICTION_CODE,
        source_member_name=source_member_name,
        release_identifier=release_identifier,
        table_name=COLLIN_TABLE_NAME,
        source_row_number=source_row_number,
        parser_contract_version=COLLIN_PARSER_CONTRACT_VERSION,
        layout_fingerprint=schema.schema_fingerprint,
    )
    source_record = CollinAppraisalSourceRecord(
        prop_id=prop_id,
        geo_id=geo_id,
        property_status=property_status,
        current_value_year=current_value_year,
        certified_value_year=certified_value_year,
        current_values=current_values,
        certified_values=certified_values,
        provenance=source_provenance,
    )
    observations = [
        _build_observation(
            source_record,
            source_family="current",
            source_year=current_value_year,
            classification=property_status,
            values=current_values,
        )
    ]
    if certified_value_year is not None and has_certified_values:
        observations.append(
            _build_observation(
                source_record,
                source_family="certified",
                source_year=certified_value_year,
                classification="Certified",
                values=certified_values,
            )
        )
    return CollinRowConversionResult(
        source_record=source_record,
        observations=tuple(observations),
        diagnostics=schema.diagnostics,
    )


def _build_observation(
    source_record: CollinAppraisalSourceRecord,
    *,
    source_family: CollinSourceFamily,
    source_year: int,
    classification: CollinPropertyStatus,
    values: Mapping[str, SourceNativeValue | None],
) -> CollinAppraisalObservation:
    provenance = source_record.provenance
    return CollinAppraisalObservation(
        prop_id=source_record.prop_id,
        geo_id=source_record.geo_id,
        source_family=source_family,
        source_year=source_year,
        classification=classification,
        values=values,
        provenance=CollinObservationProvenance(
            shared=provenance,
            source_family=source_family,
            source_year=source_year,
            property_status=source_record.property_status,
            value_source_columns=tuple(
                column for column, value in values.items() if value is not None
            ),
        ),
    )


def convert_collin_observation(
    observation: CollinAppraisalObservation,
) -> AppraisalSourceRecord:
    """Convert one Collin observation to one vendor-neutral record.

    One observation in, one record out.  Current and certified never merge, and
    no value is copied between them, because the accepted Collin contract
    forbids filling a missing value from the other family.

    `source_account_id` is `None` on purpose.  Collin approves no account key:
    `prop_id` "MUST NOT be declared a unique or canonical account key" and
    `geo_id` "MUST NOT be equated with `prop_id`".  Both are preserved as
    source-native identifiers under their exact source names, as two distinct
    entries asserting no equivalence between them.
    """

    provenance = observation.provenance
    shared = provenance.shared
    return AppraisalSourceRecord(
        jurisdiction_code=COLLIN_JURISDICTION_CODE,
        source_account_id=None,
        source_native_identifiers={
            "prop_id": str(observation.prop_id),
            "geo_id": observation.geo_id,
        },
        appraisal_year=observation.source_year,
        source_family=observation.source_family,
        source_status=observation.classification,
        parcel_reference=None,
        # An absent value is an omitted entry.  A value holding no value would
        # claim the column was observed empty, which is a different fact.
        source_native_values={
            column: value for column, value in observation.values.items() if value is not None
        },
        provenance=SourceProvenance(
            jurisdiction_code=shared.jurisdiction_code,
            release_identifier=shared.release_identifier,
            source_member_name=shared.source_member_name,
            source_row_number=shared.source_row_number,
            parser_contract_version=shared.parser_contract_version,
            layout_fingerprint=shared.layout_fingerprint,
            table_name=shared.table_name,
            source_family=provenance.source_family,
            source_year=provenance.source_year,
            source_status=provenance.property_status,
        ),
    )


def _validate_prop_id(
    value: object,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_PROP_ID, "prop_id", schema, source_row_number
        )
    return value


def _validate_geo_id(
    value: object,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> str:
    if not isinstance(value, str):
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_GEO_ID, "geo_id", schema, source_row_number
        )
    normalized = value.strip(" \t\r\n\v\f")
    invalid_character = any(
        ord(character) < 0x20 or 0xD800 <= ord(character) <= 0xDFFF for character in normalized
    )
    if not 1 <= len(normalized) <= 255 or invalid_character:
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_GEO_ID, "geo_id", schema, source_row_number
        )
    return normalized


def _validate_property_status(
    value: object,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> CollinPropertyStatus:
    normalized = value.strip(" \t\r\n\v\f") if isinstance(value, str) else None
    if normalized not in {"Preliminary", "InProgress", "Certified"}:
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_PROPERTY_STATUS,
            "property_status",
            schema,
            source_row_number,
        )
    return cast(CollinPropertyStatus, normalized)


def _decode_value_year(
    value: object,
    descriptor: CollinColumnDescriptor,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> int:
    decoded = decode_collin_numeric(
        value,
        precision=descriptor.precision,
        scale=descriptor.scale,
        field_name=descriptor.name,
        source_row_number=source_row_number,
        schema_fingerprint=schema.schema_fingerprint,
    )
    if decoded.scale != 0 or decoded.value != decoded.value.to_integral_value():
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_VALUE_YEAR,
            descriptor.name,
            schema,
            source_row_number,
        )
    year = int(decoded.value)
    if not 1900 <= year <= 2100:
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_VALUE_YEAR,
            descriptor.name,
            schema,
            source_row_number,
        )
    return year


def _decode_monetary_value(
    value: object,
    descriptor: CollinColumnDescriptor,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> SourceNativeValue | None:
    if value is None:
        return None
    decoded = decode_collin_numeric(
        value,
        precision=descriptor.precision,
        scale=descriptor.scale,
        field_name=descriptor.name,
        source_row_number=source_row_number,
        schema_fingerprint=schema.schema_fingerprint,
    )
    if not Decimal(0) <= decoded.value <= Decimal(10**28 - 1):
        _raise_row_diagnostic(
            CollinDiagnosticCode.INVALID_MONETARY_VALUE,
            descriptor.name,
            schema,
            source_row_number,
        )
    return SourceNativeValue(
        source_field=descriptor.name,
        value=decoded.value,
        # The approved 17-byte wrapper is binary; there is no original text to
        # preserve, and `""` would claim an empty text was observed.
        lexical_text=None,
        precision=decoded.precision,
        scale=decoded.scale,
    )


def _row_value(
    row: Mapping[str, object],
    field_name: str,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> object:
    try:
        return row[field_name]
    except KeyError:
        _raise_row_diagnostic(
            CollinDiagnosticCode.UNSUPPORTED_SCHEMA,
            field_name,
            schema,
            source_row_number,
        )


def _raise_row_diagnostic(
    code: CollinDiagnosticCode,
    field_name: str,
    schema: CollinValidatedSchema,
    source_row_number: int,
) -> Never:
    _raise_contract_error(
        _diagnostic(
            code,
            field_name=field_name,
            source_row_number=source_row_number,
            schema_fingerprint=schema.schema_fingerprint,
        )
    )


def _require_parser_input(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip(" \t\r\n\v\f"):
        raise CollinParserInputError(field_name)


def _descriptor_diagnostics(
    descriptor: CollinColumnDescriptor,
    schema_fingerprint: str,
) -> tuple[CollinDiagnostic, ...]:
    diagnostics: list[CollinDiagnostic] = []
    if descriptor.name == "prop_id":
        expected_type = CollinAccessPhysicalType.LONG
    elif descriptor.name in {"geo_id", "property_status"}:
        expected_type = CollinAccessPhysicalType.TEXT
    else:
        expected_type = CollinAccessPhysicalType.NUMERIC

    if str(descriptor.physical_type) != expected_type.value:
        diagnostics.append(
            _diagnostic(
                CollinDiagnosticCode.INCOMPATIBLE_PHYSICAL_TYPE,
                field_name=descriptor.name,
                schema_fingerprint=schema_fingerprint,
            )
        )
        return tuple(diagnostics)

    if expected_type is CollinAccessPhysicalType.LONG:
        if type(descriptor.width) is not int or descriptor.width != 4:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_WIDTH,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
        if descriptor.precision is not None:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_PRECISION,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
        if descriptor.scale is not None:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_SCALE,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
    elif expected_type is CollinAccessPhysicalType.TEXT:
        if type(descriptor.width) is not int or descriptor.width <= 0 or descriptor.width > 255:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_WIDTH,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
        if descriptor.precision is not None:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_PRECISION,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
        if descriptor.scale is not None:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_SCALE,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
    else:
        if type(descriptor.width) is not int or descriptor.width != 17:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_WIDTH,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
        if type(descriptor.precision) is not int or not 1 <= descriptor.precision <= 28:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_PRECISION,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )
        if descriptor.name in {"curr_val_yr", "cert_val_yr"}:
            valid_scale = (
                type(descriptor.scale) is int
                and type(descriptor.precision) is int
                and descriptor.scale == 0
                and descriptor.scale <= descriptor.precision
            )
        else:
            valid_scale = (
                type(descriptor.scale) is int
                and type(descriptor.precision) is int
                and 0 <= descriptor.scale <= 4
                and descriptor.scale <= descriptor.precision
            )
        if not valid_scale:
            diagnostics.append(
                _diagnostic(
                    CollinDiagnosticCode.INCOMPATIBLE_SCALE,
                    field_name=descriptor.name,
                    schema_fingerprint=schema_fingerprint,
                )
            )

    expected_nullable = descriptor.name not in {
        "prop_id",
        "geo_id",
        "property_status",
        "curr_val_yr",
    }
    if type(descriptor.nullable) is not bool or descriptor.nullable is not expected_nullable:
        diagnostics.append(
            _diagnostic(
                CollinDiagnosticCode.INCOMPATIBLE_NULLABILITY,
                field_name=descriptor.name,
                schema_fingerprint=schema_fingerprint,
            )
        )
    return tuple(diagnostics)


def _diagnostic(
    code: CollinDiagnosticCode,
    *,
    field_name: str | None = None,
    table_name: str | None = None,
    source_row_number: int | None = None,
    schema_fingerprint: str | None = None,
) -> CollinDiagnostic:
    return CollinDiagnostic(
        code=code,
        field_name=field_name,
        table_name=table_name,
        source_row_number=source_row_number,
        schema_fingerprint=schema_fingerprint,
    )


def _ascii_casefold(value: str) -> str:
    return value.translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )


def _deduplicate_diagnostics(
    diagnostics: Sequence[CollinDiagnostic],
) -> tuple[CollinDiagnostic, ...]:
    return tuple(dict.fromkeys(diagnostics))


def _immutable_mapping[Value](values: Mapping[str, Value]) -> Mapping[str, Value]:
    return MappingProxyType(dict(values))


def _raise_contract_error(*diagnostics: CollinDiagnostic) -> Never:
    raise CollinContractError(tuple(diagnostics))


__all__ = [
    "CERTIFIED_VALUE_COLUMNS",
    "COLLIN_NUMERIC_BUFFER_WIDTH",
    "COLLIN_PARSER_CONTRACT_VERSION",
    "COLLIN_SOURCE",
    "COLLIN_SOURCE_NATIVE_CLASSIFICATION",
    "COLLIN_TABLE_NAME",
    "CURRENT_VALUE_COLUMNS",
    "REQUIRED_COLUMN_NAMES",
    "CollinAccessPhysicalType",
    "CollinAppraisalObservation",
    "CollinAppraisalSourceRecord",
    "convert_collin_observation",
    "CollinColumnDescriptor",
    "CollinContractError",
    "CollinDecodedNumeric",
    "CollinDiagnostic",
    "CollinDiagnosticCode",
    "CollinObservationProvenance",
    "CollinParserInputError",
    "CollinPropertyStatus",
    "CollinRowConversionResult",
    "CollinSourceFamily",
    "CollinValidatedSchema",
    "AppraisalSourceRecord",
    "SourceNativeValue",
    "SourceProvenance",
    "convert_collin_row",
    "decode_collin_numeric",
    "fingerprint_collin_schema",
    "validate_collin_schema",
]
