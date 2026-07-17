## ADDED Requirements

### Requirement: Authoritative Tarrant source discovery
The system SHALL discover Tarrant Appraisal District releases from the official data-download page, SHALL assign Tarrant County FIPS `48439` from version-controlled configuration, and SHALL preserve page evidence, visible labels, source locators, retrieval timestamps, and remote metadata as provenance. Certified core, mutable current, exemption, and other companion artifacts SHALL be separate source mappings.

#### Scenario: Discover a certified property archive
- **WHEN** the official page exposes one certified property-data link for a tax year
- **THEN** the system creates a certified Tarrant source candidate without inferring equivalence to current or exemption sources

### Requirement: Tarrant conditional observation
The system SHALL use validators and byte ranges only when the response contract matches the approved Tarrant behavior and SHALL retain complete-content SHA-256 as artifact identity.

#### Scenario: Server returns a valid 304
- **WHEN** a conditional request uses validators from a completed acquisition and Tarrant returns status 304
- **THEN** the system records a no-change observation without republishing the release

#### Scenario: Probe is indeterminate
- **WHEN** status, range, length, representation, or validators differ from the approved probe contract
- **THEN** the system downloads and hashes the complete artifact or stops for review rather than declaring it unchanged

### Requirement: Tarrant certified archive contract
The system SHALL validate the supported certified ZIP as containing exactly one approved pipe-delimited text member with a header row, SHALL fingerprint the complete header and schema, and SHALL quarantine missing, extra, ambiguous, ragged, or incompatible structures.

#### Scenario: Accept the measured certified structure
- **WHEN** exactly one member matches the approved media, delimiter, header, column-count, and row-shape fingerprint
- **THEN** the system streams it without extracting the complete member or retaining all keys in process memory

#### Scenario: Member resolution is ambiguous
- **WHEN** zero or multiple members match the configured Tarrant contract
- **THEN** the system quarantines the archive instead of selecting the first text member

### Requirement: Tarrant account identity and divisions
The system SHALL preserve `Account_Num` as text and use it as the Tarrant source account identifier only while it remains nonblank and unique within the approved release. It SHALL preserve division codes and monitor their distributions without treating division as part of account identity.

#### Scenario: Account key baseline holds
- **WHEN** every normalized certified row has one unique nonblank `Account_Num`
- **THEN** the adapter emits county-qualified account snapshots and records key and division-count measurements

#### Scenario: Key behavior drifts
- **WHEN** duplicates, blanks, or longitudinal reuse violate the approved account contract
- **THEN** the release is quarantined until identity semantics are reviewed

### Requirement: Tarrant value semantics
The system SHALL preserve Tarrant total, appraised, land, improvement, agricultural, and other value fields as source-native values until official definitions and measured arithmetic approve each canonical mapping. An inequality or field name alone MUST NOT establish semantic equivalence.

#### Scenario: Evaluate the reported hierarchy
- **WHEN** a row contains both `Appraised_Value` and `Total_Value`
- **THEN** the system evaluates and records the approved inequality aggregate using committed reproducible tooling without automatically labeling `Total_Value` as market value

### Requirement: Tarrant companion-source gate
The system SHALL profile and approve the mutable current archive and certified exemption archive independently before using them for latest-available or exemption products. It MUST NOT infer missing taxable or exemption details from the certified core file.

#### Scenario: Core file lacks a required exemption fact
- **WHEN** the certified core mapping does not supply a required exemption or jurisdiction-taxable value
- **THEN** the fact remains absent until a verified companion source supplies it

### Requirement: Tarrant replacement semantics
The system SHALL preserve every Tarrant artifact as a separate release and MUST NOT merge current, certified, or later same-year artifacts until full-snapshot or delta behavior and deletion semantics are established.

#### Scenario: Later same-year artifact is unclassified
- **WHEN** a newer Tarrant artifact appears under a mutable or companion locator
- **THEN** the system stores it in Bronze and blocks current-state application until account-set comparison or official documentation classifies it

### Requirement: Tarrant ownership privacy gate
The system SHALL classify owner and mailing-address fields as sensitive and keep them out of Gold and API outputs until TAD confidentiality handling and a reviewed field-level policy are approved. Absence of an observable confidentiality flag MUST NOT be treated as permission to publish.

#### Scenario: Core source contains owner identity without a protection flag
- **WHEN** a Tarrant record contains owner or mailing data and no verified confidentiality marker
- **THEN** the system retains only approved protected processing and excludes those values from logs, evidence, fixtures, Gold, and API responses

### Requirement: Reproducible record-free Tarrant evidence
The system SHALL maintain a record-free manifest containing the exact acquisition instant, source and redirect provenance, archive and member byte counts and checksums, complete header fingerprint, parser and tool versions, and aggregates regenerated by committed tooling. It MUST NOT contain source rows, owner values, addresses, credentials, or host-local paths.

#### Scenario: Reproduce the Tarrant baseline
- **WHEN** an authorized reviewer acquires the same artifact and runs the documented production profiler
- **THEN** every published key, schema, row, division, and value aggregate can be regenerated from the artifact identity

### Requirement: Tarrant production-readiness gate
The system SHALL keep Tarrant out of the complete six-county publication until certified-core evidence is reproducible, current and exemption sources are classified, value and replacement semantics are approved, longitudinal identity is validated, and the ownership policy is accepted.

#### Scenario: A Tarrant blocker remains
- **WHEN** any required source, semantic, privacy, or evidence decision is incomplete
- **THEN** immutable capture and isolated Silver validation may continue but complete-cohort publication remains blocked
