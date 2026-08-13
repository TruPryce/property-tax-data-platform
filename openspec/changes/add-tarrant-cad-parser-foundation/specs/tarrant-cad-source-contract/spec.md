## ADDED Requirements

### Requirement: Decode and parse the approved certified-core physical format

The Tarrant adapter MUST parse one already-selected certified-core text member and MUST NOT acquire archives, select members, or perform any network operation. Byte input SHALL be decoded strictly as ISO-8859-1, and string input SHALL round-trip through ISO-8859-1. UTF-8, UTF-16, and UTF-32 byte-order marks SHALL be rejected with `unexpected_bom`; text that cannot be decoded SHALL be rejected with `invalid_encoding`.

The record delimiter SHALL be `|`. The quote character SHALL be `"`, a doubled `""` inside a quoted field SHALL represent one literal `"`, no escape character SHALL be supported, and malformed quoting SHALL fail closed with `malformed_delimited_record`. Embedded pipes SHALL be accepted only inside a quoted field. Embedded CR or LF inside a quoted field SHALL be rejected with `multiline_record_unsupported`, so that every accepted record has exactly one physical source-row number.

Both LF and CRLF record boundaries SHALL be accepted. A single trailing line ending SHALL be allowed. Blank and whitespace-only records SHALL NOT be silently skipped. The header SHALL be physical row 1 and data rows SHALL begin at physical row 2, with one-based physical row numbers assigned in file order.

The parser contract version SHALL be `1`.

#### Scenario: Parse a valid synthetic member
- **GIVEN** an independently authored ISO-8859-1 synthetic member with no byte-order mark
- **GIVEN** a header at physical row 1 and one valid single-line data record at physical row 2
- **GIVEN** caller-supplied release identifier, source member name, and expected source year
- **WHEN** the parser reads the member
- **THEN** one `TarrantValidationReport` is returned with `release_accepted` true
- **THEN** `accepted_row_count` is 1
- **THEN** no network, archive, or filesystem-acquisition operation is performed

#### Scenario: Accept a quoted field containing a delimiter
- **GIVEN** a synthetic member whose observed header is exactly the sixteen required names
- **GIVEN** a data row whose `Property_Class` field is quoted and contains one literal `|`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 1
- **THEN** no `row_width_mismatch` is recorded

#### Scenario: Accept a doubled quote inside a quoted field
- **GIVEN** a synthetic member whose observed header is exactly the sixteen required names
- **GIVEN** a data row whose `Property_Class` field is written as the seven characters `"a""|b"`, opening and closing with a quote
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 1
- **THEN** no `malformed_delimited_record` is recorded
- **THEN** no `row_width_mismatch` is recorded

#### Scenario: Reject an unbalanced quote
- **GIVEN** a synthetic data row whose `Property_Class` field opens a quote and never closes it
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `malformed_delimited_record` is recorded
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

#### Scenario: Reject a UTF-8 byte-order mark
- **GIVEN** a synthetic member whose first three bytes are `EF BB BF`
- **WHEN** the parser reads the member
- **THEN** `unexpected_bom` is recorded
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

#### Scenario: Reject a record spanning two physical lines
- **GIVEN** a synthetic member containing a quoted field with an embedded LF
- **WHEN** the parser reads the member
- **THEN** `multiline_record_unsupported` is recorded
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

### Requirement: Bind fields only by the exact required header projection

The adapter SHALL bind fields by untrimmed, case-sensitive, exact header name. Aliases, documentation names, delimiter sniffing, and positional binding SHALL NOT be used. Required-header order SHALL be irrelevant.

The required foundation headers SHALL be exactly these sixteen names: `RP`, `Appraisal_Year`, `Account_Num`, `PIDN`, `GIS_Link`, `Property_Class`, `State_Use_Code`, `Exemption_Code`, `Land_Value`, `Improvement_Value`, `Total_Value`, `Appraised_Value`, `Ag_Value`, `Deed_Date`, `Notice_Date`, `Appraisal_Date`.

A blank header SHALL be rejected with `blank_header`. A header carrying surrounding ASCII whitespace SHALL be rejected with `unsupported_layout`. An exact duplicate header SHALL be rejected with `duplicate_header`. Two headers colliding under ASCII case folding SHALL be rejected with `header_name_collision`. A missing required header SHALL be rejected with `missing_required_header`.

`unsupported_layout` SHALL be the code for every observed-layout rejection that the four preceding codes do not cover: a header carrying surrounding ASCII whitespace, a header containing an ASCII control character, an observed header of zero columns, and a member whose first physical row is absent. It MUST NOT be used for a condition that one of the other twenty codes names.

Every data row SHALL contain exactly the observed header width; a row of any other width SHALL be rejected with `row_width_mismatch`. Additional headers beyond the required sixteen SHALL be accepted as metadata-only extras and SHALL record the nonfatal `extra_columns_present`. Their values SHALL be parsed only as far as row alignment requires and SHALL NOT be retained in records, diagnostics, or extras.

#### Scenario: Accept reordered required headers beside one metadata extra
- **GIVEN** all sixteen required header names in a noncanonical order
- **GIVEN** one additional synthetic metadata header
- **GIVEN** data rows matching the complete observed header width
- **WHEN** the parser validates the header and reads the data rows
- **THEN** every required field is bound by its exact name
- **THEN** `extra_columns_present` is recorded and the release is not rejected
- **THEN** the additional column value is absent from the report
- **THEN** the additional column value is absent from the retained diagnostics

#### Scenario: Reject a header differing only by ASCII case
- **GIVEN** a synthetic header containing both `Account_Num` and `ACCOUNT_NUM`
- **WHEN** the parser validates the header
- **THEN** `header_name_collision` is recorded
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

#### Scenario: Reject a data row narrower than the observed header
- **GIVEN** a valid synthetic header of seventeen observed columns
- **GIVEN** a data row containing sixteen fields
- **WHEN** the parser validates that row
- **THEN** `row_width_mismatch` is recorded with the one-based physical row number
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

### Requirement: Compute the deterministic layout fingerprint as provenance

The adapter SHALL compute a lowercase layout fingerprint as the SHA-256 hexadecimal digest of one canonical JSON document. D1 fixes the five members of that document; the exact keys, literals, and serialization below are this foundation's binding choice, so that two compliant implementations produce identical digests. They are a serialization contract, not a claim about any live release.

The document SHALL be a JSON object with exactly these five keys and no others:

- `parser_contract_version` — the integer `1`;
- `encoding` — the string `iso-8859-1`;
- `dialect` — the string `pipe-delimited-double-quote-v1`, denoting delimiter `|`, quote `"`, doubled `""` as a literal quote, no escape character, and no multiline record;
- `column_count` — the observed column count as an integer;
- `headers_sorted` — the exact observed header names, unmodified, sorted by Unicode code point ascending.

The document SHALL be serialized with keys sorted ascending by Unicode code point, with the separators `,` and `:` and no other whitespace, with non-ASCII characters emitted literally rather than escaped, and SHALL be encoded as UTF-8 before hashing. The digest SHALL be rendered as lowercase hexadecimal.

The original ordered header vector SHALL be retained separately in provenance rather than inside the fingerprint document. The fingerprint SHALL be provenance only: it MUST NOT act as an allowlist, and required-layout validation SHALL remain independent of it.

#### Scenario: Produce a byte-exact fingerprint for a known document
- **GIVEN** an observed header of exactly the sixteen required names and no extras
- **GIVEN** parser contract version 1, ISO-8859-1 encoding, and the `pipe-delimited-double-quote-v1` dialect
- **WHEN** the adapter serializes the fingerprint document
- **THEN** the serialized bytes are the UTF-8 encoding of a five-key JSON object with keys in the order `column_count`, `dialect`, `encoding`, `headers_sorted`, `parser_contract_version`
- **THEN** the serialized bytes contain no space, tab, or newline outside a header name
- **THEN** the digest is the lowercase hexadecimal SHA-256 of those bytes

#### Scenario: Produce the same fingerprint for a reordered header
- **GIVEN** two synthetic members whose headers contain identical names in different orders
- **GIVEN** identical parser contract version, encoding, and quote behavior
- **WHEN** the adapter computes the layout fingerprint for each member
- **THEN** both fingerprints are identical lowercase SHA-256 hexadecimal digests
- **THEN** each report retains its own `observed_headers` in the original order

#### Scenario: Validate layout independently of the fingerprint
- **GIVEN** a synthetic member missing the `Ag_Value` header
- **WHEN** the parser validates the required header projection
- **THEN** `missing_required_header` is recorded
- **THEN** the rejection does not depend on any previously observed fingerprint

### Requirement: Validate the approved lexical, null, and range grammars

Surrounding ASCII whitespace SHALL mean space, tab, CR, LF, vertical tab, and form feed. Empty text after permitted trimming SHALL be the only null representation; the literals `NULL`, `N/A`, `None`, and similar sentinels SHALL NOT be treated as null.

`RP` SHALL be required, untrimmed, and exactly one of `R`, `C`, `M`, or `P`; any other value SHALL be rejected with `invalid_division`. `Appraisal_Year` SHALL be required, exactly four ASCII digits, parsed to `int`, accepted from 1900 through 2100 inclusive, and SHALL equal the caller-supplied expected source year; a malformed year SHALL be rejected with `invalid_appraisal_year` and a mismatched year with `appraisal_year_mismatch`. `Account_Num` SHALL be trimmed only for surrounding ASCII whitespace, SHALL contain 1 through 64 visible ASCII characters, SHALL preserve remaining case, punctuation, prefixes, and leading zeroes, and SHALL NOT be parsed numerically; a violation SHALL be rejected with `invalid_account_num`.

`PIDN` and `GIS_Link` MAY be blank as absence. A nonblank value SHALL be ASCII-trimmed, SHALL contain 1 through 512 non-control characters, and SHALL be preserved exactly after trimming; a violation SHALL be rejected with `invalid_source_identifier`. `Property_Class`, `State_Use_Code`, and `Exemption_Code` MAY be blank; a nonblank value SHALL be ASCII-trimmed, SHALL contain 1 through 128 non-control characters, and SHALL remain source-native text; a violation SHALL be rejected with `invalid_source_text`.

`Total_Value` and `Appraised_Value` SHALL be required nonblank values, and a blank SHALL be rejected with `blank_required_value`. `Land_Value`, `Improvement_Value`, and `Ag_Value` MAY be blank as source absence. Monetary grammar SHALL be `[0-9]+(?:\.[0-9]{1,4})?`. Monetary values SHALL parse with `decimal.Decimal`, SHALL retain their exact trimmed lexical text, and SHALL fall from zero through `10**28 - 1` inclusive. Leading signs, currency symbols, grouping separators, exponent notation, trailing decimal points, excessive scale, and otherwise malformed decimal text SHALL be rejected with `invalid_monetary_value`.

`Deed_Date`, `Notice_Date`, and `Appraisal_Date` MAY be blank. A nonblank date SHALL be ASCII-trimmed and SHALL match exactly `^(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])/([0-9]{4})$` — a one- or two-digit month, a solidus, a one- or two-digit day, a solidus, and a four-digit year. D6 supplies this separator and component order; D2 fixes the components, calendar validity, and range.

A date matching that pattern SHALL additionally be calendar-valid, so `2/30/2025` and `4/31/2025` are rejected, and SHALL fall within 1900 through 2100 inclusive. The original trimmed lexical text SHALL be retained as source-native, so `3/14/2025` and `03/14/2025` are preserved as written and are not normalized to one another. Any other separator, component order, two-digit year, non-ASCII digit, or otherwise malformed date SHALL be rejected with `invalid_source_date`.

The implementation MUST NOT accept a second separator, MUST NOT reorder components, and MUST NOT rewrite an accepted date into a canonical form.

The adapter MUST NOT enforce `Appraised_Value <= Total_Value`, land-plus-improvement arithmetic, or division-distribution thresholds as row-validity rules. It MUST NOT pad, truncate, case-fold, numerically coerce, silently round, or infer any field from another, and a malformed nonblank value MUST NOT become null.

#### Scenario: Accept an approved source row
- **GIVEN** a synthetic row with division `R`
- **GIVEN** an `Appraisal_Year` equal to the caller-supplied expected source year
- **GIVEN** an `Account_Num` containing leading zeroes and punctuation
- **GIVEN** monetary and date literals inside the approved grammars
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 1
- **THEN** `diagnostics` is empty

#### Scenario: Reject a date carrying an unapproved separator
- **GIVEN** a synthetic row whose `Deed_Date` is `2025-03-14`
- **GIVEN** every other field inside the approved grammars
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `invalid_source_date` is recorded with the field name and physical row number
- **THEN** `release_accepted` is false
- **THEN** the rejected date text is absent from the retained diagnostics

#### Scenario: Accept one- and two-digit date components
- **GIVEN** a synthetic row whose `Deed_Date` is `3/14/2025`
- **GIVEN** a second synthetic row whose `Notice_Date` is `03/14/2025`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 2
- **THEN** no `invalid_source_date` is recorded

#### Scenario: Reject a calendar-invalid date matching the pattern
- **GIVEN** a synthetic row whose `Appraisal_Date` is `2/30/2025`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `invalid_source_date` is recorded
- **THEN** `release_accepted` is false

#### Scenario: Distinguish accounts differing only by leading zeroes
- **GIVEN** two otherwise valid synthetic rows whose `Account_Num` values are `00123` and `123`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 2
- **THEN** no `duplicate_account_num` is recorded

#### Scenario: Treat empty text as the only null
- **GIVEN** a synthetic row whose `Land_Value` is empty after trimming
- **GIVEN** a second synthetic row whose `Land_Value` is the literal text `NULL`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** no diagnostic is recorded for the first row
- **THEN** `invalid_monetary_value` is recorded for the second row
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

#### Scenario: Reject a monetary value carrying a grouping separator
- **GIVEN** a synthetic row whose `Total_Value` is `1,250.00`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `invalid_monetary_value` is recorded with the field name and physical row number
- **THEN** `release_accepted` is false
- **THEN** the rejected lexical text is absent from the retained diagnostics

#### Scenario: Accept an unequal appraised and total pair
- **GIVEN** a synthetic row whose `Appraised_Value` exceeds its `Total_Value`
- **GIVEN** both values inside the approved monetary grammar and range
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 1
- **THEN** no monetary diagnostic is recorded

### Requirement: Enforce release-wide account uniqueness

`Account_Num` uniqueness SHALL be enforced across the complete logical certified release, and `division_code` SHALL NOT participate in the uniqueness key. The second occurrence of an account SHALL reject the logical release with `duplicate_account_num`. The same account text appearing in separately identified releases SHALL NOT be treated as a duplicate.

#### Scenario: Reject a release containing a repeated account
- **GIVEN** a logical synthetic release containing two otherwise valid rows sharing one `Account_Num`
- **GIVEN** differing `RP` values on those two rows
- **GIVEN** no other blocking condition
- **WHEN** the parser evaluates the complete logical release
- **THEN** `duplicate_account_num` is recorded for the second occurrence
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0
- **THEN** the duplicated account text is absent from the retained diagnostics

#### Scenario: Accept one account across two identified releases
- **GIVEN** two synthetic releases with distinct caller-supplied release identifiers
- **GIVEN** one row in each release sharing the same `Account_Num`
- **WHEN** the caller invokes `validate_certified_member` for each release
- **THEN** each report has `release_accepted` true
- **THEN** each report has `accepted_row_count` 1
- **THEN** no `duplicate_account_num` is recorded

### Requirement: Expose the bounded interim validation result

Until the Issue #43 contracts land, the adapter cannot return a row-shaped result without inventing a substitute for a contract that issue owns. The interim scope is therefore a **validator**, not a row producer, and its complete public surface SHALL be the following two frozen types and one function in `property_tax_adapters.sources.texas.tarrant`.

The entry point SHALL be `validate_certified_member(data, *, release_identifier, source_member_name, expected_source_year)`, accepting `bytes` or `str` and returning one `TarrantValidationReport`. It SHALL be a pure function that performs no I/O, retains no state between calls, and holds no reference to its input after returning.

`TarrantValidationReport` SHALL be a frozen dataclass with exactly these fields: `parser_contract_version: int`, `release_accepted: bool`, `layout_fingerprint: str | None`, `observed_headers: tuple[str, ...]`, `accepted_row_count: int`, `diagnostics: tuple[TarrantDiagnostic, ...]`, `total_diagnostic_count: int`, and `diagnostics_truncated: bool`. `layout_fingerprint` SHALL be `None` only when the header could not be read at all. `accepted_row_count` SHALL be `0` whenever `release_accepted` is `False`.

`TarrantDiagnostic` SHALL be a frozen dataclass with exactly these fields: `code: str` from the closed vocabulary, `field_name: str | None`, `physical_row_number: int | None`, and `layout_fingerprint: str | None`. It SHALL carry no other attribute, so the redaction rules are enforced by the type rather than by convention.

The report SHALL NOT carry parsed field values, rows, or any per-row payload. It MUST NOT be persisted, cached, logged, or returned across a process boundary, and its lifetime SHALL end with the caller that received it. It is not a substitute for `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`, and it MUST NOT grow row-carrying fields to become one.

When Issue #43 lands, row materialization SHALL be added as a separate entry point returning `TarrantCertifiedSourceRecord` values, reusing this validation rather than reimplementing it. `TarrantValidationReport` SHALL remain valid at that point and MUST NOT be removed or repurposed to carry records.

#### Scenario: Validate an accepted release without constructing a record
- **GIVEN** the shared Issue #43 contracts are absent from the repository
- **GIVEN** a valid synthetic member of three data rows and complete caller-supplied release identity
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** one `TarrantValidationReport` is returned with `release_accepted` true
- **THEN** `accepted_row_count` is 3
- **THEN** `layout_fingerprint` and `observed_headers` are populated
- **THEN** the report exposes no parsed field value and no row

#### Scenario: Report a rejected release with a zero accepted count
- **GIVEN** a synthetic release whose row 4 carries an invalid division code
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0
- **THEN** `diagnostics` contains one `TarrantDiagnostic` with code `invalid_division` and physical row number 4
- **THEN** that diagnostic carries no attribute beyond code, field name, physical row number, and layout fingerprint

### Requirement: Construct the frozen adapter-local Tarrant source record

The implementation SHALL define one frozen adapter-local `TarrantCertifiedSourceRecord` containing `division_code`, `appraisal_year`, `account_num`, optional `pidn`, optional `gis_link`, optional `property_class`, optional `state_use_code`, optional `exemption_code`, exact shared `SourceNativeValue` entries for the approved monetary and date fields, and a `TarrantSourceProvenance`.

Because the approved record holds shared `SourceNativeValue` entries, this requirement depends on the contracts owned by Issue #43 and SHALL NOT be implemented before they are accepted and implemented. The adapter MUST NOT create Tarrant-local replacements for `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord` in order to build this record sooner. Physical parsing, header binding, lexical validation, uniqueness, atomic rejection, and the diagnostic vocabulary carry no such dependency and are implementable independently, returning validated values and diagnostics rather than a record type.

The adapter MUST NOT add Tarrant vocabulary to `property_tax_domain` or `property_tax_application`. The existing `TARRANT_SOURCE` registry definition already imports both packages and SHALL be preserved unchanged, so the boundary is that neither package is modified and neither gains Tarrant parser vocabulary — not that the adapter module imports nothing from them.

No Tarrant field SHALL populate or imply canonical market, appraised, assessed, or taxable value, tax amount, payment, balance, delinquency, penalty, interest, exemption entitlement, or replacement status.

#### Scenario: Construct a Tarrant-native record
- **GIVEN** accepted and implemented shared `SourceNativeValue` contracts from Issue #43
- **GIVEN** a valid certified-core row
- **GIVEN** caller-supplied release identifier, source member name, and expected source year
- **GIVEN** an `Appraisal_Year` matching that expected source year
- **WHEN** the adapter constructs the native record
- **THEN** a frozen `TarrantCertifiedSourceRecord` is returned
- **THEN** the record carries the approved native fields and a `TarrantSourceProvenance`
- **THEN** no `property_tax_domain` or `property_tax_application` object is constructed

#### Scenario: Parse and validate while the shared contracts are absent
- **GIVEN** the shared Issue #43 contracts are absent from the repository
- **GIVEN** a valid synthetic member and complete caller-supplied release identity
- **WHEN** the parser decodes, binds headers, and validates the approved lexical grammars
- **THEN** one `TarrantValidationReport` is returned
- **THEN** no `TarrantCertifiedSourceRecord` is constructed
- **THEN** no county-local replacement for a shared contract is defined

#### Scenario: Retain a decoded quoted value on a constructed record
- **GIVEN** accepted and implemented shared `SourceNativeValue` contracts from Issue #43
- **GIVEN** a valid certified-core row whose `Property_Class` field is written as `"a""|b"`
- **WHEN** the adapter constructs the native record
- **THEN** `property_class` is the four-character text `a"|b`
- **THEN** the literal `|` is preserved rather than treated as a delimiter
- **THEN** the doubled `""` is reduced to one `"`

#### Scenario: Retain exact source values on a constructed record
- **GIVEN** accepted and implemented shared `SourceNativeValue` contracts from Issue #43
- **GIVEN** a valid certified-core row whose `Account_Num` carries leading zeroes and punctuation
- **GIVEN** monetary literals inside the approved grammar
- **WHEN** the adapter constructs the native record
- **THEN** `account_num` retains its leading zeroes and punctuation as text
- **THEN** `division_code` is stored separately from account identity
- **THEN** each monetary value carries an exact `Decimal` and its original lexical text
- **THEN** the record provenance carries the release identifier, source member name, layout fingerprint, and one-based physical row number

#### Scenario: Leave canonical semantics absent
- **GIVEN** a valid certified-core row carrying `Total_Value`, `Appraised_Value`, and `Exemption_Code`
- **WHEN** the adapter constructs the native record
- **THEN** the record exposes those three as source-native values
- **THEN** no canonical taxable value, tax amount, or exemption entitlement is present

### Requirement: Convert through the shared Issue #43 contracts

After the shared contracts owned by Issue #43 are accepted and implemented, the adapter SHALL convert each valid Tarrant native row into exactly one shared `AppraisalSourceRecord` using jurisdiction `tx-tarrant`, source account ID `Account_Num`, appraisal year `Appraisal_Year`, source family `certified-core`, source status `certified`, and parcel reference `None`.

Source-native identifiers SHALL be `Account_Num` plus any nonblank `PIDN` and `GIS_Link`. Source-native values SHALL be keyed by exact Tarrant field name for `RP`, `Property_Class`, `State_Use_Code`, `Exemption_Code`, `Land_Value`, `Improvement_Value`, `Total_Value`, `Appraised_Value`, `Ag_Value`, `Deed_Date`, `Notice_Date`, and `Appraisal_Date`. Shared provenance SHALL be derived from the Tarrant-native provenance.

One certified-core physical row SHALL produce one certified shared record. No current, exemption, companion, jurisdiction-taxable, or replacement record SHALL be synthesized, and values or identifiers SHALL NOT be copied between source families. Until Issue #43 is accepted and implemented, the adapter MUST NOT construct a county-local substitute for any shared contract.

#### Scenario: Convert through accepted shared contracts
- **GIVEN** a valid `TarrantCertifiedSourceRecord`
- **GIVEN** accepted and implemented shared adapter contracts from Issue #43
- **WHEN** the adapter converts that native record
- **THEN** exactly one shared `AppraisalSourceRecord` is returned
- **THEN** jurisdiction is `tx-tarrant` and source family is `certified-core`
- **THEN** source-native values retain their exact Tarrant field names
- **THEN** parcel reference and canonical semantic fields are absent

#### Scenario: Wait rather than substitute while Issue #43 is open
- **GIVEN** the shared Issue #43 contracts are absent from the repository
- **WHEN** a maintainer reviews the Tarrant adapter module
- **THEN** no county-local `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord` replacement is defined
- **THEN** the native parsing, validation, and diagnostic behavior is present and executable

### Requirement: Require caller-supplied release identity and retain bounded provenance

One logical release SHALL be one caller-identified certified artifact, selected member, and expected source year. The adapter SHALL require caller-supplied `release_identifier`, `source_member_name`, and `expected_source_year`, and MUST NOT infer any of them from row data or source filenames.

D4 requires those identifiers to be bounded logical identifiers rather than absolute paths or host-local locations but sets no exact bound. Decision D7 supplies one, and merging this change is what accepts it: `release_identifier` and `source_member_name` SHALL each be a `str` of 1 through 128 characters after no trimming, SHALL contain only ASCII letters, digits, `.`, `_`, and `-`, and SHALL NOT begin with `.` or `-`. That alphabet admits no `/`, `\\`, `:`, whitespace, or control character, so an absolute path, a UNC path, a drive-qualified path, and a parent-directory traversal are all unrepresentable rather than merely discouraged. `expected_source_year` SHALL be an `int` from 1900 through 2100 inclusive. `bool` SHALL NOT be accepted for it even though `bool` subclasses `int` in Python, and a non-`str` `release_identifier` or `source_member_name` SHALL be rejected rather than coerced.

A caller-supplied value violating any of these bounds SHALL raise `ValueError` before the member is read. This is a caller contract rather than source data, so it fails as a programming error and produces no diagnostic and no report; the closed diagnostic vocabulary describes the source, never the caller.

When records exist — that is, after Issue #43 lands and the record layer is built — every native and shared record SHALL retain jurisdiction `tx-tarrant`, the release identifier, the source member name, the expected source year, source family `certified-core`, source status `certified`, the original ordered observed headers, exact-name and ASCII case-fold collision metadata, the layout fingerprint, the one-based physical row number, the parser contract version, and the exact source field name with original lexical text for each source-native value. Until then the report carries the layout fingerprint, the observed headers, and the parser contract version, and the remaining provenance lives in the caller's own inputs.

#### Scenario: Require the caller to identify the release
- **GIVEN** a valid synthetic member
- **GIVEN** a caller that supplies no `expected_source_year`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** the call fails before any data row is read
- **THEN** no year is inferred from row data or from the member name

#### Scenario: Reject a caller argument of the wrong type
- **GIVEN** a valid synthetic member
- **GIVEN** a `release_identifier` of `b"tarrant-2025"` rather than a `str`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `ValueError` is raised before the member is read
- **THEN** the value is not coerced to `str`

#### Scenario: Reject a boolean expected source year
- **GIVEN** a valid synthetic member
- **GIVEN** an `expected_source_year` of `True`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `ValueError` is raised before the member is read
- **THEN** the value is not treated as the integer 1

#### Scenario: Reject a release identifier shaped like a path
- **GIVEN** a valid synthetic member
- **GIVEN** a `source_member_name` of `/var/tmp/tarrant/2025.txt`
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** `ValueError` is raised before the member is read
- **THEN** no `TarrantValidationReport` is produced
- **THEN** no diagnostic is recorded

#### Scenario: Retain bounded provenance in the report
- **GIVEN** a valid synthetic member and complete caller-supplied release identity
- **WHEN** the caller invokes `validate_certified_member`
- **THEN** the report carries the layout fingerprint and the observed headers in their original order
- **THEN** the report carries parser contract version 1
- **THEN** the report carries no absolute path or host-local location

### Requirement: Emit only the closed diagnostic vocabulary with bounded metadata

The adapter SHALL emit only these diagnostic codes: `invalid_encoding`, `unexpected_bom`, `malformed_delimited_record`, `multiline_record_unsupported`, `blank_header`, `duplicate_header`, `header_name_collision`, `missing_required_header`, `row_width_mismatch`, `unsupported_layout`, `extra_columns_present`, `blank_required_value`, `invalid_division`, `invalid_appraisal_year`, `appraisal_year_mismatch`, `invalid_account_num`, `invalid_source_identifier`, `invalid_source_text`, `invalid_monetary_value`, `invalid_source_date`, and `duplicate_account_num`.

The vocabulary SHALL remain closed at these twenty-one codes as D4 fixed them. Every code SHALL be reachable by this change, including `invalid_source_date`.

A diagnostic SHALL contain only its stable code and, where applicable, an approved field or header name, the one-based physical row number, and the layout fingerprint. Unknown source header text SHALL NOT be echoed. A diagnostic MUST NOT contain a complete row, an arbitrary field value, an account value, release or member text, an owner name, an address, a protected identity, a credential, exception text, or a host-local path.

At most 100 diagnostics SHALL be retained, the total diagnostic count SHALL be preserved, and truncation SHALL be marked deterministically.

#### Scenario: Truncate a large diagnostic set deterministically
- **GIVEN** a synthetic release producing 140 blocking diagnostics
- **WHEN** the parser evaluates the complete logical release
- **THEN** exactly 100 diagnostics are retained
- **THEN** the preserved total count is 140
- **THEN** the result is marked as truncated
- **THEN** repeating the same run retains the same 100 diagnostics in the same order

#### Scenario: Keep an unknown header name out of a diagnostic
- **GIVEN** a synthetic member carrying one additional column named `Owner_Name`
- **WHEN** the parser records `extra_columns_present`
- **THEN** the diagnostic carries only its stable code and approved metadata
- **THEN** the text `Owner_Name` is absent from the diagnostic
- **THEN** the value of that column is absent from the diagnostic

### Requirement: Reject a logical release atomically

When any blocking diagnostic occurs the report SHALL carry `release_accepted` false and `accepted_row_count` zero, and once the record layer exists the same condition SHALL yield zero native and zero shared records. `extra_columns_present` SHALL be nonfatal; every other code in the closed vocabulary SHALL reject the logical release. There SHALL be no row-continues quarantine path, and no partially accepted release SHALL be observable in either form.

A future production reader SHALL follow Issue #43 by validating layout, opening the caller-supplied atomic stage, staging records invisibly, finalizing release-wide checks, and committing once; failure at any point SHALL abort the stage and expose zero accepted records. Production duplicate detection SHALL belong to the stage's bounded external unique or index contract, and the production reader MUST NOT retain every account key in Python memory.

#### Scenario: Return nothing when one row of many fails
- **GIVEN** a synthetic release of 50 rows where row 37 carries an invalid division code
- **GIVEN** 49 otherwise valid rows
- **WHEN** the parser evaluates the complete logical release
- **THEN** `invalid_division` is recorded for physical row 37
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

#### Scenario: Accept a release whose only diagnostic is nonfatal
- **GIVEN** a synthetic release whose rows are all valid
- **GIVEN** one additional metadata column
- **WHEN** the parser evaluates the complete logical release
- **THEN** `extra_columns_present` is the only recorded diagnostic
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` equals the number of data rows

### Requirement: Exclude sensitive and unknown-column values

The header names `Owner_Name`, `Owner_Address`, `Owner_CityState`, `Owner_Zip`, `Owner_Zip4`, `Owner_CRRT`, `Situs_Address`, and `LegalDescription` MAY participate in layout provenance. Their values MUST NOT enter records, extras, diagnostics, fixtures, evidence, logs, Gold, or API output.

Unknown-column values SHALL also be discarded, because an unknown field may carry identity or address data and the absence of a confidentiality flag is not publication permission.

#### Scenario: Carry a sensitive header name without its value
- **GIVEN** a synthetic member whose observed header includes `Owner_Name` and `Situs_Address`
- **GIVEN** synthetic non-identifying placeholder text in those two columns
- **WHEN** the parser accepts the release
- **THEN** both header names appear in the original ordered header vector in provenance
- **THEN** neither column value appears in the report or its diagnostics

#### Scenario: Discard an unknown column value
- **GIVEN** a synthetic member carrying one column absent from the required projection and from the known sensitive list
- **WHEN** the parser accepts the release
- **THEN** `extra_columns_present` is recorded
- **THEN** that column value is absent from the report and its diagnostics

### Requirement: Use only privacy-safe synthetic fixtures

All Tarrant fixtures MUST be small, independently authored, synthetic, identity-free, and redistribution-safe. They MUST NOT contain county bytes, production rows, owner values, mailing or situs addresses, protected identities, credentials, host paths, or network responses. Expected fixture results SHALL be authored independently rather than generated by the code under test.

#### Scenario: Inspect the synthetic fixture corpus
- **GIVEN** the committed Tarrant fixture module and its documented provenance
- **GIVEN** the prohibited identity, address, credential, county-byte, and production-record categories
- **WHEN** a maintainer reviews the fixture corpus
- **THEN** every fixture is identified as independently authored synthetic data
- **THEN** no prohibited category appears in the corpus
- **THEN** each expected result is stated literally rather than produced by the parser

### Requirement: Keep the foundation adapter-local and non-production

The implementation MUST remain limited to the existing Tarrant adapter module, Tarrant-local synthetic fixtures and tests, and directly related Tarrant source documentation. It MUST NOT add archive acquisition, network access, services, DAGs, persistence, migrations, Bronze, Silver, Gold, workflows, infrastructure, deployment, owner publication, new dependencies, domain or application vocabulary, or a production-ready designation.

The documentation SHALL state that live-release compatibility and production readiness remain unproved.

#### Scenario: Inspect the bounded implementation diff
- **GIVEN** an implementation diff derived from this accepted plan
- **GIVEN** the approved adapter-local and documentation boundaries
- **WHEN** a maintainer reviews the diff
- **THEN** no acquisition, network, service, DAG, persistence, or deployment component is present
- **THEN** the `property_tax_domain` and `property_tax_application` packages are unchanged
- **THEN** the preserved `TARRANT_SOURCE` registry definition still imports both packages
- **THEN** no Tarrant parser vocabulary is added to either package
- **THEN** the dependency manifests are unchanged
- **THEN** the Tarrant source documentation states that live compatibility and production readiness are unproved
