## MODIFIED Requirements

### Requirement: An acquisition is manifested before its releases are known
Every successfully acquired artifact SHALL have its acquisition manifested, whether or not any logical release has yet been established. An acquisition manifest SHALL therefore be recordable carrying no release partition, and SHALL carry the jurisdiction explicitly rather than deriving it from partitions it may not have.

A release partition established later SHALL be attachable without altering the immutable acquisition record. The two stores associate it at deliberately different grains: the object store associates a three-part Bronze/source partition with the **artifact**, whose identity is content alone, while the queryable index associates the partition evidence with the **acquisition and complete logical release identity** the run binds to. The contract SHALL keep those distinct rather than describing them as one association. Where partitions are present in an acquisition manifest, each SHALL name the same jurisdiction the manifest names.

`ReleasePartition` SHALL remain the Bronze/source-partition value carrying `jurisdiction_code`, `tax_year`, `release_kind`, and optional `source_as_of`. It SHALL NOT gain a release identifier and SHALL NOT be treated as canonical release identity. A source partition MAY exist before parsing establishes the fourth canonical identity component. `LogicalReleaseEvidence` promotion SHALL remain the single seam that produces a complete `ReleaseIdentity`; registration or attachment SHALL NOT infer or synthesize that identifier from a partition, filename, artifact checksum, acquisition instant, row order, or storage location.

**A partition SHALL carry the source as-of instant established for its logical release, where one was established, timezone-aware.** The object-store manifest retains immutable Bronze evidence at three-part source-partition grain. The queryable index is the durable publication-retry path and SHALL retain the partition evidence, including `source_as_of`, under the acquisition reference and complete `ReleaseIdentity`. That full-release attachment grain is what lets publication resuming in a later process state the freshness of the exact release it exposes without a candidate in memory or a mutable source page.

The durable queryable representation SHALL be capable of retaining two complete release identities that differ only by `release_identifier`, including distinct source-as-of instants, under one acquisition reference. A relational implementation therefore SHALL NOT treat a nullable source-as-of column on a three-part Bronze partition as sufficient by itself. Its schema SHALL provide storage equivalent to acquisition reference plus all four `ReleaseIdentity` components plus the attached partition evidence. The exact relation and migration remain adapter implementation decisions; an existing migration SHALL NOT be rewritten to manufacture this grain.

Where no instant was established for a logical release, its full-release attachment SHALL retain a partition whose `source_as_of` is absent. That attached absence SHALL remain distinguishable from no attachment for that full identity. Acquisition time, page observation time, and application clock time SHALL NOT be substituted.

No partition SHALL be fabricated to make an acquisition recordable, and an artifact that fails inspection before any release is established SHALL still have a durable record of what was acquired. Registering an acquisition SHALL NOT manufacture a complete release attachment from any three-part partitions already present in its manifest. A queryable attachment SHALL occur only after a caller supplies an actual promoted `ReleaseIdentity`.

#### Scenario: A partition records the freshness of its own release
- **WHEN** a partition is attached for a complete logical release identity whose evidence established a source as-of instant
- **THEN** the full-release attachment records that instant, timezone-aware, and two releases of one acquisition retain their own rather than sharing one

#### Scenario: A partition's release established no instant
- **WHEN** a partition is attached for a complete logical release identity whose evidence established no source as-of instant
- **THEN** the attachment records a partition carrying absence, and acquisition, observation, and clock instants are not substituted

#### Scenario: The durable home is examined for a migration
- **WHEN** the queryable index is examined for what persists release-level source freshness
- **THEN** its future relational representation is required to retain acquisition reference, all four release identity components, and partition evidence including nullable source-as-of, rather than adding only freshness to the existing three-part Bronze grain or rewriting an existing migration

#### Scenario: An artifact is acquired before anything is known about its releases
- **WHEN** an artifact is acquired from a source whose release facts live only in its content
- **THEN** its acquisition manifest is recorded carrying the jurisdiction and no partition, and a reference to it is returned

#### Scenario: Inspection fails before any release is established
- **WHEN** archive or schema inspection fails before a tax year or release kind is established
- **THEN** the acquired bytes still have a recorded acquisition manifest, and no partition is invented to produce one

#### Scenario: A release established by parsing is attached
- **WHEN** parsing promotes complete identity for a logical release of an already-recorded acquisition
- **THEN** its source partition may remain associated with the artifact in the object store while its partition evidence is explicitly attached to the acquisition reference and complete release identity in the queryable index, and the recorded acquisition manifest is unaltered

#### Scenario: Registration sees a manifest partition before identity promotion
- **WHEN** an acquisition manifest already carries a three-part Bronze partition and the acquisition is registered
- **THEN** no complete release attachment is manufactured, and a lookup for a matching three-component release remains absent until the caller explicitly attaches a promoted `ReleaseIdentity`

#### Scenario: An acquisition manifest is written to durable storage
- **WHEN** an acquisition manifest carrying no partition is written
- **THEN** the written record carries the jurisdiction, so the county is recoverable without a partition to read it from

#### Scenario: A consumer identifies the manifest shape
- **WHEN** a written manifest is inspected
- **THEN** its pinned version distinguishes the shape carrying an explicit jurisdiction and possibly no partition from the earlier shape whose county was recoverable only from a non-empty partition tuple

#### Scenario: A partition disagrees with its acquisition
- **WHEN** a partition naming a different jurisdiction than its acquisition manifest is offered to object-store manifest construction
- **THEN** it is refused

#### Scenario: A Bronze partition is examined for canonical identity
- **WHEN** a source partition is inspected before its release identifier has been established
- **THEN** its three overlapping components remain Bronze evidence, and it cannot be promoted or treated as complete release identity without the single explicit promotion seam

### Requirement: A manifest reference is produced by manifest persistence
The system SHALL provide an application-owned reference identifying a recorded acquisition manifest, produced where that manifest is recorded, and SHALL NOT require a caller to derive it from an object-store locator, a checksum, or any other evidence.

Recording the same acquisition again SHALL yield the same reference, so that several logical releases carried by one artifact bind their runs to one acquisition rather than to duplicates of it. The reference SHALL be an opaque locator on the same terms as any other persistence-generated handle.

The queryable index SHALL attach partition evidence through this exact application operation:

```python
def attach_partition(
    self,
    reference: ManifestRef,
    release: ReleaseIdentity,
    partition: ReleasePartition,
) -> None: ...
```

The key of that attachment SHALL be exactly `(ManifestRef, ReleaseIdentity)`. The reference selects the recorded acquisition; the complete identity selects one canonical logical release of that acquisition; the partition carries the overlapping Bronze/source evidence and optional source-as-of instant. Neither the manifest reference nor the release identity SHALL be treated as identifying the other.

Before an attachment is recorded, all three overlapping components SHALL agree: `release.jurisdiction.rendered` with `partition.jurisdiction_code`, `release.tax_year` with `partition.tax_year`, and `release.release_kind.value` with `partition.release_kind`. Any disagreement SHALL be refused before stored state changes. Agreement SHALL NOT infer the release identifier; the explicit `ReleaseIdentity` is its only source.

Attaching the same reference, complete identity, and equal partition evidence again SHALL be idempotent and SHALL NOT create another attachment. Offering different partition evidence for an already-attached `(ManifestRef, ReleaseIdentity)` SHALL raise `ManifestAttachmentConflictError`, SHALL NOT overwrite the first evidence, and SHALL leave the attachment unchanged. Last-write-wins release evidence SHALL NOT be permitted.

**The index SHALL offer a read path for what it recorded, not only writes.** Given a manifest reference and a complete logical release identity, it SHALL return the partition evidence recorded for exactly that pair — the source as-of instant among it — or state that no attachment exists for that full identity:

```python
def partition_for(
    self,
    reference: ManifestRef,
    release: ReleaseIdentity,
) -> ReleasePartition | None: ...
```

The lookup SHALL be acquisition-scoped and SHALL take the reference rather than any locator, checksum, or storage path, so a caller never reconstructs an identity it was handed. It SHALL NOT reduce the release identity to jurisdiction, year, and kind. Two releases differing only by release identifier SHALL remain independently attachable and independently readable under the same manifest reference.

The read SHALL distinguish *no attachment for that full release identity* from *a partition attached for it that established no instant*: the first returns no partition; the second returns a partition whose `source_as_of` is absent. Those facts differ because one means the release is not indexed under this acquisition and the other means the indexed release established no freshness.

Reading SHALL change nothing. The index remains the queryable counterpart of the object-store record, and this operation SHALL NOT be a second way to write one. Registration SHALL record the acquisition and return its opaque reference, but SHALL NOT attach any full release identity from the manifest's three-part partition tuple.

#### Scenario: Recorded freshness is read back for a release
- **WHEN** a caller holding a manifest reference asks for the partition evidence of one complete logical release identity of that acquisition
- **THEN** it receives the evidence recorded for exactly that full identity, the source as-of instant included, without a candidate in memory and without reading the source page

#### Scenario: A release was never attached to that acquisition
- **WHEN** the lookup names a complete logical release identity for which no attachment was recorded under that manifest reference
- **THEN** it returns no partition, distinguishably from a partition that was attached and established no instant

#### Scenario: Release identifiers at one three-part grain do not alias
- **WHEN** identities `A` and `B` differ only by release identifier and each is attached under one manifest reference to partition evidence with equal jurisdiction, year, and kind
- **THEN** both attachments are retained, and each lookup returns only the partition attached to that complete identity

#### Scenario: A different release identifier was never attached
- **WHEN** identity `A` is attached and a lookup names identity `B` that differs only by release identifier
- **THEN** the lookup returns no attachment and never returns `A`'s partition

#### Scenario: Two releases retain distinct freshness
- **WHEN** identities `A` and `B` under one manifest reference are attached with distinct source-as-of instants
- **THEN** each full-identity lookup returns its own instant

#### Scenario: Attached freshness absence differs from missing attachment
- **WHEN** identity `A` is attached to a partition whose source-as-of is absent and identity `B` is not attached
- **THEN** lookup of `A` returns its partition carrying absence while lookup of `B` returns no partition

#### Scenario: Overlapping partition evidence disagrees with release identity
- **WHEN** jurisdiction, tax year, or release kind differs between the explicit release identity and partition in turn
- **THEN** each attachment is refused before queryable index state changes, and no release identifier is inferred from the partition

#### Scenario: An exact attachment is retried
- **WHEN** the same manifest reference, complete release identity, and equal partition evidence are attached again
- **THEN** the operation is a no-op and attachment cardinality is unchanged

#### Scenario: An attachment retry conflicts with immutable evidence
- **WHEN** one manifest reference and complete release identity are offered partition evidence different from what was first recorded
- **THEN** `ManifestAttachmentConflictError` is raised, the original partition remains readable, and no last-write-wins update occurs

#### Scenario: Registration does not invent a complete release attachment
- **WHEN** an acquisition manifest carrying a three-part partition is registered and no explicit attachment has occurred
- **THEN** a lookup by any matching complete release identity returns no attachment because registration has no release identifier to supply

#### Scenario: The read path is examined for writes
- **WHEN** the lookup is examined
- **THEN** it changes nothing it reads, and it is not a second way to record or attach

#### Scenario: A manifest is recorded and referenced
- **WHEN** an acquisition manifest is recorded
- **THEN** a reference to it is returned, and no caller derives that reference from a storage locator or a checksum

#### Scenario: One artifact carries two releases
- **WHEN** two processing runs handle two complete logical release identities carried by one acquisition
- **THEN** both bind to the same manifest reference while the queryable evidence remains separate by complete release identity

#### Scenario: The same acquisition is recorded again
- **WHEN** an acquisition already recorded is recorded again
- **THEN** the same reference is returned and no duplicate acquisition is created
