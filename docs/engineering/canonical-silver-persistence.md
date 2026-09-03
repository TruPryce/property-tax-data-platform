# Canonical Silver persistence

How the promoted canonical domain maps into PostgreSQL. Normative behaviour stays in the promoted
capabilities — [canonical appraisal records](../../openspec/specs/canonical-appraisal-records/spec.md)
and [canonical identity and provenance](../../openspec/specs/canonical-identity-and-provenance/spec.md)
— and this page records the relations that carry them and the consequences a loader has to know.
Where the two disagree the capability wins; nothing here restates a domain rule as though this were
the place it lives.

Migrations `0001`–`0005` persist acquisition, adapter/source-grain, and runtime evidence. Migrations
`0006`–`0016` map the canonical domain into a `canonical` schema beside them. Neither is derived from
the other, and the [migration contract](../../infra/postgres/README.md) has the apply procedure.

## Record to relation

Every **snapshot-parented** relation carries the same four lineage columns — `snapshot_key`,
`release_key`, `load_key`, `provenance_key` — with two composite foreign keys:
`(snapshot_key, release_key)` into the snapshot, and `(provenance_key, release_key, load_key)` into
provenance.

`canonical.owner_value_allocation` is the one exception, and deliberately: the domain parents an
allocation on the owner association rather than on the snapshot, so it carries `association_key`,
`release_key`, `load_key`, and `provenance_key` and **no `snapshot_key`**. Its parent key is
`(association_key, release_key)` into the association, and the snapshot is reached through that. A
loader writing allocations therefore resolves an association first; it has no snapshot column to fill
and must not invent one.

Every `*_key` generated column is a persistence locator and says so in its comment.

| record | relation | notes |
| --- | --- | --- |
| `AccountIdentity` | `canonical.account` | Identity is `(jurisdiction_code, source_account_id)` as a `UNIQUE`. No FIPS column. |
| `AccountSnapshot` | `canonical.account_snapshot` | Situs and legal description compose as named columns. Grain is a **non-unique** index. |
| `OwnerObservation` | `canonical.owner_observation` | Mailing address composes as named columns. No natural key over name or address. |
| `OwnerAssociation` | `canonical.owner_association` | References an owner observation of its own snapshot. |
| `OwnerValueAllocation` | `canonical.owner_value_allocation` | Parented by the association, and carries **no `snapshot_key`**. |
| `AppraisalValueObservation` | `canonical.appraisal_value_observation` | `kind` is exactly market, appraised, assessed. |
| `TaxingUnitObservation` | `canonical.taxing_unit_observation` | Source-native code and name, with no vocabulary. |
| `TaxableValueObservation` | `canonical.taxable_value_observation` | `taxing_unit_key` is `NOT NULL` and of the same snapshot. |
| `ExemptionObservation` | `canonical.exemption_observation` | Explicit scope; the association reference is present when and only when the scope says so. |
| `LandObservation` | `canonical.land_observation` | Area is a magnitude: finite and not negative. |
| `ImprovementObservation` | `canonical.improvement_observation` | Adds `year_built`, 1600–2200. |
| `GeometryObservation` | `canonical.geometry_observation` | Two payload columns, one logical field. |

`SitusAddress`, `MailingAddress`, and `LegalDescription` have no relation of their own. They compose
as prefixed named columns on the record that owns them, because giving them a relation would give
them a surrogate key and an independent grain, which is what "they are not records" denies.

Lineage lives in `canonical.jurisdiction`, `canonical.release`,
`canonical.artifact_release_binding`, `canonical.release_load`, and `canonical.provenance`.

## Four identity concepts a loader must keep apart

Collapsing these into one "primary key" idea is how a schema quietly narrows a domain.

| concept | what it answers | where it lives |
| --- | --- | --- |
| **domain grain** | which account, in which release | the non-unique index `account_snapshot (account_key, release_key)` |
| **evidence identity** | which release, artifact, member, row, parser contract, and layout produced this | `canonical.provenance` and its `NULLS NOT DISTINCT` source-position key |
| **persistence locator** | how a foreign key points at a row | every generated `*_key` |
| **retry key** | has this run already loaded this release | `canonical.release_load (release_key, run_id)` |

The snapshot relation deliberately carries **no** uniqueness beyond its surrogate primary key and
`(snapshot_key, release_key)` as the parent key target. Snapshot equality is structural over every
field except the source as-of value, so two snapshots sharing an account, a release, and a provenance
while differing in a situs or legal value are distinct values at one grain and both persist. A
`UNIQUE (load_key, account_key, provenance_key)` would refuse the second.

## The contract task 3.5 codes against

A canonical load is one transaction, and it opens with

```sql
INSERT INTO canonical.release_load (...) VALUES (...)
ON CONFLICT (release_key, run_id) DO NOTHING
RETURNING load_key;
```

A key back means this run has not loaded this release and the load proceeds under it. Nothing back
means the load already happened and the transaction ends having done nothing — no rows compared, no
child deduplicated, no natural key manufactured. `ON CONFLICT DO NOTHING` is available to
`property_tax_ingestion`; `ON CONFLICT DO UPDATE` is not, because `UPDATE` is not granted.

Two different runs of one release produce two loads and two complete record sets. That is divergence
kept, and it is also how a release observed in two artifacts is represented, since a load names
exactly one artifact. Choosing between them is the published-product boundary's decision, made by
run — the way `publication.publication` already chooses.

## What the database cannot enforce, said plainly

**Timezone-awareness.** PostgreSQL accepts a value with no offset into a `timestamptz` column and
reads it in the session time zone, so the same literal becomes two different instants under two
different sessions. No check can recover the difference, because the value is already absolute by the
time a constraint sees it. Refusing a naive value is therefore the domain constructor's obligation —
`AccountSnapshot.__post_init__` rejects one, and
`tests/unit/property_tax_domain/test_account.py` proves it — and the writing boundary must bind an
offset-bearing value. What persistence guarantees is that every instant column is
`timestamp with time zone` and never a wall-clock type, and that a supplied instant is returned
unchanged under any session zone.

**Which source field an adapter mapped.** The schema cannot tell an approved account key from an
owner-row discriminator carrying the same characters. The existence of a column is not permission to
map an unresolved source field into it; that rule is the county contract's and is tested at the
adapter boundary.

## The privilege boundary

| role | schema | relations |
| --- | --- | --- |
| `property_tax_ingestion` | `USAGE` | `SELECT, INSERT`. No `UPDATE`, no `DELETE`. `SELECT` only on `canonical.jurisdiction`. |
| `property_tax_api` | **nothing, not even `USAGE`** | nothing |

The canonical relations hold owner names, mailing addresses, situs addresses, and legal descriptions,
and `silver.field_publication_policy` is metadata that no view, row policy, or privilege applies. A
`SELECT` would return every value including those the policy denies, so the reading role is refused
by the schema before any table grant is consulted. Extending field-level policy to canonical columns,
and any bounded projection built on it, belongs to the Gold boundary rather than here.

## Validated state

Measured on the final candidate — rebased onto `main` at `51642fd` — rather than on an earlier one.
OpenSpec task checkboxes and bootstrap task 3.4 remain untouched; the separate completion and
archival pull request owns those mutations.

`make check` produces a different total in each environment it runs in, so every count below is
labelled with the environment that actually produced it rather than one being presented as the
default:

| `make check` | passed | skipped |
| --- | ---: | ---: |
| **GitHub Actions**, no PostgreSQL — what continuous integration actually sees | **1,468** | **266** |
| local host, no PostgreSQL | 1,482 | 252 |
| local host, PostgreSQL, no `psql` client | 1,725 | 9 |
| local host, PostgreSQL and `psql` client | 1,729 | 5 |

Three axes move those numbers, and only the first two are about this work:

- **A reachable PostgreSQL** through `PTDP_TEST_DATABASE_URL`. Continuous integration has none, so
  every database-backed test skips there.
- **A `psql` client on `PATH`.** Three of the twenty-one migration-contract tests run the documented
  apply command and the checksum guard, both client-side behaviour the wire protocol cannot reach.
- **Host-only infrastructure prerequisites**, which have nothing to do with canonical persistence and
  are the entire difference between the first two rows. Those fourteen tests are
  `tests/unit/test_infrastructure_contract.py` cases at lines 347, 376, 413, 438, and 1768, which skip
  with *"requires the bws and docker executables the wrapper preflights"* and pass on a host carrying
  both. The psql-related skips cancel between those two rows — the same tests skip locally for a
  missing client and in CI for a missing database — so the fourteen are the whole delta.

Under the last row the five remaining skips are none of this work's: four are the same
infrastructure-contract cases needing Docker or a host identity file, and one is a pre-existing
intentional skip recorded in `test_migrations.py` itself.

| other gate | result |
| --- | --- |
| `ruff format --check .` and `ruff check .` | pass |
| `mypy` | pass, 92 source files |
| documentation links | pass, 62 documents |
| `openspec validate --all --strict` and `openspec doctor` | 17 passed, 0 failed; doctor ok |
| repository artifact policy | pass, 532 files |
| `make infra-check` | pass, 83 passed, 4 skipped — the same four environment cases |
| `make prepr-no-ai` | pass; paid provider review skipped by policy |

### Against a real server

The constraints in `0006`–`0016` are claims about a running PostgreSQL, so they were run against one
rather than asserted from the SQL text.

| | |
| --- | --- |
| image | `postgres:16.11-bookworm`, the tag the runtime pins |
| server | `PostgreSQL 16.11 (Debian 16.11-1.pgdg12+1) on x86_64-pc-linux-gnu` |
| client | `psql (PostgreSQL) 16.8` |

| suite | passed | skipped |
| --- | ---: | ---: |
| `tests/integration/postgres/test_canonical_identity.py` | 14 | 0 |
| `tests/integration/postgres/test_canonical_cardinality.py` | 13 | 0 |
| `tests/integration/postgres/test_canonical_values.py` | 28 | 0 |
| `tests/integration/postgres/test_canonical_privileges.py` | 14 | 0 |
| `tests/integration/postgres/test_canonical_migrations.py` | 21 | 0 |
| `tests/integration/postgres/test_canonical_release_load.py` | 8 | 0 |
| **total** | **98** | **0** |

A skipped suite is not passing evidence, which is why zero is the number that matters. The whole
directory, including the pre-existing `test_migrations.py`, is 264 passed and 1 skipped — that one
pre-existing intentional skip.

The same six suites are 95 passed and 3 skipped with a database but no `psql`, and 3 passed and 95
skipped with neither: the three that pass are the ones reading the migration files rather than a
server. Continuous integration has no PostgreSQL service, so the last of those is what it sees;
wiring one is bootstrap task 3.6 and is deliberately not attempted here.

The deltas this work adds reconcile exactly, measured on the local host with no database so the
infrastructure axis is held still: `+3` passed are those three file-reading tests, `+95` skips are the
rest of the canonical suites, and a further `+11` skips are the pre-existing
`test_applying_a_migration_twice_is_refused`, which parametrizes over the migration files and so now
covers `0006`–`0016` as well.

## Related

- [Engineering documentation](../README.md)
- [Canonical appraisal records](canonical-appraisal-records.md)
- [Canonical identity and provenance](canonical-identity.md)
- [PostgreSQL schema and migrations](../../infra/postgres/README.md)
