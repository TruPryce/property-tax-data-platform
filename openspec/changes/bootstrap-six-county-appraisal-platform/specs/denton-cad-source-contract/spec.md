## ADDED Requirements

### Requirement: Authoritative Denton source discovery
The system SHALL discover Denton Central Appraisal District bulk releases from the official `dentoncad.net` data directory, SHALL assign Denton County FIPS `48121` from version-controlled configuration, and SHALL preserve the year directory, roll-status directory, visible filename, source locator, discovery timestamp, and page metadata as provenance.

#### Scenario: Discover a Denton roll
- **WHEN** a tax-year directory contains one unambiguous ZIP in a supported `PreliminaryDataAllProperty` or `CertifiedDataAllProperty` directory and a compatible published layout
- **THEN** the system creates a source candidate whose tax year and preliminary or certified status derive from the authoritative directory path

#### Scenario: Discover a new tax-year directory
- **WHEN** the official root lists a year not yet present in the source registry
- **THEN** the system records the year as a discovery candidate without requiring a hard-coded current year

#### Scenario: Denton discovery is ambiguous
- **WHEN** a supported roll directory contains no ZIP, multiple candidate ZIPs, or no identifiable compatible layout
- **THEN** the system records an actionable discovery failure and schedules no automatic acquisition

### Requirement: Denton parallel-source control
The system SHALL treat Denton's official nightly appraisal CSV, text, geodatabase, and GIS schema as a distinct, unverified source mapping from the annual full PACS Appraisal Export. It MUST NOT silently substitute the nightly source for preliminary, certified, or roll-correction archives until coverage, fields, identity, status, cadence, and equivalence are measured and approved.

#### Scenario: Nightly appraisal extract is discovered
- **WHEN** the official data directory exposes a nightly appraisal artifact
- **THEN** the system records a separate source candidate and does not parse it with the annual PACS fixed-width mapping

#### Scenario: Product requires fresher Denton data
- **WHEN** the accepted freshness target cannot be met by the annual PACS and roll-correction sources
- **THEN** the nightly extract receives its own source-contract update before it can supply a latest-available product

### Requirement: Denton conditional observation
The system SHALL use Denton's observed `ETag` and `Last-Modified` validators for conditional observation, SHALL treat only a valid status 304 response bound to a previously acquired artifact as a no-change signal, and SHALL retain SHA-256 as immutable artifact identity.

#### Scenario: Conditional request returns 304
- **WHEN** Denton honors a conditional request using validators bound to a completed prior artifact
- **THEN** the system records a no-change observation without downloading or republishing the artifact

#### Scenario: Conditional request returns content
- **WHEN** the server returns status 200 or the prior validators are absent or indeterminate
- **THEN** the system streams and hashes the complete artifact and compares its SHA-256 with prior versions

### Requirement: Denton PACS archive contract
The system SHALL validate a supported Denton full PACS Appraisal Export as a ZIP containing the exact expected member mapping, SHALL resolve every layout table to exactly one archive member, and SHALL fingerprint the member set, member sizes, checksums, header version, encoding, line endings, and observed record widths before canonical loading.

#### Scenario: Accept a supported Denton archive
- **WHEN** the archive passes shared safety checks, contains the required property and child members, and each required logical table resolves to exactly one physical member
- **THEN** the system records the PACS export fingerprint and makes the verified members available for streaming parsing

#### Scenario: Member resolution is missing or ambiguous
- **WHEN** suffix normalization resolves a required table to zero or more than one archive member
- **THEN** the system quarantines the artifact instead of selecting the first matching member

### Requirement: Denton fixed-width layout compatibility
The system SHALL parse Denton fixed-width fields from a content-validated published layout using 1-indexed inclusive positions, SHALL validate field order, non-overlap, declared length, and required-field end positions, and SHALL version the layout fingerprint separately from the export-header version. A field whose end exceeds the observed record width MUST NOT be emitted as a valid truncated value.

#### Scenario: Layout and export versions match
- **WHEN** the published layout fingerprint and observed member widths match an approved mapping
- **THEN** the parser emits supported fields and records their source positions and layout version as provenance

#### Scenario: Layout documents fields beyond the record
- **WHEN** a layout field starts or ends beyond the observed record width
- **THEN** the parser marks the field absent or incompatible according to the approved mapping, quarantines the release when the field is required, and never emits a partial slice as a valid value

#### Scenario: Export contains undocumented trailing bytes
- **WHEN** a record is wider than the approved layout boundary
- **THEN** the system preserves a structural fingerprint of the unknown trailing region, emits no inferred fields from it, and requires review before mapping it canonically

### Requirement: Bounded Denton parsing
The system SHALL stream Denton members directly from the verified ZIP and SHALL use bounded-memory batches or external storage for row counts, uniqueness checks, relationship checks, and loading.

#### Scenario: Process a multi-gigabyte member
- **WHEN** a Denton member exceeds local extraction or in-memory limits
- **THEN** the system parses the member line by line without expanding the complete archive or retaining all source keys in process memory

### Requirement: Denton account and owner-association grain
The system SHALL preserve `prop_id` as the Denton account identifier and `(prop_id, owner_sequence)` as the physical owner-row grain. It SHALL preserve ownership percentage and owner-scoped value and exemption allocations without deriving an account roll-up until an approved rule exists. Every required key component SHALL be nonblank.

#### Scenario: Undivided-interest rows allocate values by owner
- **WHEN** rows sharing `prop_id` have different owner sequence, ownership percentage, values, or exemptions that move together as an owner allocation
- **THEN** the adapter preserves each allocation with source-row provenance and does not deduplicate or sum the rows into an unverified account value

#### Scenario: Duplicate property rows conflict
- **WHEN** rows sharing `prop_id` disagree on required account-level facts and no approved discriminator resolves the conflict
- **THEN** the adapter preserves diagnostics and blocks Denton canonical publication

### Requirement: Denton value semantics
The system SHALL map separately documented market, appraised, assessed, homestead and non-homestead land and improvement, agricultural, timber, and productivity values only to semantically matching canonical value types. It SHALL preserve `ten_percent_cap` as a source-native cap amount until its exact product mapping is approved and MUST NOT treat it as a capped value solely because of its name.

#### Scenario: Validate Denton value hierarchy
- **WHEN** a supported release contains market, appraised, and assessed values
- **THEN** the system evaluates the approved hierarchy and plausibility rules, records violations, and quarantines the release when blocking thresholds are exceeded

### Requirement: Denton child relationships
The system SHALL preserve PACS child tables at their measured source grain and SHALL apply relationship thresholds by child type rather than using one county-wide orphan rule.

#### Scenario: Core appraisal child is orphaned
- **WHEN** land, improvement, or mobile-home records fail to resolve to a property account above the approved zero-orphan baseline
- **THEN** the system blocks publication and records the affected table and measured count

#### Scenario: Legal child is orphaned
- **WHEN** ARB or lawsuit records reference absent or retired property accounts within an approved measured warning threshold
- **THEN** the system preserves the records and warning diagnostics without treating the condition as equivalent to a core appraisal orphan

### Requirement: Denton roll and correction semantics
The system SHALL create separate logical releases for preliminary, certified, and roll-correction directories. It SHALL treat the measured 2025 roll-correction archive as a full replacement snapshot, MUST NOT merge it as a delta, and SHALL retain removed accounts as historical evidence rather than resurrecting them in current state. Preliminary-to-certified replacement semantics remain subject to same-year evidence.

#### Scenario: Preliminary and certified releases coexist
- **WHEN** both statuses are acquired for the same tax year
- **THEN** the system retains both releases and compares their account multisets before approving replacement and publication precedence

#### Scenario: Apply a supported roll correction
- **WHEN** an approved same-year correction follows a certified release
- **THEN** the latest product replaces the prior account multiset atomically, including additions, changes, and removals, while history retains both releases

### Requirement: Denton ownership privacy gate
The system SHALL classify inline owner names and mailing addresses as sensitive, SHALL preserve publisher omissions, and SHALL prohibit reconstruction of identities the publisher excludes. The system SHALL record the official statement that confidential ownership and over-65 exemptions are omitted from public downloads, but SHALL keep owner and mailing-address publication disabled until that statement's applicability to the full PACS roll and a reviewed field-level publication policy are approved.

#### Scenario: Parse the inline property record
- **WHEN** the Denton parser reads a record containing ownership and appraisal facts
- **THEN** sensitive values remain absent from logs, diagnostics, evidence manifests, repository fixtures, and Gold outputs while approved non-identifying appraisal facts retain source provenance

#### Scenario: Publisher omits a protected record or field
- **WHEN** official Denton publication rules suppress confidential ownership or exemption information
- **THEN** the system preserves the omission and does not enrich, join, or infer the protected value from another source

### Requirement: Record-free Denton evidence manifest
The system SHALL maintain a record-free Denton evidence manifest containing artifact and layout SHA-256 values and byte counts, sanitized remote metadata, exact archive-member names, sizes and checksums, PACS and tool versions, schema and width fingerprints, and complete aggregate row, key, relationship, and value measurements. The manifest MUST NOT contain source rows, owner values, addresses, credentials, or host-local paths.

#### Scenario: Reproduce the Denton baseline
- **WHEN** an authorized reviewer acquires the measured artifacts and executes the documented profiler
- **THEN** the resulting artifact, layout, member, schema, and aggregate fingerprints can be compared without exposing record data

### Requirement: Denton production-readiness gate
The system SHALL keep the Denton adapter non-production until the evidence manifest is reproducible, fixed-width compatibility is approved, undivided-interest account roll-up behavior is resolved, preliminary-to-certified behavior is classified, and the ownership publication policy is accepted.

#### Scenario: Denton blocker remains unresolved
- **WHEN** any required Denton decision, reproduction, or contract test is incomplete
- **THEN** immutable evidence capture may continue but Denton cannot enter the complete six-county Gold cohort
