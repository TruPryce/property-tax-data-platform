## MODIFIED Requirements

### Requirement: Canonical account identity and grain
The system SHALL identify an appraisal account by its canonical `Jurisdiction` and a county-contract-approved source account identifier, and SHALL represent each account snapshot at the grain of logical release, tax year, and source as-of value. The system SHALL distinguish account identity from physical source-row and owner-association grain, and MUST NOT assume that duplicate physical rows imply duplicate business accounts or that a documented APN, property ID, or account identifier is sufficient without measured county-specific evidence. Owner-scoped value and exemption allocations MUST remain at owner-association grain until an approved account roll-up exists.

County FIPS remains required validated registry metadata on the jurisdiction and MUST NOT be used as a second, independent county identity. This corrects the previous `(county_fips, source_account_id)` wording, under which one part of the system would identify a county by slug while another identified it by FIPS.

#### Scenario: Receive equal account identifiers from two counties
- **WHEN** two county adapters emit the same source account identifier
- **THEN** the system stores distinct canonical account identities because their canonical jurisdictions differ

#### Scenario: Documented source key is duplicated
- **WHEN** source profiling finds duplicate rows for a documented property or account key
- **THEN** the adapter compares all account-level facts within each key group, preserves distinct owner associations at child grain, and records conflicts before approving the key as account identity

#### Scenario: Duplicate source rows carry owner allocations
- **WHEN** rows sharing an approved account key differ by owner sequence, ownership percentage, or owner-scoped values or exemptions
- **THEN** the adapter emits distinct owner-association allocation records and does not deduplicate, sum, or select an arbitrary row as the account total

#### Scenario: Duplicate account groups conflict
- **WHEN** rows sharing a candidate account key disagree on a required account-level fact and no approved source discriminator resolves the conflict
- **THEN** the adapter preserves the source rows and diagnostics and blocks canonical publication of the affected logical release
