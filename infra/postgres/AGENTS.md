# PostgreSQL Migration Agent Guide

## Rules

- Never edit, rename, or renumber a migration that has been applied anywhere; correct it with a new one.
- Name files `NNNN_snake_case_description.sql` with four-digit zero padding, so lexicographic order is the apply order.
- Never reuse a number. If two branches claim the same one, renumber the unmerged migration before merging.
- Keep migrations forward-only. There are no down migrations; recovery is a restore, not a rollback.
- One logical change per file. A migration that does two unrelated things cannot be reasoned about when one half fails.
- Grant privileges to `property_tax_ingestion` and `property_tax_api` in the same migration that creates the object, and include `ALTER DEFAULT PRIVILEGES` so later objects inherit them.
- Grant the narrowest privilege the role needs; the API role reads and does not write.
- Set `lock_timeout` and `statement_timeout` in any migration touching a populated table.
- Run migrations as `property_tax_migrator`. Needing superuser means the migration is doing something it should not.
- Put schema in `migrations/`, never in `init/`, which only executes against an empty data directory and will never reach an existing cluster.
- Keep county parsing, business rules, and environment-specific literals out of SQL. No secrets, no production data, no owner data in a migration or fixture.
- Declare explicitly when a statement cannot run in a transaction, and record how to recover if it fails halfway.
- Apply the full set from an empty cluster before publishing, and verify the result as the consuming role rather than the owner.

## Validation

```bash
make infra-check
```

Verify against a throwaway container from the pinned image, never a shared database. See
[the migration contract](README.md) for the commands.

## Related

- [Migration contract](README.md)
- [Infrastructure agent guidance](../AGENTS.md)
- [Airflow implementation ways of working](../../docs/engineering/airflow-implementation.md)
- [Root agent guidance](../../AGENTS.md)
