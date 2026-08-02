## ADDED Requirements

### Requirement: AC1 — Under the approved D1 contract, independently authored synthetic buffers for zero, signed, scaled, precision-boundary, multiword, year, and monetary cases produce the exact expected decimal coefficient and scale without binary floating-point conversion [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC2 — Every malformed or unsupported numeric, metadata, year, identifier, null, and monetary representation defined by D1 and D4 returns a stable failure rather than a guessed value, float, or silent null [sources: 515a41057d446a949cae5adc, 7676ed46a8bb877ba7fdaac0].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC3 — A structurally valid synthetic Collin row produces a typed adapter-local record and distinct current and certified observations whose exact values, source years, status, physical-row provenance, and source-field provenance are observable in tests [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC4 — Missing, duplicate, renamed, unsupported, or physically incompatible required Access metadata fails structural validation before any logical observation is emitted; column reordering is accepted only if D2 explicitly permits it [sources: 37b0be1db5c2ff2ef21f3eae, 7676ed46a8bb877ba7fdaac0].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC5 — Repeated synthetic physical rows sharing prop_id or prop_id plus geo_id all remain represented, and no type or test claims an approved account key, deduplicates owner associations, or computes an account roll-up [sources: a8d0164e015d086c00140812, 1f68cbd53a026079a9b30f8d].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC6 — Fixtures, diagnostics, records, and generated documentation contain no owner name, mailing address, protected identity, county row, Access database, archive, production appraisal record, credential, or secret [sources: 12eb90de41980a9b5226022f, 1f68cbd53a026079a9b30f8d].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC7 — Architecture checks demonstrate that Collin, PACS, and Access vocabulary remains in property_tax_adapters and does not enter property_tax_application, property_tax_domain, services, or DAGs [sources: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC8 — The change adds no live network access, source acquisition, Access runtime, persistence, migration, Bronze or Gold integration, Airflow orchestration, production configuration, or production-ready designation [sources: 515a41057d446a949cae5adc, 05e1317dff1c2a0b0cdc4827].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied

### Requirement: AC9 — The repository-supported make check gate passes, covering the repository's formatting, linting, typing, tests, documentation, OpenSpec, secret, and artifact checks [source: 12eb90de41980a9b5226022f].

The implementation SHALL satisfy this criterion.

#### Scenario: Acceptance
- **WHEN** the implementation is evaluated
- **THEN** the criterion is demonstrably satisfied
