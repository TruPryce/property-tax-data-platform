# PostgreSQL Schema and Migrations

Two mechanisms shape this database, and they are not interchangeable.

`init/10-create-runtime-databases.sh` runs **only against an empty data directory**, on the very
first start of a fresh volume, in lexicographic order with anything else placed beside it. It creates
the `airflow` and `property_tax` databases and the four login roles, and nothing else. It is cluster
bootstrap, not schema, and it is the only part of this directory copied into the image.

Everything else — schemas, tables, indexes, constraints, and the privileges that let
`property_tax_ingestion` and `property_tax_api` do more than connect — belongs in a migration.
Putting schema in `init/` would mean it never reaches an existing cluster, and never reaches
production at all after the first boot.

**There is no runner and nothing applies migrations at startup.** A database administrator reads the
SQL and executes it. That is deliberate, and it shapes everything below: each file is one
transaction, refuses to apply twice, refuses to apply out of order, and says why in a sentence
rather than leaving a constraint violation to be interpreted.

## Layout

```text
infra/postgres/
  Dockerfile                    copies init/ into the image, and nothing else
  init/                         automatic, lexicographic, only on an empty data directory
  migrations/0001_release_manifests.sql
  migrations/0002_silver_canonical.sql
  migrations/0003_release_diagnostics.sql
  migrations/0004_quality_results.sql
  migrations/0005_publication_metadata.sql
  migrations/rollback/          one per migration, reverse order only
```

`NNNN_snake_case_description.sql`, applied in ascending filename order.

The four-digit zero padding is what makes lexicographic order match numeric order. Without it `10`
sorts before `9`, and the apply order silently stops matching the order the migrations were written
in. Numbers are never reused and never renumbered.

Migrations are deliberately **not** copied into the image. They are operational SQL, not container
content, and baking them in would invite the belief that starting a container applies them.

## Applying

```sh
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f infra/postgres/migrations/0001_release_manifests.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f infra/postgres/migrations/0002_silver_canonical.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f infra/postgres/migrations/0003_release_diagnostics.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f infra/postgres/migrations/0004_quality_results.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f infra/postgres/migrations/0005_publication_metadata.sql
```

`--single-transaction` is belt to the file's own `BEGIN`/`COMMIT`, and `ON_ERROR_STOP=on` is what
stops psql continuing past a failed statement.

Migrations run as `property_tax_migrator`, which owns the `property_tax` database. They do not run
as `platform_admin`: a migration that needs superuser is a migration doing something it should not.

**Requires PostgreSQL 15 or newer.** `0001` checks this before creating anything, because
`NULLS NOT DISTINCT` is what makes the Silver retry key work and a missing-feature failure halfway
through a migration is worse than one on line one. Verified against 16.13; the pinned runtime image
is 16.11.

## What is applied

```sql
SELECT version, name, applied_at, applied_by FROM platform.schema_migration ORDER BY version;
```

The ledger is the record, not an inference from which tables happen to exist. Re-running an applied
file raises `migration 000N is already applied` and changes nothing.

## What each migration creates

| # | Schema | Holds |
|---|---|---|
| 0001 | `platform`, `bronze` | The migration ledger; artifacts keyed by content, acquisition manifests, redirect chains, and the logical release partitions those bytes carry. |
| 0002 | `silver` | County rows at source grain with provenance inlined, identifiers and values under their exact source names, and the default-deny field publication policy. |
| 0003 | `ingestion` | Processing runs, one verdict per run with its counts, and diagnostics and notices in the closed vocabulary. |
| 0004 | `quality` | Rules as rows with configurable thresholds, and one result per rule evaluated against a run. |
| 0005 | `publication` | The three Gold products, every publication attempt with its lineage, and the current-publication pointer. |

## Things the schema decides, so a loader cannot

Worth reading before writing anything that loads into these tables, because each of these will
reject data that looks reasonable:

- **Divergence is kept, never overwritten.** The same release identity recorded against different
  bytes is two manifests. `bronze.diverged_release` derives the conflict at read time; there is no
  column to store a verdict in, because a stored verdict is a claim about what else existed when some
  writer looked, and two writers can both look, both see nothing, and both write.

- **Silver retry is idempotent by unique index**, on release, member, row, appraisal year, source
  family, and source status — with `NULLS NOT DISTINCT`, so a row whose family is absent collides
  with itself rather than quietly becoming two records.

- **A native value has exactly one representation.** Text, integer, or numeric, never two and never
  none. `lexical_text` keeps the characters the source actually carried, and an observed empty string
  is allowed on purpose.

- **Diagnostics have four columns and no fifth.** There is deliberately nowhere to put a complete
  row, an arbitrary source value, exception text, a credential, an identity, an address, or a
  host-local path. A free-text detail column would become the place all of those end up.

- **A failing quality rule must state what it measured and what it expected.** Enforced as a
  constraint, because a failure an operator cannot act on is a failure they will learn to ignore.

- **At most one publication is current per product and jurisdiction**, as a partial unique index.
  That is what makes publication atomic: promoting a build and demoting its predecessor is one
  transaction, and a half-finished swap cannot leave two rows claiming to be what consumers read.

- **Publishing a sensitive field requires a named approver, an approval time, and a review
  reference.** Permission cannot be granted by a default or by a migration.

## Rolling back

```sh
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f infra/postgres/migrations/rollback/0005_publication_metadata.sql
```

Reverse order only; each rollback refuses while a later migration is still applied and names what is
blocking it.

**Rollbacks `DROP SCHEMA ... CASCADE`**, so they destroy any data loaded since. They guard ordering,
not data: nothing checks whether a table holds rows. Treat them as a development teardown for a
database that has never held a real release.

For a database that has, recovery from a bad migration is the restore path in
[ADR-0002](../../docs/decisions/0002-s3-durable-recovery-boundary.md), and the correction is a new
forward migration — the only form that also works on a database that has already moved on.

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

**The migrations here carry no grants yet.** Until they do, both roles remain connect-only and
cannot see these schemas, which blocks the ingestion loader and the read-only API role.

## Not Yet Met

Recorded so the gap is visible rather than assumed closed:

- **No checksum in the ledger.** `platform.schema_migration` records version, name, time, and role,
  but not a hash of the file. Under manual application nothing else is positioned to notice that an
  applied file was edited afterwards.
- **No grants**, as above.
- **No `lock_timeout` or `statement_timeout`.** Harmless while tables are empty; on a populated
  `silver` a statement that cannot take its lock waits behind live traffic and blocks everything
  queued behind it.

## Verifying a Migration Before It Ships

`tests/migrations/test_migrations.py` applies every file against a real PostgreSQL and then attacks
each invariant above. It needs a database and skips without one:

```sh
export PGPASSWORD="$(openssl rand -hex 16)"
docker run -d --name ptdp-test -p 5433:5432 \
    -e POSTGRES_PASSWORD="$PGPASSWORD" -e POSTGRES_DB=ptdp postgres:16-alpine

PTDP_TEST_DATABASE_URL=postgresql://postgres@localhost:5433/ptdp \
    uv run pytest tests/migrations -v
```

The password stays in `PGPASSWORD`, which libpq reads, rather than in the connection string. A URL
carrying a password ends up in shell history, process listings, and eventually in a file someone
commits.

Apply the full set from empty and confirm the end state, rather than applying only the new file to
an already-migrated database. Ordering bugs and missing grants only appear on a from-scratch run, and
check the result as the role that will use it in production, not as the owner — the owner can see
everything, which is exactly why testing as the owner proves nothing about grants.

Continuous integration has no PostgreSQL service yet, so these skip there. Bootstrap task 3.6 owns
that wiring.

## Related

- [Infrastructure overview](../README.md)
- [PostgreSQL migration agent guidance](AGENTS.md)
- [ADR-0002: S3 durable recovery boundary](../../docs/decisions/0002-s3-durable-recovery-boundary.md)
