## ADDED Requirements

### Requirement: Silver persistence
The system SHALL persist normalized account snapshots and child records in PostgreSQL Silver tables with foreign keys or equivalent load-time relationship checks and release-level lineage.

#### Scenario: Load a normalized batch
- **WHEN** a normalized batch is committed
- **THEN** every row references its canonical account identity, release identity, source artifact, parser version, and ingestion run

#### Scenario: Retry a Silver load
- **WHEN** the same normalized records are loaded again for the same release and source identity
- **THEN** the resulting Silver state contains no duplicate logical records

### Requirement: Configurable data-quality evaluation
The system SHALL evaluate required-key completeness, uniqueness, child relationships, schema compatibility, row-count drift, value validity, and configured source-specific checks before publication.

#### Scenario: Release passes quality thresholds
- **WHEN** all blocking rules pass and warning rules remain within configured thresholds
- **THEN** the system marks the release validated and records every evaluated rule result

#### Scenario: Release violates a blocking rule
- **WHEN** a blocking quality rule fails
- **THEN** the system prevents publication, quarantines the affected release, and records an actionable failure with measured and expected values

### Requirement: Quarantine preserves evidence
The system SHALL preserve Bronze artifacts, manifests, Silver load attempts, diagnostics, and quality results for quarantined releases.

#### Scenario: Operator investigates a quarantined release
- **WHEN** an operator selects the quarantined release identity
- **THEN** the operator can trace the failure to source artifacts, parser version, affected records or batches, and quality-rule outcomes

### Requirement: Sensitive ownership publication policy
The system SHALL classify owner names, mailing addresses, and publisher confidentiality markers as sensitive source fields and SHALL default-deny their publication until a reviewed county field policy explicitly permits each output. Sensitive record values MUST NOT appear in logs, diagnostics, repository fixtures, or source-contract reports.

#### Scenario: Publisher provides a confidentiality marker
- **WHEN** a source record marks an owner or address as protected or excluded
- **THEN** the system preserves the marker and publisher redactions and suppresses protected identifying fields from publication

#### Scenario: Publisher provides no confidentiality marker
- **WHEN** a source publishes ownership data without an observable protected-owner flag
- **THEN** the system does not infer that every row is publication-safe and keeps owner and mailing-address outputs disabled until the county policy is approved

### Requirement: Separate current and certified products
The system SHALL publish separate Gold products for latest available appraisal data, latest certified appraisal data, and historical appraisal snapshots.

#### Scenario: New proposed values arrive before certification
- **WHEN** validated proposed values exist for a newer tax year than the latest certified release
- **THEN** the latest-available product may expose the proposed values while the latest-certified product remains on the certified release

#### Scenario: Supplemental certified values arrive
- **WHEN** a validated supplemental release updates a certified account
- **THEN** the latest-certified product selects the supplemental account version according to deterministic release precedence while history retains both versions

### Requirement: Atomic publication
The system SHALL publish a Gold release atomically and SHALL retain the previously published version until all blocking validation and publication operations succeed.

#### Scenario: Publication fails midway
- **WHEN** a Gold build fails after writing intermediate data
- **THEN** consumers continue to read the previously successful publication and the incomplete build is not marked current

### Requirement: Publication lineage and freshness
The system SHALL expose county, tax year, release kind, source as-of value, publication timestamp, and release identity with every Gold account record or its enclosing dataset contract.

#### Scenario: Consumer reads a current record
- **WHEN** a consumer queries a Gold current product
- **THEN** the consumer can determine whether the record is proposed or certified and when its source and publication were last updated

### Requirement: Safe consumer property matching
The system SHALL provide a bridge contract that matches appraisal accounts to downstream properties using county-qualified account identity as the highest-confidence key and records match method and confidence. It MUST NOT join on unqualified APN alone.

#### Scenario: County-qualified account match
- **WHEN** a consumer property supplies matching county FIPS and source account identifier
- **THEN** the bridge records an exact match with its evidence

#### Scenario: Address-only candidate
- **WHEN** only normalized address evidence is available
- **THEN** the bridge records a candidate match separately from exact matches and does not silently merge the records

### Requirement: Estimated tax labeling
The system SHALL label any tax value derived from taxable value and rates as an estimate and SHALL retain the formula inputs and rate year.

#### Scenario: Calculate an estimated tax
- **WHEN** validated jurisdiction taxable values and applicable tax rates are available
- **THEN** the Gold record exposes an estimated tax amount with calculation provenance and does not populate an authoritative amount-due field

### Requirement: Complete-cohort source sufficiency
The system SHALL count a county as ready for the complete initial cohort only when its approved source supplies the required canonical appraisal facts and passes its county source contract. A geometry source or partial value extract MUST NOT satisfy a full appraisal-adapter readiness gate.

#### Scenario: County has only a partial GIS source
- **WHEN** a county's validated source lacks required appraisal value types, exemptions, or other source-contract facts
- **THEN** the system may publish a separately labeled partial enrichment dataset but does not count the county toward the complete six-county Gold cohort
