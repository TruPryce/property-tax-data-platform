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
| Processing run (shared) | `ingestion.run` in the database; `ReleaseOutcome` in adapters | **(3) new** — no application representation |

Seven responsibilities resolve to **eight contracts**: two retained, six added. The count differs from seven for one reason, stated rather than glossed: `source-release-ingestion` carries *two* accepted requirements here — "Official source registry" and "Release discovery" — and they are not the same responsibility. The registry resolves a county and release kind with no network access, because the accepted scenario requires an unsupported source to "fail before network acquisition". Discovery probes remote metadata. Collapsing them would make the pre-network failure inexpressible.

`ArtifactSink` and `BronzeStore` are not touched. No new object-store CRUD port is introduced; the existing bounded contracts already express the behaviour.

## Three facts from the code that shape the design

**A Bronze partition is not a canonical release.** `ReleasePartition` carries `jurisdiction_code`, `tax_year`, `release_kind` — three components. `ReleaseIdentity` carries those plus `release_identifier` — four. The fourth first appears at `ingestion.run`, which references the three-component `bronze.release_partition` and supplies `release_identifier` itself. So promotion from Bronze grain to canonical identity happens exactly once, at the run, and the canonical port must refuse a release whose identifier the source has not established rather than synthesise one.

**The accepted-outcome gate is a transaction seam.** `canonical.release_load` carries a constraint trigger that is `DEFERRABLE INITIALLY DEFERRED` and requires the run's `ingestion.release_outcome` to be `accepted`. Two application ports that each own their own commit cannot satisfy it. One unit of work must span the outcome and the load.

**The run is the spine.** `canonical.release_load`, `quality.evaluation`, and `publication.publication` all reference `ingestion.run`. The retry key is `UNIQUE (release_key, run_id)`. An application boundary with no run concept cannot express retry, quality, or publication lineage.

## Decisions

- **D1 — The run is an application concept, and its persistence key is not.** `ProcessingRunRef` names a run across ports. `ingestion.run.run_id` is `GENERATED ALWAYS AS IDENTITY`, so the reference is documented and typed as an **opaque locator**: it is comparable and passable, and it is not canonical identity, not ordering, and not a business fact. Ports that accept one say so in their contract.
- **D2 — Canonical persistence is a session, not a `save()`.** `CanonicalReleaseRepository.open(...)` returns a `ReleaseLoadSession` with `write(batch)` called many times, then exactly one `commit()` or `abort()`. This is not a new invention: `ArtifactSink` and the adapters' `ReleaseStage` already use enter/write/commit/abort for the same reason, and a third idiom for the same problem would be the defect.
- **D3 — That session owns the outcome.** The session accepts the processing outcome and its bounded diagnostics and notices, and `commit()` is the single point at which the outcome and the canonical load become durable together. This is what makes the deferred database gate satisfiable by construction rather than by an implementer's care.
- **D4 — Retry is a returned result, not an exception.** `commit()` returns a `ReleaseLoadCompletion` carrying the run reference and `already_complete: bool`. Re-running a completed release/run pairing returns `already_complete=True`, writes nothing further, and raises nothing the caller must interpret. A second, distinct run for the same release is a different pairing and therefore a new load, never a retry of the first.
- **D5 — The canonical port speaks canonical vocabulary only.** It accepts the promoted domain record types. It exposes no schema or table name, no `psycopg` type, no cursor, connection, transaction, `COPY`, staging table, `ON CONFLICT`, or surrogate key as a business identifier. 3.5 owns every one of those.
- **D6 — No idempotency key over observed values.** The port defines no natural key and no deduplication rule. Divergent evidence at one grain, several children of a one-to-many type, and several geometries all pass through unchanged, because the canonical model and the database deliberately admit them.
- **D7 — Quality is one run-bound port, not a second quality model.** `QualityRepository` reads the configured rules and records measured evaluations against a run. It reuses `quality.rule` and `quality.evaluation`; it defines no parallel persistence and no county threshold.
- **D8 — Publication is a separate unit of work with its own atomicity.** `PublicationRepository.open(...)` returns a `PublicationSession` that builds, then either `activate()` — which makes the new publication current and supersedes the previous one — or `fail()`. A failed build leaves the previously current publication current, which is the accepted rule. Publication is not in the load's transaction: it runs over completed loads, after quality.
- **D9 — Publication grants no read access.** The port carries publication *decisions* and lineage. It confers no raw canonical read privilege and no sensitive-field permission; the reviewed field policy continues to govern that separately, exactly as `canonical-silver-persistence` requires.
- **D10 — The processing outcome crossing the port is application-owned.** The adapters' `ReleaseOutcome` cannot be used: the dependency-direction test forbids the application from importing adapters, and five county modules already import from the application, so the arrow points inward. The application defines the outcome value the session accepts, and the adapter maps onto it. That is a mapping at a boundary the adapter already crosses, not a second model.
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
