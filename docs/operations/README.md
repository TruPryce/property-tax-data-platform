# Operations

The initial [runtime infrastructure foundation](../../infra/README.md) provides a version-pinned Airflow 3.3 and PostgreSQL 16 Compose topology for local validation and the future independent Akamai runtime. It is not production-ready: Tailscale provisioning, S3 remote logs, Bronze storage, monitoring, TLS, and deployment automation remain open infrastructure tasks.

PostgreSQL backup and recovery is defined and implemented in [PostgreSQL backup and recovery](postgresql-recovery.md): a pinned pgBackRest repository in S3, continuous WAL archiving, and the point-in-time and clean-host restore procedures. The repository is live and a point-in-time restore has been exercised and recorded there. **systemd backup units are implemented; installation on the Akamai host remains pending**, so scheduled physical backups are not yet running.

Production runbooks will cover connection names, scheduled discovery, explicit backfills, release state inspection, quarantine review, publication promotion, rollback, and recovery as those controls are implemented.

The initial scaffold exposes only a local, read-only registry command:

```bash
make counties
```

This command requires no source, object-store, database, or Airflow credentials.

Repository-agent control-plane operations are documented separately because they are developer-platform behavior, not appraisal runtime behavior:

- [CountyForge GitHub operations](countyforge-github-operations.md) - enablement, controlled verification, status, cancellation, retry, leases, and incident response.

## Related

- [Documentation hub](../README.md)
- [Architecture](../architecture/README.md)
- [Runtime infrastructure](../../infra/README.md)
- [Ingestion worker](../../services/ingestion-worker/README.md)
- [CountyForge GitHub operations](countyforge-github-operations.md)
- [Control-plane engineering guide](../engineering/countyforge-github-control-plane.md)
