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
  migrations/0002_silver_source_records.sql
  migrations/0003_release_diagnostics.sql
  migrations/0004_quality_results.sql
  migrations/0005_publication_metadata.sql
  migrations/0006_canonical_schema.sql
  migrations/0007_canonical_jurisdiction_registry.sql
  migrations/0008_canonical_release_identity.sql
  migrations/0009_canonical_release_load.sql
  migrations/0010_canonical_provenance.sql
  migrations/0011_canonical_accounts.sql
  migrations/0012_canonical_owners.sql
  migrations/0013_canonical_values.sql
  migrations/0014_canonical_exemptions.sql
  migrations/0015_canonical_land_and_improvements.sql
  migrations/0016_canonical_geometry.sql
```

`NNNN_snake_case_description.sql`, applied in ascending filename order.

The four-digit zero padding is what makes lexicographic order match numeric order. Without it `10`
sorts before `9`, and the apply order silently stops matching the order the migrations were written
in. Numbers are never reused and never renumbered.

The Dockerfile copies `init/` as a **directory**, so adding `20-create-extensions.sql` beside the
bootstrap script needs no change to it and the lexicographic convention is real rather than
documented. Migrations are deliberately **not** copied in: they are operational SQL, not container
content, and baking them in would invite the belief that starting a container applies them.

## Applying

```sh
(
    set -e
    cd infra/postgres/migrations
    for f in [0-9][0-9][0-9][0-9]_*.sql; do
        psql "$DATABASE_URL" --set ON_ERROR_STOP=on \
            -v file_sha256="$(sha256sum "$f" | cut -d' ' -f1)" -f "$f"
    done
)
```

The glob is matched rather than enumerated, so adding a migration needs no edit here,
and four-digit zero padding is what makes its lexicographic order the apply order.

The subshell and `set -e` are the fail-fast part, and the shape matters more than it
looks. `... || break` reads like fail-fast and is the opposite: `break` succeeds, so
the loop exits with status 0 and an operator or a script reading `$?` is told a failed
apply was a successful one. Ending the subshell on the first non-zero status propagates
psql's own exit code — 3 under `ON_ERROR_STOP` — while leaving the calling shell alive.
A test applies this block verbatim, against a fresh database and against one that would
fail, and asserts the status both times.

Each file carries its own `BEGIN`/`COMMIT`, so `--single-transaction` is not used: it opens a second
transaction, warns on every file, and the file's own `COMMIT` closes things first anyway.
`ON_ERROR_STOP=on` is what stops psql continuing past a failed statement.

`file_sha256` is required. A migration refuses to run without it and says how to supply it, because
the ledger recording that version 3 ran cannot otherwise tell you whether the 0003 file on disk is
still the one that ran — and under manual application nothing else is positioned to notice.

Migrations run as `property_tax_migrator`, which owns the `property_tax` database. They do not run
as `platform_admin`: a migration that needs superuser is a migration doing something it should not.

**Requires PostgreSQL 15 or newer.** `0001` checks this before creating anything, because
`NULLS NOT DISTINCT` is what makes the Silver retry key work and a missing-feature failure halfway
through a migration is worse than one on line one. Verified against 16.13; the pinned runtime image
is 16.11.

## What these are not

Two schemas hold county data and they are not interchangeable.

`silver` persists the shared adapter source-record shape: **one row per physical source row**,
identifiers and values under their exact source names, with `source_account_id` nullable because
Collin publishes no single account identifier. It is acquisition-shaped evidence, and it is where an
unmapped source-native value field stays — Dallas `TOT_VAL` while its semantics are unresolved, a
value with no accepted canonical equivalence, a county whose account key is unapproved.

`canonical` persists the promoted domain: account identity, the release-scoped snapshot, and the ten
parented records the canonical capability defines. Nothing in it is derived from `silver` by these
migrations, and neither replaces the other. The distinction is structural rather than a naming
convention: they are different schemas with different privileges, and `canonical`'s default
privileges grant exactly `SELECT` and `INSERT` so a relation added later cannot inherit the ability to
overwrite.

A canonical row exists only where a loader created one from evidence. No migration backfills one, and
a release whose kind, identifier, or county falls outside the canonical contract has no canonical
identity at all — the evidence stays in `bronze` and in `silver` with its lineage rather than being
canonicalized by a guess.

## What is applied

```sql
SELECT version, name, applied_at, applied_by, file_sha256
FROM platform.schema_migration ORDER BY version;
```

The ledger is the record, not an inference from which tables happen to exist. Re-running an applied
file raises `migration 000N is already applied` and changes nothing.

## What each migration creates

| # | Schema | Holds |
|---|---|---|
| 0001 | `platform`, `bronze` | The migration ledger; artifacts keyed by content, acquisition manifests, redirect chains, and the logical release partitions those bytes carry. |
| 0002 | `silver` | County rows at **adapter** grain with provenance inlined, identifiers and values under their exact source names, and the default-deny field publication policy. |
| 0003 | `ingestion` | Processing runs, one verdict per run with its counts, and diagnostics and notices in the closed vocabulary. |
| 0004 | `quality` | Rules as rows with configurable thresholds, and one result per rule evaluated against a run. |
| 0005 | `publication` | The three Gold products, every publication attempt with its lineage, and the current-publication pointer. |
| 0006 | `canonical` | The schema, and the lexical vocabulary every relation in it uses: the identifier alphabet, the control-character rule, one bounded-text predicate, and finiteness for a `numeric`. |
| 0007 | `canonical` | The county registry, seeded from the version-controlled one the domain validates against, and read-only to the loader. |
| 0008 | `canonical` | Canonical release identity, and its many-to-many association with the artifacts that carry it. |
| 0009 | `canonical`, `bronze` | One canonical load — one release, one run, one artifact — gated on an accepted outcome. **The only migration that alters a pre-existing relation:** it adds `UNIQUE (manifest_id, artifact_sha256)` to `bronze.release_manifest`, an index and nothing else, which cannot fail on existing rows because `manifest_id` is already that relation's primary key. Without it there is nothing to key a load's artifact to, and a record could claim bytes its run never opened. |
| 0010 | `canonical` | Bounded provenance, tied to its load's release, artifact, and county. |
| 0011 | `canonical` | Account identity, and one account as one logical release observed it. |
| 0012 | `canonical` | Owner observations, their associations, and owner-scoped value allocations. |
| 0013 | `canonical` | Market, appraised, and assessed values; taxing units; and taxable values that exist only for one. |
| 0014 | `canonical` | Exemptions, with the county's own classification and an explicit scope. |
| 0015 | `canonical` | Land and improvement children at their own grain. |
| 0016 | `canonical` | Geometry as an enrichment, carried opaquely and with no geospatial dependency. |

## Things the schema decides, so a loader cannot

Worth reading before writing anything that loads into these tables, because each of these will
reject data that looks reasonable:

- **Divergence is kept, never overwritten.** The same release identity recorded against different
  bytes is two manifests. `bronze.diverged_release` derives the conflict at read time; there is no
  column to store a verdict in, because a stored verdict is a claim about what else existed when some
  writer looked, and two writers can both look, both see nothing, and both write.

- **Lineage is one release, not four facts that agree.** A Silver row's run, manifest, county, and
  release identifier are a single composite reference to `ingestion.run`, and a run's county is a
  composite reference to the manifest it read. Four separate foreign keys would each hold while the
  row named one county and pointed at another's run.

- **A run processes one logical partition, not an artifact.** One archive carries current values for
  one year and certified values for another, so a run names its `tax_year` and `release_kind` and
  references `bronze.release_partition`. Binding to the manifest alone left which release a run
  processed unstated, and a publication could then claim the other one.

- **Run identity is immutable to the loader.** `property_tax_ingestion` may insert a run and update
  only `finished_at`. Silver records and publications bind to a run's county, release, and partition,
  so an `UPDATE` that repointed it would invalidate both while every foreign key still held.

- **An outcome and its retained evidence are one sealed unit.** The scalar counts and the diagnostic
  rows are two descriptions of the same thing, and a `CHECK` sees only one row of one of them.
  Deferred constraint triggers judge them together at `COMMIT`: retained rows equal
  `min(total, 100)`, truncation is true exactly when the total exceeds 100, an accepted outcome
  retains nothing, and a retained diagnostic's layout fingerprint is the outcome's own. A loader
  therefore writes the pair in one transaction, and appending evidence afterwards fails because the
  total no longer matches.

- **A persisted outcome is one the carrier could have produced.** The constraints on
  `ingestion.release_outcome` mirror `ReleaseOutcome.__post_init__`: accepted exactly when there were
  no diagnostics, commits exactly what it staged, rejects no row, boundary contract version one,
  prepared fields set together or not at all, retained evidence indexed 0 to 99. The publication gate
  reads `accepted` as authoritative, so an outcome the boundary could not have made would be trusted.

- **An outcome cannot be rewritten.** `property_tax_ingestion` may insert an outcome and its evidence
  and may not update them: a disposition is a verdict about a run that has finished, and something may
  already have published from it.

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

- **A publication is admitted as current only against an accepted release.** A trigger requires a run
  with an accepted outcome, that read this release, whose artifact carries the year and kind claimed,
  and that has no blocking quality failure. **This is admission, not maintenance**: it runs when the
  publication row is written and does not re-evaluate, so a blocking evaluation recorded afterwards
  leaves an already-current row current. Sealing quality for a published release needs a finalization
  model that task 6.2 owns, and is deliberately not attempted here. A test records that gap so it
  stays a decision rather than a surprise.

- **At most one publication is current per product and jurisdiction**, as a partial unique index.
  That is what makes publication atomic: promoting a build and demoting its predecessor is one
  transaction, and a half-finished swap cannot leave two rows claiming to be what consumers read.

- **Publishing a sensitive field requires a named approver, an approval time, and a review
  reference.** Permission cannot be granted by a default or by a migration.

- **Divergent snapshots are kept, never collapsed.** One account observed in one release through two
  acquisitions is two loads, two provenance rows, and two snapshots. The grain — account and release —
  is a plain index and deliberately not a constraint, because a `UNIQUE` over it would discard the
  second observation. There is no uniqueness over load, account, and provenance either: snapshot
  equality is structural over every field but the source as-of value, so two snapshots differing only
  in a situs or legal value are distinct and both belong.

- **A record's lineage is one authority.** No canonical relation carries a release identifier, tax
  year, release kind, or artifact of its own; each reaches all of them through `canonical.provenance`,
  whose release, artifact, and county are its load's own by composite key. A record therefore cannot
  claim bytes its processing run never opened, and both directions of that escape are closed.

- **Parent agreement is at release grain, not load grain.** A child must hang from a snapshot of its
  own release, and may legitimately come from a second artifact of that release — a GIS enrichment
  acquired separately is the case this permits. Crossing a release is refused.

- **A canonical release either rests on evidence or does not exist.** `canonical.release` enforces the
  closed four-kind vocabulary, the identifier alphabet, and membership of the persisted county
  registry. A Denton `preliminary` roll, an identifier carrying whitespace, and `tx-madeup` each have
  no canonical release, and without one there is no load and no canonical record. Nothing derives an
  identifier from a filename, a digest, a year, a kind, row order, or an acquisition time.

- **A rejected release commits no canonical record.** A deferred constraint trigger requires, at
  `COMMIT`, that the load's run carries an accepted `ingestion.release_outcome`. Deferred so a loader
  may write the records and the outcome in one transaction in either order.

- **Canonical rows are insert-only to the loader.** `property_tax_ingestion` holds `SELECT` and
  `INSERT` and neither `UPDATE` nor `DELETE`, so `ON CONFLICT DO NOTHING` is available and
  `ON CONFLICT DO UPDATE` is not: the unsafe half of a merge is unavailable rather than discouraged.
  Retry is answered once, at `canonical.release_load (release_key, run_id)`.

- **`property_tax_api` is granted nothing in `canonical`, not even `USAGE`**, so a table grant added
  by mistake is still unreachable. The canonical relations hold owner names and addresses, and
  representing a field is not permission to publish it.

## There is no rollback

Migrations are forward-only. A mistake is corrected by a new migration, which is the only form that
also works on a database that has already moved on.

A disposable database is rebuilt: drop it or destroy the volume, start a fresh cluster so `init/`
runs, and apply the migrations from `0001`. A real one is recovered through the restore path in
[PostgreSQL backup and recovery](../../docs/operations/postgresql-recovery.md), which implements the
boundary [ADR-0002](../../docs/decisions/0002-s3-durable-recovery-boundary.md) decided: an encrypted
pgBackRest repository in S3 with continuous WAL, restored to a chosen point in time into an isolated
target. Restoring a real database is never done over the production volume.

That path also carries what `init/` cannot. `init/` runs only against an empty data directory, so on a
cluster initialized long ago it will never run again and the roles it creates exist only because it ran
once. A physical restore reproduces the whole cluster — databases, roles, and privileges together —
which is why recovery is a physical backup rather than a dump of the schema these migrations build.

Inverse scripts were considered and removed. One that `DROP SCHEMA ... CASCADE` is a production
footgun sitting beside the thing it destroys, and it is a second schema history that has to stay
correct forever to be worth anything.

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

Every migration here grants what its objects need. Bronze is `SELECT`/`INSERT` only for
`property_tax_ingestion`, so acquisition evidence is immutable by privilege rather than by
intention, and no role may define a quality rule. No sequence grants are needed: every generated key
is `GENERATED ALWAYS AS IDENTITY`, whose implicit sequence is covered by `INSERT` on the table.

**`property_tax_api` is granted nothing by these migrations and stays connect-only.**
`silver.field_publication_policy` is metadata: no view, row policy, or privilege applies it, so
`SELECT` on `silver.source_native_value` would return every retained value including those the policy
denies. Dallas retains every unknown extra column by accepted contract (issue #78), so an
`OWNER_NAME` or address-shaped column in a real release lands there. The API reads approved Gold
products through bounded projections that do not exist yet; until they do, connect-only is the only
honest privilege.

## The Apply Contract, and What Still Does Not Meet It

Manual `psql` execution is the interim path, not a replacement for the apply contract. A runner
remains future work, and it owes three things this procedure cannot provide:

- **An advisory lock** taken before applying, so a deploy and a hand-run cannot both apply the same
  file. Nothing serialises two operators today.
- **Verification of every already-applied checksum**, not only recording the current one. The ledger
  stores what an operator supplied; it cannot prove that value was the hash of the file that ran, and
  it never re-reads prior entries to detect a migration edited after the fact.
- **Failing closed on a mismatch**, aborting rather than continuing past a file whose recorded hash no
  longer matches its contents.
- **A sealed quality boundary for published releases**, so `current` is a maintained invariant rather
  than a check that passed once. Task 6.2 owns it.

Also outstanding:

- **No `lock_timeout` or `statement_timeout`.** Harmless while these tables are empty; on a populated
  `silver` a statement that cannot take its lock waits behind live traffic and blocks everything
  queued behind it. Add both to any migration that touches a table holding rows.

## Verifying a Migration Before It Ships

`tests/integration/postgres/` applies every file against a real PostgreSQL and then attacks each
invariant above: `test_migrations.py` for `0001`-`0005`, and six canonical suites for `0006`-`0016` —
identity and grain, cardinality and cross-wiring, scalars and vocabularies and geometry, privileges,
the migration contract and both upgrade paths, and release atomicity. They need a database and skip
without one:

```sh
export PGPASSWORD="$(openssl rand -hex 16)"
docker run -d --name ptdp-test -p 5433:5432 \
    -e POSTGRES_PASSWORD="$PGPASSWORD" -e POSTGRES_DB=ptdp postgres:16.11-bookworm

PTDP_TEST_DATABASE_URL=postgresql://postgres@localhost:5433/ptdp \
    uv run pytest tests/integration/postgres -v
```

The image is the one the runtime pins, so the suite exercises the server that will actually run these
rather than a nearby version.

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
- [Canonical Silver persistence](../../docs/engineering/canonical-silver-persistence.md)
- [ADR-0002: S3 durable recovery boundary](../../docs/decisions/0002-s3-durable-recovery-boundary.md)
- [PostgreSQL backup and recovery](../../docs/operations/postgresql-recovery.md)
