## ADDED Requirements

### Requirement: County adapter contract
The system SHALL define one source-adapter port that supports release discovery, artifact description, record streaming, and normalization diagnostics while allowing each county adapter to implement its official format independently.

#### Scenario: Register all initial counties
- **WHEN** the adapter registry is initialized
- **THEN** it contains exactly one enabled appraisal adapter for Dallas (48113), Collin (48085), Tarrant (48439), Denton (48121), Rockwall (48397), and Ellis (48139)

#### Scenario: Exercise a source contract fixture
- **WHEN** a county adapter is tested against its versioned source fixture
- **THEN** it emits canonical records and diagnostics through the shared contract without importing Airflow or database implementation modules

### Requirement: Dallas appraisal adapter
The system SHALL support Dallas Central Appraisal District comma-delimited ZIP releases and SHALL retain the originating archive member and published layout version in record provenance.

#### Scenario: Normalize a Dallas release
- **WHEN** the Dallas adapter reads a supported current, proposed, certified, or supplemental release fixture
- **THEN** it emits canonical accounts and available child records with Dallas county FIPS and the source release classification

### Requirement: Collin appraisal adapter
The system SHALL support the approved Collin Central Appraisal District PACS Microsoft Access export using a version-controlled schema and numeric-decoding contract. The system SHALL version a future Texas Open Data source as a distinct source mapping rather than silently substituting it for the measured Access export.

#### Scenario: Normalize a Collin PACS export
- **WHEN** the Collin adapter reads an Access export matching the approved schema and decoder fingerprints
- **THEN** it emits separately identified current and certified value observations with Collin county FIPS, source-field provenance, and the shared artifact identity

#### Scenario: Collin retires the Access export
- **WHEN** Collin replaces the measured Access export with its Texas Open Data offering
- **THEN** the system treats the replacement as source onboarding and blocks an automatic parser switch until its source contract and equivalence are approved

### Requirement: Tarrant appraisal adapter
The system SHALL support the approved Tarrant Appraisal District certified ZIP containing a header-driven pipe-delimited account file and SHALL treat the mutable current and companion exemption archives as separately versioned source mappings until their contracts are approved.

#### Scenario: Normalize a Tarrant certified release
- **WHEN** the archive contains exactly one member matching the approved header and schema fingerprint
- **THEN** the adapter streams canonical account records with Tarrant county FIPS, tax year, release kind, and field-level provenance

### Requirement: Denton appraisal adapter
The system SHALL support Denton Central Appraisal District full PACS fixed-width appraisal exports using a version-controlled layout mapping and SHALL detect incompatible archive, layout, or record-width changes before canonical loading.

#### Scenario: Normalize a Denton extract
- **WHEN** a Denton fixture matches a supported schema fingerprint
- **THEN** the adapter streams account and child records with Denton county FIPS, roll status, tax year, and field-level provenance

### Requirement: Rockwall appraisal adapter
The system SHALL treat Rockwall's public GIS shapefiles as optional partial enrichment and MUST NOT use them as a substitute for the full appraisal roll required by the canonical county adapter.

#### Scenario: Receive only the public Rockwall GIS export
- **WHEN** the available Rockwall artifact contains parcel geometry and a subset of market, land, improvement, owner, situs, legal, and jurisdiction attributes but lacks the full appraisal value and exemption model
- **THEN** the system records the artifact as a partial enrichment source and keeps the Rockwall appraisal adapter disabled for complete-cohort publication

### Requirement: Ellis appraisal adapter
The system SHALL support the official Ellis Appraisal District full PACS fixed-width certified appraisal export using a version-controlled layout mapping and SHALL distinguish authoritative certified rolls from labeled hypothetical scenario rolls.

#### Scenario: Normalize an Ellis export
- **WHEN** the Ellis adapter reads a supported certified-roll fixture and its ODS layout
- **THEN** it streams canonical account and child records with Ellis county FIPS, tax year, certified status, and field-level provenance

### Requirement: Canonical account identity and grain
The system SHALL identify an appraisal account by county FIPS and a county-contract-approved source account identifier and SHALL represent each account snapshot at the grain of logical release, tax year, and source as-of value. The system SHALL distinguish account identity from physical source-row and owner-association grain, and MUST NOT assume that duplicate physical rows imply duplicate business accounts or that a documented APN, property ID, or account identifier is sufficient without measured county-specific evidence. Owner-scoped value and exemption allocations MUST remain at owner-association grain until an approved account roll-up exists.

#### Scenario: Receive equal account identifiers from two counties
- **WHEN** two county adapters emit the same source account identifier
- **THEN** the system stores distinct canonical account identities because their county FIPS values differ

#### Scenario: Documented source key is duplicated
- **WHEN** source profiling finds duplicate rows for a documented property or account key
- **THEN** the adapter compares all account-level facts within each key group, preserves distinct owner associations at child grain, and records conflicts before approving the key as account identity

#### Scenario: Duplicate source rows carry owner allocations
- **WHEN** rows sharing an approved account key differ by owner sequence, ownership percentage, or owner-scoped values or exemptions
- **THEN** the adapter emits distinct owner-association allocation records and does not deduplicate, sum, or select an arbitrary row as the account total

#### Scenario: Duplicate account groups conflict
- **WHEN** rows sharing a candidate account key disagree on a required account-level fact and no approved source discriminator resolves the conflict
- **THEN** the adapter preserves the source rows and diagnostics and blocks canonical publication of the affected logical release

### Requirement: Canonical appraisal model
The system SHALL normalize available account, situs, legal description, owner, mailing address, value, exemption, jurisdiction, land, improvement, and optional geometry data without forcing one-to-many source records into a single account row.

#### Scenario: Account has multiple exemptions and improvements
- **WHEN** a source account contains multiple exemption and improvement records
- **THEN** each child is retained at its source grain and linked to the canonical account snapshot

#### Scenario: Source field is unavailable
- **WHEN** a county does not publish a canonical field
- **THEN** the adapter leaves the canonical field absent and preserves available source extras without fabricating a value

### Requirement: Explicit release semantics
The system SHALL distinguish proposed, certified, supplemental, and current snapshot releases and SHALL retain tax year separately from acquisition year.

#### Scenario: Proposed and certified data coexist
- **WHEN** proposed data for one tax year and certified data for another tax year are both loaded
- **THEN** both remain queryable with their original release status and neither silently overwrites the other

#### Scenario: One source row carries two roll years
- **WHEN** one source row contains current-year and certified-year field families with explicit year columns
- **THEN** the adapter emits separate value observations for each year and status while preserving their common source-row and artifact provenance

### Requirement: Appraisal and collection semantics
The system SHALL model market, appraised, assessed, and taxable values separately. It MUST NOT label a calculated estimate or appraisal value as an authoritative tax bill, amount due, payment, or delinquent balance.

#### Scenario: Only appraisal values are published
- **WHEN** a county release contains values and exemptions but no collector tax roll
- **THEN** authoritative tax amount, payment, and delinquency fields remain absent

### Requirement: Complete initial county cohort
The system SHALL block the first six-county publication until every initial county adapter passes contract, normalization, provenance, and idempotency tests.

#### Scenario: One county adapter is not ready
- **WHEN** five county adapters pass and one county adapter fails a required test
- **THEN** the system does not label any publication as the complete initial six-county cohort
