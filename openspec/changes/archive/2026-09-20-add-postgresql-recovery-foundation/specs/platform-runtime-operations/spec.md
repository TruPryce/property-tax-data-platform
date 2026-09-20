## MODIFIED Requirements

### Requirement: Independent platform runtime
The system SHALL run on an independently managed Akamai Cloud VPS in Dallas `us-central` using Ubuntu 24.04 LTS and 16 GB shared CPU memory. All storage local to that host — root disk, container volumes, and any attached Block Storage — SHALL be treated as replaceable capacity rather than as a durable store, and no requirement SHALL depend on a specific local device, mount point, or capacity figure. Attached Block Storage MAY be provisioned as a capacity or performance expansion when measured growth justifies it, and its absence SHALL NOT block operation, backup, or recovery. PostgreSQL, Airflow, ingestion workers, and `appraisal-api` SHALL use separate logical databases or schemas and least-privilege roles.

#### Scenario: Consumer connects to the platform
- **WHEN** an application needs appraisal data
- **THEN** it uses the approved API or bulk-export contract and does not receive PostgreSQL or Airflow credentials

#### Scenario: Local storage is chosen or expanded
- **WHEN** an operator places PostgreSQL data on the root disk, a container volume, or attached Block Storage
- **THEN** the recovery contract is unchanged, because durability is supplied by the S3 recovery boundary rather than by the device holding the live cluster

### Requirement: S3 durable recovery boundary
The system SHALL treat the VPS and every storage device local to it as replaceable and SHALL store immutable source evidence, versioned exports, Airflow remote logs, PostgreSQL physical backups, and archived WAL in encrypted Amazon S3 locations with least-privilege access and lifecycle policy.

#### Scenario: VPS and its local storage are lost
- **WHEN** the platform must move to a clean VPS or another provider
- **THEN** automation rebuilds the runtime and restores source evidence and PostgreSQL state from S3 without relying on any storage from the lost host

## ADDED Requirements

### Requirement: Segregated backup repository and identity
PostgreSQL physical backups and archived WAL SHALL be written to a backup S3 location distinct from the source-data location, reached through a distinct IAM identity. The identity used for source-data access MUST NOT be granted object deletion or lifecycle authority over the backup location, and the identity used for backup access MUST NOT be granted authority over the source-data location. Backup object expiry SHALL be effected by a bucket lifecycle policy or by the backup identity's own retention operation, and MUST NOT require widening the source-data identity.

#### Scenario: A compromised data identity attempts to destroy recovery material
- **WHEN** the source-data identity attempts to delete, overwrite, or expire an object under the backup location
- **THEN** the request is denied, and the recovery material remains intact

#### Scenario: Retention removes an expired backup
- **WHEN** a retained full-backup cycle passes out of the documented retention window
- **THEN** it is expired by the backup identity or bucket lifecycle policy without granting the source-data identity any delete authority

### Requirement: Keyless workload credentials for durable storage
Host access to durable storage SHALL be obtained from short-lived credentials derived from an X.509 workload certificate issued by the approved certificate authority and exchanged through the approved trust anchor. A long-lived access-key identifier or secret access key MUST NOT be created, written to disk, embedded in an image, placed in Compose interpolation, or passed into a container. The credential exchange SHALL be authorized by certificate subject, so that authority is bound to a named host identity rather than to possession of a shared secret, and the exchanged credential material SHALL be passed to its consumer unmodified.

#### Scenario: A workload requests durable-storage credentials
- **WHEN** a backup or archive operation needs durable-storage access
- **THEN** it exchanges the host workload certificate for short-lived credentials scoped to the backup identity, and no long-lived key material exists on the host to be stolen

#### Scenario: An unauthorized certificate subject presents a valid chain
- **WHEN** a certificate issued by the approved authority presents a subject that is not authorized for the backup identity
- **THEN** the exchange is refused, because chain validity alone does not confer authority

### Requirement: Backup scheduling independent of the orchestrator
Physical backups and WAL archiving SHALL be scheduled and executed by the host supervisor rather than by the workflow orchestrator whose metadata database they protect. A backup schedule MUST NOT depend on the orchestrator being healthy, running, or correctly configured.

#### Scenario: The orchestrator is down
- **WHEN** Airflow is stopped, unhealthy, or its metadata database is unavailable
- **THEN** scheduled physical backups and continuous WAL archiving continue unaffected

### Requirement: Point-in-time restore proven in isolation
A recorded point-in-time restore exercise SHALL restore into an isolated target that is not the production data location and is not reachable on a production interface, and SHALL prove recovery to a chosen timestamp by demonstrating that state committed before the target is present and state committed after the target is absent. The exercise SHALL record the measured recovery point, the measured recovery time, the backup identity restored from, and the target timestamp, and MUST NOT record credentials or production source data.

#### Scenario: Restore proves the recovery target
- **WHEN** an operator restores to a timestamp between two recorded states
- **THEN** the earlier state is present, the later state is absent, the cluster starts cleanly, and the production data location is untouched

#### Scenario: An exercise reports only that a backup exists
- **WHEN** a restore exercise records backup success without demonstrating the timestamp boundary
- **THEN** recovery readiness is not satisfied and the provider-backup removal gate remains closed
