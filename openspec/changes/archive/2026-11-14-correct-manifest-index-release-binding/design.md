## Context

Issue #138 planning proved that the promoted queryable index combines two grains it cannot
implement together. `ReleaseIdentity` has four components and deliberately distinguishes two
same-county, same-year, same-kind releases by `release_identifier`; `ReleasePartition` has three
identity-like components plus optional freshness and deliberately remains Bronze/source evidence.
The current `attach_partition(reference, partition)` call never receives the fourth component,
while `partition_for(reference, release)` promises a read for the complete identity.

The existing fake demonstrates the defect: it keys attachments by manifest reference,
jurisdiction, year, and kind, so asking for identifier `B` returns evidence attached for identifier
`A`. `ReleaseManifest` and the object-store shape also reject two partitions at that same
three-part grain. Those facts are not defects in Bronze: a source partition may exist before
promotion establishes a canonical release identifier. The defect is treating that source grain as
sufficient for the queryable full-release attachment publication later reads.

This change is owned by issue #143. Bootstrap 3.5 in #138 remains blocked until the correction is
implemented, independently reviewed, promoted, and archived.

## Goals / Non-Goals

**Goals:**

- Make one `ManifestIndex` attachment unambiguously select one full `ReleaseIdentity` under one
  `ManifestRef`.
- Preserve the existing three-part `ReleasePartition` and the single promotion seam that creates a
  complete `ReleaseIdentity`.
- Keep source freshness distinguishable at full-release attachment grain, including attached
  absence versus no attachment.
- Define retry, conflict, and overlap-consistency behavior tightly enough for a future PostgreSQL
  adapter to implement without guessing.
- Leave a precise schema handoff for resumed #138 planning without prescribing a table name here.

**Non-Goals:**

- No PostgreSQL relation, migration, adapter, S3 change, publication API change, orchestration,
  bootstrap checkbox, or 3.5/3.6 implementation belongs to this correction.
- `ReleasePartition` does not gain `release_identifier` and does not become canonical identity.
- Registration does not infer, promote, or synthesize release identity from source evidence.
- S3 keys and `partition_prefix()` remain adapter renderings and never become domain identity.

## Decisions

### D1 — Bronze partition and canonical release remain different grains

`ReleasePartition` remains exactly `jurisdiction_code`, `tax_year`, `release_kind`, and optional
`source_as_of`. It is a Bronze/source partition that may be known before the source establishes a
release identifier. `LogicalReleaseEvidence -> promote -> ReleaseIdentity` remains the only seam
that creates complete canonical release identity.

Adding `release_identifier` to `ReleasePartition` was rejected because it would move canonical
identity construction into Bronze and make a valid pre-promotion source partition unrepresentable.
Treating the three-part value as canonical identity was rejected because it directly contradicts
the promoted identity requirement that identifiers `A` and `B` distinguish two releases.

### D2 — Explicit attachment carries all three values

The corrected application signature is:

```python
def attach_partition(
    self,
    reference: ManifestRef,
    release: ReleaseIdentity,
    partition: ReleasePartition,
) -> None: ...
```

The read remains:

```python
def partition_for(
    self,
    reference: ManifestRef,
    release: ReleaseIdentity,
) -> ReleasePartition | None: ...
```

The key of the queryable attachment is exactly `(ManifestRef, ReleaseIdentity)`. The manifest
reference identifies the acquisition, the release identifies the canonical logical release, and
the partition is evidence attached to that pair. Neither value identifies the other.

Reducing `ReleaseIdentity` to its first three components was rejected because it recreates the
alias. Deriving the key from an object-store locator, artifact digest, or S3 path was rejected
because each is a different grain and the promoted port already forbids that derivation.

### D3 — Registration records an acquisition and no full-release attachment

`register(manifest)` remains idempotent by acquisition evidence and returns one `ManifestRef`.
Even when `manifest.partitions` is non-empty, registration SHALL NOT call attachment implicitly:
those values contain no release identifier and cannot identify a canonical release. Explicit
attachment happens only after the caller holds a promoted `ReleaseIdentity`.

Inventing an identifier from a partition, filename, checksum, acquisition time, or row order was
rejected. Keeping the current fake's automatic attachment was rejected because a convenient test
helper would encode the precise behavior the contract now refuses.

### D4 — Overlap is verified, never used to infer the identifier

Before recording, the implementation verifies all three overlaps:

```text
release.jurisdiction.rendered == partition.jurisdiction_code
release.tax_year              == partition.tax_year
release.release_kind.value     == partition.release_kind
```

Any disagreement is an invalid pair and is refused with `ValueError` before stored state changes.
Agreement does not infer the release identifier; the explicit `ReleaseIdentity` supplies it.

Silently rewriting either value was rejected because it would turn attachment into normalization.
Allowing disagreement was rejected because the queryable record would claim one release while
returning source evidence for another.

### D5 — Exact retry is idempotent; conflicting evidence is immutable

An exact repeat of `(ManifestRef, ReleaseIdentity, ReleasePartition)` is a no-op. Reusing the same
`(ManifestRef, ReleaseIdentity)` with a different partition value raises the public
`ManifestAttachmentConflictError` and leaves the original attachment unchanged. This error joins
the application package's explicit public surface because callers must distinguish a safe retry
from immutable evidence disagreement.

Last-write-wins was rejected because publication freshness could change under a retry. Creating a
second row for the same full-release key was rejected because `partition_for()` returns one value
and would have no rule for choosing between them.

### D6 — Source freshness is durable at full-release attachment grain

The object-store manifest remains immutable Bronze evidence and may carry three-part source
partitions. The queryable index is the publication retry path and therefore must durably retain the
partition value, including `source_as_of`, under `(ManifestRef, ReleaseIdentity)`. `None` in the
returned partition means the release was attached and established no instant; a `None` return from
`partition_for()` means that full release was never attached.

Acquisition time, page observation time, and `Clock.now()` remain forbidden substitutes.

When #138 resumes, it must evaluate a new forward migration providing storage equivalent to:

```text
manifest/acquisition reference
+ jurisdiction
+ tax_year
+ release_kind
+ release_identifier
+ source_as_of
```

A separate relational attachment referencing the existing three-part Bronze partition is a likely
implementation, but this correction does not fix the relation name or SQL. Adding only
`source_as_of` to `bronze.release_partition` was rejected because it preserves the identifier alias
and cannot retain two distinct release-level instants at one three-part grain. Migration `0001`
remains immutable.

### D7 — BronzeStore and S3 mechanics do not change

`ReleaseManifest.partitions`, their three-part distinctness, artifact identity, acquisition
equivalence, manifest version, `BronzeStore.classify()`, object keys, and `partition_prefix()` keep
their current behavior. Documentation calls these Bronze/source partitions, not canonical release
identities. The implementation task has no adapter path, so an unrelated S3 change cannot arrive
under this correction.

### D8 — Publication keeps its current API and gains an unambiguous implementation

Publication still follows run -> `ManifestRef` -> `ManifestIndex.partition_for(reference,
release)`. The full release identity already reaches that read. No publication carrier changes and
no three-part lookup is added; the corrected index makes the existing read precise.

### D9 — The correction is completed before #138 resumes

Implementation changes the application Protocol, public conflict error, contract fakes, focused
tests, public-surface guard, and application documentation only. After independent code review, the
delta is promoted and archived through a separate reconciliation PR. Only then may #138 plan the
PostgreSQL relation and migration; bootstrap 3.5 remains unchecked throughout this change.

## Falsification Matrix

| ID | Attack | Required observation |
|---|---|---|
| F1 | Inspect `ManifestIndex.attach_partition` | Parameters are exactly `self`, `reference`, `release`, `partition`; the read signature is unchanged |
| F2 | Attach identifiers `A` and `B` with equal three-part partitions under one reference | Both full identities read back their own attachment; neither aliases the other |
| F3 | Attach only identifier `A`, then read identifier `B` | The read returns no attachment rather than `A`'s evidence |
| F4 | Attach `A -> T1` and `B -> T2` | Each identity returns its own source-as-of instant |
| F5 | Attach `A` with `source_as_of=None`, leave `B` unattached | `A` returns a partition carrying absence; `B` returns no partition |
| F6 | Mismatch jurisdiction, year, and kind in turn | Each pair is refused before the attachment mapping changes |
| F7 | Repeat the exact same attachment | The second call is a no-op and attachment cardinality is unchanged |
| F8 | Repeat one full-release key with changed source-as-of | `ManifestAttachmentConflictError` is raised and the first value remains readable |
| F9 | Register a manifest already carrying a three-part partition | No full-release lookup succeeds before explicit attachment |
| F10 | Inspect `ReleasePartition` fields and public surface | No identifier field was added; only the named conflict error expands the public surface |
| F11 | Publication retries after source-page mutation | The existing lookup returns the indexed attachment and performs no rediscovery or substitution |
| F12 | Search the correction diff for adapter/S3/migration/bootstrap paths | None changed; three-part object-store behavior remains outside this correction |

## Risks / Trade-offs

- **Breaking Protocol signature leaves a stale fake or caller** -> enumerate every call site with
  repository search, update all application-owned fakes, and assert the exact signature.
- **A test passes through the three-part key despite accepting a release argument** -> F2 and F3
  differ only by `release_identifier`, so reducing the key makes both fail for the intended reason.
- **Registration silently keeps its old implicit attachment** -> F9 starts with a manifest carrying
  a partition and proves the read remains absent.
- **Conflict handling mutates before refusing** -> F8 snapshots the mapping/cardinality and reads
  the original value after the exception.
- **The correction is misread as an S3 identity redesign** -> D1 and D7 fix the vocabulary and task
  paths exclude adapters.
- **#138 later adds only a nullable column to the three-part table** -> D6 records the full-release
  durable grain and the rejected column-only alternative in the artifact that planning must cite.

## Migration Plan

1. Merge this planning change with issue #143 still open and #138 still blocked.
2. Implement D1-D9 in one bounded application-only PR and run the matrix above.
3. Independently review the implementation.
4. Promote the modified `acquisition-manifest-index` requirement and archive this change, closing
   #143 through that reconciliation PR.
5. Resume #138 planning from the promoted full-release attachment grain; choose the smallest
   forward PostgreSQL migration then, without editing migration `0001`.

This correction itself has no deployment migration or rollback. Before promotion, rollback is a
normal code revert. After promotion, a new correction is required; archived evidence is retained.

## Open Questions

None. The owner decision fixes the two grains, the exact signature, and the #138 handoff. Table
shape, SQL, and migration number remain deliberately deferred implementation decisions for #138,
not unresolved questions in this application-contract correction.
