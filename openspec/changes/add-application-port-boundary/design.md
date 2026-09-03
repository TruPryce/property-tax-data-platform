# Design: Application Port Boundary

## Context

The application package owns two ports. `ArtifactSink` takes acquired bytes one chunk at a time; `BronzeStore` records manifests and classifies a repeat checksum. Everything else task 2.3 names — canonical persistence, quality, publication, time, and the run that ties them together — exists only as database tables and adapter helpers.

That is why 3.5 is blocked in a specific way. It could implement COPY-to-staging against no contract at all and be internally consistent, and the mismatch would only surface when 2.4 tried to coordinate it.

## The shape of the boundary

```text
              ┌──────────────── property_tax_application ────────────────┐
              │                                                          │
  registry    │  SourceRegistry ─────────► CountySourceDefinition        │
  discovery   │  ReleaseDiscovery ───────► ReleaseCandidate              │
              │                                                          │
  bytes       │  ArtifactSink        (retained, unchanged)               │
  manifests   │  BronzeStore         (retained, unchanged)               │
              │                                                          │
  canonical   │  CanonicalReleaseRepository ──► ReleaseLoadSession       │
              │        write(batch)…  commit() ─► ReleaseLoadCompletion  │
              │                       abort()                            │
              │                                                          │
  quality     │  QualityRepository   (run-bound)                         │
  publication │  PublicationRepository ─────► PublicationSession         │
  time        │  Clock                                                   │
              └──────────────────────────────────────────────────────────┘
                                        ▲
                     implemented by property_tax_adapters (3.5, 3.6, later)
                     composed by property_tax_ingestion
```

Nothing in that column names PostgreSQL, S3, HTTP, Airflow, or a county.

## Why the run is the spine

Three tables reference `ingestion.run`: `canonical.release_load`, `quality.evaluation`, and `publication.publication`. The canonical retry key is `UNIQUE (release_key, run_id)`. So a boundary with no run concept cannot express retry, cannot attach a quality evaluation, and cannot record publication lineage — it would push all three into whatever the adapter happened to do.

`ProcessingRunRef` therefore crosses several ports. Its value is a persistence locator, and the contract says so out loud. The temptation it exists to resist is real: `run_id` is a monotonically increasing `bigint`, so it looks orderable and looks like identity, and it is neither. Two runs of one release are two loads, and which one a consumer should read is the published-product boundary's decision, not a comparison of surrogate keys.

## Why canonical persistence is a session

The two obvious API shapes are both wrong, and they are wrong in opposite directions.

`save(release, records)` requires the whole county release in memory. That contradicts the bounded-processing contract directly: a Dallas release is hundreds of thousands of rows against a 900 MiB per-task budget.

`save_batch(release, records)` called repeatedly, each committing, gives up release atomicity. A failure on batch nine leaves batches one through eight visible, and `canonical-silver-persistence` requires a rejected run to commit zero canonical records.

The lifecycle that satisfies both already exists twice in this repository. `ArtifactSink` uses `write`/`commit`/`abort` so a caller can distinguish written from durable and cannot forget cleanup. The adapters' `ReleaseStage` uses `write`/`finalize`/`abort`/`commit` for a caller-supplied atomic destination. `ReleaseLoadSession` follows the same idiom over canonical records:

```text
open(release, run, outcome)      one logical release load
    ├── write(batch)             bounded, many times, nothing visible
    ├── write(batch)
    └── commit() ─► completion   outcome and load become durable together
        or abort()               zero canonical records
```

A third idiom for this problem would itself be the defect.

`ReleaseStage` is not reused directly, and the reason is vocabulary rather than convenience: it carries `AppraisalSourceRecord`, the vendor-neutral *source* record at physical-row grain, and lives in adapters as part of the bounded-processing boundary. `ReleaseLoadSession` carries promoted canonical records — account snapshots, owner associations, value observations. Parse produces the first; normalise produces the second. Same shape, different stage, different layer.

## The transaction seam

`canonical.release_load` carries this trigger:

```sql
CREATE CONSTRAINT TRIGGER release_load_rests_on_an_accepted_run
    AFTER INSERT OR UPDATE ON canonical.release_load
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION canonical.assert_load_rests_on_an_accepted_run();
```

The check runs at COMMIT and asks whether the run has an `accepted` `ingestion.release_outcome`. Deferral is what allows the outcome and the load to be written in either order inside one transaction — and it is also what makes two independent transactions fail.

So the decomposition that looks natural is unavailable:

```text
  rejected:  DiagnosticsStore.record_outcome(run, outcome)   ← its own commit
             CanonicalRepository.commit(load)                ← its own commit, gate fails
```

The session owns both instead. The outcome is supplied when the session is opened, and `commit()` is the one place either becomes durable. An implementation is then free to write them in whatever order suits it, inside one transaction, and the gate is satisfied structurally.

This is the single most consequential decision in the change, because it is invisible in any individual method signature and only shows up as a runtime failure at the first real load.

## Bronze grain and canonical identity

```text
  bronze.release_partition   (jurisdiction_code, tax_year, release_kind)          3 components
  ingestion.run              those three + release_identifier                     4 components
  canonical.release          jurisdiction, tax_year, release_kind, identifier     4 components
```

The fourth component enters at the run and nowhere earlier. A Bronze acquisition can legitimately know only that an archive holds "Collin, 2025, certified" — the release identifier is established by page evidence or verified content, and sometimes not at all.

The canonical port takes `ReleaseIdentity`. It does not take `ReleasePartition` and does not accept a partition plus a hint. Where the source has not established an identifier, opening a load fails with a named error, because the alternative is worse than failing: a synthesised identifier from a filename or checksum would be accepted by every constraint in the database and would silently define a release that does not exist.

## Retry, and the shape of the answer

```text
  same release, same run   ─► ReleaseLoadCompletion(already_complete=True)   nothing written
  same release, other run  ─► ReleaseLoadCompletion(already_complete=False)  second load retained
```

Returning a result rather than raising is deliberate. A retry is an ordinary orchestration event — Airflow will re-run a task after a transient failure, and the accepted contract requires it to "resume from the last verified stage without duplicating canonical records". An exception would force every caller to catch a specific type and decide it was benign, and a caller that got that wrong would turn a successful retry into a failed DAG run.

## The outcome cannot be the adapters' outcome

The session accepts the run's processing outcome, and the obvious candidate is `ReleaseOutcome` from `property_tax_adapters.release.outcome` — it already carries the disposition, the four counts, and the truncation flags, and `ingestion.release_outcome` mirrors it column for column.

The application may not import it. `FORBIDDEN_IMPORTS` in the dependency-direction test lists `property_tax_adapters` under `property_tax_application`, and the direction is real rather than nominal: five county modules already import `CountySourceDefinition` from the application, so the arrow points inward and reversing it anywhere would make the graph cyclic.

So the application defines its own outcome value carrying the facts the database gate and the accepted contract need — disposition, the counts, the bounded diagnostics and notices with their truncation flags — and the adapter maps `ReleaseOutcome` onto it at the boundary it already crosses.

This is a mapping, not a second model. The alternative, moving `ReleaseOutcome` inward, would edit the public surface of a promoted capability (`bounded-release-processing`) to serve a consumer that does not exist yet, and would drag `ReleaseDiagnostic` and `ReleaseNotice` with it.

## Quality and publication are different units of work

Quality evaluates loaded canonical data — required-key completeness, uniqueness, child relationships, row-count drift — so it necessarily runs after the load has committed. A blocking failure prevents *publication* and quarantines the release; it does not retract the load, and `validated-data-publication` says exactly that.

Publication is atomic on its own terms: build, then activate or fail. `publication.publication` carries the state machine (`building`, `current`, `superseded`, `failed`) and the supersession pointer. `PublicationSession.fail()` leaves the previously current publication current, which is the accepted requirement that consumers keep reading the last good build.

So there are three transactions in the pipeline, not one, and the boundary makes the seams explicit:

```text
  [ run + outcome + canonical load ]   one transaction, deferred gate
  [ quality evaluations ]              run-bound, after the load
  [ publication build → activate ]     atomic, over completed loads
```

## Alternatives rejected

- **One `Repository` per database schema.** Mirrors the tables, which is precisely the problem: `canonical.*`, `ingestion.*`, `quality.*`, and `publication.*` would become application vocabulary, and 3.5's freedom to choose staging mechanics would evaporate.
- **Reusing `ReleaseStage` for canonical records.** Right shape, wrong vocabulary and wrong layer. It would drag the canonical model into the adapters' bounded-processing boundary and blur parse output with normalise output.
- **A `UnitOfWork` spanning all seven responsibilities.** Ties publication and quality to the load's transaction, which the accepted contracts explicitly separate, and forces an implementation to hold one connection across work that legitimately fails independently.
- **Raising `AlreadyLoaded` on retry.** Rejected in D4: makes the ordinary path an exception.
- **Taking `ReleasePartition` on the canonical port with an optional identifier.** Makes the missing fourth component look like a nullable field rather than a refusal, and the first adapter under schedule pressure fills it in.
- **A generic object-store CRUD port.** `ArtifactSink` and `BronzeStore` already express what is needed with tighter guarantees; a general `put`/`get` would be a weaker contract replacing a stronger one.
- **Letting use cases call `datetime.now`.** Makes every use case untestable at the one point where determinism matters most, which is why the clock is a port at all.

## Risks

- **The session can be implemented as a lie.** Nothing in a Protocol forces an implementation to honour atomicity; a `commit()` that writes eagerly conforms structurally. The same is true of `ReleaseStage` today, and the answer is the same: 3.6's containerised integration tests are where atomicity is actually proven. This change states the obligation and the falsification tests assert the contract's shape, not the storage behaviour.
- **`ProcessingRunRef` invites misuse.** It is an opaque locator that will be a `bigint` in practice, and someone will eventually sort by it. The contract names it, a test asserts it carries no ordering guarantee, and that is the extent of what a type can do here.
- **The port count could still be wrong.** Eight contracts for seven named responsibilities is a judgement, defended in the proposal by the two accepted requirements behind "source discovery". If 2.4 finds the registry/discovery split artificial in practice, merging them is a smaller change than splitting a merged one.
- **`Clock` may sit unused until 2.4.** Defining a port with no consumer risks it drifting from what the use cases actually need. Mitigated by keeping it minimal — one method — so there is little to drift.

## Migration

None. No existing signature changes, no data moves, no migration is added. `ArtifactSink` and `BronzeStore` keep their contracts, and every new port is additive.

## Handoffs

**To bootstrap 3.5.** PostgreSQL implements `CanonicalReleaseRepository` and `ReleaseLoadSession` using COPY-to-staging and set-based operations, choosing its own staging tables, batch sizing, and merge SQL. None of that appears in the application contract, and 3.5 may not add it there.

**To bootstrap 2.4.** The discover, acquire, parse, normalize, validate, and publish use cases coordinate `SourceRegistry`, `ReleaseDiscovery`, `ArtifactSink`, `BronzeStore`, `CanonicalReleaseRepository`, `QualityRepository`, `PublicationRepository`, and `Clock` — never an adapter type. 2.4 also owns retiring the S3 adapter's `utc_now()` in favour of the injected clock.

## Unresolved questions

- Whether `ReleaseDiscovery` should return candidates for one jurisdiction or accept a cohort, which depends on how 2.4 shapes the six-county scheduled workflow.
- Whether `QualityRepository` should expose a computed verdict for a run or leave the blocking/warning decision to the use case. The plan leaves it to the use case, since the thresholds are configuration and the decision is orchestration.
- Whether publication products beyond the accepted three ever need a distinct session shape. Out of scope until a fourth product exists.
