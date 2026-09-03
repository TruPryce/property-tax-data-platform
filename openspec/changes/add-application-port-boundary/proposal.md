## Why

Bootstrap 3.4 is complete: PR #116 implemented canonical PostgreSQL persistence and PR #118 promoted `canonical-silver-persistence`. The next PostgreSQL task, 3.5, implements bounded batch parsing with COPY-to-staging and set-based merges.

3.5 must implement an application contract rather than invent one while designing staging tables and merge SQL. That contract does not exist. The application package owns exactly two ports today — `ArtifactSink` and `BronzeStore` — and nothing at all for canonical persistence, quality, publication, or time.

Task 2.4 has the same problem from the other side: the discover/acquire/parse/normalize/validate/publish use cases need stable ports to coordinate, not infrastructure implementations to call.

## Outcome

Establish the application-owned port boundary for bootstrap task 2.3, adding only what the inventory shows is genuinely missing and retaining what already works.

## Scope

- Originating issue: #119
- Affected capabilities: application-port-boundary (ADDED)
- Affected decisions: none. Hexagonal ownership is settled in the root `AGENTS.md`; this change works inside it.

## Inventory and disposition

Every task-2.3 responsibility, classified against what the repository contains today. This table is the reason the change is the size it is.

| Responsibility | Present today | Disposition |
| --- | --- | --- |
| Official source registry | `CountySourceDefinition`, `AcquisitionMethod` (application); `source_for_county` (adapters, a module function) | **(2) extend** — the vocabulary is right, the lookup is not injectable and does not key on release kind |
| Release discovery | nothing | **(3) new** |
| Artifact storage | `ArtifactSink` — `__enter__`/`write`/`commit`/`abort`/`__exit__` | **(1) retained unchanged** |
| Manifest | `BronzeStore` — `classify`/`record`/`reference_partition` | **(1) retained unchanged** |
| Canonical repository | nothing | **(3) new** |
| Quality | nothing in the application; the run-bound database model exists | **(3) new** |
| Publication | nothing in the application; the run-bound database model exists | **(3) new** |
| Clock | `utc_now()`, a module function in the S3 adapter, not injectable | **(3) new** |
| Processing run (shared) | `ingestion.run` in the database; `ReleaseOutcome` in adapters | **(3) new** — no application representation, and no producer for its reference |
| Release identity promotion | `ReleaseIdentity` requires four components and cannot hold fewer | **(3) new** — nothing turns partial evidence into a complete identity |
| Logical release evidence | Discovery may legitimately establish no tax year or release kind; the accepted contract has parsing create the partitions | **(3) new** — no carrier for facts established after acquisition |
| Manifest reference | `BronzeStore.record()` returns a storage locator; the run needs the relational record's generated identity | **(3) new** — no path from one to the other |

Seven responsibilities resolve to **eleven contracts**: two retained, nine added. The count differs from seven for one reason, stated rather than glossed: `source-release-ingestion` carries *two* accepted requirements here — "Official source registry" and "Release discovery" — and they are not the same responsibility. The registry resolves a county and release kind with no network access, because the accepted scenario requires an unsupported source to "fail before network acquisition". Discovery probes remote metadata. Collapsing them would make the pre-network failure inexpressible.

`ArtifactSink` and `BronzeStore` are not touched. No new object-store CRUD port is introduced; the existing bounded contracts already express the behaviour.

## Three facts from the code that shape the design

**A Bronze partition is not a canonical release.** `ReleasePartition` carries `jurisdiction_code`, `tax_year`, `release_kind` — three components. `ReleaseIdentity` carries those plus `release_identifier` — four. The fourth first appears at `ingestion.run`, which references the three-component `bronze.release_partition` and supplies `release_identifier` itself. So the fourth component is established from the source's own evidence, and promoting a candidate to a complete `ReleaseIdentity` is the one place that happens; the run then binds that promoted identity to the indexed acquisition. The canonical port refuses a release whose identifier the source has not established rather than synthesise one.

**The accepted-outcome gate is a transaction seam.** `canonical.release_load` carries a constraint trigger that is `DEFERRABLE INITIALLY DEFERRED` and requires the run's `ingestion.release_outcome` to be `accepted`. Two application ports that each own their own commit cannot satisfy it. One unit of work must span the outcome and the load.

**The run is the spine.** `canonical.release_load`, `quality.evaluation`, and `publication.publication` all reference `ingestion.run`. The retry key is `UNIQUE (release_key, run_id)`. An application boundary with no run concept cannot express retry, quality, or publication lineage.

## Decisions

- **D1 — The run is an application concept, and its persistence key is not.** `ProcessingRunRef` names a run across ports. `ingestion.run.run_id` is `GENERATED ALWAYS AS IDENTITY`, so the reference is documented and typed as an **opaque locator**: it is comparable and passable, and it is not canonical identity, not ordering, and not a business fact. Ports that accept one say so in their contract.
- **D2 — Canonical persistence is a session, not a `save()`.** `CanonicalReleaseRepository.open(...)` returns a `ReleaseLoadSession` with `write(batch)` called many times, then exactly one `commit()` or `abort()`. This is not a new invention: `ArtifactSink` and the adapters' `ReleaseStage` already use enter/write/commit/abort for the same reason, and a third idiom for the same problem would be the defect.
- **D2a — Parent linkage uses account-scoped correlation, and an account may span batches.** A record whose parent was written earlier names it by a session-local handle that is neither domain nor persistence identity and stops being valid when its account completes. An earlier draft instead required a batch to carry an account's whole descent; that solved correlation and gave up the bound, because the canonical model sets no maximum on an account's children, so one pathological account would be enough. Correlation rides on the batch rather than on the canonical records, which hold their parents directly and gain no correlation field: an entry pairs a record with the handle it may be named by and the handle naming its parent. A batch may leave at most one account continuing past its end, so ordinary accounts complete within a batch and correlation grows with neither the release nor the number of accounts in it.
- **D2d — Discovery yields a source candidate, not a release.** The accepted ingestion contract permits an artifact whose tax years and release kinds are not known from discovery metadata, and requires that "discovery records one source candidate and parsing creates separately identified logical release partitions backed by the same immutable artifact". Collin is that case: one mutable Access export whose current and certified releases are established by `curr_val_yr`, `cert_val_yr`, and `property_status`. So `SourceCandidate` carries a possibly-empty tuple of `LogicalReleaseEvidence`, and promotion consumes the evidence rather than the candidate — one seam whether a page or parsing established the facts.
- **D2b — Manifest persistence produces the reference the run binds to.** `BronzeStore.record()` returns a storage locator — `s3://<bucket>/<sha>.manifest.json` in the S3 adapter — while `ingestion.run.manifest_id` needs the relational record's generated identity, which that URI does not contain and the checksum cannot resolve, since the table carries no unique constraint on it. `ManifestIndex` returns a `ManifestRef`, idempotently per acquisition so one artifact carrying two releases binds both runs to one manifest. It is a second manifest port because the object store holds immutable evidence and the relational row is an index over it, and because adding a method to `BronzeStore` would stop its existing implementer from satisfying it.
- **D2c — The run has a producer.** `ProcessingRunRepository` starts a run and returns its reference. Without it the boundary names a run everywhere and creates one nowhere, and a use case would have to reach past the port into the database to obtain a value the database generates.
- **D3 — That session owns the outcome.** The session accepts the processing outcome and its bounded diagnostics and notices, and `commit()` is the single point at which the outcome and the canonical load become durable together. This is what makes the deferred database gate satisfiable by construction rather than by an implementer's care.
- **D3a — Identity promotion is one named seam, and it is not the repository's.** `ReleaseIdentity` already requires four components, so an incomplete one cannot exist and a repository that claimed to reject one could never receive it. Promotion from a discovered candidate is where the missing-identifier failure lives; the canonical port accepts a complete identity and has no such branch. `ReleaseIdentity` is not weakened to make the error reachable.
- **D4 — Retry is a returned result, not an exception.** `commit()` returns a `ReleaseLoadCompletion` carrying the run reference and `already_complete: bool`. Re-running a completed release/run pairing returns `already_complete=True`, writes nothing further, and raises nothing the caller must interpret. A second, distinct run for the same release is a different pairing and therefore a new load, never a retry of the first.
- **D5 — The canonical port speaks canonical vocabulary only.** It accepts the promoted domain record types. It exposes no schema or table name, no `psycopg` type, no cursor, connection, transaction, `COPY`, staging table, `ON CONFLICT`, or surrogate key as a business identifier. 3.5 owns every one of those.
- **D6 — No idempotency key over observed values.** The port defines no natural key and no deduplication rule. Divergent evidence at one grain, several children of a one-to-many type, and several geometries all pass through unchanged, because the canonical model and the database deliberately admit them.
- **D7 — Quality is one run-bound port, not a second quality model.** `QualityRepository` reads the configured rules and records measured evaluations against a run. It reuses `quality.rule` and `quality.evaluation`; it defines no parallel persistence and no county threshold.
- **D8 — Publication owns the attempt, not the build.** `PublicationRepository` opens a `PublicationAttempt` that either `activate()`s — making it current and recording what it supersedes — or `fail()`s, leaving the previously current publication current. It is scoped to attempt, lineage, and activation, because migration `0005` states that task 6.2 owns the promotion path: a boundary claiming the Gold-build transaction would promise behaviour no task here makes representable. Publication is not in the load's transaction; it runs over completed loads, after quality.
- **D9 — Publication grants no read access.** The port carries publication *decisions* and lineage. It confers no raw canonical read privilege and no sensitive-field permission; the reviewed field policy continues to govern that separately, exactly as `canonical-silver-persistence` requires.
- **D10 — The processing outcome crossing the port is application-owned, and the mapping is total.** The adapters' `ReleaseOutcome` cannot be used: the dependency-direction test forbids the application from importing adapters, and five county modules already import from the application, so the arrow points inward. The application defines the outcome value, and it carries every fact `ingestion.release_outcome` requires — including the boundary contract version and the paired parser version and layout fingerprint — so an implementation can write that row from this value alone. A duplicate representation is acceptable here because the direction forbids reuse; a *lossy* one is not, because the missing facts would have to be fetched from outside the port.
- **D11 — One clock, timezone-aware.** `Clock.now()` returns an aware `datetime`. `acquired_at` is already injected and already required to be aware, so this generalises an established idiom rather than introducing one.

## Constraints

- `property_tax_application` gains no dependency on `boto3`, `psycopg`, Airflow, an object-store SDK, or any county module. The existing dependency-direction test is extended to prove it.
- `ArtifactSink` and `BronzeStore` keep their current signatures and semantics.
- No migration is added or modified. The database contract is read, not changed.
- No adapter is implemented. This change defines contracts and the values that cross them.
- No canonical record type is added or altered; 2.2's promoted model is used as-is.
- Bootstrap 2.4, 2.5, 3.5, and 3.6 are untouched, and 2.3 stays unchecked until a separate reconciliation verifies the implementation by substance.

## Non-goals

- COPY, staging tables, and set-based merges — bootstrap 3.5.
- The discover/acquire/parse/normalize/validate/publish use cases — bootstrap 2.4.
- S3, PostgreSQL, HTTP, clock, quality, and publication adapter implementations.
- County adapters and county source semantics.
- Gold tables, views, or API access.
- Airflow DAGs and worker CLI orchestration.

## Unresolved decisions

- **The S3 adapter's `utc_now()` stays where it is.** Defining `Clock` does not by itself retire it, and rewiring the acquisition path to an injected clock touches adapter code this change excludes. It is recorded here so the residue is visible rather than assumed gone; 2.4 owns the migration when it composes the use cases.
- **`SourceRegistry` keying on release kind is an extension, not a correction.** `source_for_county` resolves a county alone, while the accepted registry requirement speaks of "a registered county and release kind". The port carries release kind; whether any current county actually varies its definition by kind is a question for the county contracts, not for this boundary.
