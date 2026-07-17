# Ingestion Worker

The ingestion worker is the runtime composition root for local CLI commands and future isolated Airflow task execution.

Inspect the initial source registry:

```bash
uv run --package property-tax-ingestion-worker property-tax-ingestion counties
```

The command performs no external network or database access.

## Related

- [Services](../README.md)
- [Source adapters](../../libs/property-tax-adapters/README.md)
- [Operations](../../docs/operations/README.md)
