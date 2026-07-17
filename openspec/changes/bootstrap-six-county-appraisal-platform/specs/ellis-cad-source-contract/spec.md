## ADDED Requirements

### Requirement: Authoritative Ellis source discovery
The system SHALL discover Ellis Appraisal District releases from the official Appraisal Data Export page, SHALL assign Ellis County FIPS `48139` from version-controlled configuration, and SHALL preserve the rendered page, visible link label, source locator, redirect chain, and discovery timestamp as provenance. Discovery SHALL use the public rendered page or an approved direct artifact URL and MUST NOT extract client-bundle credentials or call an undocumented backend content API.

#### Scenario: Discover the official certified roll
- **WHEN** the rendered official page exposes one plain certified appraisal-roll link for a tax year and it resolves through approved HTTPS hosts
- **THEN** the system creates a certified Ellis source candidate and records the page and link-label evidence

#### Scenario: Stored direct URL is used
- **WHEN** a previously approved direct artifact URL is used for acquisition
- **THEN** the system periodically renders the official page to re-establish authority, release label, and continued locator validity

### Requirement: Ellis scenario-roll exclusion
The system SHALL distinguish the plain certified appraisal roll from labeled hypothetical, potential-exemption, mineral-only, or other non-equivalent releases and MUST NOT classify those artifacts as the authoritative certified all-property roll.

#### Scenario: Page lists the RC2 potential-exemption roll
- **WHEN** a link label identifies an `RC2 Potential` homestead or over-65 exemption scenario
- **THEN** the system records it as an unsupported scenario artifact and does not acquire it as certified current state

#### Scenario: Certified-roll label is ambiguous
- **WHEN** multiple candidate links cannot be classified unambiguously from official page evidence
- **THEN** automatic acquisition stops for review instead of choosing by filename or date alone

### Requirement: Ellis PACS fixed-width compatibility
The system SHALL process Ellis's full PACS fixed-width export through the reviewed shared PACS fixed-width component while retaining Ellis-specific discovery, release, policy, and expected-schema configuration. Schema compatibility with Denton SHALL be established independently by layout and data fingerprints rather than assumed from vendor or filename.

#### Scenario: Ellis matches an approved PACS schema
- **WHEN** the archive member set, PACS export version, required field positions, observed record widths, and canonical mappings match the approved Ellis fingerprint
- **THEN** the system streams the records through the shared parser and emits Ellis-specific provenance and diagnostics

#### Scenario: Ellis diverges from Denton
- **WHEN** any required Ellis member, field position, width, type, or semantic mapping differs from the reusable PACS profile
- **THEN** the system quarantines the release or selects a separately versioned Ellis mapping without changing the vendor-neutral canonical domain

### Requirement: Ellis layout content detection
The system SHALL identify the appraisal layout by its content and validated package structure rather than its filename extension, SHALL support the approved OpenDocument Spreadsheet representation, and SHALL apply the same field-boundary and partial-field protections required by the Denton fixed-width contract.

#### Scenario: Layout has a misleading compound extension
- **WHEN** the published layout filename ends in `.xlsx.ods` but its content is a valid ODS package
- **THEN** the system parses it as ODS, records its content type and checksum, and does not invoke an XLSX parser based on the name

### Requirement: Ellis historical certified releases
The system SHALL model each official Ellis certified all-property archive as a separate tax-year release and SHALL preserve the observed 2015 through 2025 history without inferring unobserved preliminary releases.

#### Scenario: Acquire a historical certified roll
- **WHEN** an approved link identifies a certified all-property roll for a prior tax year
- **THEN** the system stores and publishes it as a distinct historical certified release with its own immutable artifact identity

#### Scenario: Preliminary status is not established
- **WHEN** no official page evidence or verified artifact establishes a preliminary Ellis release
- **THEN** the system leaves preliminary data absent rather than deriving it from acquisition time or a scenario roll

### Requirement: Ellis account and owner-association grain
The system SHALL preserve `prop_id` as the Ellis account identifier and owner sequence as physical owner-row grain. It SHALL preserve ownership percentage and owner-scoped value and exemption allocations without deriving an account roll-up until an approved rule exists.

#### Scenario: Duplicate Ellis groups carry owner allocations
- **WHEN** rows sharing `prop_id` differ by owner sequence, ownership percentage, or owner-scoped values or exemptions
- **THEN** the adapter preserves distinct owner-association allocations and does not deduplicate, sum, or select an arbitrary row as the account total

#### Scenario: Duplicate Ellis groups conflict
- **WHEN** a duplicate group contains unresolved account-level differences
- **THEN** the adapter records the conflict and blocks Ellis canonical publication

### Requirement: Ellis values and child relationships
The system SHALL map Ellis market, appraised, assessed, land, improvement, agricultural, and other documented values only to matching canonical types and SHALL apply separately approved relationship gates to core appraisal and legal child tables.

#### Scenario: Validate an Ellis certified release
- **WHEN** an Ellis release is normalized
- **THEN** the system evaluates the market, appraised, and assessed hierarchy, value plausibility, required account facts, zero-orphan core appraisal baseline, and warning thresholds for legal records before publication

### Requirement: Ellis ownership privacy gate
The system SHALL classify inline owner names and mailing addresses as sensitive and SHALL keep owner and mailing-address publication disabled until Ellis confidentiality handling and a reviewed field-level publication policy are approved.

#### Scenario: Parse an Ellis property record
- **WHEN** a source row contains owner identity beside appraisal facts
- **THEN** sensitive values remain absent from logs, evidence manifests, repository fixtures, and Gold outputs while approved non-identifying facts may proceed with provenance

### Requirement: Record-free Ellis evidence manifest
The system SHALL maintain a record-free Ellis evidence manifest containing archive and layout checksums and byte counts, rendered-page and redirect provenance, exact member names, sizes and checksums, PACS and tool versions, schema and width fingerprints, and complete aggregate row, key, relationship, and value measurements.

#### Scenario: Reproduce the Ellis baseline
- **WHEN** an authorized reviewer acquires the same certified roll and layout
- **THEN** the resulting artifact, layout, member, schema, and aggregate fingerprints can be compared without source rows, owner values, addresses, credentials, or host-local paths

### Requirement: Ellis production-readiness gate
The system SHALL keep the Ellis adapter non-production until the official rendered discovery path is reproducible, scenario-roll exclusion is contract-tested, the evidence manifest is complete, undivided-interest account roll-up behavior is resolved, and the ownership publication policy is accepted.

#### Scenario: Ellis blocker remains unresolved
- **WHEN** any required Ellis decision, reproduction, or contract test is incomplete
- **THEN** immutable evidence capture may continue but Ellis cannot enter the complete six-county Gold cohort
