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
- **THEN** one logical release result is returned
- **THEN** the accepted record carries physical row number 2
- **THEN** no network, archive, or filesystem-acquisition operation is performed

#### Scenario: Preserve a quoted field containing a delimiter
- **GIVEN** a synthetic data row whose `Property_Class` field is quoted and contains a literal `|`
- **GIVEN** a doubled `""` inside that same quoted field
- **WHEN** the parser reads the member
- **THEN** the field value contains the literal `|`
- **THEN** the doubled `""` is reduced to one `"` in the field value
- **THEN** the row is bound to the observed header width

#### Scenario: Reject a UTF-8 byte-order mark
- **GIVEN** a synthetic member whose first three bytes are `EF BB BF`
- **WHEN** the parser reads the member
- **THEN** `unexpected_bom` is recorded
- **THEN** zero native records are returned

#### Scenario: Reject a record spanning two physical lines
- **GIVEN** a synthetic member containing a quoted field with an embedded LF
- **WHEN** the parser reads the member
- **THEN** `multiline_record_unsupported` is recorded
- **THEN** zero native records are returned

### Requirement: Bind fields only by the exact required header projection

The adapter SHALL bind fields by untrimmed, case-sensitive, exact header name. Aliases, documentation names, delimiter sniffing, and positional binding SHALL NOT be used. Required-header order SHALL be irrelevant.

The required foundation headers SHALL be exactly these sixteen names: `RP`, `Appraisal_Year`, `Account_Num`, `PIDN`, `GIS_Link`, `Property_Class`, `State_Use_Code`, `Exemption_Code`, `Land_Value`, `Improvement_Value`, `Total_Value`, `Appraised_Value`, `Ag_Value`, `Deed_Date`, `Notice_Date`, `Appraisal_Date`.

A blank header SHALL be rejected with `blank_header`. A header carrying surrounding whitespace SHALL be rejected. An exact duplicate header SHALL be rejected with `duplicate_header`. Two headers colliding under ASCII case folding SHALL be rejected with `header_name_collision`. A missing required header SHALL be rejected with `missing_required_header`.

Every data row SHALL contain exactly the observed header width; a row of any other width SHALL be rejected with `row_width_mismatch`. Additional headers beyond the required sixteen SHALL be accepted as metadata-only extras and SHALL record the nonfatal `extra_columns_present`. Their values SHALL be parsed only as far as row alignment requires and SHALL NOT be retained in records, diagnostics, or extras.

#### Scenario: Accept reordered required headers beside one metadata extra
- **GIVEN** all sixteen required header names in a noncanonical order
- **GIVEN** one additional synthetic metadata header
- **GIVEN** data rows matching the complete observed header width
- **WHEN** the parser validates the header and reads the data rows
- **THEN** every required field is bound by its exact name
- **THEN** `extra_columns_present` is recorded and the release is not rejected
- **THEN** the additional column value is absent from the returned records
- **THEN** the additional column value is absent from the retained diagnostics

#### Scenario: Reject a header differing only by ASCII case
- **GIVEN** a synthetic header containing both `Account_Num` and `ACCOUNT_NUM`
- **WHEN** the parser validates the header
- **THEN** `header_name_collision` is recorded
- **THEN** zero native records are returned

#### Scenario: Reject a data row narrower than the observed header
- **GIVEN** a valid synthetic header of seventeen observed columns
- **GIVEN** a data row containing sixteen fields
- **WHEN** the parser validates that row
- **THEN** `row_width_mismatch` is recorded with the one-based physical row number
- **THEN** zero native records are returned

### Requirement: Compute the deterministic layout fingerprint as provenance

The adapter SHALL compute a lowercase layout fingerprint as SHA-256 over compact canonical JSON containing the parser contract version, the encoding identifier, the delimiter and quote behavior identifier, the observed column count, and the sorted exact observed header names. The original ordered header vector SHALL be retained separately in provenance rather than inside the fingerprint document.

The fingerprint SHALL be provenance only. It MUST NOT act as an allowlist, and required-layout validation SHALL remain independent of it.

#### Scenario: Produce the same fingerprint for a reordered header
- **GIVEN** two synthetic members whose headers contain identical names in different orders
- **GIVEN** identical parser contract version, encoding, and quote behavior
- **WHEN** the adapter computes the layout fingerprint for each member
- **THEN** both fingerprints are identical lowercase SHA-256 hexadecimal digests
- **THEN** each provenance record retains its own original ordered header vector

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

`Deed_Date`, `Notice_Date`, and `Appraisal_Date` MAY be blank. A nonblank date SHALL use a one- or two-digit month and day plus a four-digit year, SHALL be calendar-valid, SHALL fall within 1900 through 2100, and SHALL retain its original lexical text as source-native; a violation SHALL be rejected with `invalid_source_date`.

The adapter MUST NOT enforce `Appraised_Value <= Total_Value`, land-plus-improvement arithmetic, or division-distribution thresholds as row-validity rules. It MUST NOT pad, truncate, case-fold, numerically coerce, silently round, or infer any field from another, and a malformed nonblank value MUST NOT become null.

#### Scenario: Preserve an approved source row
- **GIVEN** a synthetic row with division `R`
- **GIVEN** an `Appraisal_Year` equal to the caller-supplied expected source year
- **GIVEN** an `Account_Num` containing leading zeroes and punctuation
- **GIVEN** monetary and date literals inside the approved grammars
- **WHEN** the parser converts that row
- **THEN** `Account_Num` retains its leading zeroes and punctuation as text
- **THEN** `division_code` is stored separately from account identity
- **THEN** each monetary value carries an exact `Decimal` and its original lexical text
- **THEN** no canonical appraisal or tax value is populated

#### Scenario: Treat empty text as the only null
- **GIVEN** a synthetic row whose `Land_Value` is empty after trimming
- **GIVEN** a second synthetic row whose `Land_Value` is the literal text `NULL`
- **WHEN** the parser converts both rows
- **THEN** the first row records `Land_Value` as absent
- **THEN** `invalid_monetary_value` is recorded for the second row
- **THEN** zero native records are returned

#### Scenario: Reject a monetary value carrying a grouping separator
- **GIVEN** a synthetic row whose `Total_Value` is `1,250.00`
- **WHEN** the parser converts that row
- **THEN** `invalid_monetary_value` is recorded with the field name and physical row number
- **THEN** the rejected lexical text is absent from the retained diagnostics

#### Scenario: Accept an unequal appraised and total pair
- **GIVEN** a synthetic row whose `Appraised_Value` exceeds its `Total_Value`
- **GIVEN** both values inside the approved monetary grammar and range
- **WHEN** the parser converts that row
- **THEN** the row is accepted
- **THEN** both values retain their exact `Decimal` and lexical text

### Requirement: Enforce release-wide account uniqueness

`Account_Num` uniqueness SHALL be enforced across the complete logical certified release, and `division_code` SHALL NOT participate in the uniqueness key. The second occurrence of an account SHALL reject the logical release with `duplicate_account_num`. The same account text appearing in separately identified releases SHALL NOT be treated as a duplicate.

#### Scenario: Reject a release containing a repeated account
- **GIVEN** a logical synthetic release containing two otherwise valid rows sharing one `Account_Num`
- **GIVEN** differing `RP` values on those two rows
- **GIVEN** no other blocking condition
- **WHEN** the parser evaluates the complete logical release
- **THEN** `duplicate_account_num` is recorded for the second occurrence
- **THEN** zero native records are returned
- **THEN** the duplicated account text is absent from the retained diagnostics

#### Scenario: Accept one account across two identified releases
- **GIVEN** two synthetic releases with distinct caller-supplied release identifiers
- **GIVEN** one row in each release sharing the same `Account_Num`
- **WHEN** the parser evaluates each release separately
- **THEN** each release returns its accepted record
- **THEN** no `duplicate_account_num` is recorded

### Requirement: Construct the frozen adapter-local Tarrant source record

The implementation SHALL define one frozen adapter-local `TarrantCertifiedSourceRecord` containing `division_code`, `appraisal_year`, `account_num`, optional `pidn`, optional `gis_link`, optional `property_class`, optional `state_use_code`, optional `exemption_code`, exact shared `SourceNativeValue` entries for the approved monetary and date fields, and a `TarrantSourceProvenance`.

The adapter MUST NOT create Tarrant-local replacements for `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`, and MUST NOT add Tarrant vocabulary to `property_tax_domain` or `property_tax_application`.

No Tarrant field SHALL populate or imply canonical market, appraised, assessed, or taxable value, tax amount, payment, balance, delinquency, penalty, interest, exemption entitlement, or replacement status.

#### Scenario: Construct a Tarrant-native record
- **GIVEN** a valid certified-core row
- **GIVEN** caller-supplied release identifier, source member name, and expected source year
- **GIVEN** an `Appraisal_Year` matching that expected source year
- **WHEN** the adapter constructs the native record
- **THEN** a frozen `TarrantCertifiedSourceRecord` is returned
- **THEN** the record carries the approved native fields and a `TarrantSourceProvenance`
- **THEN** no `property_tax_domain` or `property_tax_application` object is constructed

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

One logical release SHALL be one caller-identified certified artifact, selected member, and expected source year. The adapter SHALL require caller-supplied `release_identifier`, `source_member_name`, and `expected_source_year`, and MUST NOT infer any of them from row data or source filenames. Release and member identifiers SHALL be bounded logical identifiers and MUST NOT be absolute paths or host-local locations.

Every native and shared record SHALL retain jurisdiction `tx-tarrant`, the release identifier, the source member name, the expected source year, source family `certified-core`, source status `certified`, the original ordered observed headers, exact-name and ASCII case-fold collision metadata, the layout fingerprint, the one-based physical row number, the parser contract version, and the exact source field name with original lexical text for each source-native value.

#### Scenario: Require the caller to identify the release
- **GIVEN** a valid synthetic member
- **GIVEN** a caller that supplies no `expected_source_year`
- **WHEN** the parser is invoked
- **THEN** the parser fails closed before reading any data row
- **THEN** no year is inferred from row data or from the member name

#### Scenario: Retain bounded provenance on an accepted record
- **GIVEN** a valid synthetic member and complete caller-supplied release identity
- **WHEN** the parser accepts a data row at physical row 5
- **THEN** the record provenance carries jurisdiction `tx-tarrant`, the release identifier, and the source member name
- **THEN** the provenance carries the original ordered observed headers and the layout fingerprint
- **THEN** the provenance carries physical row number 5 and parser contract version 1
- **THEN** the provenance carries no absolute path or host-local location

### Requirement: Emit only the closed diagnostic vocabulary with bounded metadata

The adapter SHALL emit only these diagnostic codes: `invalid_encoding`, `unexpected_bom`, `malformed_delimited_record`, `multiline_record_unsupported`, `blank_header`, `duplicate_header`, `header_name_collision`, `missing_required_header`, `row_width_mismatch`, `unsupported_layout`, `extra_columns_present`, `blank_required_value`, `invalid_division`, `invalid_appraisal_year`, `appraisal_year_mismatch`, `invalid_account_num`, `invalid_source_identifier`, `invalid_source_text`, `invalid_monetary_value`, `invalid_source_date`, and `duplicate_account_num`.

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

The synthetic helper SHALL return zero native and zero shared records when any blocking diagnostic occurs. `extra_columns_present` SHALL be nonfatal; every other code in the closed vocabulary SHALL reject the logical release. There SHALL be no row-continues quarantine path.

A future production reader SHALL follow Issue #43 by validating layout, opening the caller-supplied atomic stage, staging records invisibly, finalizing release-wide checks, and committing once; failure at any point SHALL abort the stage and expose zero accepted records. Production duplicate detection SHALL belong to the stage's bounded external unique or index contract, and the production reader MUST NOT retain every account key in Python memory.

#### Scenario: Return nothing when one row of many fails
- **GIVEN** a synthetic release of 50 rows where row 37 carries an invalid division code
- **GIVEN** 49 otherwise valid rows
- **WHEN** the parser evaluates the complete logical release
- **THEN** `invalid_division` is recorded for physical row 37
- **THEN** zero native records are returned
- **THEN** zero shared records are returned

#### Scenario: Accept a release whose only diagnostic is nonfatal
- **GIVEN** a synthetic release whose rows are all valid
- **GIVEN** one additional metadata column
- **WHEN** the parser evaluates the complete logical release
- **THEN** `extra_columns_present` is the only recorded diagnostic
- **THEN** every valid row is returned as a native record

### Requirement: Exclude sensitive and unknown-column values

The header names `Owner_Name`, `Owner_Address`, `Owner_CityState`, `Owner_Zip`, `Owner_Zip4`, `Owner_CRRT`, `Situs_Address`, and `LegalDescription` MAY participate in layout provenance. Their values MUST NOT enter records, extras, diagnostics, fixtures, evidence, logs, Gold, or API output.

Unknown-column values SHALL also be discarded, because an unknown field may carry identity or address data and the absence of a confidentiality flag is not publication permission.

#### Scenario: Carry a sensitive header name without its value
- **GIVEN** a synthetic member whose observed header includes `Owner_Name` and `Situs_Address`
- **GIVEN** synthetic non-identifying placeholder text in those two columns
- **WHEN** the parser accepts the release
- **THEN** both header names appear in the original ordered header vector in provenance
- **THEN** neither column value appears in any record, extra, or diagnostic

#### Scenario: Discard an unknown column value
- **GIVEN** a synthetic member carrying one column absent from the required projection and from the known sensitive list
- **WHEN** the parser accepts the release
- **THEN** `extra_columns_present` is recorded
- **THEN** that column value is absent from every returned record

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
- **THEN** the dependency manifests are unchanged
- **THEN** the Tarrant source documentation states that live compatibility and production readiness are unproved
