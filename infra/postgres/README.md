# PostgreSQL Schema and Migrations

Two mechanisms shape this database, and they are not interchangeable.

`init/10-create-runtime-databases.sh` runs **only against an empty data directory**, on the very
first start of a fresh volume. It creates the `airflow` and `property_tax` databases and the four
login roles, and nothing else. It is cluster bootstrap, not schema.

Everything else — schemas, tables, indexes, constraints, and the privileges that let
`property_tax_ingestion` and `property_tax_api` do more than connect — belongs in a migration.
Putting schema in `init/` would mean it never reaches an existing cluster, and never reaches
production at all after the first boot.

Migrations are tracked by task 3.4 of the
[foundation change](../../openspec/changes/bootstrap-six-county-appraisal-platform/tasks.md). **The
runner described below is not implemented yet**; this document is the contract it has to satisfy.

## Layout

```text
infra/postgres/migrations/0001_create_release_manifest.sql
infra/postgres/migrations/0002_create_silver_account_snapshot.sql
infra/postgres/migrations/0010_add_quality_result_index.sql
```

`NNNN_snake_case_description.sql`, applied in ascending filename order.

The four-digit zero padding is what makes lexicographic order match numeric order. Without it `10`
sorts before `9`, and the apply order silently stops matching the order the migrations were written
in. Numbers are never reused and never renumbered.

## Apply Contract

A migration is applied at most once, in order, and never changes afterwards. The runner:

1. takes a PostgreSQL advisory lock, so two concurrent runners — a deploy and a manual invocation,
   or two Airflow tasks — cannot both apply the same file;
2. reads the `schema_migrations` ledger, which records filename, SHA-256 of the file contents,
   applied timestamp, and applying role;
3. **verifies the checksum of every already-applied file** and aborts if one differs, because an
   edited migration means the database and the repository have diverged silently;
4. applies each pending file in a single transaction, recording the ledger row in that same
   transaction, so a failure leaves neither partial schema nor a false ledger entry;
5. stops at the first failure rather than continuing past it.

Migrations are **forward-only**. There are no down migrations: a mistake is corrected by a new
migration, which is the only form that also works on a database that has already moved on. Recovery
from a bad migration is the restore path in
[ADR-0002](../../docs/decisions/0002-s3-durable-recovery-boundary.md), not a rollback script.

A file that genuinely cannot run inside a transaction — `CREATE INDEX CONCURRENTLY` is the usual
case — declares it explicitly in a header comment so the runner skips the wrapping. That is an
exception with a cost: such a migration can fail halfway and needs its own recovery note.

## Privileges Are Migration Work

The bootstrap deliberately leaves `property_tax_ingestion` and `property_tax_api` able only to
connect. Every migration that creates a relation is also responsible for the grants that make it
usable, **including default privileges for objects created later**:

```sql
GRANT USAGE ON SCHEMA silver TO property_tax_ingestion, property_tax_api;
GRANT SELECT, INSERT, UPDATE ON silver.account_snapshot TO property_tax_ingestion;
GRANT SELECT ON silver.account_snapshot TO property_tax_api;

ALTER DEFAULT PRIVILEGES FOR ROLE property_tax_migrator IN SCHEMA silver
  GRANT SELECT ON TABLES TO property_tax_api;
```

Omitting the `ALTER DEFAULT PRIVILEGES` line is the common failure: existing tables work, and every
table added afterwards is invisible to the reading role until someone notices in production.

Grant the narrowest privilege the role needs. `property_tax_api` reads; it does not write.

## Running Them

Migrations run as `property_tax_migrator`, which owns the `property_tax` database. They do not run
as `platform_admin`: a migration that needs superuser is a migration that is doing something it
should not.

Set `lock_timeout` and `statement_timeout` at the top of any migration touching a populated table.
Without them a migration that cannot acquire a lock waits behind live traffic and blocks every
session queued behind it, which turns a schema change into an outage.

## Verifying a Migration Before It Ships

Apply it to a throwaway cluster from the same pinned image, not to a shared database:

```bash
docker run --rm -d --name migration-check \
  -e POSTGRES_USER=platform_admin -e POSTGRES_PASSWORD=throwaway \
  -e AIRFLOW_DB_PASSWORD=x -e PROPERTY_TAX_MIGRATOR_PASSWORD=x \
  -e PROPERTY_TAX_INGESTION_PASSWORD=x -e PROPERTY_TAX_API_PASSWORD=x \
  property-tax-postgres:16.11
```

Then apply the full migration set from empty and confirm the end state, rather than applying only
the new file to an already-migrated database. Ordering bugs and missing grants only appear on a
from-scratch run.

Check the result as the role that will use it in production, not as the owner — the owner can see
everything, which is exactly why testing as the owner proves nothing about grants.

## Related

- [Infrastructure overview](../README.md)
- [PostgreSQL migration agent guidance](AGENTS.md)
- [ADR-0002: S3 durable recovery boundary](../../docs/decisions/0002-s3-durable-recovery-boundary.md)
