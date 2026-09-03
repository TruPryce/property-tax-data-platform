# Design: Application Port Boundary

## Context

The application package owns two ports. `ArtifactSink` takes acquired bytes one chunk at a time; `BronzeStore` records manifests and classifies a repeat checksum. Everything else task 2.3 names — canonical persistence, quality, publication, time, and the run that ties them together — exists only as database tables and adapter helpers.

That is why 3.5 is blocked in a specific way. It could implement COPY-to-staging against no contract at all and be internally consistent, and the mismatch would only surface when 2.4 tried to coordinate it.

## The order of the seams

One sequence, and every port sits at a named point in it:

```text
  discovery evidence ──promote──► complete ReleaseIdentity
                                          │
  acquisition ──► BronzeStore ──► ManifestIndex ──► ManifestRef
                                          │
                          ProcessingRunRepository.start(identity, manifest_ref)
                                          │
                                          ▼
                                  ProcessingRunRef
                                          │
                          canonical load ─┼─ quality evaluations
                                          └─ publication attempt
```

Promotion happens once, before the run, and the run is where the promoted identity and the indexed acquisition are bound together.

## The shape of the boundary

```text
              ┌──────────────── property_tax_application ────────────────┐
              │                                                          │
  registry    │  SourceRegistry ─────────► CountySourceDefinition        │
  discovery   │  ReleaseDiscovery ───────► ReleaseCandidate | Unchanged  │
  promotion   │      promote(candidate) ─► ReleaseIdentity               │
              │              or IncompleteReleaseIdentity                │
              │                                                          │
  bytes       │  ArtifactSink        (retained, unchanged)               │
  manifests   │  BronzeStore         (retained, unchanged)               │
              │  ManifestIndex ──────────► ManifestRef                   │
              │                                                          │
  run         │  ProcessingRunRepository.start(…) ─► ProcessingRunRef    │
              │                                                          │
  canonical   │  CanonicalReleaseRepository ──► ReleaseLoadSession       │
              │        write(CanonicalRecordBatch)…                      │
              │        commit() ─► ReleaseLoadCompletion   abort()       │
              │                                                          │
  quality     │  QualityRepository   (run-bound)                         │
  publication │  PublicationRepository ─────► PublicationAttempt         │
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

## From an acquisition to a run

`BronzeStore.record()` returns a storage locator — in the S3 adapter, `s3://<bucket>/<sha>.manifest.json`. `ingestion.run.manifest_id` needs something else entirely: a `bigint` that `bronze.release_manifest` generates, on a table that holds no column containing that URI and carries no unique constraint on the artifact checksum either. There is no path from one to the other, and nothing in the first draft produced the value `start()` was specified to take.

Left alone, 3.5 would have had to choose — parse the S3 locator, insert a second manifest row, query by evidence that is not unique, or reach across adapters — and whichever it chose would have become the contract by default. That is the outcome 2.3 exists to prevent.

So manifest persistence produces the reference:

```text
  ArtifactSink ──► bytes durable
  BronzeStore  ──► immutable evidence in the object store, returns a storage locator
  ManifestIndex ─► the relational record a run binds to, returns a ManifestRef
  ProcessingRunRepository.start(release, manifest_ref) ──► ProcessingRunRef
```

`ManifestIndex` is a second manifest port and needs its reason. `BronzeStore` writes immutable acquisition evidence to the object store and classifies a repeat checksum against it; the relational row is an index over that acquisition, holding a subset — jurisdiction, acquisition instant, source URL, artifact checksum — so that runs and partitions can reference it. Two stores, two guarantees, two lifetimes. `BronzeStore` also cannot simply gain a method: adding one to the Protocol would stop `S3BronzeStore` from satisfying it, and round one settled that its behaviour is retained.

Registration is idempotent per acquisition, which is what makes one artifact carrying two logical releases bind both runs to one manifest rather than to two copies of it.

## Who creates a run

The run is the spine, so every port names one — and until this correction nothing created one. That gap could not be pushed to 2.4: `ingestion.run.run_id` is `GENERATED ALWAYS AS IDENTITY`, so a use case cannot construct a correct reference without reaching past the boundary into the database, which is exactly what the boundary exists to prevent.

`ProcessingRunRepository.start(release, manifest_ref)` returns the reference, and nothing else in the boundary accepts a caller-constructed one. The run is also where the three-component Bronze partition and a release identifier become one four-component canonical release, because `ingestion.run` references `bronze.release_partition` on three columns and carries `release_identifier` itself.

## Where an incomplete release fails

The first draft put a `MissingReleaseIdentifier` on the canonical repository. That error was unreachable: `ReleaseIdentity.__post_init__` calls `require_identifier`, so an incomplete `ReleaseIdentity` cannot be constructed, and a method taking one can never receive the state it claimed to reject.

The failure belongs one step earlier, at the only place a partial release becomes a whole one:

```text
  ReleaseCandidate                      promote()            ReleaseIdentity
    jurisdiction                            │                  jurisdiction
    tax_year                 ──────────────►│                  tax_year
    release_kind                            │                  release_kind
    release_identifier?  ← may be absent    │                  release_identifier
                                            ▼
                              IncompleteReleaseIdentity
```

Downstream of promotion no port carries a "maybe complete" identity, and `ReleaseIdentity` is not weakened to make the error expressible. The alternative — a nullable fourth component threaded through the canonical port — is precisely how a filename ends up as a release identifier under schedule pressure.

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

The canonical port takes `ReleaseIdentity`. It does not take `ReleasePartition` and does not accept a partition plus a hint. Where the source has not established an identifier, **promotion** fails with a named error — see the promotion seam below — and the load is never reached. The alternative is worse than failing: a synthesised identifier from a filename or checksum would be accepted by every constraint in the database and would silently define a release that does not exist.

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

## How a child finds its parent

The canonical record types reference their parents **by object**: `OwnerAssociation.owner` is an `OwnerObservation`, `OwnerValueAllocation.association` is an `OwnerAssociation`, `TaxableValueObservation.taxing_unit` is a `TaxingUnitObservation`. The database gives none of those a natural key; it generates `owner_key`, `association_key`, and the rest as identity columns. So when a child is written after its parent, an implementation needs the parent's generated key, and every obvious way of finding it is closed:

```text
  key by observed values      forbidden — that is the natural key this boundary rejects
  structural equality         wrong — two equal-looking observations are legitimately distinct
  release-wide object→key map grows with the release, undoing the boundedness
  re-insert the parent        manufactures a second observation
```

The first draft answered this by requiring a batch to carry whole account groups — one snapshot with its complete descent — so parent resolution never crossed a batch. That solved correlation and quietly gave up the bound it was meant to protect. The canonical model places **no maximum** on how many owners, allocations, values, exemptions, land records, improvements, or geometries an account may carry, so a tuple of complete account groups is bounded only by the largest account in the release. One pathological account is enough to break it, and the honest fix is not to invent a maximum child count that no accepted contract establishes.

That draft also rested on a claim that is simply false: *every canonical relation carries `snapshot_key`*. `canonical.owner_value_allocation` deliberately does not, and the migration says so — "Parented by the association, not by the snapshot: there is deliberately no `snapshot_key` here, because the domain gives this record one parent and it is the association." An allocation reaches its snapshot through its association, so the graph is not the flat star the claim implied.

So correlation is explicit, and it rides on the batch rather than on the records. The canonical types hold their parents directly and gain no correlation field — they are domain types this change does not modify — so a batch entry pairs a record with the handle it may be named by and the handle naming its parent:

```text
  CorrelatedRecord(record=owner,       handle=h1,   parent=h0)
  CorrelatedRecord(record=association, handle=h2,   parent=h1)
  CorrelatedRecord(record=allocation,  handle=None, parent=h2)   ← a leaf needs no handle
```

A parent is named the same way whether it sits in this batch or an earlier one, so there is one linkage mechanism and not two, and the caller mints handles that need only be unique within an open account. The batch also names the one account, if any, left open at its end:

```text
  write(batch)  ─┐  many accounts, each complete within the batch
                 │  …except at most one, named as continuing
  write(batch)  ─┘  that one account's handles stay resolvable; the rest are released
```

"Bounded by open accounts" would be no bound at all if arbitrarily many could stay open, so a batch may leave **at most one** account continuing past its end. Ordinary accounts therefore complete inside one batch and need no cross-batch correlation at all; only a pathological account spans batches, and only one may be in flight. Beyond a single bounded batch an implementation retains handles for that one account, and only for records actually named as parents — owners, associations, taxing units — while allocations, values, exemptions, land, improvements, and geometries stream as leaves. Correlation grows with neither the release nor the number of accounts in it.

`CorrelationHandle` is deliberately neither of the two identities already in play. It is not domain identity, because the canonical model gives these observations none. It is not persistence identity, because it is discarded when the account closes and never appears in a stored row. Naming it explicitly is what keeps it from drifting into either role, which is the same reason `ProcessingRunRef` says out loud that it is an opaque locator.

## Quality and publication are different units of work

Quality evaluates loaded canonical data — required-key completeness, uniqueness, child relationships, row-count drift — so it necessarily runs after the load has committed. A blocking failure prevents *publication* and quarantines the release; it does not retract the load, and `validated-data-publication` says exactly that.

Publication is atomic on its own terms: attempt, then activate or fail. `publication.publication` carries the state machine (`building`, `current`, `superseded`, `failed`) and the supersession pointer, and `PublicationAttempt.fail()` leaves the previously current publication current, which is the accepted requirement that consumers keep reading the last good build.

The boundary stops there deliberately. Migration `0005` says task 6.2 owns the promotion path, and this port has no operation that stages or writes published content — so scoping it to attempt, lineage, and activation describes what it can actually do. A requirement promising an atomic Gold build would be a promise no task in this change makes representable.

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
- **Batches closed over whole account groups.** This was the first draft's answer, and it is rejected now: it resolves every parent inside one batch, but the canonical model sets no maximum on an account's children, so the batch is bounded only by the largest account in the release. Bounding it would mean inventing a maximum child count no accepted contract establishes. `CorrelationHandle` manages the problem instead of hiding it, and pays for that with one more opaque value — a cost `ProcessingRunRef` and `PublicationRef` already establish the shape of.
- **A nullable release identifier on the canonical port.** Makes the missing fourth component look like an optional field rather than a refusal, which is how a filename becomes a release identifier.
- **Deferring run creation to 2.4.** The reference is database-generated; a use case cannot construct a correct one without reaching through the boundary, so deferring it would have made the first implementation invent the contract.

## Risks

- **The session can be implemented as a lie.** Nothing in a Protocol forces an implementation to honour atomicity; a `commit()` that writes eagerly conforms structurally. The same is true of `ReleaseStage` today, and the answer is the same: 3.6's containerised integration tests are where atomicity is actually proven. This change states the obligation and the falsification tests assert the contract's shape, not the storage behaviour.
- **`ProcessingRunRef` invites misuse.** It is an opaque locator that will be a `bigint` in practice, and someone will eventually sort by it. The contract names it, a test asserts it carries no ordering guarantee, and that is the extent of what a type can do here.
- **The port count could still be wrong.** Eleven contracts for seven named responsibilities is a judgement, defended in the proposal by the two accepted requirements behind "source discovery". If 2.4 finds the registry/discovery split artificial in practice, merging them is a smaller change than splitting a merged one.
- **`Clock` may sit unused until 2.4.** Defining a port with no consumer risks it drifting from what the use cases actually need. Mitigated by keeping it minimal — one method — so there is little to drift.

## Migration

None. No existing signature changes, no data moves, no migration is added. `ArtifactSink` and `BronzeStore` keep their contracts, and every new port is additive.

## Handoffs

**To bootstrap 3.5.** PostgreSQL implements `CanonicalReleaseRepository` and `ReleaseLoadSession` using COPY-to-staging and set-based operations, choosing its own staging tables, batch sizing, and merge SQL. It also implements `ManifestIndex` and `ProcessingRunRepository`, which are prerequisites rather than companions: a canonical load cannot open without a run, and a run cannot start without a manifest reference, so `bronze.release_manifest` and `ingestion.run` are 3.5's to write before the first batch lands. Resolving a `CorrelationHandle` to a generated key is 3.5's mechanism to choose, subject to the bound the session states. None of that appears in the application contract, and 3.5 may not add it there.

**To bootstrap 2.4.** The discover, acquire, parse, normalize, validate, and publish use cases coordinate `SourceRegistry`, `ReleaseDiscovery`, `ArtifactSink`, `BronzeStore`, `ManifestIndex`, `ProcessingRunRepository`, `CanonicalReleaseRepository`, `QualityRepository`, `PublicationRepository`, and `Clock` — never an adapter type. 2.4 owns minting correlation handles as it walks parsed records, since it is the only layer holding both a record and its parent. It also owns retiring the S3 adapter's `utc_now()` in favour of the injected clock.

## Unresolved questions

- Whether `ReleaseDiscovery` should return candidates for one jurisdiction or accept a cohort, which depends on how 2.4 shapes the six-county scheduled workflow.
- Whether `QualityRepository` should expose a computed verdict for a run or leave the blocking/warning decision to the use case. The plan leaves it to the use case, since the thresholds are configuration and the decision is orchestration.
- Whether publication products beyond the accepted three ever need a distinct session shape. Out of scope until a fourth product exists.
