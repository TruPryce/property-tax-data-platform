# dallas-cad-source-contract Specification

## Purpose
Define the synthetic, adapter-local Dallas CAD CSV physical contract, observed-header binding
and layout identity, adapter-local Dallas and vendor-neutral source records, lexical forms and
parent-row uniqueness, parser provenance and bounded diagnostics, and privacy and fixture
boundaries that precede any production release-processing or orchestration integration.

## Requirements
### Requirement: Dallas CSV physical contract
The Dallas parser SHALL accept UTF-8 input with at most one UTF-8 BOM at the start, SHALL parse
comma-delimited records with standard CSV double-quote behavior, SHALL accept LF and CRLF line
endings, and SHALL require every logical data row to have exactly the observed header width. The
header SHALL be source row 1 and data records SHALL use one-based logical source row numbers
starting at 2. Invalid UTF-8, a BOM outside the start, malformed CSV, or a short or long row MUST
fail without producing a record.

#### Scenario: Parse a valid row
- **WHEN** a UTF-8 comma-delimited synthetic record has the required headers, valid quoting, and the header width
- **THEN** the parser emits one typed Dallas source record and one vendor-neutral adapter record for that logical row

#### Scenario: Accept an optional leading BOM
- **WHEN** one UTF-8 BOM occurs at byte offset zero before the observed header row
- **THEN** the parser removes the BOM before retaining and normalizing the first header and otherwise parses the file identically to a BOM-free file

#### Scenario: Accept LF and CRLF records
- **WHEN** equivalent synthetic files use LF or CRLF line endings
- **THEN** both files produce equivalent records, normalized headers, and layout fingerprints

#### Scenario: Parse standard double quotes
- **WHEN** a quoted field contains a comma or a literal double quote represented by two consecutive double quotes
- **THEN** the parser returns the decoded field text without changing column alignment

#### Scenario: Reject malformed quoting
- **WHEN** quoted CSV input is unterminated or otherwise violates standard double-quote syntax
- **THEN** parsing fails with `malformed_csv` and `unsupported_layout` and emits no partial accepted record

#### Scenario: Reject short and long rows
- **WHEN** a logical data row contains fewer or more fields than the observed header row
- **THEN** parsing fails with `row_width_mismatch` and `unsupported_layout` at that one-based logical row number

#### Scenario: Reject invalid encoding or misplaced BOM
- **WHEN** input is not valid UTF-8 or contains a UTF-8 BOM anywhere other than byte offset zero
- **THEN** parsing fails with `invalid_encoding` or `unexpected_bom` respectively and emits no record

### Requirement: Observed-header binding and layout identity
The Dallas parser SHALL retain original observed headers after BOM removal and CSV unquoting, SHALL
normalize each header by trimming surrounding ASCII whitespace and uppercasing, and SHALL bind known
fields only by normalized observed header name. It MUST NOT use aliases, documentation-only names,
or ordinal positions. Blank headers, exact duplicate observed headers, and distinct headers that
normalize to the same value MUST fail. The required normalized headers are exactly `ACCOUNT_NUM`,
`APPRAISAL_YR`, `GIS_PARCEL_ID`, and `TOT_VAL`; their order is irrelevant.

The parser SHALL compute a lowercase hexadecimal SHA-256 layout fingerprint from compact canonical
JSON containing parser contract version `1` and the sorted normalized header set. The fingerprint
SHALL be retained as provenance and MUST NOT act as an allowlist. Unknown columns SHALL be accepted,
keyed by normalized header in source extras, and reported with `extra_columns_present` without
shifting known mappings.

#### Scenario: Bind reordered columns
- **WHEN** two valid files contain the same normalized header set in different orders
- **THEN** known values bind to the same fields and both files have the same layout fingerprint

#### Scenario: Reject a missing required header
- **WHEN** any one of the four required normalized headers is absent
- **THEN** parsing fails with `missing_required_header` and `unsupported_layout` before any data record is accepted

#### Scenario: Reject duplicate observed headers
- **WHEN** the observed header row repeats the same header text
- **THEN** parsing fails with `duplicate_header` and `unsupported_layout`

#### Scenario: Reject a header normalization collision
- **WHEN** two distinct observed headers become equal after ASCII-whitespace trimming and uppercasing
- **THEN** parsing fails with `header_normalization_collision` and `unsupported_layout` rather than selecting either column

#### Scenario: Reject a blank header
- **WHEN** an observed header is empty or contains only ASCII whitespace
- **THEN** parsing fails with `blank_header` and `unsupported_layout`

#### Scenario: Retain unknown extras
- **WHEN** all required headers are present and one or more unknown normalized headers are unambiguous
- **THEN** the parser retains their decoded values in `extras`, emits `extra_columns_present`, and leaves all known-field mappings unchanged

#### Scenario: Treat the fingerprint as provenance
- **WHEN** a valid layout has an unseen fingerprint because an unambiguous extra column was added
- **THEN** the parser accepts the layout after contract validation and retains the new fingerprint instead of rejecting it as absent from an allowlist

### Requirement: Adapter-local Dallas and vendor-neutral records
All parser-foundation records, value wrappers, provenance types, diagnostics, and conversion types
SHALL live in `property_tax_adapters`. This change MUST NOT modify `property_tax_domain` or
`property_tax_application` and MUST NOT introduce a domain type.

`DallasAppraisalSourceRecord` SHALL provide `account_num: str`, `appraisal_year: int`,
`gis_parcel_id: str`, `tot_val: SourceNativeDecimal`, `extras: Mapping[str, str]`, and
`provenance: DallasSourceProvenance`. Adapter-local `AppraisalSourceRecord` SHALL provide
`jurisdiction_code: str` fixed to `"tx-dallas"`, `source_account_id: str`, `appraisal_year: int`,
`parcel_reference: str | None`, `source_native_values: Mapping[str, SourceNativeValue]`, and
`provenance: SourceProvenance`.

#### Scenario: Convert a valid Dallas source record
- **WHEN** a valid Dallas source record is converted at the adapter boundary
- **THEN** the output uses jurisdiction `tx-dallas`, copies the account and appraisal year, preserves the distinct parcel reference, retains source-native values and provenance, and creates no domain or application object

#### Scenario: Keep TOT_VAL source-native
- **WHEN** a valid row contains `TOT_VAL`
- **THEN** the exact lexical text and parsed `Decimal` are retained under `source_native_values` with a source-native marker and no market, appraised, assessed, taxable, tax-amount, payment-status, delinquency, penalty, or interest field is populated or implied

#### Scenario: Preserve unknown values through conversion
- **WHEN** a Dallas source record contains accepted unknown-column extras
- **THEN** conversion retains them as explicitly source-native values keyed by normalized header without assigning canonical semantics

### Requirement: Dallas lexical forms and parent-row uniqueness
`ACCOUNT_NUM` SHALL match exactly 17 ASCII digits and retain leading zeros. `APPRAISAL_YR` SHALL
match exactly four ASCII digits, parse to `int`, and fall within 1900 through 2100 inclusive.
`GIS_PARCEL_ID` SHALL be required, SHALL be trimmed only for surrounding ASCII whitespace, and
SHALL remain non-empty with its remaining lexical case, punctuation, and leading zeros preserved.
It MUST NOT be equated with `ACCOUNT_NUM`.

`TOT_VAL` SHALL match `-?[0-9]+(?:\.[0-9]+)?`, SHALL parse with `decimal.Decimal`, and SHALL retain
its exact lexical text and source-native classification. Currency symbols, grouping commas,
exponent notation, leading plus, trailing decimal point, blank text, and malformed decimal text
MUST fail. Required blank values MUST NOT become `None`. The parser SHALL reject the second record
with a duplicate `(ACCOUNT_NUM, APPRAISAL_YR)` key in one parser invocation.

#### Scenario: Reject an invalid account number
- **WHEN** `ACCOUNT_NUM` is blank, not exactly 17 characters, contains a non-ASCII digit, or contains any nondigit
- **THEN** parsing fails with `invalid_account_num` at that row and preserves no partial record

#### Scenario: Reject an invalid appraisal year
- **WHEN** `APPRAISAL_YR` is not exactly four ASCII digits or its integer value is outside 1900 through 2100
- **THEN** parsing fails with `invalid_appraisal_year`

#### Scenario: Reject an invalid parcel identifier
- **WHEN** `GIS_PARCEL_ID` is blank after surrounding ASCII whitespace is removed
- **THEN** parsing fails with `invalid_gis_parcel_id` rather than substituting `ACCOUNT_NUM` or `None`

#### Scenario: Reject an invalid total value
- **WHEN** `TOT_VAL` is blank or uses a currency symbol, grouping comma, exponent, leading plus, trailing decimal point, or malformed decimal text
- **THEN** parsing fails with `invalid_tot_val` and does not infer a canonical value

#### Scenario: Preserve valid lexical forms
- **WHEN** valid fields contain a zero-padded account, a year within range, a case-sensitive parcel reference, and a decimal such as `-001.20`
- **THEN** the account and parcel text remain lexically intact, the year is an integer, and the decimal wrapper retains both `-001.20` and its parsed `Decimal` value

#### Scenario: Reject a duplicate account-year key
- **WHEN** a later logical row repeats an accepted `(ACCOUNT_NUM, APPRAISAL_YR)` key
- **THEN** the later row fails with `duplicate_parent_key` and the diagnostic does not include either key value

### Requirement: Dallas parser provenance and bounded diagnostics
Every Dallas-native and vendor-neutral adapter record SHALL retain caller-supplied source member
name and release identifier, original observed headers, normalized headers, layout fingerprint,
one-based logical source row number, and parser contract version. Source member and release identity
MUST be parser inputs and MUST NOT be inferred from row data.

The diagnostic vocabulary SHALL be closed to `invalid_encoding`, `unexpected_bom`, `blank_header`,
`missing_required_header`, `duplicate_header`, `header_normalization_collision`, `malformed_csv`,
`row_width_mismatch`, `invalid_account_num`, `invalid_appraisal_year`,
`invalid_gis_parcel_id`, `invalid_tot_val`, `duplicate_parent_key`, `unsupported_layout`, and
`extra_columns_present`. Diagnostics MAY contain only a stable code and, when applicable, a
normalized field/header name, one-based logical row number, and layout fingerprint. They MUST NOT
contain a complete source row, owner name, mailing address, protected identity, credential, or
arbitrary source value.

#### Scenario: Retain source-native markers and provenance
- **WHEN** a valid row is parsed and converted
- **THEN** its Dallas-native and vendor-neutral records retain the same caller-supplied member, release, original and normalized headers, fingerprint, logical row, parser version, and source-native value marker

#### Scenario: Do not infer source identity
- **WHEN** caller-supplied member or release identity is absent
- **THEN** parsing fails at the input boundary rather than deriving identity from row fields or source values

#### Scenario: Redact diagnostics
- **WHEN** malformed input contains owner-like text, mailing-address text, credentials, protected identity, or arbitrary source values
- **THEN** the diagnostic contains only its allowed code and bounded header, row, and fingerprint metadata and does not echo the complete row or source values

### Requirement: Synthetic fixtures and bounded implementation scope
All committed Dallas parser fixtures SHALL be small, independently authored, synthetic,
identity-free, and redistribution-safe. Fixture documentation SHALL state that the data is
synthetic and MUST NOT claim compatibility with a live Dallas release. Implementation SHALL be
limited to `libs/property-tax-adapters`, adapter-local tests and synthetic fixtures, and `docs`.

The change MUST NOT add network access, Dallas source contact, county artifacts, production data,
new dependencies, acquisition, Bronze, database work, Silver, Gold, Airflow, services, tools,
workflows, infrastructure, persistence, deployment, owner publication, protected-identity
reconstruction, or a production-ready designation.

#### Scenario: Exercise redistribution-safe fixtures
- **WHEN** parser contract tests run
- **THEN** every input is a small synthetic identity-free fixture with documented project authorship and no county or production bytes

#### Scenario: Enforce permitted implementation paths
- **WHEN** the approved implementation change is reviewed
- **THEN** modified implementation files are confined to `libs/property-tax-adapters`, its tests and synthetic fixtures, and `docs`

#### Scenario: Preserve excluded platform behavior
- **WHEN** the parser foundation is complete
- **THEN** network, acquisition, persistence, publication, orchestration, deployment, owner publication, and production-readiness behavior remain unchanged

