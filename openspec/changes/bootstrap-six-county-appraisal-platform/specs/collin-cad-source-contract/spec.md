## ADDED Requirements

### Requirement: Authoritative Collin source discovery
The system SHALL discover the Collin PACS database export from the official Collin Central Appraisal District database-export page, SHALL assign Collin County FIPS `48085` from version-controlled configuration, and SHALL preserve the fetched page, visible link label, source locator, redirect chain, and discovery timestamp as provenance.

#### Scenario: Discover the public database export
- **WHEN** the official page exposes one unambiguous database-export link that resolves through the approved public file host
- **THEN** the system creates a Collin source candidate without requiring a static share token or authenticated portal session

#### Scenario: Encounter an unavailable or ambiguous link
- **WHEN** the database-export link is missing, duplicated, requires authentication, or no longer resolves to an approved downloadable artifact
- **THEN** the system records the discovery failure and schedules no automatic acquisition

### Requirement: Collin source-transition control
The system SHALL record that the measured Microsoft Access export is marked for retirement and SHALL treat the Texas Open Data offering as a distinct, unverified source until its datasets, identifiers, release semantics, and equivalence are approved.

#### Scenario: Publisher changes the preferred source
- **WHEN** the official page removes the Access export or directs consumers to a replacement dataset
- **THEN** the existing adapter stops automatic ingestion and requires a versioned source-contract change before using the replacement

### Requirement: Safe Collin file-host requests
The system SHALL use manual redirect handling, SHALL permit HTTPS requests only to configured Collin publisher and file-distribution hosts, and SHALL validate each redirect destination before contacting it.

#### Scenario: Public link redirects to the approved file host
- **WHEN** the Collin page redirects acquisition to the configured file-distribution host
- **THEN** the system validates the host, records the redirect, and requests the artifact without sending application credentials

#### Scenario: Public link redirects to an unapproved host
- **WHEN** any redirect targets a host outside the configured allowlist
- **THEN** the system rejects the redirect before contacting that host and records a non-retryable security failure

### Requirement: Collin remote-probe contract
The system SHALL NOT use Collin HEAD metadata as artifact size, media-type, or unchanged-content evidence. The system SHALL use a bounded `Range: bytes=0-0` request for cheap observation, SHALL require status 206, an exact `bytes 0-0/{total}` content range, one response byte, and the expected artifact media type, and SHALL bind observed validators and total length to the SHA-256 of a previously completed artifact. Probe outcomes SHALL distinguish valid change, valid no-probe-change, and indeterminate failure.

#### Scenario: HEAD returns the HTML decoy
- **WHEN** a HEAD response describes the small HTML intermediary rather than the database archive
- **THEN** the system ignores that response for artifact identity and does not compare its length with a prior archive

#### Scenario: One-byte range probe succeeds
- **WHEN** a range request returns status 206, exactly one body byte, a valid total length, and validators previously bound to an acquired artifact
- **THEN** the system records the observation and downloads the complete artifact when any bound signal changes

#### Scenario: Conditional request returns a full response
- **WHEN** Collin ignores `If-None-Match` or `If-Modified-Since` and returns status 200 with the full representation
- **THEN** the system does not interpret the response as a cheap no-change result and either completes it as a bounded acquisition or aborts it safely

#### Scenario: Range behavior changes
- **WHEN** a range request returns an unexpected status, length, content range, media type, or redirect
- **THEN** the system records an indeterminate probe failure, does not persist it as the comparison baseline, and does not claim that the remote artifact is unchanged

### Requirement: Immutable Collin mutable-slot observations
The system SHALL model the single Collin export locator separately from each acquired artifact version, SHALL identify content by SHA-256, and SHALL retain every changed artifact because the publisher does not provide dated historical database exports.

#### Scenario: Current export changes
- **WHEN** the range probe changes or a complete verification produces a new SHA-256
- **THEN** the system stores a distinct immutable artifact and never overwrites the earlier Collin capture

#### Scenario: Repeated bytes are acquired
- **WHEN** a complete download produces a SHA-256 already recorded for the locator
- **THEN** the system records a no-content-change observation without reparsing or republishing duplicate content

### Requirement: Collin archive and Access schema contract
The system SHALL validate the Collin ZIP and its expected Access database and reference-document members before parsing, SHALL fingerprint the Access table and columns, and SHALL process records with bounded resources.

#### Scenario: Accept the measured PACS export family
- **WHEN** the archive passes shared safety checks and its Access table contains the supported required columns
- **THEN** the system records archive-member and database-schema fingerprints before emitting source records

#### Scenario: Access schema drifts
- **WHEN** a required table or column is missing, duplicated, renamed, or has an incompatible physical type
- **THEN** the system quarantines the artifact before canonical loading and preserves the observed schema for review

### Requirement: Record-free Collin evidence manifest
The system SHALL maintain a record-free Collin source-contract manifest containing the archive SHA-256 and byte count, sanitized response metadata and redirect chain, archive-member sizes and checksums, Access schema fingerprint, aggregate row/key/value measurements, parser and tool versions, and an explicit assertion that no source record data is present. The manifest MUST NOT contain owner values, addresses, source rows, credentials, or host-local paths.

#### Scenario: Reproduce the Collin baseline
- **WHEN** an authorized reviewer acquires the same artifact and runs the documented profiling procedure
- **THEN** the resulting artifact, member, schema, and aggregate fingerprints can be compared with the committed manifest without exposing record data

#### Scenario: Evidence artifact changes
- **WHEN** the mutable Collin locator produces a different archive SHA-256 or schema fingerprint
- **THEN** the system records a distinct evidence observation rather than replacing the baseline manifest silently

### Requirement: Verified Access NUMERIC decoding
The system SHALL decode Collin Access NUMERIC fields with a reviewed implementation that preserves sign, scale, precision, and word order, SHALL return exact decimal values without binary floating-point conversion, SHALL verify the decoder against independently derived year and monetary vectors, and SHALL reject malformed or implausible decoded values before canonical loading.

#### Scenario: Decoder passes known vectors
- **WHEN** synthetic and redistribution-safe fixtures exercise zero, positive, signed, scaled, boundary, year, and monetary NUMERIC values
- **THEN** the decoder returns the independently expected exact decimal values without using a fixture encoder that merely mirrors the implementation under test or relying on aggregate plausibility alone

#### Scenario: Non-null numeric buffer is malformed
- **WHEN** a non-null source value has an unsupported width, sign, scale, or representation
- **THEN** the system records a decoding failure and quarantines the affected logical release instead of converting the source value to null

#### Scenario: Decoder produces implausible appraisal values
- **WHEN** decoded years fall outside the supported release context or value distributions and arithmetic invariants violate configured plausibility gates
- **THEN** the system quarantines the logical release and does not write decoded values to canonical tables

#### Scenario: Candidate parser exceeds resource limits
- **WHEN** an Access parsing implementation exceeds the configured time or memory budget on the measured export
- **THEN** the implementation fails its production-readiness benchmark and the adapter remains disabled

### Requirement: Collin account and source-row grain remain unresolved
The system SHALL preserve `prop_id` and `geo_id` as source fields and SHALL distinguish account identity from the repeated physical row or owner-association grain. The system MUST NOT approve `prop_id` as account identity until duplicate groups are shown to contain consistent account-level facts or an approved discriminator resolves their conflicts.

#### Scenario: Profile the documented property key
- **WHEN** duplicate `prop_id` values remain after adding `geo_id`
- **THEN** the system records duplicate counts, classifies every differing field as account-level or owner-association data, retains the rows at source grain, and blocks approval until group consistency is measured

#### Scenario: Duplicate groups differ only by ownership
- **WHEN** all rows sharing a `prop_id` agree on required account, value, situs, legal, year, and release fields and differ only in approved owner-association fields
- **THEN** the system may approve `prop_id` as the account identifier while preserving each owner association as a child record

#### Scenario: Approve a Collin account identity
- **WHEN** profiling or official clarification establishes a stable account key and its null, consistency, and conflict gates pass
- **THEN** the reviewed key is versioned in the Collin mapping before canonical identities are emitted

### Requirement: Collin dual-roll semantics
The system SHALL derive current and certified logical value releases from the explicit `curr_val_yr`, `cert_val_yr`, `property_status`, `curr_*`, and `cert_*` field families and SHALL retain both logical releases against the same immutable source artifact.

#### Scenario: Current and certified years differ
- **WHEN** one row contains current values for a newer year and certified values for the preceding year
- **THEN** the adapter emits year- and status-specific value observations without assigning both families to the artifact acquisition year

#### Scenario: Current property status changes
- **WHEN** `property_status` changes from in-progress or preliminary to certified in a later artifact
- **THEN** the system retains both source observations and applies publication precedence by logical release semantics rather than filename

### Requirement: Collin canonical value mapping
The system SHALL map the documented current and certified market, appraised, and assessed fields to distinct canonical value types with their source year and status. It MUST NOT use those appraisal values as authoritative tax bills, balances, or payments.

#### Scenario: Validate appraised value semantics
- **WHEN** a Collin logical release contains market and appraised values
- **THEN** the system validates the source-defined relationship that appraised value does not exceed market value and records violations before publication

#### Scenario: Preserve current and certified values
- **WHEN** both current and certified value families are populated
- **THEN** each canonical value retains its source column, value type, tax year, logical release kind, and common artifact lineage

### Requirement: Collin ownership privacy gate
The system SHALL classify `file_as_name` and owner mailing fields as sensitive, SHALL NOT assume publication is permitted because the flat export lacks a confidentiality marker, and SHALL keep owner and mailing-address outputs disabled until Collin's handling of protected records and the platform field policy are approved.

#### Scenario: Process a flat row containing ownership and values
- **WHEN** a Collin source row contains owner identity beside appraisal values
- **THEN** the system prevents owner values from entering logs, diagnostics, repository fixtures, or Gold outputs while allowing non-identifying appraisal facts to proceed only under the approved policy

#### Scenario: No protected-owner flag is visible
- **WHEN** the supported schema contains no verified equivalent of a protected-owner or excluded-owner marker
- **THEN** the adapter records the missing control as a production blocker instead of inferring that all owner rows are safe to publish

### Requirement: Collin operational cadence
The system SHALL probe the mutable Collin export daily, SHALL acquire and hash it whenever a bound range signal changes, and SHALL run a configurable periodic complete verification to detect incorrect or stale remote validators.

#### Scenario: Daily probe detects change
- **WHEN** the observed ETag, Last-Modified value, total length, or source locator differs from the values bound to the last artifact
- **THEN** the system acquires and hashes the complete export and stores new content immutably

#### Scenario: Daily probe is unchanged
- **WHEN** all bound range signals match the prior observation and complete verification is not due
- **THEN** the system records a no-probe-change result without parsing or publishing

### Requirement: Collin production-readiness gate
The system SHALL keep the Collin adapter non-production until the exact spike evidence is reviewed and reproducible, the Access runtime and NUMERIC decoder pass resource and correctness tests, the account key is approved, the protected-owner policy is resolved, and source-transition behavior is accepted.

#### Scenario: Collin blocker remains unresolved
- **WHEN** any required Collin decision, reproduction, or contract test is incomplete
- **THEN** immutable evidence capture may continue but Collin cannot enter the complete six-county Gold cohort
