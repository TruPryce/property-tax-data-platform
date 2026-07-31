## ADDED Requirements

### Requirement: After all blocking decisions are approved, a valid synthetic Dallas row produces an approved typed Dallas source record and an approved vendor-neutral typed record. [source_id: ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Required fields bind by approved normalized observed-header names rather than ordinal position, and column reordering does not alter known-field mappings. [source_id: ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Missing, duplicate, normalization-colliding, ambiguous, incompatible, and unsupported required layouts fail closed with deterministic diagnostics. [source_ids: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Invalid numeric, date, account-identifier, row-width, and quoting forms fail deterministically without producing a partial accepted record. [source_id: ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: ACCOUNT_NUM remains exactly 17-character zero-padded text, GIS_PARCEL_ID remains a distinct identifier, APPRAISAL_YR remains explicit, and approved source-member, header, and release provenance is retained. [source_ids: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Unknown columns are retained as source extras with deterministic schema diagnostics and cannot shift mappings for known fields. [source_id: ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: TOT_VAL and other unresolved Dallas values remain labeled source-native facts and are not exposed as canonical market, appraised, assessed, or taxable values. [source_ids: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Duplicate parent records at the ACCOUNT_NUM and APPRAISAL_YR grain are rejected deterministically. [source_ids: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Fixtures, diagnostics, and committed artifacts contain no county release bytes, production data, owner name, mailing address, protected identity, credential, or secret. [source_ids: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0, 1f68cbd53a026079a9b30f8d]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: The change adds no live source discovery or download, archive acquisition, Bronze persistence, database migration or backfill, Gold publication, Airflow orchestration, cross-county abstraction, production deployment, or production-ready designation. [source_ids: ca0df171cabe5f246f2a4fe5, 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: The named OpenSpec change validates and make check completes successfully, covering repository lint, typing, tests, documentation, specification, secret, and artifact gates. [source_ids: 12eb90de41980a9b5226022f, 714534bcff3cb21530465c55]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied
