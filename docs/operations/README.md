# Operations

The initial [runtime infrastructure foundation](../../infra/README.md) provides a version-pinned Airflow 3.3 and PostgreSQL 16 Compose topology for local validation and the future independent Akamai runtime. It is not production-ready: Tailscale provisioning, S3 remote logs, Bronze storage, backup and WAL archiving, restore exercises, monitoring, TLS, and deployment automation remain open infrastructure tasks.

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
