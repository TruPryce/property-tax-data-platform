## Why

Bootstrap tasks 2.1 and 2.2 are complete and both capabilities are promoted. The platform now has a
canonical vocabulary — `canonical-identity-and-provenance` and `canonical-appraisal-records`,
16 requirements and 42 scenarios of it — and no durable place to put anything it names.

Migrations `0001`–`0005` persist acquisition, adapter/source-grain, and runtime evidence. They say so
themselves: `infra/postgres/README.md` records that `silver` "is **not** the canonical Silver model.
There is no account snapshot and no owner, allocation, exemption, jurisdiction, land, improvement, or
geometry child table", and that bootstrap task **3.4 is therefore not complete**. The storage-facing
engineering note for the promoted records ends with "No table, column, surrogate key, index, or DDL
is selected here."

This change selects them.

## What changes

`0001`–`0005` persist acquisition, source-grain, and runtime evidence. New forward migrations map the
already-promoted canonical domain into durable Silver **without changing the domain model and without
rewriting migration history**.

Eleven forward migrations, `0006` through `0016`, add a `canonical` schema holding the jurisdiction
registry, release identity, the artifact–release association, the release load that ties a canonical
release to the run and artifact it came from, provenance, account identity, the account snapshot, and
the ten parented record relations, each with its constraints, indexes, and privileges. Migrations
`0001`–`0005` are not edited; `0009` adds one constraint to `bronze.release_manifest`, which adds an
index and nothing else and cannot fail against existing rows. This planning change writes none of that
SQL; it decides it.

The result is a `canonical` schema whose shape a loader cannot argue with: an account identity that is
county-qualified, a snapshot grain that admits divergent evidence rather than collapsing it, every
parented record one-to-many because nothing established otherwise, a taxable value that cannot exist
without its taxing unit, provenance that cannot be cross-wired between counties or releases, and a
canonical release identity that either rests on evidence or does not exist.

## Scope

- Originating issue: #114
- Affected capabilities: canonical-silver-persistence (ADDED)
- Affected decisions: none; ADR-0002 and the forward-only contract in `infra/postgres/AGENTS.md` are
  followed rather than amended.

## The four dispositions

Every object in `0001`–`0005` was audited against the promoted contracts and falls into exactly one
of these. Nothing is left unclassified, and nothing old is changed to resolve a mismatch.

### A — sufficient, and unchanged

| object | why it is already right |
| --- | --- |
| `platform.schema_migration`, `platform.is_named` | The ledger and the one place the whitespace definition is written down. New migrations use both. |
| `bronze.artifact` | Content-keyed by SHA-256 — exactly `ArtifactIdentity`. Canonical provenance references it rather than repeating a digest. |
| `bronze.release_redirect`, `bronze.diverged_release` | Acquisition evidence and derived divergence. Canonical storage adds nothing here. |
| `ingestion.run` and its two composite unique keys | A run already carries all four canonical release components and the manifest. Its `UNIQUE (run_id, jurisdiction_code, release_identifier, tax_year, release_kind)` is the exact target the canonical bridge needs. |
| `ingestion.release_outcome`, `release_diagnostic`, `release_notice`, and the deferred seal | Issue #43's bounded diagnostic contract, already implemented: a closed twelve-code vocabulary, four columns and no fifth, and an outcome sealed against its evidence. |
| `quality.rule`, `quality.evaluation`, `quality.blocking_failure` | Rules as rows, evaluations bound to a run. Canonical loads bind to a run, so canonical-grain rules evaluate through the existing model. |
| `publication.product`, `publication.publication`, `current_publication`, and the admission trigger | Publication binds to a run, which now also reaches canonical rows. The task-6.2 sealing gap stays 6.2's. |
| `silver.field_publication_policy` | Default-deny, keyed by county and **source field**, requiring a named approver. Still authoritative for source fields. |

### B — useful, and adapter/source-grain rather than canonical

| object | what it is, and stays |
| --- | --- |
| `silver.source_record`, `silver.source_native_identifier`, `silver.source_native_value` | One row per **physical source row**, identifiers and values under their exact source names, `source_account_id` nullable because Collin publishes no single account identifier. This is where an unmapped source-native value field lives, and it is where one stays. |
| `bronze.release_partition` | `(manifest_id, jurisdiction_code, tax_year, release_kind)` — which logical partitions an artifact carries. It has **no** `release_identifier`, so it is not a canonical `ReleaseIdentity` and must not be read as one. |

### C — missing canonical persistence, added by `0006`+

The jurisdiction registry; canonical release identity; the artifact–release association; the release
load that binds a canonical release to one run and the one artifact that run read; canonical
provenance; account identity; the account snapshot with its composed situs and legal description; and
the ten parented record relations — owner observation and association, owner value allocation,
appraisal value, taxing unit, taxable value, exemption, land, improvement, and geometry — with their
constraints, indexes, and privileges.

### D — existing structure that needs a forward-compatible bridge

1. **`ingestion.run.release_identifier` is only "not blank"**, and `release_kind` is the open
   identifier grammar rather than the closed canonical vocabulary of four. A run can therefore name a
   release that has no canonical identity — Denton `preliminary` is a real example the promoted
   capability explicitly refuses to canonicalize. The bridge is a `canonical.release` relation that
   enforces the canonical grammar itself, joined to the run by a composite key over all four
   components. A run whose components fall outside the canonical contract simply has no canonical
   release, and therefore no canonical rows. **It fails closed; nothing is derived.**
2. **The jurisdiction code is constrained only by grammar**, everywhere it appears. `tx-madeup`
   matches it, and no domain `Jurisdiction` can be constructed for it, because registry validation
   refuses a slug the version-controlled registry does not describe. The bridge is a persisted
   `canonical.jurisdiction` registry seeded from that same source, which every canonical relation
   naming a county references.
3. **Nothing ties a record's artifact to the run that read it.** `ingestion.run` names a manifest and
   `bronze.release_manifest` names that manifest's artifact, but the pair is not a key, so canonical
   provenance could reference any artifact at all. The bridge is one `UNIQUE (manifest_id,
   artifact_sha256)` on `bronze.release_manifest` — an index and nothing else — which the canonical
   load keys into, and which every record's own provenance then inherits through its load. Parented
   records agree at the accepted release grain rather than being forced onto one load: the canonical
   domain permits a child from a second artifact of the same release, including partial GIS
   enrichment, while still requiring that each record's own artifact is the one its own run read.
4. **`silver.source_record.source_member_name` is only "not blank"** where canonical provenance
   requires the identifier grammar. Canonical provenance enforces its own rule rather than inheriting
   the looser one.

None is solved by editing an old migration.

## What this change deliberately does not do

- **It writes no SQL.** This is the planning change. `0006`+ are specified here and authored under the
  accepted plan.
- **It does not implement task 3.5.** COPY-to-staging and set-based idempotent merges are 3.5's. This
  change owes 3.5 an unambiguous target — a stated retry identity that is not a natural key — and
  stops there.
- **It creates no parallel diagnostic, quality, or publication model.** Task 3.4 names those
  categories; the audit found `0003`, `0004`, and `0005` already satisfy them. The single genuinely
  missing object is the release-atomicity gate that makes "a rejected release has no canonical rows"
  structural rather than a loader's promise.
- **It resolves no county semantics.** Dallas `TOT_VAL` (#58), the Dallas extras boundary (#78), and
  any unapproved account or child key stay unresolved and stay outside canonical tables. A SQL column
  existing is not permission to map an unresolved source field into it.
- **It enables no publication.** No canonical relation carries a publication, visibility, permission,
  or redaction-override column, and `property_tax_api` is granted nothing in the canonical schema —
  not even schema usage.
- **It edits no existing migration file.** The one alteration to a pre-existing relation is a single
  `UNIQUE` added by a new migration, which creates an index, adds no column or check, and cannot fail
  against existing rows because the leading column is already that relation's primary key.
- It does not check bootstrap task 3.4.

## Constraints

- Forward-only. No down migration, no renumbering, no squash, no reinterpretation.
- One logical concern per migration file, each its own transaction, each ledger-recorded with its file
  SHA-256, each refusing reapplication and refusing missing prerequisites.
- Migrations run as `property_tax_migrator`. Needing superuser means the migration is doing something
  it should not.
- `lock_timeout` and `statement_timeout` in any migration that touches a populated relation, including
  one it only references.
- No PostGIS, no geospatial extension, no floating point, no JSONB for a canonical record field.
- The design must hold on a database already at `0005` with rows in it, without a backfill that
  canonicalizes old source-native values by guessing.
