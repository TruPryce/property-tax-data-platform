The replaceable-storage and PostgreSQL recovery foundation is defined in the
[accepted runtime specification](../../../../specs/platform-runtime-operations/spec.md).
The remaining bootstrap runtime requirements follow.

## ADDED Requirements

### Requirement: Administrative network boundary
The system SHALL use Tailscale for host, database, and Airflow administration. Administrative ports MUST NOT be exposed as public consumer interfaces.

#### Scenario: Operator performs maintenance
- **WHEN** an authorized operator accesses the VPS, PostgreSQL administration, or Airflow administration
- **THEN** access traverses the approved Tailscale administrative path and is auditable

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
