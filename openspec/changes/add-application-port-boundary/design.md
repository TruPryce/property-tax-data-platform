# Design: Application Port Boundary

## Context

The application package owns two ports. `ArtifactSink` takes acquired bytes one chunk at a time; `BronzeStore` records manifests and classifies a repeat checksum. Everything else task 2.3 names — canonical persistence, quality, publication, time, and the run that ties them together — exists only as database tables and adapter helpers.

That is why 3.5 is blocked in a specific way. It could implement COPY-to-staging against no contract at all and be internally consistent, and the mismatch would only surface when 2.4 tried to coordinate it.

## The order of the seams

One sequence, and every port sits at a named point in it:

```text
  page evidence ─┐
                 ├─► LogicalReleaseEvidence ──promote──► ReleaseIdentity
  parsed content ┘
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
  discovery   │  ReleaseDiscovery ─────► SourceCandidate | Unchanged     │
  promotion   │      promote(evidence) ─► ReleaseIdentity                │
              │              or IncompleteReleaseIdentity                │
              │                                                          │
  bytes       │  ArtifactSink        (retained, unchanged)               │
  manifests   │  BronzeStore         (retained, unchanged)               │
              │  ManifestIndex ──────────► ManifestRef                   │
              │                                                          │
  run         │  ProcessingRunRepository.start(…) ─► ProcessingRunStart  │
              │                                                          │
  canonical   │  defined by add-canonical-load-session, cited here       │
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

## From an acquisition to a run

`BronzeStore.record()` returns a storage locator. In the S3 adapter that is, **before task 1.2**, the artifact-keyed `s3://<bucket>/<sha>.manifest.json`, and **after it** an acquisition-grain locator; in neither case is it a `ManifestRef`, which is the point of this section. `ingestion.run.manifest_id` needs something else entirely: a `bigint` that `bronze.release_manifest` generates, on a table that holds no column containing that URI and carries no unique constraint on the artifact checksum either. There is no path from one to the other, and nothing in the first draft produced the value `start()` was specified to take.

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

`ProcessingRunRepository.start(release, manifest_ref)` returns the reference, and nothing else in the boundary accepts a caller-constructed one.

Starting is also where concurrency has to be settled, because nothing below it settles concurrency. The accepted workflow requires that "overlapping active runs for the same county and release are prevented", and `ingestion.run` carries no constraint expressing it — its UNIQUE keys all include `run_id`, so each holds trivially for a single row. Two workers starting the same release would both get a run and both go on to create canonical loads. So `start` refuses by name, and refuses atomically, while a run is *held*; which mechanism provides that atomicity is 3.5's to choose. The rule is about overlap, not repetition: once the previous run has finished, the next one starts normally. The run is also where the three-component Bronze partition and a release identifier become one four-component canonical release, because `ingestion.run` references `bronze.release_partition` on three columns and carries `release_identifier` itself.

Refusing every *unfinished* run would settle concurrency and wedge recovery. A worker that dies after `start` commits and before `finish` leaves `finished_at` null forever — nothing else marks a run over — so every retry would meet the refusal, and the release would wait for someone to edit the run row by hand, which is the out-of-band repair the accepted retry scenario forbids. The rule is therefore about holding, not about `finished_at`:

```text
  run held by a live worker       ─► start refuses, by name, atomically
  run unfinished, holder gone     ─► start resumes it: same reference, resumed
  run finished                    ─► start creates a new run
```

Resuming rather than creating is what keeps the retry honest on both sides of the load. Before the load committed, the session that died left zero canonical records, and the resumed run simply loads. After it committed, the retried worker's `commit()` returns `already_complete=True` (D4), and quality and publication bind to the run that actually holds the load, instead of a second run loading the whole release again to reach them. What "held" means is the mechanism 3.5 chooses — a lock scoped to the worker's connection releases itself when the worker dies; a lease with a deadline needs renewing — and the contract fixes only the property, exactly as it does for atomicity.

## What the registry can be required to know

The same argument reaches one step further back. The accepted registry scenarios are phrased as an ingestion run *requesting* a county and release kind, and requiring every caller to supply a kind would make Collin unresolvable before it is unacquirable: something must produce a `CountySourceDefinition` before discovery can probe the source, and Collin's kinds are in `curr_val_yr` and `cert_val_yr`. Today's registry already agrees — it is `source_for_county(county)`, indexed by county alone.

So the kind is optional, and the accepted rules survive intact by splitting on what the caller actually knows:

```text
  unregistered jurisdiction              ─► fail before network
  caller supplied an unregistered kind   ─► fail before network   (the accepted scenario)
  kind learned only from content         ─► validate after parsing, before promotion
```

The third line is not a weakening. Rejecting a kind before network acquisition is physically impossible when the kind is inside the artifact, and the alternative — making the caller name `current` or `certified` just to discover Collin — is exactly the invention this boundary exists to refuse.

## What discovery can be required to know

A source candidate is not a release. The accepted ingestion contract permits an artifact whose tax years and release kinds are not known from discovery metadata, and says what happens then: "discovery records one source candidate and parsing creates separately identified logical release partitions backed by the same immutable artifact."

Collin is that case, and it is not hypothetical. The published source is one mutable Access export; its current and certified releases are established by `curr_val_yr`, `cert_val_yr`, and `property_status` — content fields, readable only after acquisition. A discovery contract requiring a tax year and a release kind would make Collin inexpressible, and the only ways to satisfy it would be the ones this boundary forbids: guess from a filename, or assume the current year.

So the two grains are separated, and the evidence is the thing promotion consumes:

```text
  SourceCandidate ──acquire──► artifact ──► acquisition manifest ──► ManifestRef M
        │                                        │
        │ page established the facts?            │
        ├── yes ──► LogicalReleaseEvidence       ├──────────────┐
        └── no  ──► parsing establishes them ────┘              │
                              │                                 │
                   ┌──────────┴──────────┐                      │
                   ▼                     ▼                      │
          evidence (current)     evidence (certified)           │
                   │                     │                      │
              ReleaseIdentity A    ReleaseIdentity B            │
                   │                     │                      │
                 run A(M) ◄──────────────┴──────────────────────┘
                 run B(M)        both runs bind the same manifest
```

The previous draft ordered this parse-first, because `ReleaseManifest` required a non-empty tuple of partitions. That ordering has a hole. An artifact can be acquired successfully — bytes durable, checksum final — and then fail archive or schema inspection before any tax year or release kind is established. Parse-first leaves those immutable bytes with no manifest at all: nothing records what was acquired, which is the one thing Bronze exists to guarantee, and the release is quarantined with no provenance to quarantine it *by*.

The database already models it the other way round. `bronze.release_manifest` carries its own `jurisdiction_code NOT NULL`, and migration `0001` adds `release_manifest_identity UNIQUE (manifest_id, jurisdiction_code)` for the sole purpose of letting `bronze.release_partition` reference it compositely:

```text
  bronze.release_manifest        the acquisition event, jurisdiction its own column
        │
        ├── release_partition A  (tax_year, release_kind)   attached when established
        └── release_partition B
```

The manifest owns the jurisdiction; a partition inherits it and adds only tax year and release kind. So the acquisition is manifested first, and partitions attach as they become known:

```text
  acquire bytes
    └─► record acquisition manifest      jurisdiction known, zero partitions
          └─► ManifestIndex ─► ManifestRef
                └─► establish LogicalReleaseEvidence   (page evidence, or parsing)
                      └─► derive ReleasePartition each  (three Bronze components)
                            └─► attach to the recorded acquisition
                                  └─► promote ─► ReleaseIdentity ─► start(run)
```

`BronzeStore` needs no redesign: `reference_partition` already exists precisely to attach a partition discovered after acquisition without touching the immutable manifest. What was missing is the relational half, so `ManifestIndex` gains the matching attachment.

Two bounded changes to a retained value follow. `ReleaseManifest.partitions` admits an empty tuple — a widening, so every existing construction stays valid — and `ReleaseManifest` gains an explicit `jurisdiction`, because with partitions possibly absent it can no longer derive one from them, and because the database makes it the manifest's own column anyway. The alternative, passing the jurisdiction beside the manifest only at registration, leaves the manifest value unable to describe itself and the object-store record without a county. Fabricating a partition to carry it is the one thing not on the table.

Changing what the value carries is only half of it. `serialize_manifest` in the S3 adapter enumerates fields by hand, so a new field is not written unless the serializer is changed, and the only county in the JSON today is the `jurisdiction_code` inside each partition — which a zero-partition acquisition has none of. Leaving the adapter alone would produce precisely the record this change exists to prevent:

```text
  ReleaseManifest(jurisdiction=tx-collin, partitions=())
        └─► <sha>.manifest.json     no partition, and no county either
```

So this one change reaches into the adapter, and the plan says so rather than forbidding what it requires. The surface is the manifest serialization, the manifest-storage mechanics that the acquisition grain requires, and their tests — in `objectstore/s3.py` and `test_s3_bronze.py`, and nothing else. No new or general object-store capability is added beyond that bounded correction to what already exists.

The pinned `BRONZE_MANIFEST_VERSION` then has to move. It exists so a consumer identifies the shape rather than inferring it from which fields are present, and two shapes both claiming version 1 would defeat that:

```text
  v1   non-empty partitions; county recoverable only from them
  v2   explicit jurisdiction; partitions may be empty
```

Stored v1 objects are immutable and stay exactly as they are. Nothing in the repository deserializes a manifest today — they are write-only evidence — so no stored object is re-read, rewritten, or migrated.

One claim in the first draft of this task was simply wrong: that adding `jurisdiction` was a widening leaving every existing construction valid. Relaxing `partitions` is; adding a required field is not. `from_acquisition` takes `partitions` keyword-only and would take `jurisdiction` the same way, so the four constructions are updated. The alternative — inferring the county from a non-empty partition tuple and requiring it only when empty — gives one fact two sources of truth and quietly restores the derivation this lifecycle removes.

### The grain the manifest is stored at

Adding the jurisdiction exposed something older. Two docstrings in this repository contradict each other:

```text
  manifest_key      "The manifest describes an artifact, so it is keyed like one."
                    bronze/artifacts/<sha>.manifest.json
  ReleaseManifest   "The immutable record of one acquisition."
```

Both cannot be true. The value is acquisition-grain — it carries `acquired_at`, the source URL, response metadata, redirects — and the database agrees, giving `bronze.release_manifest` no unique constraint on `artifact_sha256` precisely so one artifact can carry several acquisitions. The object store keys it by artifact anyway, and `record()` justifies treating an existing object as success because "it describes the same artifact by construction". That reasoning was sound while a manifest was artifact-grain. It is wrong now.

The accepted artifact contract makes the collision reachable rather than theoretical: identity is "the SHA-256 content digest alone", and the same digest under two source URLs compares equal. So:

```text
  acquisition A   tx-dallas, Dallas URL, T1  ─┐
                                              ├─► one key: bronze/artifacts/X.manifest.json
  acquisition B   tx-collin, Collin URL, T2  ─┘   B is silently discarded
```

The v1→v2 case is worse because it needs no second county. A stored v1 manifest occupies the key, the conditional put finds it, `record()` reports success — and the v2 acquisition's explicit jurisdiction is never written. Retaining v1, which is right, would permanently prevent v2 for those bytes.

Before any of that, something has to say when two recordings are *one* acquisition — "idempotent per acquisition" is not a contract until it does. The manifest is already the answer: it is immutable, application-owned, and describes exactly one acquisition. Two recordings are the same acquisition when their manifests agree on every acquisition-describing field, with the partition tuple excluded:

```text
  compared    jurisdiction · artifact content identity (sha256) · acquired_at
              source_url · response metadata · redirects · manifest_version
              tool_versions
  excluded    partitions              attached after recording; including them would
                                      make an acquisition look new for having gained one
              locator, byte_count,    artifact-grain evidence, held once per artifact
              media_type              and not per acquisition
```

That is decidable from the value alone — no locator, key, lock, digest choice, or query — and it needs no acquisition identifier beside the manifest, which is the second identifier vocabulary D2a and D2c already refused.

The artifact takes part by its content identity alone, and the database settles why. `bronze.artifact` is keyed by `sha256` and carries the locator, byte count, and media type **once per artifact**; `bronze.release_manifest` references it by `artifact_sha256` and persists none of the three:

```text
  bronze.artifact          sha256 PK · locator · byte_count · media_type    per artifact
  bronze.release_manifest  jurisdiction_code · artifact_sha256 · acquired_at
                           source_url · response_status/headers
                           manifest_version · tool_versions                 per acquisition
  bronze.release_redirect  the redirect chain                               per acquisition
```

A rule making two same-digest acquisitions distinct because their locators or media types differed would be one `ManifestIndex` could not honour: there is nowhere at acquisition grain to record the difference, and nowhere to read it back from when the acquisition is registered again. Honouring it would take a migration, or hidden cross-adapter state, and both are out of scope. So those three are named for what they are — storage evidence, integrity evidence, and metadata about the bytes — and a disagreement about them for a digest already known is an artifact-consistency concern, not a second acquisition.

Read the other way, the rule is exactly implementable: every acquisition-defining component already has an acquisition-grain home, `jurisdiction_code` through `tool_versions` with the redirect chain in its own table. Nothing in the comparison has to be invented, and nothing has to be stored that is not stored today.

It also gives the distinction the storage grain exists for, with one honest limit. Two recordings whose retained evidence differs are different acquisitions even when the bytes are identical; artifact identity is the digest alone and cannot see that, which is why the manifest has to carry it. But the contract stops there and does not promise that a repeated fetch is *always* a new acquisition. It cannot: under a fixed or coarse clock with an unchanged response, two fetches can leave evidence identical in every compared component, and then nothing retained distinguishes them. They are observationally equivalent and may coalesce. Inventing a physical-attempt identifier to force them apart would mean a new identifier, a column, and a migration to record something no consumer can act on:

```text
  register(M)  then  register(M)      one acquisition, one manifest, one ManifestRef
  fetch → M1;  later fetch → M2       same digest, different acquired_at
                                      two acquisitions, two manifests, neither displaced
```

So the manifest gets an acquisition-grain locator while the artifact bytes stay content-addressed, and the plan states properties rather than a scheme:

```text
  same artifact, same acquisition       ─► same manifest, no duplicate written
  same artifact, different acquisition  ─► different manifest, neither displaced
  already recorded                      ─► never overwritten
  stored v1 object                      ─► immutable, and does not block v2
```

A digest over a canonical **acquisition-equivalence preimage** — the compared components, with partitions excluded — is one possible implementation. A digest over the full serialized manifest is not, because that serialization carries the partitions, so attaching one afterwards would change the digest and manufacture a second acquisition out of the same one. Either way the adapter chooses, and the port contract fixes nothing.

The two partition associations differ in the same way and should not be flattened. `reference_partition(partition, sha256)` takes a checksum, so in the object store a partition is associated with the artifact; `ManifestIndex` associates it with the acquisition a run binds to. Content identity on one side, acquisition identity on the other — deliberate, and worth saying out loud.

The manifest still exists before normalisation, which is what the accepted contract asks. Deriving a partition stays a projection rather than a decision: `ReleasePartition` is `LogicalReleaseEvidence` with the release identifier dropped.

One promotion seam serves both origins, so evidence established by a page and evidence established by content are indistinguishable downstream — which is what keeps the six counties on one contract rather than two. The many-to-many artifact/release model this preserves is already accepted: `canonical-identity-and-provenance` requires the association to "support one artifact carrying several logical releases and one logical release observed in several artifacts."

## Where an incomplete release fails

The first draft put a `MissingReleaseIdentifier` on the canonical repository. That error was unreachable: `ReleaseIdentity.__post_init__` calls `require_identifier`, so an incomplete `ReleaseIdentity` cannot be constructed, and a method taking one can never receive the state it claimed to reject.

The failure belongs one step earlier, at the only place a partial release becomes a whole one:

```text
  LogicalReleaseEvidence                promote()            ReleaseIdentity
    jurisdiction                            │                  jurisdiction
    tax_year                 ──────────────►│                  tax_year
    release_kind                            │                  release_kind
    release_identifier?  ← may be absent    │                  release_identifier
                                            ▼
                              IncompleteReleaseIdentity
```

Downstream of promotion no port carries a "maybe complete" identity, and `ReleaseIdentity` is not weakened to make the error expressible. The alternative — a nullable fourth component threaded through the canonical port — is precisely how a filename ends up as a release identifier under schedule pressure.

The evidence carries one more fact that is not identity: the source as-of instant established for that logical release, where one was. Promotion does not consume it — it rides beside the identity to the publication attempt, which is what lets a current release and the certified release packed in the same artifact each publish their own freshness. A page instant for the export as a whole applies to every release drawn from it; a content-established instant for one release takes precedence for that release; absence is recorded, and the acquisition instant is never substituted.

## Bronze grain and canonical identity

```text
  bronze.release_partition   (jurisdiction_code, tax_year, release_kind)          3 components
  ingestion.run              those three + release_identifier                     4 components
  canonical.release          jurisdiction, tax_year, release_kind, identifier     4 components
```

In the database the fourth component first appears at `ingestion.run`, which is why the run is where identity and acquisition are bound. It is *established* earlier than that, by promotion, and promotion is what `start()` consumes — the run records the component rather than inventing it. A Bronze acquisition can legitimately know less than the three Bronze components too: a Dallas archive may be published as "2025, certified" while the Collin export announces neither, and both are acquired before anything establishes a tax year. Tax year and release kind come from page evidence or verified content; the release identifier comes from the same two places, and sometimes from neither.

The canonical port takes `ReleaseIdentity`. It does not take `ReleasePartition` and does not accept a partition plus a hint. Where the source has not established an identifier, **promotion** fails with a named error — see the promotion seam below — and the load is never reached. The alternative is worse than failing: a synthesised identifier from a filename or checksum would be accepted by every constraint in the database and would silently define a release that does not exist.

## The outcome cannot be the adapters' outcome

The session accepts the run's processing outcome, and the obvious candidate is `ReleaseOutcome` from `property_tax_adapters.release.outcome` — it already carries the disposition, the four counts, and the truncation flags, and `ingestion.release_outcome` mirrors it column for column.

The application may not import it. `FORBIDDEN_IMPORTS` in the dependency-direction test lists `property_tax_adapters` under `property_tax_application`, and the direction is real rather than nominal: five county modules already import `CountySourceDefinition` from the application, so the arrow points inward and reversing it anywhere would make the graph cyclic.

So the application defines its own outcome value carrying the facts the database gate and the accepted contract need — disposition, the counts, the bounded diagnostics and notices with their truncation flags — and the adapter maps `ReleaseOutcome` onto it at the boundary it already crosses. One fact in that value is a constant rather than a measurement: `ingestion.release_outcome` carries `CHECK (boundary_contract_version = 1)`, and the adapters pin it as `BOUNDARY_CONTRACT_VERSION`. The application cannot import that constant, so it holds a copy and refuses any other integer at construction, and the dependency-direction test — which may import both packages — asserts the two copies are equal. Without the pin an outcome carrying `2` would satisfy every enumerated invariant and abort the canonical completion at persistence, the same shape of defect the evidence seal closed.

This is a mapping, not a second model. The alternative, moving `ReleaseOutcome` inward, would edit the public surface of a promoted capability (`bounded-release-processing`) to serve a consumer that does not exist yet, and would drag `ReleaseDiagnostic` and `ReleaseNotice` with it.

## Quality and publication are different units of work

Quality evaluates loaded canonical data — required-key completeness, uniqueness, child relationships, row-count drift — so it necessarily runs after the load has committed. A blocking failure prevents *publication* and quarantines the release; it does not retract the load, and `validated-data-publication` says exactly that.

Publication is atomic on its own terms: attempt, then activate or fail. `publication.publication` carries the state machine (`building`, `current`, `superseded`, `failed`) and the supersession pointer, and `PublicationAttempt.fail()` leaves the previously current publication current, which is the accepted requirement that consumers keep reading the last good build.

What stands between the two is a verdict the database cannot compute. The persisted gate, `publication.assert_current_is_validated`, refuses a current publication when the run's outcome is not accepted or when `quality.blocking_failure` holds a row for it — and that view is derived from *recorded* evaluations that failed. A blocking rule nobody evaluated leaves no row, so the gate waves it through, and `quality.evaluation`'s own comment names the blind spot: a release that passed because a rule never ran looks identical afterwards to one that passed because it did. The accepted requirement is that all blocking rules pass, not that none recorded a failure. An earlier draft left the blocking-or-warning decision to the use case; it cannot make that decision after a crash, because nothing in the boundary read back which evaluations a dead worker had recorded. So `QualityRepository` computes a run-level verdict when asked — the active blocking rules with no recorded evaluation for the run at their active version, the recorded blocking failures, the warning failures — and `activate()` refuses by name unless that verdict is complete and clean at the moment of activation. The verdict is stored nowhere: a stored verdict would be the second quality model D7 forbids, and it would go stale the moment a rule was activated, which is exactly the case that must refuse. The rule set that counts is the one active at activation, at exact versions: an evaluation at a version since replaced is stale, not coverage. The remedy for missing or stale coverage is a new processing run, never re-evaluation within the run. An earlier draft of this paragraph promised re-evaluation, and the schema forbids it: `quality.evaluation` is unique on run, rule, and subject without the version, and the loading role holds SELECT and INSERT only, so the first verdict a run records for a rule is the only one it will ever hold. Judging the run under "the rules of its time" by timestamp was considered and rejected: `quality.rule` records when a version was defined, not when it became active; a rule can be defined inactive and activated later; no activation history exists; nothing prevents two versions being active at once; and evaluation timestamps do not mark a completed quality cycle. Any cutoff inferred from those columns would replace a known defect with history the database does not store. Two active versions of one rule is therefore a named configuration error the verdict reports and activation fails closed on; keeping one version active and switching atomically is the migrator's obligation, and a partial unique constraint over active versions is a follow-up migration issue outside this change. The check is admission-time: a publication already current stays current whatever becomes active afterwards, exactly as the persisted trigger judges only the row becoming current.

**"At the moment of activation" has to mean inside it.** An earlier draft said the verdict must be
clean at the moment of activation and left who computes it unstated, which reads as a guarantee and
is not one: a caller reads a clean verdict through `QualityRepository`, a rule version becomes active,
the caller then calls `activate()`, and a publication is admitted that the rule set active at
activation would have refused. Two decisions with a window between them is the same defect as the
persisted gate's blind spot, arriving one layer up. So the verdict admitting an activation is derived
**within the same atomic boundary as the state change**, against the rule set active inside that
boundary; a verdict a caller obtained earlier is advisory — good for reporting and for deciding
whether to bother attempting — and never the admission decision. Where the store cannot serialize the
derivation with the state change, activation refuses rather than proceeding on a verdict it cannot
vouch for. That is what the persisted trigger already does, and this is the same rule where the
database cannot reach.

**The ambiguity is about the rule, not its severity.** Two active versions of one rule fail closed
whatever those versions' severities are. Narrowing it to blocking versions reads as a tightening and
is a loophole: severity is a property of a *version*, so two active versions that disagree about
whether the rule blocks are precisely the case where "is this a blocking rule?" has no answer, and
the verdict would have to pick one to decide whether to care. It reports the ambiguity without
reading either severity.

The boundary stops there deliberately. Migration `0005` says task 6.2 owns the promotion path, and this port has no operation that stages or writes published content — so scoping it to attempt, lineage, and activation describes what it can actually do. A requirement promising an atomic Gold build would be a promise no task in this change makes representable.

So there are three transactions in the pipeline, not one, and the boundary makes the seams explicit:

```text
  [ run + outcome + canonical load ]   one transaction, deferred gate
  [ quality evaluations → verdict ]    run-bound, after the load; the verdict is computed, never stored
  [ publication build → activate ]     atomic, over completed loads; activation refuses unless the verdict is clean
```

## Cross-spec contract matrix

The change carries six capability specs. Every shared concept is defined in exactly one of them or in an accepted spec, and the others cite the owner by name rather than restating it. A reviewer's first sweep after any fix is this table: two review rounds on this change found one fact stated two ways in two places, and a split into several files makes that the likeliest defect rather than the rarest.

| Concept | Owning spec | Cited by |
| --- | --- | --- |
| No infrastructure vocabulary in any port | `application-port-boundary` | every other spec; proven by task 7.1 |
| Opaque persistence locators (`ProcessingRunRef`, `ManifestRef`, `PublicationRef`) | `application-port-boundary` | `processing-run`, `acquisition-manifest-index`, `run-bound-quality-and-publication` |
| `ReleaseIdentity`, four components | accepted `canonical-identity-and-provenance` | `source-registry-and-discovery` (promotion), `processing-run`, `canonical-load-session` |
| Promotion from `LogicalReleaseEvidence`; `IncompleteReleaseIdentity` | `source-registry-and-discovery` | `processing-run` (`start` takes the promoted identity), `canonical-load-session` |
| `SourceCandidate`, `PageEvidence`, `UnchangedRelease`, and the per-release source as-of instant on `LogicalReleaseEvidence` | `source-registry-and-discovery` | `acquisition-manifest-index` (a `ReleasePartition` is the evidence with the identifier dropped), `run-bound-quality-and-publication` (each release's own instant at its attempt) |
| `CountySourceDefinition`, `AcquisitionMethod`, expected media types, `SourceRegistry` | `source-registry-and-discovery` | — |
| `ArtifactSink`, `BronzeStore`, `ReleaseManifest`, `ReleasePartition`, `StoredArtifact` | `acquisition-manifest-index` (retained; bounded corrections) | `source-registry-and-discovery` |
| Acquisition equivalence, acquisition-grain storage, the manifest shape version | `acquisition-manifest-index` | — |
| `ManifestIndex`, `ManifestRef` | `acquisition-manifest-index` | `processing-run` |
| `ProcessingRunRef`, `ProcessingRunRepository`, the active-run refusal | `processing-run` | `canonical-load-session`, `run-bound-quality-and-publication` |
| `ReleaseProcessingOutcome`, `ReleaseDiagnosticRecord`, `ReleaseNoticeRecord`, `ReleaseDisposition`, the evidence seal, the mirrored `BOUNDARY_CONTRACT_VERSION` | `processing-run` | `canonical-load-session` (the session accepts it at `open`); task 7.1 pins the mirror equal to the adapters' constant |
| The closed diagnostic vocabulary; the bounded notice grammar | accepted `bounded-release-processing` | `processing-run` (validates against them; defines no second enum) |
| Outcome, diagnostic, notice, quality, and publication records reused rather than replaced | accepted `canonical-silver-persistence` | `processing-run`, `run-bound-quality-and-publication` |
| The canonical load session, its state machine, batch, correlation, and adoption | `canonical-load-session`, defined by the sibling change `add-canonical-load-session` | cited here, never restated |
| Account snapshot grain (deliberately non-unique), one-to-many children, cross-load lineage, release-scoped retry | accepted `canonical-silver-persistence` | `canonical-load-session` (adoption names an **opaque locator**, never the grain, and never provenance — both name more than one snapshot; round 4 records why) |
| The canonical record types | accepted `canonical-appraisal-records` | `canonical-load-session` |
| `RuleSeverity`, `QualityRule`, `QualityEvaluation`, `QualityVerdict`, `QualityRepository` | `run-bound-quality-and-publication` | the publication attempt's activation, in the same spec, checks the verdict |
| `PublicationProduct`, `PublicationRef`, `PublicationAttempt`, `PublicationRepository` | `run-bound-quality-and-publication` | — |
| `Clock` | `run-bound-quality-and-publication` | — |

## The falsification matrix

Task 7.2 implements every case below. They live here rather than inside the task line for two
reasons: the rendered task line is bounded at 2,048 characters by the planning materializer, and a
list this long is only reviewable if it is grouped by the scope that owns it — which is how this
change is reviewed.

Each case names a defect. A case that cannot fail is not on this list.

### `registry-and-discovery`

- An unregistered jurisdiction raises `UnsupportedSource` **before any network call**, proved with a
  fake that fails the test if asked to acquire.
- A registered jurisdiction resolves with no release kind supplied.
- A caller-supplied unregistered kind raises before any network call.
- A kind established only by parsing is validated after parsing and before promotion.
- A resolved definition carries its expected media types, and every one of the six registered
  counties carries a non-empty tuple of its own rather than a shared default.
- Discovery distinguishes a candidate from an unchanged result, and the unchanged path performs no
  download.
- A source candidate carrying no logical release evidence is valid, so a source whose tax years and
  release kinds live only in content is expressible.
- Evidence that established three components records three and does not synthesise a fourth.
- Promoting incomplete evidence raises `IncompleteReleaseIdentity` naming the missing component;
  promoting complete evidence yields a `ReleaseIdentity`.
- Evidence established by parsing promotes through that same seam, and two evidences drawn from one
  artifact yield two identities and two runs bound to one `ManifestRef`.

### `run-and-manifest`

- A `ReleaseManifest` carrying no partition is valid and carries its jurisdiction; one whose
  partition names a different jurisdiction is refused.
- Acquisition equivalence is falsified **table-driven**, one case per declared acquisition-defining
  component — jurisdiction, artifact `sha256`, `acquired_at`, `source_url`, response metadata,
  redirects, `manifest_version`, `tool_versions` — mutating exactly one and asserting the acquisition
  becomes different.
- Companion cases mutate only `partitions`, and only the artifact's `locator`, `byte_count`, or
  `media_type`, each asserting the acquisition stays the same. No case claims that a locator, byte
  count, or media type alone makes a different acquisition.
- Two manifests equal in every compared component compare as one acquisition, including where their
  content digests agree and nothing else was changed.
- A `ManifestIndex` fake returns one `ManifestRef` for a re-registered acquisition, distinct
  references for two acquisitions of one artifact, and attaches a later partition without altering
  what was recorded.
- Recording one acquisition twice yields one `ManifestRef`, and two releases carried by one artifact
  bind to that same reference.
- A run reference is never required to be invented — every port takes the reference type rather than
  a raw value — and a reference resolving to no started run is refused.
- Starting a run for a release whose run is held is refused by name, while one whose previous run
  finished starts normally.
- Starting a run for a release whose unfinished run's holder is gone returns the same reference with
  `resumed=True` and creates no second run; of two racing retries exactly one resumes and the other
  is refused by name; completing the load again under the resumed run returns `already_complete=True`.
- `ProcessingRunRef` supports equality and not ordering.

### `quality-publication-clock`

- A failing `QualityEvaluation` without measured and expected values is rejected.
- A run's verdict reports an active blocking rule with no recorded evaluation as **missing**, one
  whose only evaluation is at a replaced version as **stale**, and one with two active versions as a
  named **configuration error**, each making the verdict incomplete; and is complete and clean when
  every active blocking rule has a recorded pass at exactly its active version, whatever the warnings
  say.
- Two active versions of one rule are that configuration error **even when the two versions disagree
  about whether the rule blocks**, and the verdict reaches that answer without reading the severity
  of either — the ambiguity is about the rule identifier, not about severity.
- `PublicationAttempt.activate()` refuses by name and leaves the previously current publication
  current for a missing, stale, or ambiguous rule or a blocking failure; activates on a clean
  verdict; and a publication already current stays current when a rule's active version changes
  afterwards.
- **The admitting verdict is derived inside the activation.** A fake flips the active rule set
  *between* the caller reading a clean verdict and calling `activate()`; activation refuses by name.
  A caller that reads clean and then activates must not be able to publish what the rule set active
  at activation would refuse.
- **Where the fake cannot serialize the derivation with the state change**, `activate()` refuses by
  name rather than proceeding on a verdict it cannot vouch for.
- **A new run is the recovery, and it works.** A run holding an evaluation at v1 becomes stale when
  v2 becomes active and its activation refuses; a new run evaluated against v2 is complete and clean;
  and that new run activates. Proving the refusal without proving the recovery would leave the
  remedy asserted rather than demonstrated.
- `PublicationAttempt.fail()` leaves the previously current publication current.
- Two evidences drawn from one artifact carry their own source as-of instants and each attempt opened
  for them receives its own; a page-established instant for the export reaches both releases drawn
  from it; and an attempt opened for a release whose evidence carries none receives its absence
  rather than a substituted time.
- `Clock` returns an aware instant, with a fixed fake observed by the caller.

### `surface-and-proof`

- The suite is application-contract only: it asserts value semantics and Protocol properties, and
  never an object key, a serialized manifest body, or any storage behaviour — those belong to task
  1.2's adapter tests.
- The module is collected by the default repository configuration.

## Alternatives rejected

- **One `Repository` per database schema.** Mirrors the tables, which is precisely the problem: `canonical.*`, `ingestion.*`, `quality.*`, and `publication.*` would become application vocabulary, and 3.5's freedom to choose staging mechanics would evaporate.
- **A `UnitOfWork` spanning all seven responsibilities.** Ties publication and quality to the load's transaction, which the accepted contracts explicitly separate, and forces an implementation to hold one connection across work that legitimately fails independently.
- **A generic object-store CRUD port.** `ArtifactSink` and `BronzeStore` already express what is needed with tighter guarantees; a general `put`/`get` would be a weaker contract replacing a stronger one.
- **Letting use cases call `datetime.now`.** Makes every use case untestable at the one point where determinism matters most, which is why the clock is a port at all.
- **Keying the acquisition manifest by artifact digest.** It is what the adapter does today, and it was coherent while the manifest was artifact-grain. Once the value carries a jurisdiction, a source URL, and an acquisition instant, one key per artifact discards every acquisition after the first and lets a stored v1 object block v2 forever.
- **Fixing the manifest keying scheme in the port contract.** The application would be naming an object-store layout, which is exactly the infrastructure vocabulary this boundary keeps out. The contract states the four properties and leaves the mechanism to the adapter.
- **Changing the manifest value without changing the serializer.** Keeps the plan's no-adapter rule intact and writes an object-store record with no county — the exact defect the change is meant to fix.
- **Keeping the manifest at version 1 while adding a field.** The version is pinned so a consumer can identify the shape; two shapes sharing a number make it useless for the one job it has.
- **Inferring the jurisdiction from a non-empty partition tuple.** Avoids updating four constructions, at the price of one fact having two sources of truth and the derivation returning by the back door.
- **Keeping `ReleaseManifest.partitions` non-empty and ordering parse before the manifest.** It preserves a retained value untouched at the cost of leaving a successfully acquired artifact unmanifested whenever inspection fails first — the case Bronze exists for. `reference_partition` already anticipates later attachment, and the database's composite `release_manifest_identity` key shows the intended shape.
- **Passing the jurisdiction beside the manifest at registration instead of on the value.** Avoids touching `ReleaseManifest`, and leaves a manifest that cannot say which county it belongs to — including in the object-store record, where nothing is passing anything beside it.
- **Requiring a release kind to resolve a source.** It would make Collin unresolvable one step before it is undiscoverable, since the definition must exist before the source can be probed and the kinds are inside the artifact. Today's `source_for_county(county)` already resolves by county alone, and the accepted scenarios are about what a caller *requests*, so making the kind optional keeps both intact.
- **Requiring discovery to establish the tax year and release kind.** It makes the common case tidy and the Collin case impossible: one mutable export whose releases live in `curr_val_yr` and `cert_val_yr` cannot be classified before it is read. The contract already anticipated this — one source candidate, and parsing creates the logical release partitions — so requiring it here would have contradicted an accepted requirement to save a field.
- **A second promotion seam for parsed evidence.** Two entry points for one transition, differing only in where the facts came from, and the second would be written under schedule pressure by whoever implements the first county whose releases are in content. One evidence type with one promotion keeps them indistinguishable downstream.
- **Deferring run creation to 2.4.** The reference is database-generated; a use case cannot construct a correct one without reaching through the boundary, so deferring it would have made the first implementation invent the contract.
- **Refusing every unfinished run.** It prevents overlap and also prevents recovery: a dead worker never finishes its run, and the boundary offered no way to obtain or retire it, so the release waited for a database edit. Holding is what distinguishes a live worker from a dead one, and it is worth the mechanism.
- **Returning the existing run to any caller.** It recovers from a crash by letting two live workers share one run, so the accepted overlap scenario fails and one run carries two workers' outcomes.
- **Trusting the persisted publication gate for quality.** It counts recorded blocking failures, so a blocking rule nobody evaluated passes it; the accepted contract requires every blocking rule to pass. Leaving the verdict to the use case fails the same way after a crash, because the boundary offered no read of what was recorded.
- **Re-evaluating a run under a newer rule version.** The evaluation record is one immutable verdict per rule and subject per run and the loading role cannot replace it, so the remedy could never be carried out; a release whose rule versions moved would have waited forever. A new run is the only remedy the schema admits.
- **Judging a run under the rules of its time by timestamp.** The rule table stores when a version was defined, not when it became active, and keeps no activation history; a cutoff inferred from `defined_at` and `evaluated_at` would be history the database does not hold.
- **A candidate-level source as-of instant only.** One Collin export carries a current release and a certified one; a single instant on the candidate cannot let them publish different freshness, and after promotion nothing but the evidence travels with the release.

## Risks

- **`ProcessingRunRef` invites misuse.** It is an opaque locator that will be a `bigint` in practice, and someone will eventually sort by it. The contract names it, a test asserts it carries no ordering guarantee, and that is the extent of what a type can do here.
- **The port count could still be wrong.** Eleven contracts for seven named responsibilities is a judgement, defended in the proposal by the two accepted requirements behind "source discovery". If 2.4 finds the registry/discovery split artificial in practice, merging them is a smaller change than splitting a merged one.
- **`Clock` may sit unused until 2.4.** Defining a port with no consumer risks it drifting from what the use cases actually need. Mitigated by keeping it minimal — one method — so there is little to drift.
- **Two versions of one rule can be active at once.** Nothing in `quality.rule` prevents it, and the verdict fails closed on it rather than choosing. A follow-up migration issue adds a partial unique constraint over active versions; until then the migrator switches versions atomically, and a release caught by a non-atomic switch refuses activation until the rule set is corrected.
- **A held run needs a liveness mechanism.** A lease that a live but stalled worker fails to renew looks abandoned, and a retry would resume a run its first worker later continues. A lock scoped to the worker's connection has no such window; if 3.5 chooses a lease instead, the holder must re-verify it still holds the run before every durable write, and the contract test for two racing retries is what pins that only one wins.

## Migration

No data moves and no migration is added. `ArtifactSink` keeps its signatures and semantics, the `BronzeStore` Protocol keeps its operations and their signatures, and every new port is additive.

One construction signature does change: `ReleaseManifest` gains a required `jurisdiction`, so `ReleaseManifest(...)` and `ReleaseManifest.from_acquisition(...)` take one more keyword argument. The four call sites are all in `libs/property-tax-adapters/tests/objectstore/test_s3_bronze.py` and are updated with it. Stored v1 manifest objects are untouched and are not re-read or rewritten.

## Handoffs

**To bootstrap 3.5.** This change gives 3.5 `ManifestIndex` and `ProcessingRunRepository`, which are prerequisites of the canonical load rather than companions to it: a canonical load cannot open without a run, and a run cannot start without a manifest reference, so `bronze.release_manifest` and `ingestion.run` are 3.5's to write before the first batch lands — including whatever represents a held run, since `ingestion.run` carries no such column. The canonical session 3.5 implements is specified by the sibling change `add-canonical-load-session`, and its handoff is stated there.

**To bootstrap 2.4.** The discover, acquire, parse, normalize, validate, and publish use cases coordinate `SourceRegistry`, `ReleaseDiscovery`, `ArtifactSink`, `BronzeStore`, `ManifestIndex`, `ProcessingRunRepository`, `CanonicalReleaseRepository`, `QualityRepository`, `PublicationRepository`, and `Clock` — never an adapter type. Minting correlation handles and carrying adoptions in the batches it builds are 2.4's, and are stated by `add-canonical-load-session`, which owns that port. It also owns retiring the S3 adapter's `utc_now()` in favour of the injected clock.

## Unresolved questions

- Whether `ReleaseDiscovery` should return candidates for one jurisdiction or accept a cohort, which depends on how 2.4 shapes the six-county scheduled workflow.
- Whether publication products beyond the accepted three ever need a distinct session shape. Out of scope until a fourth product exists.
