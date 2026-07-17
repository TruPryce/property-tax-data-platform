## ADDED Requirements

### Requirement: Independent platform runtime
The system SHALL run on an independently managed Akamai Cloud VPS in Dallas `us-central` using Ubuntu 24.04 LTS, 16 GB shared CPU memory, and a 250 GB attached volume. PostgreSQL, Airflow, ingestion workers, and `appraisal-api` SHALL use separate logical databases or schemas and least-privilege roles.

#### Scenario: Consumer connects to the platform
- **WHEN** an application needs appraisal data
- **THEN** it uses the approved API or bulk-export contract and does not receive PostgreSQL or Airflow credentials

### Requirement: Administrative network boundary
The system SHALL use Tailscale for host, database, and Airflow administration. Administrative ports MUST NOT be exposed as public consumer interfaces.

#### Scenario: Operator performs maintenance
- **WHEN** an authorized operator accesses the VPS, PostgreSQL administration, or Airflow administration
- **THEN** access traverses the approved Tailscale administrative path and is auditable

### Requirement: S3 durable recovery boundary
The system SHALL treat the VPS and attached volume as replaceable and SHALL store immutable source evidence, versioned exports, Airflow remote logs, PostgreSQL physical backups, and archived WAL in encrypted Amazon S3 locations with least-privilege access and lifecycle policy.

#### Scenario: VPS and volume are lost
- **WHEN** the platform must move to a clean VPS or another provider
- **THEN** automation rebuilds the runtime and restores source evidence and PostgreSQL state from S3 without relying on the lost volume

### Requirement: PostgreSQL point-in-time recovery
The system SHALL archive WAL continuously and take scheduled physical backups under a documented retention policy. Backup success alone MUST NOT satisfy recovery readiness; automated integrity checks and periodic point-in-time restores SHALL be recorded.

#### Scenario: Recover to a point before corruption
- **WHEN** an operator selects a recoverable timestamp inside the retention window
- **THEN** PostgreSQL is restored to an isolated target, validated against release and publication invariants, and promoted only after approval

### Requirement: Provider-backup removal gate
The system SHALL keep the Linode backup add-on enabled until clean-host rebuild, S3 access recovery, and PostgreSQL point-in-time restore meet accepted RPO and RTO objectives in an exercised runbook. The add-on MAY be disabled only after that evidence is approved.

#### Scenario: Restore proof is incomplete
- **WHEN** any recovery dependency, exercise, alert, RPO, or RTO is unverified
- **THEN** provider backups remain enabled as temporary independent coverage

### Requirement: Bitwarden secret recovery
The hosted Bitwarden vault at `https://vault.bitwarden.com` SHALL hold the operator-controlled off-host recovery copy of environment secrets. Secret values MUST NOT be committed to Git, embedded in images, written to logs or manifests, or stored with source data in S3.

#### Scenario: Rebuild requires environment secrets
- **WHEN** an authorized operator provisions a clean runtime
- **THEN** the operator retrieves the approved values through the documented Bitwarden recovery procedure and injects them through the reviewed runtime mechanism without creating plaintext repository files

### Requirement: Backup and recovery observability
The system SHALL alert on WAL archive lag, failed backups, stale successful backups, failed integrity checks, stale restore exercises, and S3 access failures.

#### Scenario: WAL stops archiving
- **WHEN** archive lag exceeds the accepted recovery-point threshold
- **THEN** operations receive an actionable alert and production changes that increase recovery risk are blocked until archiving is healthy
