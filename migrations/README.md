# Database migrations

Numbered SQL files, applied in order by a database administrator. There is no
runner and nothing in the platform applies these at startup — the deployment
step is a person reading SQL and executing it.

That shapes what is here. Each file is one transaction, refuses to apply twice,
refuses to apply out of order, and says why in a sentence rather than leaving a
constraint violation to be interpreted. Every file has a matching rollback.

## Applying

```sh
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f 0001_release_manifests.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f 0002_silver_canonical.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f 0003_release_diagnostics.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f 0004_quality_results.sql
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f 0005_publication_metadata.sql
```

`--single-transaction` is belt to the file's own `BEGIN`/`COMMIT`, and
`ON_ERROR_STOP=on` is what stops psql continuing past a failed statement.

**Requires PostgreSQL 15 or newer.** `0001` checks this before creating anything,
because `NULLS NOT DISTINCT` is what makes the Silver retry key work and a
missing-feature failure halfway through a migration is worse than one on line
one. Verified against 16.13.

## What is applied

```sql
SELECT version, name, applied_at, applied_by FROM platform.schema_migration ORDER BY version;
```

The ledger is the record, not an inference from which tables happen to exist.
Re-running an applied file raises `migration 000N is already applied` and
changes nothing.

## Rolling back

```sh
psql "$DATABASE_URL" --single-transaction --set ON_ERROR_STOP=on -f rollback/0005_publication_metadata.sql
```

Reverse order only; each rollback refuses while a later migration is still
applied and names what is blocking it. **Rollbacks `DROP SCHEMA ... CASCADE`**,
so they destroy any data loaded since. That is the real cost of undoing a
schema, and it is stated here rather than discovered.

## What each migration creates

| # | Schema | Holds |
|---|---|---|
| 0001 | `platform`, `bronze` | The migration ledger; artifacts keyed by content, acquisition manifests, redirect chains, and the logical release partitions those bytes carry. |
| 0002 | `silver` | County rows at source grain with provenance inlined, identifiers and values under their exact source names, and the default-deny field publication policy. |
| 0003 | `ingestion` | Processing runs, one verdict per run with its counts, and diagnostics and notices in the closed vocabulary. |
| 0004 | `quality` | Rules as rows with configurable thresholds, and one result per rule evaluated against a run. |
| 0005 | `publication` | The three Gold products, every publication attempt with its lineage, and the current-publication pointer. |

## Things the schema decides, so a loader cannot

Worth reading before writing anything that loads into these tables, because
each of these will reject data that looks reasonable:

- **Divergence is kept, never overwritten.** The same release identity recorded
  against different bytes is two manifests. `bronze.diverged_release` derives
  the conflict at read time; there is no column to store a verdict in, because a
  stored verdict is a claim about what else existed when some writer looked, and
  two writers can both look, both see nothing, and both write.

- **Silver retry is idempotent by unique index**, on release, member, row,
  appraisal year, source family, and source status — with `NULLS NOT DISTINCT`,
  so a row whose family is absent collides with itself rather than quietly
  becoming two records.

- **A native value has exactly one representation.** Text, integer, or numeric,
  never two and never none. `lexical_text` keeps the characters the source
  actually carried, and an observed empty string is allowed on purpose.

- **Diagnostics have four columns and no fifth.** There is deliberately nowhere
  to put a complete row, an arbitrary source value, exception text, a
  credential, an identity, an address, or a host-local path. A free-text detail
  column would become the place all of those end up.

- **A failing quality rule must state what it measured and what it expected.**
  Enforced as a constraint, because a failure an operator cannot act on is a
  failure they will learn to ignore.

- **At most one publication is current per product and jurisdiction**, as a
  partial unique index. That is what makes publication atomic: promoting a build
  and demoting its predecessor is one transaction, and a half-finished swap
  cannot leave two rows claiming to be what consumers read.

- **Publishing a sensitive field requires a named approver, an approval time,
  and a review reference.** Permission cannot be granted by a default or by a
  migration.

## Verifying

`tests/migrations/test_migrations.py` applies every file against a real
PostgreSQL and then attacks each of the invariants above. It needs a database
and skips without one:

```sh
export PGPASSWORD="$(openssl rand -hex 16)"
docker run -d --name ptdp-test -p 5433:5432 \
    -e POSTGRES_PASSWORD="$PGPASSWORD" -e POSTGRES_DB=ptdp postgres:16-alpine

PTDP_TEST_DATABASE_URL=postgresql://postgres@localhost:5433/ptdp \
    uv run pytest tests/migrations -v
```

The password stays in `PGPASSWORD`, which libpq reads, rather than in the
connection string. A URL carrying a password ends up in shell history, process
listings, and eventually in a file someone commits.

Continuous integration has no PostgreSQL service yet, so these skip there. Task
3.6 owns that wiring.
