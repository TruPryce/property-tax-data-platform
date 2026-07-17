## ADDED Requirements

### Requirement: Consumer-neutral read-only API
The system SHALL provide a lightweight Python `appraisal-api` that reads only approved Gold products through a least-privilege read-only database role. Its domain and contract MUST NOT depend on TruPryce or any other single consumer.

#### Scenario: Consumer requests an account
- **WHEN** an authorized consumer supplies county FIPS and source account identifier
- **THEN** the API returns the approved account representation without writing source, Silver, or Gold state

### Requirement: Explicit appraisal products
The API SHALL distinguish latest available, latest certified, and historical products and SHALL include tax year, release kind, source as-of evidence, publication time, and release identity.

#### Scenario: Proposed and certified years differ
- **WHEN** a newer proposed release and an older certified release both exist
- **THEN** their endpoints or explicit selectors return distinct products with unambiguous status and freshness

### Requirement: Matching evidence
The API SHALL expose exact county-qualified account matches separately from candidate address or geospatial matches and SHALL include match method, confidence, and evidence.

#### Scenario: Only an address candidate exists
- **WHEN** no exact county-qualified account mapping exists
- **THEN** the response labels the result as a candidate and does not present it as an exact property identity

### Requirement: Sensitive fields default denied
The API SHALL omit owner names, mailing addresses, confidentiality markers, and other restricted fields by default. A field MAY be exposed only after its county publication policy, authorization rule, response contract, and audit behavior are approved.

#### Scenario: Default consumer reads an account
- **WHEN** the underlying source contains sensitive ownership data
- **THEN** the response contains approved appraisal facts and no sensitive owner or mailing values

### Requirement: Versioned and observable contract
The API SHALL publish a versioned OpenAPI contract, stable error shapes, health and readiness endpoints, request correlation, and dependency-safe availability behavior. Authentication, TLS, and rate limits SHALL be configured before non-administrative production access.

#### Scenario: Database or publication dependency is unavailable
- **WHEN** the API cannot read the last successful Gold publication safely
- **THEN** readiness fails and the API returns a bounded service error without leaking credentials, SQL, or internal topology

### Requirement: Bulk delivery boundary
The API SHALL serve bounded interactive queries. Large county or historical extracts SHALL use versioned S3 exports with checksums and dataset manifests rather than unbounded pagination through account endpoints.

#### Scenario: Consumer requests a complete county export
- **WHEN** the requested result exceeds the interactive API limit
- **THEN** the system directs the authorized consumer to an immutable versioned bulk export contract
