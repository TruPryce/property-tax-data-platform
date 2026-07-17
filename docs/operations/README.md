# Operations

Production runbooks will cover connection names, scheduled discovery, explicit backfills, release state inspection, quarantine review, publication promotion, and rollback. They will be added as the infrastructure tasks in the active change are implemented.

The initial scaffold exposes only a local, read-only registry command:

```bash
make counties
```

This command requires no source, object-store, database, or Airflow credentials.

## Related

- [Documentation hub](../README.md)
- [Architecture](../architecture/README.md)
- [Ingestion worker](../../services/ingestion-worker/README.md)
