# Operations

Production runbooks will cover connection names, scheduled discovery, explicit backfills, release state inspection, quarantine review, publication promotion, and rollback. They will be added as the infrastructure tasks in the active change are implemented.

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
- [Ingestion worker](../../services/ingestion-worker/README.md)
- [CountyForge GitHub operations](countyforge-github-operations.md)
- [Control-plane engineering guide](../engineering/countyforge-github-control-plane.md)
