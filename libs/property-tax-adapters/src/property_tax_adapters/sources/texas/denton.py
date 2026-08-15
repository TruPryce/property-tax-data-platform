"""Denton CAD source metadata and PACS fixed-width parser foundation.

Accepted in OpenSpec change ``add-denton-cad-pacs-parser-foundation``. Parses
one already-selected, caller-supplied PACS member from synthetic evidence and
makes no claim of live-release compatibility.

Serialization mechanics live in :mod:`property_tax_adapters.sources.pacs`, which
Ellis binds to as well. Everything county-specific lives here: field names,
lexical grammars, the owner-row grain, child classification, thresholds, the
diagnostic vocabulary, and privacy policy.

Each member kind has a validator and a materializing sibling over one shared
traversal: `validate_property_member` with `materialize_property_member`, and
`validate_child_member` with `materialize_child_member`. Records correspond
exactly to the rows the report counted as accepted, and `convert_denton_record`
converts a property record into the vendor-neutral contract Issue #43 owns.

Materialization is atomic with validation: a rejected release yields no records.

The validators remain what they were: :func:`validate_property_member` and
:func:`validate_child_member` return a bounded :class:`DentonValidationReport`
carrying counts, diagnostics, and layout provenance, and no field values at all.
No county-local substitute for a shared contract exists, and that prohibition
has not lifted -- only the wait for the real thing has ended.
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

DENTON_JURISDICTION_CODE: Literal["tx-denton"] = "tx-denton"
DENTON_PARSER_CONTRACT_VERSION: Final = 1
DENTON_ENCODING: Final = "iso-8859-1"

DENTON_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.DENTON),
    official_url="https://dentoncad.net/data/_uploaded/files/datafiles/",
    acquisition_method=AcquisitionMethod.FIXED_WIDTH,
    parser_id="texas.denton.pacs-fixed-width-v1",
)

#: The synthetic Denton property layout. Positions are 1-indexed inclusive.
#: This is a foundation contract authored for testing, not a reproduction of the
#: published Denton PACS layout, which remains unproved.
DENTON_PROPERTY_LAYOUT = PacsLayout(
    layout_id="denton.property",
    layout_version="v1",
    fields=(
        PacsField("prop_id", 1, 12),
        PacsField("owner_sequence", 13, 16),
        PacsField("tax_year", 17, 20),
        PacsField("ownership_percentage", 21, 30),
        PacsField("market_value", 31, 45),
        PacsField("appraised_value", 46, 60),
        PacsField("assessed_value", 61, 75),
        PacsField("land_value", 76, 90, required=False),
        PacsField("improvement_value", 91, 105, required=False),
        PacsField("agricultural_value", 106, 120, required=False),
        PacsField("ten_percent_cap", 121, 135, required=False),
        PacsField("owner_name", 136, 185, required=False),
        PacsField("owner_address", 186, 245, required=False),
        PacsField("situs_address", 246, 305, required=False),
    ),
)

#: The synthetic Denton child layout, shared by every child table.
DENTON_CHILD_LAYOUT = PacsLayout(
    layout_id="denton.child",
    layout_version="v1",
    fields=(
        PacsField("prop_id", 1, 12),
        PacsField("child_sequence", 13, 16),
        PacsField("child_value", 17, 31, required=False),
    ),
)

#: D4: a core appraisal orphan blocks the release; a legal orphan warns.
DENTON_CORE_CHILD_TABLES: Final[frozenset[str]] = frozenset({"land", "improvement", "mobile_home"})
DENTON_LEGAL_CHILD_TABLES: Final[frozenset[str]] = frozenset({"arb", "lawsuit"})

#: Field names whose values are default-deny. The positions participate in
#: layout provenance; the values never enter a report, diagnostic, or fixture.
DENTON_SENSITIVE_FIELDS: Final[frozenset[str]] = frozenset(
    {"owner_name", "owner_address", "situs_address"}
)

#: Account-level facts that records sharing one `prop_id` must agree on.
DENTON_ACCOUNT_FACTS: Final[tuple[str, ...]] = (
    "tax_year",
    "market_value",
    "appraised_value",
    "assessed_value",
)

#: Owner-scoped fields, which legitimately differ across an allocation.
DENTON_MONETARY_FIELDS: Final[tuple[str, ...]] = (
    "market_value",
    "appraised_value",
    "assessed_value",
    "land_value",
    "improvement_value",
    "agricultural_value",
    "ten_percent_cap",
)

#: The approved Denton layout fingerprints, pinned as literals.
#:
#: Deriving these from the layout would make the gate tautological: editing a
#: position would move the expected value with it and the comparison could never
#: fail. Written out, an unreviewed mapping edit breaks the gate, which is the
#: whole point of having one.
DENTON_EXPECTED_PROPERTY_FINGERPRINT: Final = (
    "ffa28810356375cf71441068c46467d946da47ac9ea900709c1fdd41a87904c2"  # pragma: allowlist secret
)
DENTON_EXPECTED_CHILD_FINGERPRINT: Final = (
    "faa76621da3e8f86617d087c5ed2d5b15a8590a0f4883a3a15dc43bab555c13b"  # pragma: allowlist secret
)

DENTON_DIAGNOSTIC_RETENTION_LIMIT: Final = 100

_ASCII_WHITESPACE: Final = " \t\r\n\v\f"
_BOMS: Final[tuple[bytes, ...]] = (
    b"\xef\xbb\xbf",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
    b"\xff\xfe",
    b"\xfe\xff",
)
_TEXT_BOM: Final = "﻿"

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


class DentonDiagnosticCode(StrEnum):
    """The closed Denton diagnostic vocabulary."""

    INVALID_ENCODING = "invalid_encoding"
    UNEXPECTED_BOM = "unexpected_bom"
    RECORD_WIDTH_MISMATCH = "record_width_mismatch"
    UNSUPPORTED_LAYOUT_FINGERPRINT = "unsupported_layout_fingerprint"
    UNDOCUMENTED_TRAILING_REGION = "undocumented_trailing_region"
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
    CORE_CHILD_ORPHANED = "core_child_orphaned"
    LEGAL_CHILD_ORPHANED = "legal_child_orphaned"


#: Every other code rejects the logical release.
#:
#: `undocumented_trailing_region` is *not* here. Issue #20 requires unknown
#: trailing regions to fail closed, and treating them as a warning contradicted
#: that: a member carrying undocumented bytes would have been accepted with its
#: unknown region merely noted. The region is still fingerprinted, so the
#: rejection carries evidence of what was found.
_NONFATAL_CODES: Final[frozenset[DentonDiagnosticCode]] = frozenset(
    {DentonDiagnosticCode.LEGAL_CHILD_ORPHANED}
)


@dataclass(frozen=True, slots=True)
class DentonDiagnostic:
    """One bounded diagnostic.

    These four fields are the complete permitted metadata, so the redaction
    rules are enforced by the type: there is nowhere to put a record, an
    arbitrary value, an account value, release or member text, an owner name, an
    address, a credential, exception text, or a host path.
    """

    code: DentonDiagnosticCode
    field_name: str | None = None
    physical_row_number: int | None = None
    layout_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class DentonValidationReport:
    """The complete interim result of validating one logical Denton member.

    Carries no parsed field value and no record. It is not persisted, cached, or
    logged, its lifetime ends with the caller that received it, and it is not a
    substitute for any contract Issue #43 owns.
    """

    parser_contract_version: int
    release_accepted: bool
    layout_fingerprint: str
    layout_version: str
    accepted_row_count: int
    owner_row_count: int
    trailing_region_bytes: int
    diagnostics: tuple[DentonDiagnostic, ...]
    total_diagnostic_count: int
    diagnostics_truncated: bool


#: The Denton fields whose values travel as source-native values.  Owner name,
#: owner address, and situs address are absent by construction: a declared
#: position may participate in layout provenance, a value never enters a record.
DENTON_SOURCE_VALUE_FIELDS: Final[tuple[str, ...]] = (
    "tax_year",
    "ownership_percentage",
    "market_value",
    "appraised_value",
    "assessed_value",
    "land_value",
    "improvement_value",
    "agricultural_value",
    "ten_percent_cap",
)


@dataclass(frozen=True, slots=True)
class DentonSourceProvenance:
    """County-native provenance for one materialized Denton row.

    Holds the shared provenance as a stored field rather than deriving it, and
    checks that the county fields it duplicates agree with it at construction.

    `field_positions` records the 1-indexed inclusive span each named field was
    sliced from.  A fixed-width county has no header row to name its columns, so
    the positions *are* the binding evidence: without them a value cannot be
    traced back to the bytes it came from.
    """

    jurisdiction_code: Literal["tx-denton"]
    release_identifier: str
    source_member_name: str
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
            )
            if county != neutral
        ]
        if mismatched:
            raise ValueError(
                "shared provenance disagrees with Denton provenance on: " + ", ".join(mismatched)
            )


@dataclass(frozen=True, slots=True)
class DentonSourceRecord:
    """One validated owner row, at `(prop_id, owner_sequence)` grain.

    `ten_percent_cap` is carried as a source-native cap amount among the values.
    It is not a canonical capped value and nothing derives one from it: the
    county published an amount, and that is all this records.
    """

    prop_id: str
    owner_sequence: str
    source_native_values: Mapping[str, SourceNativeValue]
    provenance: DentonSourceProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_native_values",
            MappingProxyType(dict(self.source_native_values)),
        )


@dataclass(frozen=True, slots=True)
class DentonChildProvenance:
    """Provenance for one child row, naming the table it was measured in."""

    jurisdiction_code: Literal["tx-denton"]
    child_table: str
    layout_fingerprint: str
    layout_version: str
    physical_row_number: int
    parser_contract_version: int


@dataclass(frozen=True, slots=True)
class DentonChildRecord:
    """One child row at its measured source grain.

    No roll-up to the parent account is derived here.  A child is evidence about
    a child; summing children into an account amount would invent a figure the
    county never published.
    """

    prop_id: str
    child_sequence: str
    child_value: SourceNativeValue | None
    provenance: DentonChildProvenance


@dataclass(frozen=True, slots=True)
class DentonMaterializationResult:
    """The validation report and, only if the release was accepted, its records."""

    report: DentonValidationReport
    records: tuple[DentonSourceRecord, ...]


@dataclass(frozen=True, slots=True)
class DentonChildMaterializationResult:
    """The child validation report and, if accepted, its child records."""

    report: DentonValidationReport
    records: tuple[DentonChildRecord, ...]


def validate_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str = DENTON_EXPECTED_PROPERTY_FINGERPRINT,
) -> DentonValidationReport:
    """Validate one already-selected Denton PACS property member.

    Performs no I/O, retains no state between calls, and holds no reference to
    `data` after returning. Caller identity is a programming contract rather
    than source data, so a violation raises `ValueError` before the member is
    read and produces no report and no diagnostic.
    """

    return _process_property_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        expected_tax_year=expected_tax_year,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=False,
    ).report


def materialize_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str = DENTON_EXPECTED_PROPERTY_FINGERPRINT,
) -> DentonMaterializationResult:
    """Validate one property member and materialize the rows it accepted.

    Reuses the validation `validate_property_member` performs rather than
    repeating it, so the two entry points cannot drift about what a valid Denton
    row is.  A rejected release yields no records: there is no partial output.
    """

    return _process_property_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        expected_tax_year=expected_tax_year,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=True,
    )


def _process_property_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    expected_tax_year: int,
    expected_layout_fingerprint: str,
    materialize: bool,
) -> DentonMaterializationResult:
    """The one traversal both property entry points share."""

    _require_caller_identity(release_identifier, source_member_name, expected_tax_year)
    layout = DENTON_PROPERTY_LAYOUT

    if not _assert_layout_approved(
        layout, expected_layout_fingerprint, DENTON_EXPECTED_PROPERTY_FINGERPRINT
    ):
        return _no_property_records(
            _report(
                [
                    _diagnostic(
                        DentonDiagnosticCode.UNSUPPORTED_LAYOUT_FINGERPRINT, layout, None, None
                    )
                ],
                layout=layout,
                accepted=0,
                owner_rows=0,
                trailing=0,
            )
        )

    records, early = _records(data, layout)
    if early is not None:
        return _no_property_records(
            _report([early], layout=layout, accepted=0, owner_rows=0, trailing=0)
        )

    preflight = _preflight(records, layout)
    if preflight:
        # A member that is not the declared layout is rejected rather than
        # parsed at a guessed width, so nothing below runs on ambiguous input.
        return _no_property_records(
            _report(preflight, layout=layout, accepted=0, owner_rows=0, trailing=0)
        )

    diagnostics: list[DentonDiagnostic] = []
    trailing_bytes = 0

    # Truncation and the trailing region are properties of the uniform observed
    # width, not of any one record, so they are determined once. Emitting them
    # per row would report the same layout defect once per record.
    # Width is already gated against the declared width, so nothing can be
    # truncated here; the component still reports truncation for callers that
    # slice directly.
    probe = layout.slice_record(records[0][1], encoding=DENTON_ENCODING)
    if probe.trailing is not None:
        trailing_bytes = probe.trailing.byte_length
        diagnostics.append(
            _diagnostic(DentonDiagnosticCode.UNDOCUMENTED_TRAILING_REGION, layout, None, 1)
        )
    accepted = 0
    owner_rows: set[tuple[str, str]] = set()
    account_facts: dict[str, dict[str, str]] = {}
    materialized: list[DentonSourceRecord] = []

    for row_number, record in records:
        values = layout.slice_record(record, encoding=DENTON_ENCODING).values
        row_diagnostics = _validate_property_values(values, layout, row_number, expected_tax_year)
        if row_diagnostics:
            diagnostics.extend(row_diagnostics)
            continue

        prop_id = values["prop_id"].strip(_ASCII_WHITESPACE)
        sequence = values["owner_sequence"].strip(_ASCII_WHITESPACE)
        key = (prop_id, sequence)
        if key in owner_rows:
            diagnostics.append(
                _diagnostic(
                    DentonDiagnosticCode.DUPLICATE_OWNER_ROW, layout, "owner_sequence", row_number
                )
            )
            continue
        owner_rows.add(key)

        # Records sharing an account must agree on account-level facts. Owner
        # sequence, ownership percentage, and owner-scoped values legitimately
        # differ across an allocation and are never compared here.
        facts = {name: values[name].strip(_ASCII_WHITESPACE) for name in DENTON_ACCOUNT_FACTS}
        established = account_facts.setdefault(prop_id, facts)
        conflicting = [name for name, value in facts.items() if established[name] != value]
        if conflicting:
            diagnostics.append(
                _diagnostic(
                    DentonDiagnosticCode.CONFLICTING_ACCOUNT_FACTS,
                    layout,
                    conflicting[0],
                    row_number,
                )
            )
            continue

        accepted += 1
        if materialize:
            materialized.append(
                _materialize_property_row(
                    values,
                    layout=layout,
                    prop_id=prop_id,
                    owner_sequence=sequence,
                    row_number=row_number,
                    release_identifier=release_identifier,
                    source_member_name=source_member_name,
                    expected_tax_year=expected_tax_year,
                )
            )

    blocking = any(entry.code not in _NONFATAL_CODES for entry in diagnostics)
    report = _report(
        diagnostics,
        layout=layout,
        accepted=0 if blocking else accepted,
        owner_rows=0 if blocking else len(owner_rows),
        trailing=trailing_bytes,
    )
    # Atomic with validation: a blocked release publishes nothing, so rows
    # already built are discarded rather than returned as a partial set.
    return DentonMaterializationResult(
        report=report, records=() if blocking else tuple(materialized)
    )


def _no_property_records(report: DentonValidationReport) -> DentonMaterializationResult:
    return DentonMaterializationResult(report=report, records=())


def _field_positions(layout: PacsLayout) -> dict[str, tuple[int, int]]:
    """The 1-indexed inclusive span each named field was sliced from.

    Sensitive fields are excluded.  Their positions may participate in layout
    provenance generally, but a record is per-row evidence and carrying them
    there would put an owner-name span beside the row it belongs to.
    """

    return {
        field.name: (field.start, field.end)
        for field in layout.fields
        if field.name not in DENTON_SENSITIVE_FIELDS
    }


def _materialize_property_row(
    values: Mapping[str, str],
    *,
    layout: PacsLayout,
    prop_id: str,
    owner_sequence: str,
    row_number: int,
    release_identifier: str,
    source_member_name: str,
    expected_tax_year: int,
) -> DentonSourceRecord:
    """Build one record from a row the validation above already accepted."""

    native: dict[str, SourceNativeValue] = {}
    for name in DENTON_SOURCE_VALUE_FIELDS:
        raw = values.get(name)
        if raw is None:
            continue
        stripped = raw.strip(_ASCII_WHITESPACE)
        if not stripped:
            # Empty text after trimming is the only null, and a null is an
            # omitted entry rather than a value holding no value.
            continue
        parsed: str | int | Decimal
        if name in DENTON_MONETARY_FIELDS or name == "ownership_percentage":
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
        jurisdiction_code=DENTON_JURISDICTION_CODE,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        source_row_number=row_number,
        parser_contract_version=DENTON_PARSER_CONTRACT_VERSION,
        layout_fingerprint=layout.fingerprint,
        table_name=layout.layout_id,
        source_year=expected_tax_year,
    )
    return DentonSourceRecord(
        prop_id=prop_id,
        owner_sequence=owner_sequence,
        source_native_values=native,
        provenance=DentonSourceProvenance(
            jurisdiction_code=DENTON_JURISDICTION_CODE,
            release_identifier=release_identifier,
            source_member_name=source_member_name,
            tax_year=expected_tax_year,
            layout_fingerprint=layout.fingerprint,
            layout_version=layout.layout_version,
            field_positions=_field_positions(layout),
            physical_row_number=row_number,
            parser_contract_version=DENTON_PARSER_CONTRACT_VERSION,
            shared=shared,
        ),
    )


def convert_denton_record(record: DentonSourceRecord) -> AppraisalSourceRecord:
    """Convert one Denton owner row into exactly one shared record.

    The `(prop_id, owner_sequence)` grain survives conversion: one owner row
    produces one shared record, and `owner_sequence` travels as a source-native
    identifier.  No account roll-up is derived, because summing an allocation
    would invent an account figure the county never published.
    """

    return AppraisalSourceRecord(
        jurisdiction_code=DENTON_JURISDICTION_CODE,
        source_account_id=record.prop_id,
        source_native_identifiers={
            "prop_id": record.prop_id,
            "owner_sequence": record.owner_sequence,
        },
        appraisal_year=record.provenance.tax_year,
        source_family=None,
        source_status=None,
        parcel_reference=None,
        source_native_values=record.source_native_values,
        provenance=record.provenance.shared,
    )


def _observed_width(
    records: list[tuple[int, str]], layout: PacsLayout
) -> tuple[int, list[DentonDiagnostic]]:
    """The member's uniform observed width, or the records that disagree.

    Width is a member-level property: PACS records carry no delimiter, so a
    record of a different width is not a narrow record but evidence that the
    member is not the layout it claims to be.

    Uniformity alone is not enough. Comparing rows only with one another
    accepted a member whose every record was 75 characters against a layout
    declaring 305, because the required fields all happen to end by 75 and the
    optional remainder simply looked absent. The observed width must reach the
    declared width; anything beyond it is the trailing region.
    """

    observed = len(records[0][1])
    mismatched = [
        _diagnostic(DentonDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, row_number)
        for row_number, record in records
        if len(record) != observed
    ]
    if not mismatched and observed < layout.declared_width:
        mismatched.append(_diagnostic(DentonDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, 1))
    return observed, mismatched


def materialize_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    accepted_account_ids: Iterable[str],
    child_table: str = "land",
    expected_layout_fingerprint: str = DENTON_EXPECTED_CHILD_FINGERPRINT,
) -> DentonChildMaterializationResult:
    """Validate one child member and materialize the rows it accepted.

    Shares `validate_child_member`'s traversal rather than re-walking the
    member, so a record exists for exactly the rows the report counted.  An
    unresolved child is not an accepted row, whether it blocks the release or
    only warns, so it produces no record either way.

    Each child stays at its measured source grain.  Nothing is rolled up to the
    parent account: summing children would invent an account figure the county
    never published.
    """

    return _process_child_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        accepted_account_ids=accepted_account_ids,
        child_table=child_table,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=True,
    )


def _materialize_child_row(
    values: Mapping[str, str],
    *,
    layout: PacsLayout,
    row_number: int,
    child_table: str,
) -> DentonChildRecord:
    """Build one child record from a row validation already accepted.

    D5 fixes the bounds this relies on: `child_sequence` is required and one to
    four ASCII digits, and `child_value` is optional with empty text after
    trimming as the only null.
    """

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
    return DentonChildRecord(
        prop_id=values["prop_id"].strip(_ASCII_WHITESPACE),
        child_sequence=values["child_sequence"].strip(_ASCII_WHITESPACE),
        child_value=child_value,
        provenance=DentonChildProvenance(
            jurisdiction_code=DENTON_JURISDICTION_CODE,
            child_table=child_table,
            layout_fingerprint=layout.fingerprint,
            layout_version=layout.layout_version,
            physical_row_number=row_number,
            parser_contract_version=DENTON_PARSER_CONTRACT_VERSION,
        ),
    )


def validate_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    child_table: str,
    accepted_account_ids: Iterable[str],
    expected_layout_fingerprint: str = DENTON_EXPECTED_CHILD_FINGERPRINT,
) -> DentonValidationReport:
    """Validate one Denton child member against the accepted account set.

    D4: an unresolved core appraisal child blocks the release; an unresolved
    legal child warns without blocking.

    A warned row is still a row: an unresolved legal child is counted and, on
    the materializing path, produces a record.  Only an unresolved core child is
    withheld, and that is because it rejects the release outright.
    """

    return _process_child_member(
        data,
        release_identifier=release_identifier,
        source_member_name=source_member_name,
        accepted_account_ids=accepted_account_ids,
        child_table=child_table,
        expected_layout_fingerprint=expected_layout_fingerprint,
        materialize=False,
    ).report


def _process_child_member(
    data: bytes | str,
    *,
    release_identifier: str,
    source_member_name: str,
    child_table: str,
    accepted_account_ids: Iterable[str],
    expected_layout_fingerprint: str,
    materialize: bool,
) -> DentonChildMaterializationResult:
    """The one traversal both child entry points share."""

    _require_caller_identity(release_identifier, source_member_name, _MIN_YEAR)
    if child_table not in DENTON_CORE_CHILD_TABLES | DENTON_LEGAL_CHILD_TABLES:
        raise ValueError("child_table is not an approved Denton child table")

    layout = DENTON_CHILD_LAYOUT
    if not _assert_layout_approved(
        layout, expected_layout_fingerprint, DENTON_EXPECTED_CHILD_FINGERPRINT
    ):
        return _no_child_records(
            _report(
                [
                    _diagnostic(
                        DentonDiagnosticCode.UNSUPPORTED_LAYOUT_FINGERPRINT, layout, None, None
                    )
                ],
                layout=layout,
                accepted=0,
                owner_rows=0,
                trailing=0,
            )
        )
    accounts = {str(value) for value in accepted_account_ids}
    orphan_code = (
        DentonDiagnosticCode.CORE_CHILD_ORPHANED
        if child_table in DENTON_CORE_CHILD_TABLES
        else DentonDiagnosticCode.LEGAL_CHILD_ORPHANED
    )

    records, early = _records(data, layout)
    if early is not None:
        return _no_child_records(
            _report([early], layout=layout, accepted=0, owner_rows=0, trailing=0)
        )

    preflight = _preflight(records, layout)
    if preflight:
        return _no_child_records(
            _report(preflight, layout=layout, accepted=0, owner_rows=0, trailing=0)
        )

    # A child member wider than its declared layout is drift just as a property
    # member is. Checking only nonuniform and short records let a uniformly wide
    # child member through with no diagnostic and no trailing byte count.
    probe = layout.slice_record(records[0][1], encoding=DENTON_ENCODING)
    if probe.trailing is not None:
        return _no_child_records(
            _report(
                [_diagnostic(DentonDiagnosticCode.UNDOCUMENTED_TRAILING_REGION, layout, None, 1)],
                layout=layout,
                accepted=0,
                owner_rows=0,
                trailing=probe.trailing.byte_length,
            )
        )

    diagnostics: list[DentonDiagnostic] = []
    accepted = 0
    materialized: list[DentonChildRecord] = []
    for row_number, record in records:
        sliced = layout.slice_record(record, encoding=DENTON_ENCODING)
        values = sliced.values
        prop_id = values["prop_id"].strip(_ASCII_WHITESPACE)
        if not prop_id:
            diagnostics.append(
                _diagnostic(DentonDiagnosticCode.BLANK_REQUIRED_KEY, layout, "prop_id", row_number)
            )
            continue

        # D5, applied here so both entry points enforce it.  The vocabulary is
        # closed at seventeen codes and has no child-specific member, so the
        # sequence and monetary codes carry the child field name instead.
        row_diagnostics = _validate_child_values(values, layout, row_number)
        if row_diagnostics:
            diagnostics.extend(row_diagnostics)
            continue

        if prop_id not in accounts:
            # An orphan is diagnosed and then kept: a warning does not delete the
            # row it warns about, and dropping one would be a third behaviour,
            # neither blocking nor warning-and-continuing.
            #
            # A *core* orphan needs no special case here. Its code is blocking,
            # and a blocking diagnostic zeroes both the accepted count and the
            # records below, so skipping the row as well would be a branch no
            # input could distinguish. The test asserting `core_child_orphaned`
            # is not in `_NONFATAL_CODES` is what keeps that true.
            diagnostics.append(_diagnostic(orphan_code, layout, None, row_number))
        accepted += 1
        if materialize:
            materialized.append(
                _materialize_child_row(
                    values, layout=layout, row_number=row_number, child_table=child_table
                )
            )

    blocking = any(entry.code not in _NONFATAL_CODES for entry in diagnostics)
    report = _report(
        diagnostics,
        layout=layout,
        accepted=0 if blocking else accepted,
        owner_rows=0,
        trailing=0,
    )
    return DentonChildMaterializationResult(
        report=report, records=() if blocking else tuple(materialized)
    )


def _no_child_records(report: DentonValidationReport) -> DentonChildMaterializationResult:
    return DentonChildMaterializationResult(report=report, records=())


def _validate_child_values(
    values: Mapping[str, str], layout: PacsLayout, row_number: int
) -> list[DentonDiagnostic]:
    """D5: the child lexical bounds this plan decided rather than discovered.

    `child_sequence` is required and one to four ASCII digits.  `child_value`
    may be blank as source absence; a nonblank value uses the property monetary
    grammar bounded zero through `10**26 - 1`.  Empty text after trimming is the
    only null, so a whitespace-only field is absence rather than a malformed
    amount.
    """

    diagnostics: list[DentonDiagnostic] = []
    # `invalid_child_sequence` is this change's eighteenth code.  Borrowing the
    # owner code would have reported a child defect under a name that names a
    # different field, and the owner and child sequences are separate facts even
    # though their grammars agree today.
    sequence = values.get("child_sequence", "").strip(_ASCII_WHITESPACE)
    if not sequence:
        diagnostics.append(
            _diagnostic(
                DentonDiagnosticCode.BLANK_REQUIRED_KEY, layout, "child_sequence", row_number
            )
        )
    elif _OWNER_SEQUENCE_PATTERN.fullmatch(sequence) is None:
        diagnostics.append(
            _diagnostic(
                DentonDiagnosticCode.INVALID_CHILD_SEQUENCE, layout, "child_sequence", row_number
            )
        )

    value = values.get("child_value", "").strip(_ASCII_WHITESPACE)
    if value and not _is_approved_monetary(value):
        diagnostics.append(
            _diagnostic(
                DentonDiagnosticCode.INVALID_MONETARY_VALUE, layout, "child_value", row_number
            )
        )
    return diagnostics


def _preflight(records: list[tuple[int, str]], layout: PacsLayout) -> list[DentonDiagnostic]:
    """Checks every member must pass, whatever it contains.

    Property and child members are both fixed-width text with no delimiter, so
    a control character and a width disagreement mean the same thing in each.
    Running these only for property members let a uniformly short child member
    through, and let a control character inside a child corrupt `prop_id` into
    a false `core_child_orphaned` rather than reporting the real defect.
    """

    control = [
        _diagnostic(DentonDiagnosticCode.INVALID_SOURCE_TEXT, layout, None, row_number)
        for row_number, record in records
        if any(_is_control(character) for character in record)
    ]
    if control:
        return control
    _, mismatched = _observed_width(records, layout)
    return mismatched


def _records(
    data: bytes | str, layout: PacsLayout
) -> tuple[list[tuple[int, str]], DentonDiagnostic | None]:
    """Decode and split a member, or return the diagnostic that stops it."""

    text = _decode(data)
    if text is None:
        return [], _diagnostic(DentonDiagnosticCode.INVALID_ENCODING, layout, None, None)
    if text.startswith(_TEXT_BOM):
        return [], _diagnostic(DentonDiagnosticCode.UNEXPECTED_BOM, layout, None, None)

    lines = _physical_lines(text)
    if not lines:
        return [], _diagnostic(DentonDiagnosticCode.RECORD_WIDTH_MISMATCH, layout, None, 1)

    # A PACS member has no header row, so row 1 is the first data record.
    return list(enumerate(lines, start=1)), None


def _decode(data: bytes | str) -> str | None:
    if isinstance(data, bytes):
        if data.startswith(_BOMS):
            return _TEXT_BOM
        try:
            return data.decode(DENTON_ENCODING, errors="strict")
        except UnicodeDecodeError:
            return None
    try:
        data.encode(DENTON_ENCODING, errors="strict")
    except UnicodeEncodeError:
        return None
    return data


def _physical_lines(text: str) -> list[str]:
    """Split on LF and CRLF, allowing one trailing line ending.

    A bare CR is not a boundary: treating one as a record separator would accept
    a physical layout the contract does not describe.
    """

    if not text:
        return []
    normalized = text.replace("\r\n", "\n")
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return normalized.split("\n")


def _validate_property_values(
    values: Mapping[str, str],
    layout: PacsLayout,
    row_number: int,
    expected_tax_year: int,
) -> list[DentonDiagnostic]:
    """Apply the approved Denton lexical grammars to one sliced record."""

    diagnostics: list[DentonDiagnostic] = []

    def report(code: DentonDiagnosticCode, field_name: str) -> None:
        diagnostics.append(_diagnostic(code, layout, field_name, row_number))

    prop_id = values["prop_id"].strip(_ASCII_WHITESPACE)
    if not prop_id:
        report(DentonDiagnosticCode.BLANK_REQUIRED_KEY, "prop_id")
    elif _PROP_ID_PATTERN.fullmatch(prop_id) is None:
        report(DentonDiagnosticCode.INVALID_ACCOUNT_ID, "prop_id")

    sequence = values["owner_sequence"].strip(_ASCII_WHITESPACE)
    if not sequence:
        report(DentonDiagnosticCode.BLANK_REQUIRED_KEY, "owner_sequence")
    elif _OWNER_SEQUENCE_PATTERN.fullmatch(sequence) is None:
        report(DentonDiagnosticCode.INVALID_OWNER_SEQUENCE, "owner_sequence")

    year = values["tax_year"].strip(_ASCII_WHITESPACE)
    if not year:
        report(DentonDiagnosticCode.BLANK_REQUIRED_KEY, "tax_year")
    elif _YEAR_PATTERN.fullmatch(year) is None or not _MIN_YEAR <= int(year) <= _MAX_YEAR:
        report(DentonDiagnosticCode.INVALID_TAX_YEAR, "tax_year")
    elif int(year) != expected_tax_year:
        report(DentonDiagnosticCode.TAX_YEAR_MISMATCH, "tax_year")

    percentage = values["ownership_percentage"].strip(_ASCII_WHITESPACE)
    if not percentage:
        report(DentonDiagnosticCode.BLANK_REQUIRED_KEY, "ownership_percentage")
    elif not _is_approved_percentage(percentage):
        report(DentonDiagnosticCode.INVALID_OWNERSHIP_PERCENTAGE, "ownership_percentage")

    for name in DENTON_MONETARY_FIELDS:
        raw = values.get(name)
        if raw is None:
            continue
        value = raw.strip(_ASCII_WHITESPACE)
        if not value:
            # Only the three required monetary fields must be present; the rest
            # are source absence.
            if name in {"market_value", "appraised_value", "assessed_value"}:
                report(DentonDiagnosticCode.BLANK_REQUIRED_KEY, name)
            continue
        if not _is_approved_monetary(value):
            report(DentonDiagnosticCode.INVALID_MONETARY_VALUE, name)

    return diagnostics


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
    # `bool` subclasses `int`, so an explicit check keeps `True` from reading as
    # the year 1.
    if isinstance(expected_tax_year, bool) or not isinstance(expected_tax_year, int):
        raise ValueError("expected_tax_year must be an int")
    if not _MIN_YEAR <= expected_tax_year <= _MAX_YEAR:
        raise ValueError("expected_tax_year is out of the approved range")


def _diagnostic(
    code: DentonDiagnosticCode,
    layout: PacsLayout,
    field_name: str | None,
    row_number: int | None,
) -> DentonDiagnostic:
    return DentonDiagnostic(
        code=code,
        field_name=field_name,
        physical_row_number=row_number,
        layout_fingerprint=layout.fingerprint,
    )


def _report(
    diagnostics: list[DentonDiagnostic],
    *,
    layout: PacsLayout,
    accepted: int,
    owner_rows: int,
    trailing: int,
) -> DentonValidationReport:
    """Apply the retention cap while preserving the total and marking truncation."""

    total = len(diagnostics)
    retained = tuple(diagnostics[:DENTON_DIAGNOSTIC_RETENTION_LIMIT])
    blocking = any(entry.code not in _NONFATAL_CODES for entry in diagnostics)
    return DentonValidationReport(
        parser_contract_version=DENTON_PARSER_CONTRACT_VERSION,
        release_accepted=not blocking,
        layout_fingerprint=layout.fingerprint,
        layout_version=layout.layout_version,
        accepted_row_count=accepted,
        owner_row_count=owner_rows,
        trailing_region_bytes=trailing,
        diagnostics=retained,
        total_diagnostic_count=total,
        diagnostics_truncated=total > len(retained),
    )


__all__ = [
    "DENTON_SOURCE_VALUE_FIELDS",
    "DentonChildMaterializationResult",
    "DentonChildProvenance",
    "DentonChildRecord",
    "DentonMaterializationResult",
    "DentonSourceProvenance",
    "DentonSourceRecord",
    "convert_denton_record",
    "materialize_child_member",
    "materialize_property_member",
    "DENTON_ACCOUNT_FACTS",
    "DENTON_EXPECTED_CHILD_FINGERPRINT",
    "DENTON_EXPECTED_PROPERTY_FINGERPRINT",
    "DENTON_CHILD_LAYOUT",
    "DENTON_CORE_CHILD_TABLES",
    "DENTON_DIAGNOSTIC_RETENTION_LIMIT",
    "DENTON_ENCODING",
    "DENTON_JURISDICTION_CODE",
    "DENTON_LEGAL_CHILD_TABLES",
    "DENTON_MONETARY_FIELDS",
    "DENTON_PARSER_CONTRACT_VERSION",
    "DENTON_PROPERTY_LAYOUT",
    "DENTON_SENSITIVE_FIELDS",
    "DENTON_SOURCE",
    "DentonDiagnostic",
    "DentonDiagnosticCode",
    "DentonValidationReport",
    "validate_child_member",
    "validate_property_member",
]
