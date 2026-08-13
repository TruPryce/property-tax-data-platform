"""Tarrant Appraisal District source metadata and certified-core parser foundation.

This is the synthetic foundation accepted in OpenSpec change
``add-tarrant-cad-parser-foundation``.  It parses one already-selected
certified-core text member and makes no claim of live-release compatibility.

The public surface is deliberately a **validator**, not a row producer.  The
approved Tarrant-native record holds shared ``SourceNativeValue`` entries owned
by Issue #43, and that contract does not exist yet; returning rows today would
mean inventing a county-local stand-in, which decision D5 forbids.  So
:func:`validate_certified_member` returns a bounded
:class:`TarrantValidationReport` of counts, diagnostics, fingerprint, and
observed headers, and carries no field values at all.  Row materialization
arrives with the record layer once Issue #43 lands, reusing this validation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final, Literal

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

TARRANT_JURISDICTION_CODE: Literal["tx-tarrant"] = "tx-tarrant"
TARRANT_PARSER_CONTRACT_VERSION: Final = 1
TARRANT_SOURCE_FAMILY: Final = "certified-core"
TARRANT_SOURCE_STATUS: Final = "certified"

#: Identifies the delimiter and quote behaviour inside the layout fingerprint:
#: delimiter ``|``, quote ``"``, doubled ``""`` as a literal quote, no escape
#: character, and no multiline record.
TARRANT_DIALECT: Final = "pipe-delimited-double-quote-v1"
TARRANT_ENCODING: Final = "iso-8859-1"

TARRANT_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.TARRANT),
    official_url="https://www.tad.org/",
    acquisition_method=AcquisitionMethod.FIXED_WIDTH,
    parser_id="texas.tarrant.fixed-width-v1",
)

#: D1: the required foundation headers, bound by untrimmed exact name.  Order is
#: irrelevant because binding is by name; additional headers are metadata-only.
TARRANT_REQUIRED_HEADERS: Final[tuple[str, ...]] = (
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

#: D4: header names whose values are default-deny.  The names may appear in
#: layout provenance; the values never enter a report, diagnostic, or record.
TARRANT_SENSITIVE_HEADERS: Final[frozenset[str]] = frozenset(
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

#: D4: at most this many diagnostics are retained; the total is preserved.
TARRANT_DIAGNOSTIC_RETENTION_LIMIT: Final = 100

_ASCII_WHITESPACE: Final = " \t\r\n\v\f"
_BOMS: Final[tuple[bytes, ...]] = (
    b"\xef\xbb\xbf",  # UTF-8
    b"\xff\xfe\x00\x00",  # UTF-32 LE
    b"\x00\x00\xfe\xff",  # UTF-32 BE
    b"\xff\xfe",  # UTF-16 LE
    b"\xfe\xff",  # UTF-16 BE
)
_TEXT_BOM: Final = "﻿"

_DELIMITER: Final = "|"
_QUOTE: Final = '"'

_DIVISION_CODES: Final[frozenset[str]] = frozenset({"R", "C", "M", "P"})
_YEAR_PATTERN: Final = re.compile(r"[0-9]{4}\Z")
_ACCOUNT_PATTERN: Final = re.compile(r"[\x21-\x7e]{1,64}\Z")
_MONETARY_PATTERN: Final = re.compile(r"[0-9]+(?:\.[0-9]{1,4})?\Z")
#: D6: slash-separated, one- or two-digit month and day, four-digit year.
_DATE_PATTERN: Final = re.compile(r"(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])/([0-9]{4})\Z")
#: D7: bounded logical identifiers.  The alphabet admits no path separator, so a
#: host-local location is unrepresentable rather than merely discouraged.
_IDENTIFIER_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")

_MIN_YEAR: Final = 1900
_MAX_YEAR: Final = 2100
_MAX_MONETARY: Final = Decimal(10) ** 28 - 1
_MAX_IDENTIFIER_TEXT: Final = 512
_MAX_SOURCE_TEXT: Final = 128

_OPTIONAL_IDENTIFIER_FIELDS: Final[tuple[str, ...]] = ("PIDN", "GIS_Link")
_OPTIONAL_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "Property_Class",
    "State_Use_Code",
    "Exemption_Code",
)
_REQUIRED_MONETARY_FIELDS: Final[tuple[str, ...]] = ("Total_Value", "Appraised_Value")
_OPTIONAL_MONETARY_FIELDS: Final[tuple[str, ...]] = (
    "Land_Value",
    "Improvement_Value",
    "Ag_Value",
)
_DATE_FIELDS: Final[tuple[str, ...]] = ("Deed_Date", "Notice_Date", "Appraisal_Date")


class TarrantDiagnosticCode(StrEnum):
    """D4: the closed diagnostic vocabulary, complete and closed at 21 codes."""

    INVALID_ENCODING = "invalid_encoding"
    UNEXPECTED_BOM = "unexpected_bom"
    MALFORMED_DELIMITED_RECORD = "malformed_delimited_record"
    MULTILINE_RECORD_UNSUPPORTED = "multiline_record_unsupported"
    BLANK_HEADER = "blank_header"
    DUPLICATE_HEADER = "duplicate_header"
    HEADER_NAME_COLLISION = "header_name_collision"
    MISSING_REQUIRED_HEADER = "missing_required_header"
    ROW_WIDTH_MISMATCH = "row_width_mismatch"
    UNSUPPORTED_LAYOUT = "unsupported_layout"
    EXTRA_COLUMNS_PRESENT = "extra_columns_present"
    BLANK_REQUIRED_VALUE = "blank_required_value"
    INVALID_DIVISION = "invalid_division"
    INVALID_APPRAISAL_YEAR = "invalid_appraisal_year"
    APPRAISAL_YEAR_MISMATCH = "appraisal_year_mismatch"
    INVALID_ACCOUNT_NUM = "invalid_account_num"
    INVALID_SOURCE_IDENTIFIER = "invalid_source_identifier"
    INVALID_SOURCE_TEXT = "invalid_source_text"
    INVALID_MONETARY_VALUE = "invalid_monetary_value"
    INVALID_SOURCE_DATE = "invalid_source_date"
    DUPLICATE_ACCOUNT_NUM = "duplicate_account_num"


#: Every code except this one rejects the logical release.
_NONFATAL_CODES: Final[frozenset[TarrantDiagnosticCode]] = frozenset(
    {TarrantDiagnosticCode.EXTRA_COLUMNS_PRESENT}
)


@dataclass(frozen=True, slots=True)
class TarrantDiagnostic:
    """One bounded diagnostic.

    The four fields below are the complete permitted metadata, so D4's
    redaction rules are enforced by the type rather than by convention: there is
    nowhere to put a row, an arbitrary value, an account, release or member
    text, an identity, an address, a credential, exception text, or a host path.
    """

    code: TarrantDiagnosticCode
    field_name: str | None = None
    physical_row_number: int | None = None
    layout_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class TarrantValidationReport:
    """The complete interim result of validating one logical release.

    Carries no parsed field value and no row.  It is not persisted, cached, or
    logged, its lifetime ends with the caller that received it, and it is not a
    substitute for any contract Issue #43 owns.
    """

    parser_contract_version: int
    release_accepted: bool
    layout_fingerprint: str | None
    observed_headers: tuple[str, ...]
    accepted_row_count: int
    diagnostics: tuple[TarrantDiagnostic, ...]
    total_diagnostic_count: int
    diagnostics_truncated: bool


def validate_certified_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    expected_source_year: int,
) -> TarrantValidationReport:
    """Validate one already-selected certified-core member.

    Performs no I/O, retains no state between calls, and holds no reference to
    ``data`` after returning.  Caller identity is a programming contract rather
    than source data, so a violation raises :class:`ValueError` before the
    member is read and produces no report and no diagnostic: the closed
    diagnostic vocabulary describes the source, never the caller.
    """

    _require_caller_identity(release_identifier, source_member_name, expected_source_year)

    text = _decode(data)
    if text is None:
        return _rejected(TarrantDiagnostic(TarrantDiagnosticCode.INVALID_ENCODING))
    if text.startswith(_TEXT_BOM):
        return _rejected(TarrantDiagnostic(TarrantDiagnosticCode.UNEXPECTED_BOM))

    lines = _physical_lines(text)
    if not lines:
        return _rejected(TarrantDiagnostic(TarrantDiagnosticCode.UNSUPPORTED_LAYOUT))

    header_fields = _split_record(lines[0])
    if header_fields is None:
        return _rejected(
            TarrantDiagnostic(
                TarrantDiagnosticCode.MALFORMED_DELIMITED_RECORD, physical_row_number=1
            )
        )
    if any("\n" in field or "\r" in field for field in header_fields):
        return _rejected(
            TarrantDiagnostic(
                TarrantDiagnosticCode.MULTILINE_RECORD_UNSUPPORTED, physical_row_number=1
            )
        )

    observed = tuple(header_fields)
    fingerprint = layout_fingerprint(observed)
    header_diagnostics = _validate_header(observed, fingerprint)
    if any(diagnostic.code not in _NONFATAL_CODES for diagnostic in header_diagnostics):
        return _rejected(*header_diagnostics, headers=observed, fingerprint=fingerprint)

    diagnostics = list(header_diagnostics)
    index_of = {name: position for position, name in enumerate(observed)}
    accepted = 0
    seen_accounts: set[str] = set()

    for offset, line in enumerate(lines[1:], start=2):
        fields = _split_record(line)
        if fields is None:
            diagnostics.append(
                TarrantDiagnostic(
                    TarrantDiagnosticCode.MALFORMED_DELIMITED_RECORD,
                    physical_row_number=offset,
                    layout_fingerprint=fingerprint,
                )
            )
            continue
        if any("\n" in field or "\r" in field for field in fields):
            diagnostics.append(
                TarrantDiagnostic(
                    TarrantDiagnosticCode.MULTILINE_RECORD_UNSUPPORTED,
                    physical_row_number=offset,
                    layout_fingerprint=fingerprint,
                )
            )
            continue
        if len(fields) != len(observed):
            diagnostics.append(
                TarrantDiagnostic(
                    TarrantDiagnosticCode.ROW_WIDTH_MISMATCH,
                    physical_row_number=offset,
                    layout_fingerprint=fingerprint,
                )
            )
            continue

        row_diagnostics = _validate_row(
            fields,
            index_of=index_of,
            physical_row_number=offset,
            fingerprint=fingerprint,
            expected_source_year=expected_source_year,
            seen_accounts=seen_accounts,
        )
        diagnostics.extend(row_diagnostics)
        if not row_diagnostics:
            accepted += 1

    blocking = any(diagnostic.code not in _NONFATAL_CODES for diagnostic in diagnostics)
    return _report(
        diagnostics,
        headers=observed,
        fingerprint=fingerprint,
        accepted_row_count=0 if blocking else accepted,
        release_accepted=not blocking,
    )


def layout_fingerprint(observed_headers: tuple[str, ...]) -> str:
    """Digest the exact canonical layout document defined by the capability spec.

    The five members come from D1.  The exact keys, literals, and serialization
    are this foundation's binding choice so that two compliant implementations
    agree byte for byte; they are a serialization contract, not a claim about a
    live release.
    """

    document = {
        "column_count": len(observed_headers),
        "dialect": TARRANT_DIALECT,
        "encoding": TARRANT_ENCODING,
        "headers_sorted": sorted(observed_headers),
        "parser_contract_version": TARRANT_PARSER_CONTRACT_VERSION,
    }
    payload = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_caller_identity(
    release_identifier: str,
    source_member_name: str,
    expected_source_year: int,
) -> None:
    """D7: reject a caller argument rather than coercing it."""

    for name, value in (
        ("release_identifier", release_identifier),
        ("source_member_name", source_member_name),
    ):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a str")
        if _IDENTIFIER_PATTERN.fullmatch(value) is None or value[0] in {".", "-"}:
            raise ValueError(f"{name} is not a bounded logical identifier")
    # `bool` subclasses `int`, so an explicit check is required to keep `True`
    # from being read as the year 1.
    if isinstance(expected_source_year, bool) or not isinstance(expected_source_year, int):
        raise ValueError("expected_source_year must be an int")
    if not _MIN_YEAR <= expected_source_year <= _MAX_YEAR:
        raise ValueError("expected_source_year is out of the approved range")


def _decode(data: bytes | str) -> str | None:
    """Decode strictly as ISO-8859-1, or report that it cannot be decoded."""

    if isinstance(data, bytes):
        if data.startswith(_BOMS):
            return _TEXT_BOM
        try:
            return data.decode(TARRANT_ENCODING, errors="strict")
        except UnicodeDecodeError:
            return None
    try:
        data.encode(TARRANT_ENCODING, errors="strict")
    except UnicodeEncodeError:
        return None
    return data


def _physical_lines(text: str) -> list[str]:
    """Split on LF and CRLF, allowing exactly one trailing line ending.

    Blank and whitespace-only records are preserved rather than silently
    skipped, so they reach row validation and fail there.
    """

    if not text:
        return []
    normalized = text.replace("\r\n", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return normalized.split("\n")


def _split_record(line: str) -> list[str] | None:
    """Split one physical line, or return ``None`` when quoting is malformed.

    Embedded pipes are accepted only inside a quoted field, and a doubled quote
    inside one represents a literal quote.  There is no escape character.
    """

    fields: list[str] = []
    current: list[str] = []
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char != _QUOTE:
            if char == _DELIMITER:
                fields.append("".join(current))
                current = []
            else:
                current.append(char)
            index += 1
            continue
        if current:
            # A quote may only open a field, never appear mid-field unquoted.
            return None
        index += 1
        closed = False
        while index < length:
            char = line[index]
            if char != _QUOTE:
                current.append(char)
                index += 1
                continue
            if index + 1 < length and line[index + 1] == _QUOTE:
                current.append(_QUOTE)
                index += 2
                continue
            index += 1
            closed = True
            break
        if not closed:
            return None
        if index < length:
            if line[index] != _DELIMITER:
                return None
            index += 1
            fields.append("".join(current))
            current = []
            continue
        fields.append("".join(current))
        return fields
    fields.append("".join(current))
    return fields


def _validate_header(observed: tuple[str, ...], fingerprint: str) -> list[TarrantDiagnostic]:
    """D1: bind by untrimmed exact name, and reject an unusable layout."""

    diagnostics: list[TarrantDiagnostic] = []
    if not observed:
        return [
            TarrantDiagnostic(
                TarrantDiagnosticCode.UNSUPPORTED_LAYOUT,
                physical_row_number=1,
                layout_fingerprint=fingerprint,
            )
        ]
    for name in observed:
        if not name.strip(_ASCII_WHITESPACE):
            diagnostics.append(
                TarrantDiagnostic(
                    TarrantDiagnosticCode.BLANK_HEADER,
                    physical_row_number=1,
                    layout_fingerprint=fingerprint,
                )
            )
        elif name != name.strip(_ASCII_WHITESPACE) or any(
            character < " " or character == "\x7f" for character in name
        ):
            # Surrounding whitespace and control characters are layout defects
            # the four named header codes do not cover.
            diagnostics.append(
                TarrantDiagnostic(
                    TarrantDiagnosticCode.UNSUPPORTED_LAYOUT,
                    physical_row_number=1,
                    layout_fingerprint=fingerprint,
                )
            )
    if len(set(observed)) != len(observed):
        diagnostics.append(
            TarrantDiagnostic(
                TarrantDiagnosticCode.DUPLICATE_HEADER,
                physical_row_number=1,
                layout_fingerprint=fingerprint,
            )
        )
    folded = [name.casefold() for name in observed]
    if len(set(folded)) != len(folded) and len(set(observed)) == len(observed):
        diagnostics.append(
            TarrantDiagnostic(
                TarrantDiagnosticCode.HEADER_NAME_COLLISION,
                physical_row_number=1,
                layout_fingerprint=fingerprint,
            )
        )
    for required in TARRANT_REQUIRED_HEADERS:
        if required not in observed:
            diagnostics.append(
                TarrantDiagnostic(
                    TarrantDiagnosticCode.MISSING_REQUIRED_HEADER,
                    field_name=required,
                    physical_row_number=1,
                    layout_fingerprint=fingerprint,
                )
            )
    if set(observed) - set(TARRANT_REQUIRED_HEADERS):
        # Nonfatal, and the extra header's own name is never echoed: an unknown
        # column may itself carry identity or address data.
        diagnostics.append(
            TarrantDiagnostic(
                TarrantDiagnosticCode.EXTRA_COLUMNS_PRESENT,
                physical_row_number=1,
                layout_fingerprint=fingerprint,
            )
        )
    return diagnostics


def _validate_row(
    fields: list[str],
    *,
    index_of: dict[str, int],
    physical_row_number: int,
    fingerprint: str,
    expected_source_year: int,
    seen_accounts: set[str],
) -> list[TarrantDiagnostic]:
    """D2 and D6: validate one row's approved lexical grammars."""

    diagnostics: list[TarrantDiagnostic] = []

    def report(code: TarrantDiagnosticCode, field_name: str) -> None:
        diagnostics.append(
            TarrantDiagnostic(
                code,
                field_name=field_name,
                physical_row_number=physical_row_number,
                layout_fingerprint=fingerprint,
            )
        )

    def raw(name: str) -> str:
        return fields[index_of[name]]

    # `RP` is required and untrimmed.
    if raw("RP") not in _DIVISION_CODES:
        report(TarrantDiagnosticCode.INVALID_DIVISION, "RP")

    year_text = raw("Appraisal_Year").strip(_ASCII_WHITESPACE)
    if not year_text:
        report(TarrantDiagnosticCode.BLANK_REQUIRED_VALUE, "Appraisal_Year")
    elif _YEAR_PATTERN.fullmatch(year_text) is None:
        report(TarrantDiagnosticCode.INVALID_APPRAISAL_YEAR, "Appraisal_Year")
    elif not _MIN_YEAR <= int(year_text) <= _MAX_YEAR:
        report(TarrantDiagnosticCode.INVALID_APPRAISAL_YEAR, "Appraisal_Year")
    elif int(year_text) != expected_source_year:
        report(TarrantDiagnosticCode.APPRAISAL_YEAR_MISMATCH, "Appraisal_Year")

    account = raw("Account_Num").strip(_ASCII_WHITESPACE)
    if not account:
        report(TarrantDiagnosticCode.BLANK_REQUIRED_VALUE, "Account_Num")
    elif _ACCOUNT_PATTERN.fullmatch(account) is None:
        report(TarrantDiagnosticCode.INVALID_ACCOUNT_NUM, "Account_Num")
    elif account in seen_accounts:
        # Compared as text, so `00123` and `123` are distinct accounts.
        report(TarrantDiagnosticCode.DUPLICATE_ACCOUNT_NUM, "Account_Num")
    else:
        seen_accounts.add(account)

    for name in _OPTIONAL_IDENTIFIER_FIELDS:
        value = raw(name).strip(_ASCII_WHITESPACE)
        if value and not _is_bounded_text(value, _MAX_IDENTIFIER_TEXT):
            report(TarrantDiagnosticCode.INVALID_SOURCE_IDENTIFIER, name)

    for name in _OPTIONAL_TEXT_FIELDS:
        value = raw(name).strip(_ASCII_WHITESPACE)
        if value and not _is_bounded_text(value, _MAX_SOURCE_TEXT):
            report(TarrantDiagnosticCode.INVALID_SOURCE_TEXT, name)

    for name in _REQUIRED_MONETARY_FIELDS:
        value = raw(name).strip(_ASCII_WHITESPACE)
        if not value:
            report(TarrantDiagnosticCode.BLANK_REQUIRED_VALUE, name)
        elif not _is_approved_monetary(value):
            report(TarrantDiagnosticCode.INVALID_MONETARY_VALUE, name)

    for name in _OPTIONAL_MONETARY_FIELDS:
        value = raw(name).strip(_ASCII_WHITESPACE)
        if value and not _is_approved_monetary(value):
            report(TarrantDiagnosticCode.INVALID_MONETARY_VALUE, name)

    for name in _DATE_FIELDS:
        value = raw(name).strip(_ASCII_WHITESPACE)
        if value and not _is_approved_date(value):
            report(TarrantDiagnosticCode.INVALID_SOURCE_DATE, name)

    return diagnostics


def _is_bounded_text(value: str, limit: int) -> bool:
    """Non-control text within the approved length."""

    if len(value) > limit:
        return False
    return not any(character < " " or character == "\x7f" for character in value)


def _is_approved_monetary(value: str) -> bool:
    """D2: exact decimal text, never coerced through float."""

    if _MONETARY_PATTERN.fullmatch(value) is None:
        return False
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return False
    return Decimal(0) <= parsed <= _MAX_MONETARY


def _is_approved_date(value: str) -> bool:
    """D6 pattern plus D2 calendar validity and range."""

    match = _DATE_PATTERN.fullmatch(value)
    if match is None:
        return False
    month, day, year = (int(part) for part in match.groups())
    if not _MIN_YEAR <= year <= _MAX_YEAR:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _rejected(
    *diagnostics: TarrantDiagnostic,
    headers: tuple[str, ...] = (),
    fingerprint: str | None = None,
) -> TarrantValidationReport:
    return _report(
        list(diagnostics),
        headers=headers,
        fingerprint=fingerprint,
        accepted_row_count=0,
        release_accepted=False,
    )


def _report(
    diagnostics: list[TarrantDiagnostic],
    *,
    headers: tuple[str, ...],
    fingerprint: str | None,
    accepted_row_count: int,
    release_accepted: bool,
) -> TarrantValidationReport:
    """Apply D4's retention cap while preserving the total and marking truncation."""

    total = len(diagnostics)
    retained = tuple(diagnostics[:TARRANT_DIAGNOSTIC_RETENTION_LIMIT])
    return TarrantValidationReport(
        parser_contract_version=TARRANT_PARSER_CONTRACT_VERSION,
        release_accepted=release_accepted,
        layout_fingerprint=fingerprint,
        observed_headers=headers,
        accepted_row_count=accepted_row_count,
        diagnostics=retained,
        total_diagnostic_count=total,
        diagnostics_truncated=total > len(retained),
    )


__all__ = [
    "TARRANT_DIAGNOSTIC_RETENTION_LIMIT",
    "TARRANT_DIALECT",
    "TARRANT_ENCODING",
    "TARRANT_JURISDICTION_CODE",
    "TARRANT_PARSER_CONTRACT_VERSION",
    "TARRANT_REQUIRED_HEADERS",
    "TARRANT_SENSITIVE_HEADERS",
    "TARRANT_SOURCE",
    "TARRANT_SOURCE_FAMILY",
    "TARRANT_SOURCE_STATUS",
    "TarrantDiagnostic",
    "TarrantDiagnosticCode",
    "TarrantValidationReport",
    "layout_fingerprint",
    "validate_certified_member",
]
