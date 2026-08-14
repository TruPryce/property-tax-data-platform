"""Dallas Central Appraisal District source metadata and parser foundation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from io import StringIO
from types import MappingProxyType
from typing import Literal, Never

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

from property_tax_adapters.sources.contracts import (
    AppraisalSourceRecord,
    SourceNativeValue,
    SourceProvenance,
)

DALLAS_JURISDICTION_CODE: Literal["tx-dallas"] = "tx-dallas"
DALLAS_PARSER_CONTRACT_VERSION = 1
SOURCE_NATIVE_CLASSIFICATION: Literal["source-native"] = "source-native"

_ASCII_WHITESPACE = " \t\r\n\v\f"
_UTF8_BOM = b"\xef\xbb\xbf"
_REQUIRED_HEADERS = (
    "ACCOUNT_NUM",
    "APPRAISAL_YR",
    "GIS_PARCEL_ID",
    "TOT_VAL",
)
_ACCOUNT_NUM_PATTERN = re.compile(r"[0-9]{17}\Z")
_APPRAISAL_YEAR_PATTERN = re.compile(r"[0-9]{4}\Z")
_TOT_VAL_PATTERN = re.compile(r"-?[0-9]+(?:\.[0-9]+)?\Z")

DALLAS_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.DALLAS),
    official_url="https://www.dallascad.org/DataProducts.aspx",
    acquisition_method=AcquisitionMethod.BULK_ZIP,
    parser_id="texas.dallas.dcad-delimited-v1",
)


class DallasDiagnosticCode(StrEnum):
    """Closed diagnostic vocabulary for the Dallas parser contract."""

    INVALID_ENCODING = "invalid_encoding"
    UNEXPECTED_BOM = "unexpected_bom"
    BLANK_HEADER = "blank_header"
    MISSING_REQUIRED_HEADER = "missing_required_header"
    DUPLICATE_HEADER = "duplicate_header"
    HEADER_NORMALIZATION_COLLISION = "header_normalization_collision"
    MALFORMED_CSV = "malformed_csv"
    ROW_WIDTH_MISMATCH = "row_width_mismatch"
    INVALID_ACCOUNT_NUM = "invalid_account_num"
    INVALID_APPRAISAL_YEAR = "invalid_appraisal_year"
    INVALID_GIS_PARCEL_ID = "invalid_gis_parcel_id"
    INVALID_TOT_VAL = "invalid_tot_val"
    DUPLICATE_PARENT_KEY = "duplicate_parent_key"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    EXTRA_COLUMNS_PRESENT = "extra_columns_present"


@dataclass(frozen=True, slots=True)
class DallasDiagnostic:
    """Bounded parser diagnostic that never stores source row values."""

    code: DallasDiagnosticCode
    field_name: str | None = None
    source_row_number: int | None = None
    layout_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class SourceNativeDecimal:
    """Dallas decimal text retained alongside its exact parsed value."""

    lexical_text: str
    value: Decimal
    classification: Literal["source-native"] = SOURCE_NATIVE_CLASSIFICATION


@dataclass(frozen=True, slots=True)
class DallasSourceProvenance:
    """Source identity and layout evidence attached to a Dallas-native row.

    County-native, and it stays that way.  The header vectors are a CSV concept
    that a fixed-width county has no use for, so this composes the shared
    provenance rather than subclassing it: Dallas may record more without every
    county inheriting an obligation to record the same.
    """

    source_member_name: str
    release_identifier: str
    observed_headers: tuple[str, ...]
    normalized_headers: tuple[str, ...]
    layout_fingerprint: str
    source_row_number: int
    parser_contract_version: int
    #: A stored field, not a computed view.  The accepted contract requires this
    #: type to *hold* a shared provenance, so it appears in `dataclasses.fields`
    #: and travels with the record rather than being rebuilt on each access.
    shared: SourceProvenance

    def __post_init__(self) -> None:
        # A stored copy can drift from what it copies; a derived one could not.
        # That is the cost of holding it, so the agreement is checked once here
        # rather than trusted.
        mismatched = [
            name
            for name, county, neutral in (
                ("source_member_name", self.source_member_name, self.shared.source_member_name),
                ("release_identifier", self.release_identifier, self.shared.release_identifier),
                ("layout_fingerprint", self.layout_fingerprint, self.shared.layout_fingerprint),
                ("source_row_number", self.source_row_number, self.shared.source_row_number),
                (
                    "parser_contract_version",
                    self.parser_contract_version,
                    self.shared.parser_contract_version,
                ),
                ("observed_headers", self.observed_headers, self.shared.observed_fields),
                ("normalized_headers", self.normalized_headers, self.shared.normalized_fields),
            )
            if county != neutral
        ]
        if mismatched:
            raise ValueError(
                "shared provenance disagrees with Dallas provenance on: " + ", ".join(mismatched)
            )
        if self.shared.jurisdiction_code != DALLAS_JURISDICTION_CODE:
            raise ValueError(f"shared provenance jurisdiction must be {DALLAS_JURISDICTION_CODE!r}")


@dataclass(frozen=True, slots=True)
class DallasAppraisalSourceRecord:
    """Validated Dallas-native appraisal source row."""

    account_num: str
    appraisal_year: int
    gis_parcel_id: str
    tot_val: SourceNativeDecimal
    extras: Mapping[str, str]
    provenance: DallasSourceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "extras", _immutable_mapping(self.extras))


@dataclass(frozen=True, slots=True)
class DallasParseResult:
    """Atomic successful parse result and non-fatal schema warnings."""

    source_records: tuple[DallasAppraisalSourceRecord, ...]
    records: tuple[AppraisalSourceRecord, ...]
    diagnostics: tuple[DallasDiagnostic, ...]


class DallasParserInputError(ValueError):
    """Raised when required caller-supplied source identity is absent."""

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(f"required parser input is absent: {field_name}")


class DallasParseError(ValueError):
    """Raised with bounded diagnostics when parsing fails atomically."""

    def __init__(self, diagnostics: tuple[DallasDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("Dallas source parsing failed")


def parse_dallas_appraisal_csv(
    content: bytes | str,
    *,
    source_member_name: str,
    release_identifier: str,
) -> DallasParseResult:
    """Parse one synthetic-contract Dallas CSV input without partial output."""

    _require_source_identity(source_member_name, release_identifier)
    text = _decode_content(content)
    reader = csv.reader(
        StringIO(text, newline=""),
        delimiter=",",
        quotechar='"',
        doublequote=True,
        strict=True,
    )

    try:
        observed_headers = tuple(next(reader))
    except StopIteration:
        _raise_parse_error(
            DallasDiagnostic(DallasDiagnosticCode.MALFORMED_CSV, source_row_number=1),
            DallasDiagnostic(DallasDiagnosticCode.UNSUPPORTED_LAYOUT, source_row_number=1),
        )
    except csv.Error:
        _raise_parse_error(
            DallasDiagnostic(DallasDiagnosticCode.MALFORMED_CSV, source_row_number=1),
            DallasDiagnostic(DallasDiagnosticCode.UNSUPPORTED_LAYOUT, source_row_number=1),
        )

    normalized_headers = tuple(_normalize_header(header) for header in observed_headers)
    layout_fingerprint = _fingerprint(normalized_headers)
    header_diagnostics = _validate_headers(
        observed_headers,
        normalized_headers,
        layout_fingerprint,
    )
    if header_diagnostics:
        _raise_parse_error(
            *header_diagnostics,
            DallasDiagnostic(
                DallasDiagnosticCode.UNSUPPORTED_LAYOUT,
                source_row_number=1,
                layout_fingerprint=layout_fingerprint,
            ),
        )

    header_indices = {header: index for index, header in enumerate(normalized_headers)}
    extra_headers = tuple(sorted(set(normalized_headers) - set(_REQUIRED_HEADERS)))
    warnings = tuple(
        DallasDiagnostic(
            DallasDiagnosticCode.EXTRA_COLUMNS_PRESENT,
            field_name=header,
            source_row_number=1,
            layout_fingerprint=layout_fingerprint,
        )
        for header in extra_headers
    )

    source_records: list[DallasAppraisalSourceRecord] = []
    parent_keys: set[tuple[str, int]] = set()
    logical_row_number = 2

    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error:
            _raise_parse_error(
                DallasDiagnostic(
                    DallasDiagnosticCode.MALFORMED_CSV,
                    source_row_number=logical_row_number,
                    layout_fingerprint=layout_fingerprint,
                ),
                DallasDiagnostic(
                    DallasDiagnosticCode.UNSUPPORTED_LAYOUT,
                    source_row_number=logical_row_number,
                    layout_fingerprint=layout_fingerprint,
                ),
            )

        if len(row) != len(observed_headers):
            _raise_parse_error(
                DallasDiagnostic(
                    DallasDiagnosticCode.ROW_WIDTH_MISMATCH,
                    source_row_number=logical_row_number,
                    layout_fingerprint=layout_fingerprint,
                ),
                DallasDiagnostic(
                    DallasDiagnosticCode.UNSUPPORTED_LAYOUT,
                    source_row_number=logical_row_number,
                    layout_fingerprint=layout_fingerprint,
                ),
            )

        source_record = _parse_source_record(
            row,
            header_indices=header_indices,
            extra_headers=extra_headers,
            observed_headers=observed_headers,
            normalized_headers=normalized_headers,
            layout_fingerprint=layout_fingerprint,
            source_member_name=source_member_name,
            release_identifier=release_identifier,
            source_row_number=logical_row_number,
        )
        parent_key = (source_record.account_num, source_record.appraisal_year)
        if parent_key in parent_keys:
            _raise_parse_error(
                DallasDiagnostic(
                    DallasDiagnosticCode.DUPLICATE_PARENT_KEY,
                    source_row_number=logical_row_number,
                    layout_fingerprint=layout_fingerprint,
                )
            )
        parent_keys.add(parent_key)
        source_records.append(source_record)
        logical_row_number += 1

    records = tuple(convert_dallas_appraisal_record(record) for record in source_records)
    return DallasParseResult(tuple(source_records), records, warnings)


def convert_dallas_appraisal_record(
    source_record: DallasAppraisalSourceRecord,
) -> AppraisalSourceRecord:
    """Convert a Dallas-native row to the vendor-neutral adapter record."""

    native_values = {
        # `extras` is keyed by normalized header, and the shared contract
        # requires a value's `source_field` to equal its mapping key, so the
        # normalized header is the only choice that keeps the two in agreement.
        # The ordered observed headers stay in provenance, where they were.
        "TOT_VAL": SourceNativeValue(
            source_field="TOT_VAL",
            lexical_text=source_record.tot_val.lexical_text,
            value=source_record.tot_val.value,
        ),
        **{
            header: SourceNativeValue(source_field=header, lexical_text=value, value=value)
            for header, value in sorted(source_record.extras.items())
        },
    }
    return AppraisalSourceRecord(
        jurisdiction_code=DALLAS_JURISDICTION_CODE,
        source_account_id=source_record.account_num,
        appraisal_year=source_record.appraisal_year,
        parcel_reference=source_record.gis_parcel_id,
        # Dallas classifies neither today.  The shared fields are optional so a
        # county that has no family is representable without inventing one.
        source_family=None,
        source_status=None,
        source_native_values=native_values,
        provenance=source_record.provenance.shared,
    )


def _parse_source_record(
    row: list[str],
    *,
    header_indices: Mapping[str, int],
    extra_headers: tuple[str, ...],
    observed_headers: tuple[str, ...],
    normalized_headers: tuple[str, ...],
    layout_fingerprint: str,
    source_member_name: str,
    release_identifier: str,
    source_row_number: int,
) -> DallasAppraisalSourceRecord:
    account_num = row[header_indices["ACCOUNT_NUM"]]
    appraisal_year_text = row[header_indices["APPRAISAL_YR"]]
    gis_parcel_id = row[header_indices["GIS_PARCEL_ID"]].strip(_ASCII_WHITESPACE)
    tot_val_text = row[header_indices["TOT_VAL"]]

    diagnostics: list[DallasDiagnostic] = []
    if _ACCOUNT_NUM_PATTERN.fullmatch(account_num) is None:
        diagnostics.append(
            _field_diagnostic(
                DallasDiagnosticCode.INVALID_ACCOUNT_NUM,
                "ACCOUNT_NUM",
                source_row_number,
                layout_fingerprint,
            )
        )

    appraisal_year: int | None = None
    if _APPRAISAL_YEAR_PATTERN.fullmatch(appraisal_year_text) is not None:
        appraisal_year = int(appraisal_year_text)
    if appraisal_year is None or not 1900 <= appraisal_year <= 2100:
        diagnostics.append(
            _field_diagnostic(
                DallasDiagnosticCode.INVALID_APPRAISAL_YEAR,
                "APPRAISAL_YR",
                source_row_number,
                layout_fingerprint,
            )
        )

    if not gis_parcel_id:
        diagnostics.append(
            _field_diagnostic(
                DallasDiagnosticCode.INVALID_GIS_PARCEL_ID,
                "GIS_PARCEL_ID",
                source_row_number,
                layout_fingerprint,
            )
        )

    tot_val: Decimal | None = None
    if _TOT_VAL_PATTERN.fullmatch(tot_val_text) is not None:
        try:
            tot_val = Decimal(tot_val_text)
        except InvalidOperation:
            pass
    if tot_val is None:
        diagnostics.append(
            _field_diagnostic(
                DallasDiagnosticCode.INVALID_TOT_VAL,
                "TOT_VAL",
                source_row_number,
                layout_fingerprint,
            )
        )

    if diagnostics:
        _raise_parse_error(*diagnostics)

    assert appraisal_year is not None
    assert tot_val is not None
    provenance = DallasSourceProvenance(
        source_member_name=source_member_name,
        release_identifier=release_identifier,
        observed_headers=observed_headers,
        normalized_headers=normalized_headers,
        layout_fingerprint=layout_fingerprint,
        source_row_number=source_row_number,
        parser_contract_version=DALLAS_PARSER_CONTRACT_VERSION,
        shared=SourceProvenance(
            jurisdiction_code=DALLAS_JURISDICTION_CODE,
            release_identifier=release_identifier,
            source_member_name=source_member_name,
            source_row_number=source_row_number,
            parser_contract_version=DALLAS_PARSER_CONTRACT_VERSION,
            layout_fingerprint=layout_fingerprint,
            observed_fields=observed_headers,
            normalized_fields=normalized_headers,
        ),
    )
    return DallasAppraisalSourceRecord(
        account_num=account_num,
        appraisal_year=appraisal_year,
        gis_parcel_id=gis_parcel_id,
        tot_val=SourceNativeDecimal(lexical_text=tot_val_text, value=tot_val),
        extras={header: row[header_indices[header]] for header in extra_headers},
        provenance=provenance,
    )


def _require_source_identity(source_member_name: str, release_identifier: str) -> None:
    if not source_member_name:
        raise DallasParserInputError("source_member_name")
    if not release_identifier:
        raise DallasParserInputError("release_identifier")


def _decode_content(content: bytes | str) -> str:
    if isinstance(content, bytes):
        encoded = content
        if encoded.startswith(_UTF8_BOM):
            encoded = encoded[len(_UTF8_BOM) :]
        if _UTF8_BOM in encoded:
            _raise_parse_error(DallasDiagnostic(DallasDiagnosticCode.UNEXPECTED_BOM))
        try:
            return encoded.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _raise_parse_error(DallasDiagnostic(DallasDiagnosticCode.INVALID_ENCODING))

    text = content
    if text.startswith("\ufeff"):
        text = text[1:]
    if "\ufeff" in text:
        _raise_parse_error(DallasDiagnostic(DallasDiagnosticCode.UNEXPECTED_BOM))
    return text


def _normalize_header(header: str) -> str:
    return header.strip(_ASCII_WHITESPACE).upper()


def _fingerprint(normalized_headers: tuple[str, ...]) -> str:
    payload = json.dumps(
        {
            "headers": sorted(set(normalized_headers)),
            "parser_contract_version": DALLAS_PARSER_CONTRACT_VERSION,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_headers(
    observed_headers: tuple[str, ...],
    normalized_headers: tuple[str, ...],
    layout_fingerprint: str,
) -> tuple[DallasDiagnostic, ...]:
    diagnostics: list[DallasDiagnostic] = []
    seen_observed: set[str] = set()
    observed_by_normalized: dict[str, set[str]] = {}

    if not observed_headers:
        diagnostics.append(
            _field_diagnostic(
                DallasDiagnosticCode.BLANK_HEADER,
                None,
                1,
                layout_fingerprint,
            )
        )

    for observed, normalized in zip(observed_headers, normalized_headers, strict=True):
        if not normalized:
            diagnostics.append(
                _field_diagnostic(
                    DallasDiagnosticCode.BLANK_HEADER,
                    None,
                    1,
                    layout_fingerprint,
                )
            )
        if observed in seen_observed:
            diagnostics.append(
                _field_diagnostic(
                    DallasDiagnosticCode.DUPLICATE_HEADER,
                    normalized or None,
                    1,
                    layout_fingerprint,
                )
            )
        elif normalized in observed_by_normalized:
            diagnostics.append(
                _field_diagnostic(
                    DallasDiagnosticCode.HEADER_NORMALIZATION_COLLISION,
                    normalized or None,
                    1,
                    layout_fingerprint,
                )
            )
        seen_observed.add(observed)
        observed_by_normalized.setdefault(normalized, set()).add(observed)

    normalized_set = set(normalized_headers)
    for required_header in _REQUIRED_HEADERS:
        if required_header not in normalized_set:
            diagnostics.append(
                _field_diagnostic(
                    DallasDiagnosticCode.MISSING_REQUIRED_HEADER,
                    required_header,
                    1,
                    layout_fingerprint,
                )
            )
    return _deduplicate_diagnostics(diagnostics)


def _field_diagnostic(
    code: DallasDiagnosticCode,
    field_name: str | None,
    source_row_number: int,
    layout_fingerprint: str,
) -> DallasDiagnostic:
    return DallasDiagnostic(
        code,
        field_name=field_name,
        source_row_number=source_row_number,
        layout_fingerprint=layout_fingerprint,
    )


def _deduplicate_diagnostics(
    diagnostics: list[DallasDiagnostic],
) -> tuple[DallasDiagnostic, ...]:
    return tuple(dict.fromkeys(diagnostics))


def _immutable_mapping[Value](values: Mapping[str, Value]) -> Mapping[str, Value]:
    return MappingProxyType(dict(values))


def _raise_parse_error(*diagnostics: DallasDiagnostic) -> Never:
    raise DallasParseError(tuple(diagnostics))


__all__ = [
    "DALLAS_JURISDICTION_CODE",
    "DALLAS_PARSER_CONTRACT_VERSION",
    "DALLAS_SOURCE",
    "AppraisalSourceRecord",
    "DallasAppraisalSourceRecord",
    "DallasDiagnostic",
    "DallasDiagnosticCode",
    "DallasParseError",
    "DallasParseResult",
    "DallasParserInputError",
    "DallasSourceProvenance",
    "SourceNativeDecimal",
    "SourceNativeValue",
    "SourceProvenance",
    "convert_dallas_appraisal_record",
    "parse_dallas_appraisal_csv",
]
