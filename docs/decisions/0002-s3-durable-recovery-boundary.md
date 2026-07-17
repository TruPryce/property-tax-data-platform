# ADR-0002: S3 Durable Recovery Boundary

## Status

Accepted on 2026-07-16. The provider backup add-on will be disabled after recovery validation succeeds.

## Context

The platform must be portable to another VPS provider. Akamai's instance backup service does not protect attached Block Storage volumes and is not a substitute for PostgreSQL point-in-time recovery.

## Decision

The VPS, root disk, and attached volume are replaceable compute and performance capacity. Amazon S3 is the durable recovery boundary for:

- immutable Bronze source artifacts and manifests;
- versioned consumer exports;
- Airflow remote task logs; and
- encrypted PostgreSQL physical backups and continuous WAL archives.

PostgreSQL backup and recovery will use `pgBackRest` or an equivalently reviewed tool that produces base backups plus continuous WAL archives. The initial policy targets a maximum five-minute WAL archive interval, daily differential backups, weekly full backups, and at least three retained full-backup cycles. Recovery testing must restore the complete cluster, including platform and Airflow databases, into a clean environment.

The Linode backup add-on is temporary bootstrap protection only. It will be disabled after a database point-in-time restore and a complete clean-host rebuild from Git, S3, and secret escrow both succeed.

## Alternatives

- Depending on Linode snapshots was rejected because the database is expected on an attached volume and provider snapshots do not provide the required recovery or portability contract.
- WAL-only archiving was rejected because WAL cannot restore without a valid base backup.
- Treating the attached volume as durable storage was rejected because it prevents a provider-independent rebuild.

## Consequences

- Backup health, archive lag, retention, encryption, and restore tests become platform-owned operational responsibilities.
- S3 bucket policies and credentials must limit blast radius and protect backup deletion.
- Recovery time depends on provisioning a replacement host and transferring the retained database backup.
- Local-only state outside PostgreSQL must either be reproducible from Git and deployment automation or be copied to an approved durable store.

## Related

- [Architecture decisions](README.md)
- [ADR-0001: Independent Akamai runtime](0001-independent-akamai-runtime.md)
- [ADR-0003: Bitwarden environment-secret recovery](0003-bitwarden-environment-secret-recovery.md)
- [Active OpenSpec design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md)

## References

- [Akamai Block Storage limits](https://techdocs.akamai.com/cloud-computing/docs/block-storage): attached volumes are not covered by the Backups service.
- [Akamai Backups service](https://techdocs.akamai.com/cloud-computing/docs/backup-service): backups remain in the same data center and live database-file snapshots may be inconsistent.
- [Akamai backup cancellation](https://techdocs.akamai.com/cloud-computing/docs/cancel-backups): cancellation deletes all retained provider backups.
