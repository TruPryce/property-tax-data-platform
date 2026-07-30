## ADDED Requirements

### Requirement: Before implementation, the accepted design and delta specification explicitly resolve D1 through D4 and contain no unresolved blocking marker. Sources: 714534bcff3cb21530465c55, 2e0a24560feb74d4881dab53.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: A valid synthetic row with approved headers in a noncanonical order produces one typed Dallas source record and one record conforming to the approved vendor-neutral contract without ordinal field binding. Source: ca0df171cabe5f246f2a4fe5.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: `ACCOUNT_NUM` remains exact 17-character zero-padded text, `GIS_PARCEL_ID` remains distinct, and appraisal year, source-member identity, header fingerprint, and release provenance remain observable. Sources: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: `TOT_VAL` and every other unresolved Dallas value remain source-native and are not exposed as canonical market, appraised, assessed, or taxable values. Sources: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Missing, duplicate, ambiguous, incompatible, or unsupported required headers and layouts fail closed with deterministic typed diagnostics. Sources: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Malformed quoting, incompatible row widths, and invalid approved numeric, date, account-identifier, or other field forms fail deterministically without producing a partial record. Source: ca0df171cabe5f246f2a4fe5.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Unknown columns are handled according to D4, cannot shift known mappings, and never cause privacy-restricted values to appear in diagnostics. Sources: ca0df171cabe5f246f2a4fe5, b34baeeecb2d6f95937ce5a1, 7676ed46a8bb877ba7fdaac0.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Duplicate `(ACCOUNT_NUM, APPRAISAL_YR)` rows are rejected across the scope approved by D3 while record production remains compatible with bounded streaming. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Fixtures, assertions, and diagnostics contain no county release extracts, production data, owner names, mailing addresses, protected identities, or credentials, and tests make no network contact. Sources: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Repository checks demonstrate that Dallas vocabulary remains adapter-local, dependency direction remains `adapters -> application -> domain`, and the parser foundation does not designate Dallas as production-ready. Sources: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, 05e1317dff1c2a0b0cdc4827.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: The work adds no persistence migration, Bronze acquisition, Gold publication, Airflow orchestration, production configuration, or deployment behavior. Source: ca0df171cabe5f246f2a4fe5.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: `make check` succeeds, covering the repository's formatting, linting, typing, tests, documentation, OpenSpec, secret, and artifact gates. Source: 12eb90de41980a9b5226022f.

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied
