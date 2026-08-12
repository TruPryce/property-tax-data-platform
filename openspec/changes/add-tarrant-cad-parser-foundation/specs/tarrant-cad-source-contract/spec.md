## ADDED Requirements

### Requirement: Parse the approved certified-core physical format

The Tarrant adapter MUST strictly decode an already-selected member as ISO-8859-1, reject UTF BOMs, parse pipe-delimited records using the approved double-quote rules, accept only LF or CRLF record boundaries, reject multiline quoted records, assign one-based physical row numbers, and return no accepted records when a blocking physical-format diagnostic occurs.

#### Scenario: Parse a valid synthetic physical member
- **GIVEN** an independently authored ISO-8859-1 synthetic member
- **GIVEN** a header at physical row 1
- **GIVEN** one valid single-line data record at physical row 2
- **WHEN** the parser receives the member bytes with caller-supplied release inputs as one logical release result containing the preserved data fields and physical row number 2 without performing network or archive operations returned afterward as observable output evidence.
- **THEN** one logical release result is returned with the preserved data fields and physical row number 2
- **THEN** no network or archive operation occurs

[source_ids: c197b56afee6f9e9f5fb3bb3]

### Requirement: Validate exact headers and observed row width

The Tarrant adapter SHALL bind fields only by untrimmed case-sensitive exact header names; SHALL reject blank, whitespace-padded, duplicate, ASCII case-fold-colliding, or missing required headers; MUST validate every data row against the complete observed header width; and SHALL discard additional-column values after recording the nonfatal extra_columns_present diagnostic.

#### Scenario: Accept reordered required headers with a metadata extra
- **GIVEN** all 16 required exact header names in a noncanonical order
- **GIVEN** one additional synthetic metadata header
- **GIVEN** data rows matching the complete observed header width
- **WHEN** the parser validates the observed header and data rows as required fields bound by exact name and an extra_columns_present diagnostic recorded while the additional value is absent from records and diagnostics afterward.
- **THEN** required fields are bound by exact name
- **THEN** extra_columns_present is recorded without rejecting the release
- **THEN** the additional column value is absent from records and diagnostics

[source_ids: c197b56afee6f9e9f5fb3bb3, 7edd4e7de23f27539de02658]

### Requirement: Validate Tarrant source values without coercion

The adapter MUST preserve Account_Num as trimmed nonblank text with leading zeroes and punctuation intact, MUST enforce release-wide uniqueness without using division in the key, SHALL validate the approved division, year, identifier, text, monetary, and date grammars exactly, and MUST NOT pad, truncate, case-fold, silently round, convert monetary values through float, infer null sentinels, or enforce unapproved arithmetic inequalities.

#### Scenario: Preserve an approved source row
- **GIVEN** a synthetic row with division R
- **GIVEN** an appraisal year matching the caller-supplied expected source year
- **GIVEN** an Account_Num containing leading zeroes
- **GIVEN** valid monetary and date literals
- **WHEN** the parser converts the row as Account_Num preserved as text, division stored separately, monetary values represented by exact Decimal values with original lexical text, and no canonical value inferred in the returned record.
- **THEN** Account_Num is preserved as text with leading zeroes
- **THEN** division is stored separately from account identity
- **THEN** monetary values retain exact Decimal and lexical representations
- **THEN** no canonical value is populated

[source_ids: 7a428c5d41ca8b7be2132ac7]

### Requirement: Create an adapter-local Tarrant source record

The implementation SHALL define a frozen adapter-local TarrantCertifiedSourceRecord containing the approved Tarrant fields, source-native values, and Tarrant provenance, and MUST NOT add Tarrant vocabulary to property_tax_domain or property_tax_application or create county-local replacements for shared vendor-neutral contracts.

#### Scenario: Construct a Tarrant-native record
- **GIVEN** a valid certified-core row
- **GIVEN** caller-supplied release and member identifiers
- **GIVEN** an expected source year matching Appraisal_Year
- **WHEN** the adapter constructs the native record as a frozen TarrantCertifiedSourceRecord containing approved fields and provenance without creating a domain or application object returned afterward.
- **THEN** a frozen TarrantCertifiedSourceRecord is returned
- **THEN** the record contains approved native fields and provenance
- **THEN** no domain or application object is returned

[source_ids: 744640b7f3706d11325b9a7a, a8d0164e015d086c00140812]

### Requirement: Use the shared adapter source-record contract

After the shared contracts owned by Issue #43 are accepted and implemented, the adapter SHALL convert each valid Tarrant native row into exactly one shared AppraisalSourceRecord using jurisdiction tx-tarrant, source family certified-core, source status certified, Account_Num as source account ID, no parcel reference, exact-name source-native values, and shared provenance; it MUST NOT create a local substitute or populate canonical appraisal, taxable, tax-collection, exemption-entitlement, or replacement fields.

#### Scenario: Convert through accepted shared contracts
- **GIVEN** a valid TarrantCertifiedSourceRecord
- **GIVEN** accepted and implemented shared adapter contracts from Issue #43
- **WHEN** the adapter converts the native record as exactly one shared record with tx-tarrant provenance and exact-name source-native values returned without parcel or canonical semantic fields.
- **THEN** one shared AppraisalSourceRecord is returned
- **THEN** jurisdiction is tx-tarrant
- **THEN** source-native values retain exact Tarrant field names
- **THEN** parcel and canonical semantic fields are absent

[source_ids: 744640b7f3706d11325b9a7a, acd3ec5543a2bae6735f761b]

### Requirement: Reject a logical release atomically with safe diagnostics

The parser MUST return zero native and shared records when any blocking diagnostic occurs, SHALL use only the approved closed diagnostic vocabulary, MUST retain at most 100 diagnostics while preserving the total count and deterministic truncation state, and MUST NOT expose complete rows, arbitrary values, account values, release or member text, identities, addresses, credentials, exception text, or host-local paths.

#### Scenario: Reject a release containing a duplicate account
- **GIVEN** a logical synthetic release containing two otherwise valid rows with the same Account_Num
- **GIVEN** no other blocking error
- **WHEN** the parser evaluates the complete logical release as duplicate_account_num recorded for the second occurrence, zero records returned, and the account text absent from retained diagnostics.
- **THEN** duplicate_account_num is recorded for the second occurrence
- **THEN** zero native and shared records are returned
- **THEN** the duplicate account text is absent from diagnostics

[source_ids: 7edd4e7de23f27539de02658]

### Requirement: Use only privacy-safe synthetic fixtures

All Tarrant fixtures MUST be small, independently authored, synthetic, identity-free, redistribution-safe, and free of county bytes, production rows, owner values, mailing or situs addresses, protected identities, credentials, host paths, and network responses; sensitive and unknown-column values SHALL NOT enter records, diagnostics, logs, or outputs.

#### Scenario: Inspect the synthetic fixture corpus
- **GIVEN** the committed Tarrant fixture corpus and manifest
- **GIVEN** the prohibited identity, address, credential, county-byte, and production-record categories
- **WHEN** a maintainer reviews the fixture corpus as every fixture identified as independently authored synthetic data, prohibited categories absent, and deterministic expected results documented in the repository.
- **THEN** every fixture is identified as independently authored synthetic data
- **THEN** prohibited categories are absent
- **THEN** deterministic expected results are documented

[source_ids: 7edd4e7de23f27539de02658, 1b6acee37fd0a4979b5390da]

### Requirement: Keep the foundation adapter-local and non-production

The eventual implementation MUST remain limited to the existing Tarrant adapter boundary, Tarrant-local synthetic fixtures and tests, and directly related source documentation, and MUST NOT add acquisition, network access, services, DAGs, persistence, migrations, Bronze, Silver, Gold, workflows, infrastructure, deployment, owner publication, new dependencies, domain or application vocabulary, or a production-ready designation.

#### Scenario: Inspect the bounded implementation diff
- **GIVEN** an implementation diff derived from the accepted parser-foundation plan
- **GIVEN** the approved adapter-local and documentation boundaries
- **WHEN** a maintainer reviews the diff as no prohibited runtime or publication component present, domain and application packages unchanged, and documentation states live compatibility and production readiness are unproved.
- **THEN** no prohibited runtime or publication component is present
- **THEN** domain and application packages remain unchanged
- **THEN** documentation states that live compatibility and production readiness are unproved

[source_ids: 120cbcad362436f6c106e146, 7edd4e7de23f27539de02658, a8d0164e015d086c00140812]
