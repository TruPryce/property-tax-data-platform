## ADDED Requirements

### Requirement: Authoritative Dallas source discovery
The system SHALL discover Dallas appraisal releases from `https://www.dallascad.org/dataproducts.aspx`, SHALL assign Dallas County FIPS `48113` from version-controlled configuration, and SHALL preserve the fetched page, section heading, visible link label, source locator, and discovery timestamp as provenance.

#### Scenario: Discover an approved Dallas release
- **WHEN** the official page contains one unambiguous supported archive link with a leading tax year and recognized release wording
- **THEN** the system records the page evidence and creates a Dallas release candidate without inferring county or release status from record payloads

#### Scenario: Encounter ambiguous discovery
- **WHEN** a required selector is missing, matches multiple links, has no leading tax year, or has unrecognized release wording
- **THEN** the system records the ambiguity and schedules no automatic acquisition for that selector

### Requirement: Safe Dallas source requests
The system SHALL permit HTTPS requests only to the configured Dallas source host and SHALL validate the scheme and host before issuing the initial request and every redirected request.

#### Scenario: Receive an off-host redirect
- **WHEN** a Dallas page or archive response redirects to a host outside the configured allowlist
- **THEN** the system rejects the redirect before contacting the disallowed host and records a non-retryable security failure

### Requirement: Label-derived Dallas release semantics
The system SHALL classify supported Dallas releases as `proposed`, `certified`, or `certified-with-supplemental` from the visible official-page label and SHALL NOT derive roll status from the archive URL, archive filename, or internal member names.

#### Scenario: Classify a mutable current slot
- **WHEN** a `DCAD{YYYY}_CURRENT.ZIP` link is labeled as proposed values or certified data with supplemental changes
- **THEN** the release receives the label-derived status and preserves the verbatim label that established that status

#### Scenario: Classify a dated certification
- **WHEN** a label identifies data files at certification and contains a certification date
- **THEN** the release is classified as certified with the leading label year as tax year and the parsed certification date as source as-of evidence

### Requirement: Immutable observations of mutable Dallas artifacts
The system SHALL model a Dallas source locator separately from each acquired artifact version, SHALL identify artifact content by SHA-256, and SHALL never overwrite prior Bronze content when the same `CURRENT` locator yields different bytes or a different release status.

#### Scenario: Current slot changes content
- **WHEN** an acquired `CURRENT` locator produces a SHA-256 not previously observed for that locator
- **THEN** the system stores a distinct immutable artifact, links both observations to the locator, and retains the earlier artifact

#### Scenario: Current slot changes release status
- **WHEN** the official label for a `CURRENT` locator changes from proposed to certified-with-supplemental
- **THEN** the system preserves both release observations and the proposed artifact remains independently reproducible

#### Scenario: Dated archive changes unexpectedly
- **WHEN** a dated certified locator produces bytes that differ from its first verified SHA-256
- **THEN** the system retains the new bytes separately, quarantines the observation, and alerts on the violated immutability expectation

### Requirement: Dallas change detection
The system SHALL treat `Content-Length` as a positive early-change signal only and SHALL use remote validators or a scheduled complete download plus SHA-256 to establish Dallas artifact content identity.

#### Scenario: Mutable archive length is unchanged
- **WHEN** a scheduled mutable-slot verification observes the same `Content-Length` and no `ETag` or `Last-Modified` is available
- **THEN** the system does not claim the remote artifact is unchanged and performs the configured complete-download verification

#### Scenario: Downloaded content is unchanged
- **WHEN** a complete verified download produces a SHA-256 already recorded for the same locator and release semantics
- **THEN** the system records a no-content-change observation without parsing or republishing duplicate content

### Requirement: Dallas archive contract
The system SHALL support Dallas ZIP archives containing the 14 observed CSV data members and four reference documents, SHALL stream data members without expanding the complete archive, and SHALL apply the shared archive safety limits before integrity testing or extraction.

#### Scenario: Accept the supported Dallas archive family
- **WHEN** a Dallas archive passes ZIP integrity and safety checks and contains the supported member set
- **THEN** the system records all member names, compressed and expanded sizes, checksums, media classifications, and the archive fingerprint before parsing

#### Scenario: Detect archive-family drift
- **WHEN** a Dallas archive adds, removes, duplicates, renames, or changes the media type of an expected member
- **THEN** the system quarantines the release for source-contract review before canonical loading

### Requirement: Observed-header Dallas parsing
The system SHALL bind Dallas CSV fields by normalized observed header name, SHALL NOT bind fields by documented name or ordinal position, and SHALL retain the observed header and source member in record provenance.

#### Scenario: Documentation disagrees with the header
- **WHEN** a reference document's field name differs from the observed CSV header
- **THEN** the parser uses the observed header for physical binding and requires an explicit reviewed semantic mapping rather than silently substituting the documented name

#### Scenario: Dallas adds a column
- **WHEN** a supported member gains a previously unknown column while all required columns remain unambiguous
- **THEN** the system preserves the new field as a source extra, emits a schema warning, and does not shift any existing field mapping

#### Scenario: Dallas removes or ambiguously renames a required column
- **WHEN** a required observed header is absent, duplicated, or can no longer be mapped unambiguously
- **THEN** the system quarantines the release before canonical loading

### Requirement: Dallas account and parcel identity
The system SHALL preserve `ACCOUNT_NUM` as a 17-character zero-padded string, SHALL use `(48113, ACCOUNT_NUM)` as the stable source-account identity, and SHALL represent `GIS_PARCEL_ID` as a distinct optional parcel reference.

#### Scenario: Normalize a Dallas account snapshot
- **WHEN** a supported parent row contains `ACCOUNT_NUM` and `APPRAISAL_YR`
- **THEN** the snapshot is linked to the county-qualified source account, retains its appraisal year and release identity, and no identifier is coerced to a number

#### Scenario: Account and parcel identifiers differ
- **WHEN** `GIS_PARCEL_ID` is blank or differs from `ACCOUNT_NUM`, including a business-personal-property account
- **THEN** the system does not relabel the account identifier as a parcel identifier and preserves the account-to-parcel relationship explicitly when available

### Requirement: Dallas relationship and grain validation
The system SHALL join Dallas source members on `(ACCOUNT_NUM, APPRAISAL_YR)`, SHALL require zero orphan child rows for the supported source-contract fingerprint, and SHALL preserve each one-to-many member at source grain.

#### Scenario: Validate account-grain members
- **WHEN** `ACCOUNT_APPRL_YEAR` and `ACCOUNT_INFO` are parsed
- **THEN** their account-year keys are non-null and unique and `APPRAISAL_YR` agrees with the label-derived tax year

#### Scenario: Encounter a child record without a parent
- **WHEN** any supported child member contains an account-year key absent from `ACCOUNT_APPRL_YEAR`
- **THEN** the release is quarantined and the prior published Dallas snapshot remains active

#### Scenario: Natural child key is unresolved
- **WHEN** a Dallas child member's component key has not been statistically validated
- **THEN** the system may retain its source row in Bronze or run-scoped staging but does not publish that child as a uniquely identified canonical entity

### Requirement: Dallas supplemental replacement semantics
The system SHALL treat a Dallas certified-with-supplemental archive as a complete replacement snapshot, SHALL apply deletions represented by absent accounts, and SHALL retain the dated certified-at-certification snapshot separately.

#### Scenario: Publish a supplemental snapshot
- **WHEN** a certified-with-supplemental release passes all quality gates
- **THEN** the system atomically replaces the prior current supplemental state for that tax year instead of merging rows and retains every earlier release in history

#### Scenario: Account disappears after certification
- **WHEN** an account exists in the dated certified snapshot but is absent from the validated supplemental replacement
- **THEN** the latest supplemental product excludes the account while the certified-at-certification history still contains it

### Requirement: Dallas value semantics remain explicit
The system SHALL preserve Dallas `TOT_VAL`, component values, homestead-cap values, and jurisdiction-specific taxable values as source-native facts and MUST NOT map them to canonical market, appraised, assessed, or unlabeled taxable value until the relevant semantics are approved.

#### Scenario: Normalize unresolved total value
- **WHEN** a Dallas row contains `TOT_VAL` before its official meaning and arithmetic relationship are resolved
- **THEN** the system retains the source value and provenance but leaves canonical market, appraised, assessed, and taxable value absent

#### Scenario: Publish jurisdiction taxable values
- **WHEN** Dallas supplies multiple jurisdiction-specific taxable values
- **THEN** each published value retains its jurisdiction and basis and no arbitrary jurisdiction is selected as a single property-wide taxable value

### Requirement: Dallas protected ownership handling
The system SHALL treat `EXCLUDE_OWNER` as a sensitive-record marker, SHALL preserve publisher redactions, and SHALL default to suppressing owner and mailing-address publication for marked records until a reviewed field-level policy establishes permitted handling.

#### Scenario: Process an excluded owner record
- **WHEN** `ACCOUNT_INFO.EXCLUDE_OWNER` marks an account as private
- **THEN** no owner name, mailing address, or reconstructed protected identity from that account is emitted to Silver publication fields, Gold products, logs, diagnostics, or fixtures

#### Scenario: Preserve non-identifying appraisal evidence
- **WHEN** a marked account contains non-identifying appraisal facts
- **THEN** those facts remain protected from publication unless the approved policy explicitly permits them, without assuming that the marker alone provides a final legal interpretation for every field

### Requirement: Dallas operational cadence
The system SHALL check the Dallas product page daily and SHALL support configurable complete-download verification for mutable current archives with a default cadence of daily during the certification window, weekly from proposed publication through supplement season, and monthly during the quiet season.

#### Scenario: Same-length current archive reaches its verification cadence
- **WHEN** the current locator has no usable validator and its configured complete-download verification is due
- **THEN** the system downloads and hashes the complete archive even when HEAD metadata has not changed

### Requirement: Dallas production-readiness gate
The system SHALL keep the Dallas adapter non-production until its value mapping, child grains required for publication, protected-owner policy, immutable mutable-slot handling, and source-contract tests are approved.

#### Scenario: Dallas blocker remains unresolved
- **WHEN** any required Dallas production-readiness decision or contract test is incomplete
- **THEN** Bronze evidence gathering may continue but Dallas cannot enter the complete six-county Gold cohort
