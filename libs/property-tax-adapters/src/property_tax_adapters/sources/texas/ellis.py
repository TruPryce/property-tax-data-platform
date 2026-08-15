"""Ellis CAD certified-roll source metadata and PACS fixed-width binding.

Accepted in OpenSpec change ``add-ellis-cad-pacs-parser-binding``. Parses one
already-selected, caller-supplied PACS member from synthetic evidence and makes
no claim of live-release compatibility.

This module **binds** to :mod:`property_tax_adapters.sources.pacs` rather than
forking it: it declares a layout with the shared types and defines no position
slicing, no layout validation, and no fingerprint computation of its own. It
also imports nothing from the Denton module. The two counties are independent
bindings of one component, and a dependency between them would let a Denton
layout change silently alter Ellis behaviour.

Compatibility is established by Ellis's own fingerprint. Sharing a vendor with
Denton is not evidence that the schemas agree, so the fingerprint gate and the
release-label gate both run **before** any record is read: reading records from
a misidentified artifact is how a mineral-only scenario roll becomes certified
current state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

from property_tax_adapters.sources.contracts import (
    AppraisalSourceRecord,
    SourceNativeValue,
    SourceProvenance,
)
from property_tax_adapters.sources.pacs import PacsField, PacsLayout

ELLIS_JURISDICTION_CODE: Literal["tx-ellis"] = "tx-ellis"
ELLIS_PARSER_CONTRACT_VERSION: Final = 1
ELLIS_ENCODING: Final = "iso-8859-1"

ELLIS_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.ELLIS),
    official_url="https://www.elliscad.com/appraisal-data-export",
    acquisition_method=AcquisitionMethod.FIXED_WIDTH,
    parser_id="texas.ellis.pacs-fixed-width-v1",
)

#: The synthetic Ellis property layout. Positions are 1-indexed inclusive.
#: Declared independently of Denton: the layouts may or may not agree, and this
#: foundation measures neither. A synthetic contract, not a reproduction of the
#: published Ellis layout.
ELLIS_PROPERTY_LAYOUT = PacsLayout(
    layout_id="ellis.property",
    layout_version="v1",
    fields=(
        PacsField("prop_id", 1, 12, declared_length=12),
        PacsField("owner_sequence", 13, 16, declared_length=4),
        PacsField("tax_year", 17, 20, declared_length=4),
        PacsField("ownership_percentage", 21, 30, declared_length=10),
        PacsField("market_value", 31, 45),
        PacsField("appraised_value", 46, 60),
        PacsField("assessed_value", 61, 75),
        PacsField("land_value", 76, 90, required=False),
        PacsField("improvement_value", 91, 105, required=False),
        PacsField("agricultural_value", 106, 120, required=False),
        PacsField("owner_name", 121, 170, required=False),
        PacsField("owner_address", 171, 230, required=False),
        PacsField("situs_address", 231, 290, required=False),
    ),
)

#: D1: the expected Ellis fingerprints, pinned as literals.
#:
#: Deriving these from the layout would make the gate tautological: editing a
#: position would move the expected value with it and the comparison could never
#: fail. Written out, an unreviewed mapping edit breaks the gate, which is the
#: whole point of having one. Compatibility is established against these values,
#: never against Denton's and never from the vendor or a filename.
ELLIS_EXPECTED_LAYOUT_FINGERPRINT: Final = (
    "f7e275e9c22b021029b2b34b0daebd066b2c87933bc76ac8fd941de31280f101"  # pragma: allowlist secret
)
ELLIS_EXPECTED_CHILD_FINGERPRINT: Final = (
    "8f4e69d0cf3d55836f98d98dac7ad9800caa08b9143b4789f6cb873c505d17e2"  # pragma: allowlist secret
)

#: The synthetic Ellis child layout, mirroring the Denton child grain.
ELLIS_CHILD_LAYOUT = PacsLayout(
    layout_id="ellis.child",
    layout_version="v1",
    fields=(
        PacsField("prop_id", 1, 12, declared_length=12),
        PacsField("child_sequence", 13, 16, declared_length=4),
        PacsField("child_value", 17, 31, required=False, declared_length=15),
    ),
)

#: Core appraisal orphans block the release; legal orphans warn.
ELLIS_CORE_CHILD_TABLES: Final[frozenset[str]] = frozenset({"land", "improvement", "mobile_home"})
ELLIS_LEGAL_CHILD_TABLES: Final[frozenset[str]] = frozenset({"arb", "lawsuit"})

#: D3: the only release label this foundation parses as certified current state.
ELLIS_CERTIFIED_LABEL: Final = "certified-all-property"
#: What a report says when the label was refused. Echoing the caller's text back
#: would put arbitrary input into a default-deny output.
ELLIS_REJECTED_LABEL: Final = "unsupported"

#: D2: an OpenDocument Spreadsheet package begins with the ZIP local-file-header
#: signature and stores `mimetype` as its first member.
_ZIP_LOCAL_HEADER: Final = b"PK\x03\x04"
_ODS_MEDIA_TYPE: Final = b"application/vnd.oasis.opendocument.spreadsheet"
_MIMETYPE_MEMBER: Final = b"mimetype"
#: A ZIP local file header is 30 bytes before the member name begins.
_LOCAL_HEADER_LENGTH: Final = 30
#: Compression method 0. ODS stores `mimetype` uncompressed by specification.
_STORED: Final = 0
#: The signature check reads no further than this, so a hostile package cannot
#: turn recognition into extraction.
_SIGNATURE_WINDOW: Final = 128

ELLIS_SENSITIVE_FIELDS: Final[frozenset[str]] = frozenset(
    {"owner_name", "owner_address", "situs_address"}
)

ELLIS_ACCOUNT_FACTS: Final[tuple[str, ...]] = (
    "tax_year",
    "market_value",
    "appraised_value",
    "assessed_value",
)

ELLIS_MONETARY_FIELDS: Final[tuple[str, ...]] = (
    "market_value",
    "appraised_value",
    "assessed_value",
    "land_value",
    "improvement_value",
    "agricultural_value",
)

_REQUIRED_MONETARY: Final[frozenset[str]] = frozenset(
    {"market_value", "appraised_value", "assessed_value"}
)

ELLIS_DIAGNOSTIC_RETENTION_LIMIT: Final = 100

_ASCII_WHITESPACE: Final = " \t\r\n\v\f"
_BOMS: Final[tuple[bytes, ...]] = (
    b"\xef\xbb\xbf",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
    b"\xff\xfe",
    b"\xfe\xff",
)
_TEXT_BOM: Final = "﻿"

# D4: the Denton bounds, declared here rather than imported. No Ellis
# measurement exists, so diverging would invent a difference instead of
# measuring one; declaring them per county means a later measurement changes
# one county without touching the other.
_PROP_ID_PATTERN: Final = re.compile(r"[\x21-\x7e]{1,32}\Z")
_OWNER_SEQUENCE_PATTERN: Final = re.compile(r"[0-9]{1,4}\Z")
_MONETARY_PATTERN: Final = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?\Z")
_PERCENTAGE_PATTERN: Final = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,6})?\Z")
_YEAR_PATTERN: Final = re.compile(r"[0-9]{4}\Z")
_IDENTIFIER_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")

_MIN_YEAR: Final = 1900
_MAX_YEAR: Final = 2100
_MAX_MONETARY: Final = Decimal(10) ** 26 - 1
_MAX_PERCENTAGE: Final = Decimal(100)


class EllisDiagnosticCode(StrEnum):
    """The closed Ellis diagnostic vocabulary."""

    INVALID_ENCODING = "invalid_encoding"
    UNEXPECTED_BOM = "unexpected_bom"
    RECORD_WIDTH_MISMATCH = "record_width_mismatch"
    UNSUPPORTED_LAYOUT_FINGERPRINT = "unsupported_layout_fingerprint"
    UNDOCUMENTED_TRAILING_REGION = "undocumented_trailing_region"
    UNSUPPORTED_SCENARIO_LABEL = "unsupported_scenario_label"
    CORE_CHILD_ORPHANED = "core_child_orphaned"
    LEGAL_CHILD_ORPHANED = "legal_child_orphaned"
    BLANK_REQUIRED_KEY = "blank_required_key"
    INVALID_ACCOUNT_ID = "invalid_account_id"
    INVALID_OWNER_SEQUENCE = "invalid_owner_sequence"
    INVALID_CHILD_SEQUENCE = "invalid_child_sequence"
    INVALID_MONETARY_VALUE = "invalid_monetary_value"
    INVALID_OWNERSHIP_PERCENTAGE = "invalid_ownership_percentage"
    INVALID_TAX_YEAR = "invalid_tax_year"
    TAX_YEAR_MISMATCH = "tax_year_mismatch"
    INVALID_SOURCE_TEXT = "invalid_source_text"
    DUPLICATE_OWNER_ROW = "duplicate_owner_row"
    CONFLICTING_ACCOUNT_FACTS = "conflicting_account_facts"


#: `undocumented_trailing_region` is deliberately absent: the governing issue
#: requires unknown trailing regions to fail closed, as the Denton binding notes.
_NONFATAL_CODES: Final[frozenset[EllisDiagnosticCode]] = frozenset(
    {EllisDiagnosticCode.LEGAL_CHILD_ORPHANED}
)


class LayoutPackageKind(StrEnum):
    """What a caller-supplied layout package is, judged from its content.

    This is the reportable outcome of classification, and it is why the
    diagnostic vocabulary carries no `unrecognised_layout_package` code: a
    caller receives `UNRECOGNISED` directly, and a declared code that no path
    can emit promises a diagnostic that never arrives.
    """

    OPENDOCUMENT_SPREADSHEET = "opendocument_spreadsheet"
    UNRECOGNISED = "unrecognised"


@dataclass(frozen=True, slots=True)
class EllisDiagnostic:
    """One bounded diagnostic.

    These four fields are the complete permitted metadata, so the redaction
    rules are enforced by the type rather than by convention.
    """

    code: EllisDiagnosticCode
    field_name: str | None = None
    physical_row_number: int | None = None
    layout_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class EllisValidationReport:
    """The complete interim result of validating one logical Ellis member.

    Carries no parsed field value and no record, and is not a substitute for any
    contract Issue #43 owns.
    """

    parser_contract_version: int
    release_accepted: bool
    layout_fingerprint: str
    layout_version: str
    release_label: str
    accepted_row_count: int
    owner_row_count: int
    trailing_region_bytes: int
    diagnostics: tuple[EllisDiagnostic, ...]
    total_diagnostic_count: int
    diagnostics_truncated: bool


def classify_layout_package(package_bytes: bytes) -> LayoutPackageKind:
    """Classify a layout package from its content, never from its name.

    The published Ellis layout is named `.xlsx.ods`, so extension-based
    selection picks the wrong parser. This reads a bounded window of the
    caller-supplied bytes and checks the OpenDocument signature: the ZIP
    local-file-header, then `mimetype` as the first member, then the
    OpenDocument Spreadsheet media type.

    It extracts nothing, enumerates nothing, and decompresses nothing, so it
    cannot be turned into an archive reader by a hostile package. An absent,
    truncated, or ambiguous signature fails closed.
    """

    if not isinstance(package_bytes, bytes):
        raise ValueError("package_bytes must be bytes")
    window = package_bytes[:_SIGNATURE_WINDOW]
    if len(window) < _LOCAL_HEADER_LENGTH or not window.startswith(_ZIP_LOCAL_HEADER):
        return LayoutPackageKind.UNRECOGNISED

    # Parse the local file header rather than searching for the marker. Finding
    # `mimetype` and the media type *somewhere* after a ZIP signature accepts
    # any archive that happens to contain those bytes, including one where the
    # member is deflated or is not the first entry.
    compression = int.from_bytes(window[8:10], "little")
    compressed_size = int.from_bytes(window[18:22], "little")
    uncompressed_size = int.from_bytes(window[22:26], "little")
    name_length = int.from_bytes(window[26:28], "little")
    extra_length = int.from_bytes(window[28:30], "little")

    # ODS requires `mimetype` first and stored uncompressed, which is what makes
    # the media type readable without decompressing anything.
    if compression != _STORED:
        return LayoutPackageKind.UNRECOGNISED
    if name_length != len(_MIMETYPE_MEMBER):
        return LayoutPackageKind.UNRECOGNISED
    # A stored member declares the same compressed and uncompressed size, and
    # for `mimetype` that size is the media type's length. Ignoring the declared
    # sizes accepted a header claiming zero bytes while carrying forty-six --
    # a package that does not exist, and a hand-assembled prefix passing as one.
    if compressed_size != uncompressed_size or compressed_size != len(_ODS_MEDIA_TYPE):
        return LayoutPackageKind.UNRECOGNISED

    name_start = _LOCAL_HEADER_LENGTH
    name_end = name_start + name_length
    if window[name_start:name_end] != _MIMETYPE_MEMBER:
        return LayoutPackageKind.UNRECOGNISED

    value_start = name_end + extra_length
    if window[value_start : value_start + len(_ODS_MEDIA_TYPE)] != _ODS_MEDIA_TYPE:
        return LayoutPackageKind.UNRECOGNISED
    return LayoutPackageKind.OPENDOCUMENT_SPREADSHEET


#: The Ellis fields whose values travel as source-native values. Owner name,
#: owner address, and situs address are absent by construction: a declared
#: position may participate in layout provenance, a value never enters a record.
ELLIS_SOURCE_VALUE_FIELDS: Final[tuple[str, ...]] = (
    "tax_year",
    "ownership_percentage",
    "market_value",
    "appraised_value",
    "assessed_value",
    "land_value",
    "improvement_value",
    "agricultural_value",
)


@dataclass(frozen=True, slots=True)
class EllisSourceProvenance:
    """County-native provenance for one materialized Ellis row.

    Holds the shared provenance as a stored field rather than deriving it, and
    checks that the county fields it duplicates agree with it at construction.

    `release_label` is Ellis-specific and load-bearing: a mineral-only scenario
    roll is not certified current state, and a record that did not carry the
    label it was accepted under could not be told apart from one that was.
    """

    jurisdiction_code: Literal["tx-ellis"]
    release_identifier: str
    source_member_name: str
    release_label: str
    tax_year: int
    layout_fingerprint: str
    layout_version: str
    field_positions: Mapping[str, tuple[int, int]]
    physical_row_number: int
    parser_contract_version: int
    shared: SourceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_positions", MappingProxyType(dict(self.field_positions)))
        mismatched = [
            name
            for name, county, neutral in (
                ("jurisdiction_code", self.jurisdiction_code, self.shared.jurisdiction_code),
                ("release_identifier", self.release_identifier, self.shared.release_identifier),
                ("source_member_name", self.source_member_name, self.shared.source_member_name),
                ("layout_fingerprint", self.layout_fingerprint, self.shared.layout_fingerprint),
                ("physical_row_number", self.physical_row_number, self.shared.source_row_number),
                (
                    "parser_contract_version",
                    self.parser_contract_version,
                    self.shared.parser_contract_version,
                ),
                ("tax_year", self.tax_year, self.shared.source_year),
                ("release_label", self.release_label, self.shared.source_status),
            )
            if county != neutral
        ]
        if mismatched:
            raise ValueError(
                "shared provenance disagrees with Ellis provenance on: " + ", ".join(mismatched)
            )


@dataclass(frozen=True, slots=True)
class EllisSourceRecord:
    """One validated owner row, at `(prop_id, owner_sequence)` grain."""

    prop_id: str
    owner_sequence: str
    source_native_values: Mapping[str, SourceNativeValue]
    provenance: EllisSourceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_native_values",
            MappingProxyType(dict(self.source_native_values)),
        )


@dataclass(frozen=True, slots=True)
class EllisChildProvenance:
    """Provenance for one child row, naming the table and the release label."""

    jurisdiction_code: Literal["tx-ellis"]
    child_table: str
    release_label: str
    layout_fingerprint: str
    layout_version: str
    physical_row_number: int
    parser_contract_version: int


@dataclass(frozen=True, slots=True)
class EllisChildRecord:
    """One child row at its measured source grain, with no roll-up derived."""

    prop_id: str
    child_sequence: str
    child_value: SourceNativeValue | None
    provenance: EllisChildProvenance


@dataclass(frozen=True, slots=True)
class EllisMaterializationResult:
    """The validation report and, only if the release was accepted, its records."""

    report: EllisValidationReport
    records: tuple[EllisSourceRecord, ...]


@dataclass(frozen=True, slots=True)
class EllisChildMaterializationResult:
    """The child validation report and, if accepted, its child records."""

    report: EllisValidationReport
    records: tuple[EllisChildRecord, ...]


def validate_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str = ELLIS_EXPECTED_LAYOUT_FINGERPRINT,
) -> EllisValidationReport:
    """Validate one already-selected Ellis PACS property member.

    The label and fingerprint gates run before any record is read. Both answer
    "is this the artifact we think it is?", and reading records from a
    misidentified artifact is precisely the failure the Ellis contract forbids.
    """

    return _process_property_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        release_label=release_label,
        expected_tax_year=expected_tax_year,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=False,
    ).report


def materialize_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str = ELLIS_EXPECTED_LAYOUT_FINGERPRINT,
) -> EllisMaterializationResult:
    """Validate one property member and materialize the rows it accepted.

    Shares `validate_property_member`'s traversal rather than repeating it, so a
    record exists for exactly the rows the report counted.
    """

    return _process_property_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        release_label=release_label,
        expected_tax_year=expected_tax_year,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=True,
    )


def _process_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str,
    materialize: bool,
) -> EllisMaterializationResult:
    """Run the walk once, then decide what may leave with the report.

    Records are withheld unless the release was accepted.  Deciding that here,
    from the report the walk returned, means every early exit inside the walk
    keeps its exact behaviour and none can be overlooked.
    """

    materialized: list[EllisSourceRecord] = []
    report = _walk_property_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        release_label=release_label,
        expected_tax_year=expected_tax_year,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialized=materialized if materialize else None,
    )
    return EllisMaterializationResult(
        report=report,
        records=tuple(materialized) if report.release_accepted else (),
    )


def _field_positions(layout: PacsLayout) -> dict[str, tuple[int, int]]:
    """The 1-indexed inclusive span each named field was sliced from.

    Sensitive fields are excluded.  Their positions may participate in layout
    provenance generally, but a record is per-row evidence and carrying them
    there would put an owner-name span beside the row it belongs to.
    """

    return {
        field.name: (field.start, field.end)
        for field in layout.fields
        if field.name not in ELLIS_SENSITIVE_FIELDS
    }


def _walk_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str,
    materialized: list[EllisSourceRecord] | None,
) -> EllisValidationReport:
    """The validation, unchanged, optionally collecting records as it goes."""

    _require_caller_identity(release_identifier, source_member_name, expected_tax_year)
    layout = ELLIS_PROPERTY_LAYOUT

    if release_label != ELLIS_CERTIFIED_LABEL:
        return _report(
            [_diagnostic(EllisDiagnosticCode.UNSUPPORTED_SCENARIO_LABEL, layout, None, None)],
            layout=layout,
            label=ELLIS_REJECTED_LABEL,
            accepted=0,
            owner_rows=0,
            trailing=0,
        )

    if not _assert_layout_approved(
        layout, expected_layout_fingerprint, ELLIS_EXPECTED_LAYOUT_FINGERPRINT
    ):
        return _report(
            [_diagnostic(EllisDiagnosticCode.UNSUPPORTED_LAYOUT_FINGERPRINT, layout, None, None)],
            layout=layout,
            label=release_label,
            accepted=0,
            owner_rows=0,
            trailing=0,
        )

    text = _decode(data)
    if text is None:
        return _fail(EllisDiagnosticCode.INVALID_ENCODING, layout, release_label)
    if text.startswith(_TEXT_BOM):
        return _fail(EllisDiagnosticCode.UNEXPECTED_BOM, layout, release_label)

    lines = _physical_lines(text)
    if not lines:
        return _fail(EllisDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, release_label)

    # A PACS member has no header row, so row 1 is the first data record.
    records = list(enumerate(lines, start=1))

    control = [
        _diagnostic(EllisDiagnosticCode.INVALID_SOURCE_TEXT, layout, None, row_number)
        for row_number, record in records
        if any(_is_control(character) for character in record)
    ]
    if control:
        return _report(
            control, layout=layout, label=release_label, accepted=0, owner_rows=0, trailing=0
        )

    observed = len(records[0][1])
    mismatched = [
        _diagnostic(EllisDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, row_number)
        for row_number, record in records
        if len(record) != observed
    ]
    # Uniformity alone is not enough: a member whose every record falls short of
    # the declared width is not the declared layout, however consistent it is.
    if not mismatched and observed < layout.declared_width:
        mismatched.append(_diagnostic(EllisDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, 1))
    if mismatched:
        return _report(
            mismatched, layout=layout, label=release_label, accepted=0, owner_rows=0, trailing=0
        )

    diagnostics: list[EllisDiagnostic] = []
    trailing_bytes = 0

    # Truncation and the trailing region follow from the uniform observed width,
    # so they are determined once rather than reported per record.
    # Width is already gated against the declared width, so nothing can be
    # truncated here; the component still reports truncation for callers that
    # slice directly.
    probe = layout.slice_record(records[0][1], encoding=ELLIS_ENCODING)
    if probe.trailing is not None:
        trailing_bytes = probe.trailing.byte_length
        diagnostics.append(
            _diagnostic(EllisDiagnosticCode.UNDOCUMENTED_TRAILING_REGION, layout, None, 1)
        )
    accepted = 0
    owner_rows: set[tuple[str, str]] = set()
    account_facts: dict[str, dict[str, str]] = {}

    for row_number, record in records:
        values = layout.slice_record(record, encoding=ELLIS_ENCODING).values
        row_diagnostics = _validate_values(values, layout, row_number, expected_tax_year)
        if row_diagnostics:
            diagnostics.extend(row_diagnostics)
            continue

        prop_id = values["prop_id"].strip(_ASCII_WHITESPACE)
        sequence = values["owner_sequence"].strip(_ASCII_WHITESPACE)
        key = (prop_id, sequence)
        if key in owner_rows:
            diagnostics.append(
                _diagnostic(
                    EllisDiagnosticCode.DUPLICATE_OWNER_ROW, layout, "owner_sequence", row_number
                )
            )
            continue
        owner_rows.add(key)

        facts = {name: values[name].strip(_ASCII_WHITESPACE) for name in ELLIS_ACCOUNT_FACTS}
        established = account_facts.setdefault(prop_id, facts)
        conflicting = [name for name, value in facts.items() if established[name] != value]
        if conflicting:
            diagnostics.append(
                _diagnostic(
                    EllisDiagnosticCode.CONFLICTING_ACCOUNT_FACTS,
                    layout,
                    conflicting[0],
                    row_number,
                )
            )
            continue

        accepted += 1
        if materialized is not None:
            materialized.append(
                _materialize_property_row(
                    values,
                    layout=layout,
                    prop_id=prop_id,
                    owner_sequence=sequence,
                    row_number=row_number,
                    release_identifier=release_identifier,
                    source_member_name=source_member_name,
                    release_label=release_label,
                    expected_tax_year=expected_tax_year,
                )
            )

    blocking = any(entry.code not in _NONFATAL_CODES for entry in diagnostics)
    return _report(
        diagnostics,
        layout=layout,
        label=release_label,
        accepted=0 if blocking else accepted,
        owner_rows=0 if blocking else len(owner_rows),
        trailing=trailing_bytes,
    )


def _materialize_property_row(
    values: Mapping[str, str],
    *,
    layout: PacsLayout,
    prop_id: str,
    owner_sequence: str,
    row_number: int,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    expected_tax_year: int,
) -> EllisSourceRecord:
    """Build one record from a row the validation above already accepted.

    Only the documented Ellis monetary facts and the percentage normalize to
    `Decimal`; the tax year to `int`.  Anything else keeps the text it arrived
    as, because normalizing an undocumented field would assert a type the
    contract never approved.
    """

    native: dict[str, SourceNativeValue] = {}
    for name in ELLIS_SOURCE_VALUE_FIELDS:
        raw = values.get(name)
        if raw is None:
            continue
        stripped = raw.strip(_ASCII_WHITESPACE)
        if not stripped:
            # Empty text after trimming is the only null, and a null is an
            # omitted entry rather than a value holding no value.
            continue
        parsed: str | int | Decimal
        if name in ELLIS_MONETARY_FIELDS or name == "ownership_percentage":
            parsed = Decimal(stripped)
        elif name == "tax_year":
            parsed = int(stripped)
        else:
            parsed = stripped
        native[name] = SourceNativeValue(
            source_field=name,
            value=parsed,
            lexical_text=stripped,
        )

    shared = SourceProvenance(
        jurisdiction_code=ELLIS_JURISDICTION_CODE,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        source_row_number=row_number,
        parser_contract_version=ELLIS_PARSER_CONTRACT_VERSION,
        layout_fingerprint=layout.fingerprint,
        table_name=layout.layout_id,
        source_year=expected_tax_year,
        source_status=release_label,
    )
    return EllisSourceRecord(
        prop_id=prop_id,
        owner_sequence=owner_sequence,
        source_native_values=native,
        provenance=EllisSourceProvenance(
            jurisdiction_code=ELLIS_JURISDICTION_CODE,
            release_identifier=release_identifier,
            source_member_name=source_member_name,
            release_label=release_label,
            tax_year=expected_tax_year,
            layout_fingerprint=layout.fingerprint,
            layout_version=layout.layout_version,
            field_positions=_field_positions(layout),
            physical_row_number=row_number,
            parser_contract_version=ELLIS_PARSER_CONTRACT_VERSION,
            shared=shared,
        ),
    )


def convert_ellis_record(record: EllisSourceRecord) -> AppraisalSourceRecord:
    """Convert one Ellis owner row into exactly one shared record.

    The `(prop_id, owner_sequence)` grain survives conversion: one owner row
    produces one shared record, and `owner_sequence` travels as a source-native
    identifier.  No account roll-up is derived, because summing an allocation
    would invent an account figure the county never published.
    """

    return AppraisalSourceRecord(
        jurisdiction_code=ELLIS_JURISDICTION_CODE,
        source_account_id=record.prop_id,
        source_native_identifiers={
            "prop_id": record.prop_id,
            "owner_sequence": record.owner_sequence,
        },
        appraisal_year=record.provenance.tax_year,
        source_family=None,
        source_status=record.provenance.release_label,
        parcel_reference=None,
        source_native_values=record.source_native_values,
        provenance=record.provenance.shared,
    )


def validate_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    child_table: str,
    accepted_account_ids: Iterable[str],
    expected_layout_fingerprint: str = ELLIS_EXPECTED_CHILD_FINGERPRINT,
) -> EllisValidationReport:
    """Validate one Ellis child member against the accepted account set.

    Child facts and relationship provenance are part of the Ellis contract, and
    the same label and fingerprint gates apply: a child member from a scenario
    roll is no more parseable than a property member from one.

    An unresolved legal child warns and is kept.  A warning does not delete the
    row it warns about; only a core orphan withholds output, and that is because
    it rejects the release outright.
    """

    return _process_child_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        release_label=release_label,
        child_table=child_table,
        accepted_account_ids=accepted_account_ids,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=False,
    ).report


def materialize_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    child_table: str,
    accepted_account_ids: Iterable[str],
    expected_layout_fingerprint: str = ELLIS_EXPECTED_CHILD_FINGERPRINT,
) -> EllisChildMaterializationResult:
    """Validate one child member and materialize the rows it accepted.

    Each child stays at its measured source grain.  Nothing is rolled up to the
    parent account: summing children would invent an account figure the county
    never published.
    """

    return _process_child_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        release_label=release_label,
        child_table=child_table,
        accepted_account_ids=accepted_account_ids,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=True,
    )


def _process_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    child_table: str,
    accepted_account_ids: Iterable[str],
    expected_layout_fingerprint: str,
    materialize: bool,
) -> EllisChildMaterializationResult:
    """Run the child walk once, then decide what may leave with the report."""

    materialized: list[EllisChildRecord] = []
    report = _walk_child_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        release_label=release_label,
        child_table=child_table,
        accepted_account_ids=accepted_account_ids,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialized=materialized if materialize else None,
    )
    return EllisChildMaterializationResult(
        report=report,
        records=tuple(materialized) if report.release_accepted else (),
    )


def _validate_child_values(
    values: Mapping[str, str], layout: PacsLayout, row_number: int
) -> list[EllisDiagnostic]:
    """D5: the child lexical bounds this plan decided rather than discovered.

    `child_sequence` is required and one to four ASCII digits.  `child_value`
    may be blank as source absence; a nonblank value uses the property monetary
    grammar bounded zero through `10**26 - 1`.  Empty text after trimming is the
    only null, so a whitespace-only field is absence rather than a malformed
    amount.

    A malformed sequence reports `invalid_child_sequence` rather than borrowing
    the owner code: the two sequences are separate facts even where their
    grammars agree today.
    """

    diagnostics: list[EllisDiagnostic] = []
    sequence = values.get("child_sequence", "").strip(_ASCII_WHITESPACE)
    if not sequence:
        diagnostics.append(
            _diagnostic(
                EllisDiagnosticCode.BLANK_REQUIRED_KEY, layout, "child_sequence", row_number
            )
        )
    elif _OWNER_SEQUENCE_PATTERN.fullmatch(sequence) is None:
        diagnostics.append(
            _diagnostic(
                EllisDiagnosticCode.INVALID_CHILD_SEQUENCE, layout, "child_sequence", row_number
            )
        )

    value = values.get("child_value", "").strip(_ASCII_WHITESPACE)
    if value and not _is_approved_monetary(value):
        diagnostics.append(
            _diagnostic(
                EllisDiagnosticCode.INVALID_MONETARY_VALUE, layout, "child_value", row_number
            )
        )
    return diagnostics


def _materialize_child_row(
    values: Mapping[str, str],
    *,
    layout: PacsLayout,
    row_number: int,
    child_table: str,
    release_label: str,
) -> EllisChildRecord:
    """Build one child record from a row validation already accepted."""

    raw_value = values.get("child_value", "").strip(_ASCII_WHITESPACE)
    child_value = (
        SourceNativeValue(
            source_field="child_value",
            value=Decimal(raw_value),
            lexical_text=raw_value,
        )
        if raw_value
        else None
    )
    return EllisChildRecord(
        prop_id=values["prop_id"].strip(_ASCII_WHITESPACE),
        child_sequence=values["child_sequence"].strip(_ASCII_WHITESPACE),
        child_value=child_value,
        provenance=EllisChildProvenance(
            jurisdiction_code=ELLIS_JURISDICTION_CODE,
            child_table=child_table,
            release_label=release_label,
            layout_fingerprint=layout.fingerprint,
            layout_version=layout.layout_version,
            physical_row_number=row_number,
            parser_contract_version=ELLIS_PARSER_CONTRACT_VERSION,
        ),
    )


def _walk_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    release_label: str,
    child_table: str,
    accepted_account_ids: Iterable[str],
    expected_layout_fingerprint: str,
    materialized: list[EllisChildRecord] | None,
) -> EllisValidationReport:
    """The child validation, optionally collecting records as it goes."""

    _require_caller_identity(release_identifier, source_member_name, _MIN_YEAR)
    if child_table not in ELLIS_CORE_CHILD_TABLES | ELLIS_LEGAL_CHILD_TABLES:
        raise ValueError("child_table is not an approved Ellis child table")

    layout = ELLIS_CHILD_LAYOUT
    if release_label != ELLIS_CERTIFIED_LABEL:
        return _fail(EllisDiagnosticCode.UNSUPPORTED_SCENARIO_LABEL, layout, ELLIS_REJECTED_LABEL)
    if not _assert_layout_approved(
        layout, expected_layout_fingerprint, ELLIS_EXPECTED_CHILD_FINGERPRINT
    ):
        return _fail(EllisDiagnosticCode.UNSUPPORTED_LAYOUT_FINGERPRINT, layout, release_label)

    text = _decode(data)
    if text is None:
        return _fail(EllisDiagnosticCode.INVALID_ENCODING, layout, release_label)
    if text.startswith(_TEXT_BOM):
        return _fail(EllisDiagnosticCode.UNEXPECTED_BOM, layout, release_label)
    lines = _physical_lines(text)
    if not lines:
        return _fail(EllisDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, release_label)

    records = list(enumerate(lines, start=1))
    preflight = _preflight(records, layout)
    if preflight:
        return _report(
            preflight, layout=layout, label=release_label, accepted=0, owner_rows=0, trailing=0
        )

    # A child member wider than its declared layout is drift just as a property
    # member is. Checking only nonuniform and short records let a uniformly wide
    # child member through with no diagnostic and no trailing byte count.
    probe = layout.slice_record(records[0][1], encoding=ELLIS_ENCODING)
    if probe.trailing is not None:
        return _report(
            [_diagnostic(EllisDiagnosticCode.UNDOCUMENTED_TRAILING_REGION, layout, None, 1)],
            layout=layout,
            label=release_label,
            accepted=0,
            owner_rows=0,
            trailing=probe.trailing.byte_length,
        )

    accounts = {str(value) for value in accepted_account_ids}
    orphan_code = (
        EllisDiagnosticCode.CORE_CHILD_ORPHANED
        if child_table in ELLIS_CORE_CHILD_TABLES
        else EllisDiagnosticCode.LEGAL_CHILD_ORPHANED
    )

    diagnostics: list[EllisDiagnostic] = []
    accepted = 0
    for row_number, record in records:
        sliced = layout.slice_record(record, encoding=ELLIS_ENCODING)
        values = sliced.values
        prop_id = values["prop_id"].strip(_ASCII_WHITESPACE)
        if not prop_id:
            diagnostics.append(
                _diagnostic(EllisDiagnosticCode.BLANK_REQUIRED_KEY, layout, "prop_id", row_number)
            )
            continue

        # D5, applied in the shared walk so both entry points enforce it.
        row_diagnostics = _validate_child_values(values, layout, row_number)
        if row_diagnostics:
            diagnostics.extend(row_diagnostics)
            continue

        if prop_id not in accounts:
            # An orphan is diagnosed and then kept: a warning does not delete
            # the row it warns about. A core orphan needs no special case, since
            # its code is blocking and a blocked release publishes nothing.
            diagnostics.append(_diagnostic(orphan_code, layout, None, row_number))
        accepted += 1
        if materialized is not None:
            materialized.append(
                _materialize_child_row(
                    values,
                    layout=layout,
                    row_number=row_number,
                    child_table=child_table,
                    release_label=release_label,
                )
            )

    blocking = any(entry.code not in _NONFATAL_CODES for entry in diagnostics)
    return _report(
        diagnostics,
        layout=layout,
        label=release_label,
        accepted=0 if blocking else accepted,
        owner_rows=0,
        trailing=0,
    )


def _preflight(records: list[tuple[int, str]], layout: PacsLayout) -> list[EllisDiagnostic]:
    """Checks every member must pass, whatever it contains."""

    control = [
        _diagnostic(EllisDiagnosticCode.INVALID_SOURCE_TEXT, layout, None, row_number)
        for row_number, record in records
        if any(_is_control(character) for character in record)
    ]
    if control:
        return control
    observed = len(records[0][1])
    mismatched = [
        _diagnostic(EllisDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, row_number)
        for row_number, record in records
        if len(record) != observed
    ]
    if not mismatched and observed < layout.declared_width:
        mismatched.append(_diagnostic(EllisDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, 1))
    return mismatched


def _validate_values(
    values: Mapping[str, str], layout: PacsLayout, row_number: int, expected_tax_year: int
) -> list[EllisDiagnostic]:
    """Apply the approved Ellis lexical grammars to one sliced record."""

    diagnostics: list[EllisDiagnostic] = []

    def report(code: EllisDiagnosticCode, field_name: str) -> None:
        diagnostics.append(_diagnostic(code, layout, field_name, row_number))

    prop_id = values["prop_id"].strip(_ASCII_WHITESPACE)
    if not prop_id:
        report(EllisDiagnosticCode.BLANK_REQUIRED_KEY, "prop_id")
    elif _PROP_ID_PATTERN.fullmatch(prop_id) is None:
        report(EllisDiagnosticCode.INVALID_ACCOUNT_ID, "prop_id")

    sequence = values["owner_sequence"].strip(_ASCII_WHITESPACE)
    if not sequence:
        report(EllisDiagnosticCode.BLANK_REQUIRED_KEY, "owner_sequence")
    elif _OWNER_SEQUENCE_PATTERN.fullmatch(sequence) is None:
        report(EllisDiagnosticCode.INVALID_OWNER_SEQUENCE, "owner_sequence")

    year = values["tax_year"].strip(_ASCII_WHITESPACE)
    if not year:
        report(EllisDiagnosticCode.BLANK_REQUIRED_KEY, "tax_year")
    elif _YEAR_PATTERN.fullmatch(year) is None or not _MIN_YEAR <= int(year) <= _MAX_YEAR:
        report(EllisDiagnosticCode.INVALID_TAX_YEAR, "tax_year")
    elif int(year) != expected_tax_year:
        report(EllisDiagnosticCode.TAX_YEAR_MISMATCH, "tax_year")

    percentage = values["ownership_percentage"].strip(_ASCII_WHITESPACE)
    if not percentage:
        report(EllisDiagnosticCode.BLANK_REQUIRED_KEY, "ownership_percentage")
    elif not _is_approved_percentage(percentage):
        report(EllisDiagnosticCode.INVALID_OWNERSHIP_PERCENTAGE, "ownership_percentage")

    for name in ELLIS_MONETARY_FIELDS:
        raw = values.get(name)
        if raw is None:
            continue
        value = raw.strip(_ASCII_WHITESPACE)
        if not value:
            if name in _REQUIRED_MONETARY:
                report(EllisDiagnosticCode.BLANK_REQUIRED_KEY, name)
            continue
        if not _is_approved_monetary(value):
            report(EllisDiagnosticCode.INVALID_MONETARY_VALUE, name)

    return diagnostics


def _decode(data: bytes | str) -> str | None:
    if isinstance(data, bytes):
        if data.startswith(_BOMS):
            return _TEXT_BOM
        try:
            return data.decode(ELLIS_ENCODING, errors="strict")
        except UnicodeDecodeError:
            return None
    try:
        data.encode(ELLIS_ENCODING, errors="strict")
    except UnicodeEncodeError:
        return None
    return data


def _physical_lines(text: str) -> list[str]:
    """Split on LF and CRLF, allowing one trailing line ending.

    A bare CR is not a boundary; it reaches record validation, where an embedded
    control character is refused.
    """

    if not text:
        return []
    normalized = text.replace("\r\n", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return normalized.split("\n")


def _is_control(character: str) -> bool:
    """C0, DEL, and the C1 range, all representable in ISO-8859-1."""

    return character < " " or "\x7f" <= character <= "\x9f"


def _is_approved_monetary(value: str) -> bool:
    if _MONETARY_PATTERN.fullmatch(value) is None:
        return False
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return False
    return Decimal(0) <= parsed <= _MAX_MONETARY


def _is_approved_percentage(value: str) -> bool:
    if _PERCENTAGE_PATTERN.fullmatch(value) is None:
        return False
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return False
    return Decimal(0) <= parsed <= _MAX_PERCENTAGE


def _assert_layout_approved(layout: PacsLayout, expected: str, pinned: str) -> bool:
    """Both halves of the gate, in that order.

    Comparing the caller's value against `layout.fingerprint` alone made the
    pinned constant decorative: if the mapping drifted, the live digest drifted
    with it, and a caller passing the current value sailed through while the
    approved constant still held the old one. The declared layout is checked
    against the pinned constant first, so repository drift fails regardless of
    what the caller supplies; only then is the caller's value checked.
    """

    return layout.fingerprint == pinned and expected == pinned


def _require_caller_identity(
    release_identifier: str, source_member_name: str, expected_tax_year: int
) -> None:
    """Reject a caller argument rather than coercing it."""

    for name, value in (
        ("release_identifier", release_identifier),
        ("source_member_name", source_member_name),
    ):
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a str")
        if _IDENTIFIER_PATTERN.fullmatch(value) is None or value[0] in {".", "-"}:
            raise ValueError(f"{name} is not a bounded logical identifier")
    if isinstance(expected_tax_year, bool) or not isinstance(expected_tax_year, int):
        raise ValueError("expected_tax_year must be an int")
    if not _MIN_YEAR <= expected_tax_year <= _MAX_YEAR:
        raise ValueError("expected_tax_year is out of the approved range")


def _diagnostic(
    code: EllisDiagnosticCode,
    layout: PacsLayout,
    field_name: str | None,
    row_number: int | None,
) -> EllisDiagnostic:
    return EllisDiagnostic(
        code=code,
        field_name=field_name,
        physical_row_number=row_number,
        layout_fingerprint=layout.fingerprint,
    )


def _fail(code: EllisDiagnosticCode, layout: PacsLayout, label: str) -> EllisValidationReport:
    return _report(
        [_diagnostic(code, layout, None, None)],
        layout=layout,
        label=label,
        accepted=0,
        owner_rows=0,
        trailing=0,
    )


def _report(
    diagnostics: list[EllisDiagnostic],
    *,
    layout: PacsLayout,
    label: str,
    accepted: int,
    owner_rows: int,
    trailing: int,
) -> EllisValidationReport:
    """Apply the retention cap while preserving the total and marking truncation."""

    total = len(diagnostics)
    retained = tuple(diagnostics[:ELLIS_DIAGNOSTIC_RETENTION_LIMIT])
    blocking = any(entry.code not in _NONFATAL_CODES for entry in diagnostics)
    return EllisValidationReport(
        parser_contract_version=ELLIS_PARSER_CONTRACT_VERSION,
        release_accepted=not blocking,
        layout_fingerprint=layout.fingerprint,
        layout_version=layout.layout_version,
        release_label=label,
        accepted_row_count=accepted,
        owner_row_count=owner_rows,
        trailing_region_bytes=trailing,
        diagnostics=retained,
        total_diagnostic_count=total,
        diagnostics_truncated=total > len(retained),
    )


__all__ = [
    "ELLIS_SOURCE_VALUE_FIELDS",
    "EllisChildMaterializationResult",
    "EllisChildProvenance",
    "EllisChildRecord",
    "EllisMaterializationResult",
    "EllisSourceProvenance",
    "EllisSourceRecord",
    "convert_ellis_record",
    "materialize_child_member",
    "materialize_property_member",
    "ELLIS_ACCOUNT_FACTS",
    "ELLIS_CHILD_LAYOUT",
    "ELLIS_CORE_CHILD_TABLES",
    "ELLIS_EXPECTED_CHILD_FINGERPRINT",
    "ELLIS_LEGAL_CHILD_TABLES",
    "ELLIS_REJECTED_LABEL",
    "ELLIS_CERTIFIED_LABEL",
    "ELLIS_DIAGNOSTIC_RETENTION_LIMIT",
    "ELLIS_ENCODING",
    "ELLIS_EXPECTED_LAYOUT_FINGERPRINT",
    "ELLIS_JURISDICTION_CODE",
    "ELLIS_MONETARY_FIELDS",
    "ELLIS_PARSER_CONTRACT_VERSION",
    "ELLIS_PROPERTY_LAYOUT",
    "ELLIS_SENSITIVE_FIELDS",
    "ELLIS_SOURCE",
    "EllisDiagnostic",
    "EllisDiagnosticCode",
    "EllisValidationReport",
    "LayoutPackageKind",
    "classify_layout_package",
    "validate_child_member",
    "validate_property_member",
]
