## ADDED Requirements

### Requirement: After D1 approval, independently reviewed literal vectors for canonical zero, positive, negative, scaled, multiword, precision-boundary, year, and monetary cases decode to their reviewed exact Decimal values without float conversion or a fixture encoder that mirrors the decoder. [source_ids: 515a41057d446a949cae5adc, a8d0164e015d086c00140812]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Every representation that D1 classifies as malformed or unsupported fails with a stable bounded diagnostic and produces no substituted null, float, partial record, or arbitrary source-value output. [source_ids: 515a41057d446a949cae5adc, d6f1df2be541d1dcdefcc482]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: After D2 through D4 approval, a conforming synthetic row parses into the approved typed Collin source record and emits distinct current and certified logical observations with exact values and approved source-year, status, and row provenance. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: The D2-approved structural contract produces a deterministic fingerprint, and tests demonstrate fail-closed behavior for each missing, duplicate, renamed, unsupported, or type-incompatible structure that D2 declares invalid. [source_ids: 515a41057d446a949cae5adc, 7676ed46a8bb877ba7fdaac0]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Synthetic repeated-row tests preserve the original physical row count and separate row provenance without declaring prop_id, geo_id, or their pair to be an approved account key and without deduplication or aggregation. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Fixtures, records, diagnostics, and documentation contain no owner name, mailing address, protected identity, copied county row, Access database, archive, credential, or production source byte, and repository artifact and secret checks pass. [source_ids: 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f, b34baeeecb2d6f95937ce5a1]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: Tests operate only on caller-supplied synthetic values and introduce no source contact, network acquisition, production Access runtime, persistence, publication, orchestration, deployment, or unapproved dependency. The Collin adapter remains explicitly non-production-ready. [source_ids: 515a41057d446a949cae5adc, 05e1317dff1c2a0b0cdc4827, 37b0be1db5c2ff2ef21f3eae]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: The repository-supported comprehensive validation gate completes successfully after implementation. [source_ids: 12eb90de41980a9b5226022f]

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied
