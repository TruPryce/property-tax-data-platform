# ADR-0010: Replaceable Local Storage and a Segregated S3 Backup Repository

## Status

Accepted on 2026-08-26. Amends the storage statements in [ADR-0001](0001-independent-akamai-runtime.md) and [ADR-0002](0002-s3-durable-recovery-boundary.md). Implementation is tracked in the `add-postgresql-recovery-foundation` OpenSpec change.

## Context

ADR-0001 specified "an attached 250 GB volume" and ADR-0002 rejected treating that volume as durable storage while still assuming "the database is expected on an attached volume". The accepted `platform-runtime-operations` requirement carried the same 250 GB figure as a `SHALL`.

No such volume is attached. PostgreSQL runs on the root disk inside a Docker named volume, and the operator has decided it stays there while recovery is built. Implementing recovery against the contract as written would have meant either violating an accepted requirement or provisioning storage for no operational reason, so the storage statement is amended first.

Two further facts shaped this decision. The host already holds a working keyless AWS identity — a private CA, an X.509 workload certificate, and an IAM Roles Anywhere trust anchor exchanging it for short-lived credentials. And the existing `trupryce-data-platform-vps` role that identity assumes is a *data* role, deliberately without object-delete authority, because it handles untrusted county source archives.

## Decision

**Local storage is replaceable capacity, not a durable store.** The contract states what must remain true — that no requirement depends on a specific local device, mount point, or capacity figure — rather than naming a device or a size. Root disk, container volume, and attached Block Storage are interchangeable for correctness purposes.

**Attached Block Storage is optional expansion.** It may be provisioned when measured growth justifies capacity or performance, and its absence blocks nothing. Provisioning it later requires no further amendment.

**S3 is the recovery boundary, implemented with pgBackRest.** Encrypted physical backups plus continuous WAL archiving to `s3://trupryce-property-tax-backups/pgbackrest/platform`, under stanza `platform`, with a weekly full backup on Sunday, differentials Monday through Saturday, four retained full cycles, and `archive_timeout=300`. The two never overlap on schedule, which is what removes any need for a serialisation primitive between them.

`archive_timeout=300` establishes the maximum idle WAL segment-switch interval while archiving is healthy. It is not a durability guarantee. The actual recovery point is the age of the most recent WAL segment **confirmed present in the archive**, which can exceed 300 seconds whenever archiving is failing or backlogged — a network partition, an expired certificate, an S3 authorization change, or an async queue that is not draining. That gap is precisely why [backup and recovery observability](#consequences) remains open: the alert that matters is on the age of the latest successfully archived WAL, not on the configured interval.

**Backup access is a separate IAM identity.** `trupryce-data-platform-backup` holds read, write, list, and delete confined to the backup prefix. `trupryce-data-platform-vps` is not modified and gains no delete authority anywhere. One workload certificate, two Roles Anywhere profiles, two roles with disjoint authority.

**No long-lived AWS key is ever created.** Credentials are exchanged per invocation from the workload certificate, and pgBackRest consumes them through `repo1-s3-key-type=process`. The backup role's trust policy pins both the trust anchor and `CN=trupryce-data-platform-vps`, so a valid chain alone is not authority.

**Backups are scheduled by the host supervisor.** systemd timers, never Airflow, because Airflow's own metadata database is one of the protected databases. The units are implemented; their installation is an operator step and is not itself a decision.

## Alternatives

- **Provisioning the 250 GB volume to satisfy the contract as written** was rejected as buying hardware to make a document true. The capacity was never measured; the figure came from an initial estimate.
- **Silently ignoring the 250 GB requirement** was rejected because an accepted `SHALL` that implementation contradicts is worse than either honouring or amending it.
- **Granting delete to the existing data role** so it could expire its own backups was rejected: it would let the identity that processes untrusted county archives destroy the backups protecting against them.
- **A second workload certificate for the backup role** was rejected on the same host. The certificate attests which host this is, and it is the same host; authority is separated at the role. A distinct certificate per *host* remains correct and is what a provider migration gets.
- **Long-lived IAM access keys** were rejected as the failure mode Roles Anywhere exists to remove.
- **Filesystem snapshots of the Docker volume** were rejected as not crash-consistent for a running cluster and as leaving recovery material on the host being recovered from.
- **`pg_dump`** was rejected because logical dumps cannot perform point-in-time recovery and do not restore a cluster with its roles.

## Consequences

- Recovery no longer depends on any property of the host's storage, so a provider migration is a restore rather than a volume transfer.
- The pgBackRest cipher passphrase becomes recovery-critical material: losing it makes every backup unrecoverable. It is escrowed in Bitwarden under [ADR-0003](0003-bitwarden-environment-secret-recovery.md).
- The workload certificate becomes an availability dependency of backup, not just of data access. It expires 2026-11-17 and renewal is not yet automated.
- Enabling `archive_mode` requires one PostgreSQL restart.
- A sustained S3 outage accumulates WAL on the root disk, and PostgreSQL stops if that disk fills. This is a monitored condition the observability requirement must eventually cover.
- Creating and changing the backup identity requires administrative AWS credentials that the runtime host deliberately does not hold, so parts of the procedure are operator actions rather than automation.

## Related

- [Architecture decisions](README.md)
- [ADR-0001: Independent Akamai runtime](0001-independent-akamai-runtime.md)
- [ADR-0002: S3 durable recovery boundary](0002-s3-durable-recovery-boundary.md)
- [ADR-0003: Bitwarden environment-secret recovery](0003-bitwarden-environment-secret-recovery.md)
- [PostgreSQL backup and recovery runbook](../operations/postgresql-recovery.md)
