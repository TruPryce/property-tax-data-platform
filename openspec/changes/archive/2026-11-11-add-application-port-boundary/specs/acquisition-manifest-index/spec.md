## ADDED Requirements

<!-- Owns: the retained `ArtifactSink` and `BronzeStore` contracts; the
     bounded `ReleaseManifest` corrections (explicit jurisdiction, admissible
     empty partitions, shape version); acquisition equivalence and the
     acquisition-grain storage contract; `ManifestIndex` and `ManifestRef`.
     Cites: `application-port-boundary` for the opaque-locator rule;
     `source-registry-and-discovery` for the `LogicalReleaseEvidence` a
     `ReleasePartition` is derived from. -->

### Requirement: Existing artifact and manifest contracts are retained
The streaming artifact contract SHALL be retained unchanged, and the manifest contract SHALL retain its current operations and their behaviour. The manifest *value* takes the bounded corrections this capability specifies — an explicit jurisdiction, an admissible empty partition tuple, and a serialized shape version distinguishing it from the earlier one — and no manifest operation is added, removed, or re-signed. The distinction between streaming bytes and a durable object, between an artifact and a manifest, between one artifact and one or more logical release partitions, and between a read-time conflict classification and a persisted verdict SHALL be preserved.

No general-purpose object-store create/read/update/delete port SHALL be introduced.

#### Scenario: An acquisition is written and committed
- **WHEN** acquired bytes are written in chunks and committed
- **THEN** the artifact becomes durable only at commit, and an aborted acquisition leaves no partial object

#### Scenario: A repeat checksum is judged
- **WHEN** a checksum is classified against a release partition
- **THEN** the classification is returned to the caller and is not persisted as a verdict

### Requirement: An acquisition is manifested before its releases are known
Every successfully acquired artifact SHALL have its acquisition manifested, whether or not any logical release has yet been established. An acquisition manifest SHALL therefore be recordable carrying no release partition, and SHALL carry the jurisdiction explicitly rather than deriving it from partitions it may not have.

A release partition established later SHALL be attachable without altering the immutable acquisition record. The two stores associate it at deliberately different grains: the object store associates a partition with the **artifact**, whose identity is content alone, while the queryable index associates it with the **acquisition** the run binds to. The contract SHALL keep those distinct rather than describing them as one association. Where partitions are present, each SHALL name the same jurisdiction the manifest names.

**A partition SHALL carry the source as-of instant established for its logical release, where one
was established, timezone-aware.** A partition is one logical release of one acquisition, which is
exactly the grain the instant belongs to, and the manifest is already immutable and already
retrievable from the reference a run is started with. Recording it here is what lets a publication
resuming in a later process state the freshness of what it exposes without a candidate in memory.

This SHALL require no migration: the instant rides in the manifest the object store holds, whose
shape this change is already versioning, and no relational column is added for it. An
implementation MAY index it later; the contract fixes where the fact is recorded and that it is
retrievable, not how it is looked up.

Where no instant was established for a logical release, its partition SHALL record absence, and the
acquisition instant SHALL NOT be substituted — the same rule the evidence follows, for the same
reason: an acquisition time says when bytes were fetched, not what the release was current as of.

No partition SHALL be fabricated to make an acquisition recordable, and an artifact that fails inspection before any release is established SHALL still have a durable record of what was acquired.

#### Scenario: A partition records the freshness of its own release
- **WHEN** a partition is attached for a logical release whose evidence established a source as-of instant
- **THEN** the partition records that instant, timezone-aware, and two partitions of one acquisition record their own rather than sharing one

#### Scenario: A partition's release established no instant
- **WHEN** a partition is attached for a logical release whose evidence established no source as-of instant
- **THEN** the partition records absence, and the acquisition instant is not substituted, because when bytes were fetched is not what the release was current as of

#### Scenario: The durable home is examined for a migration
- **WHEN** the change is examined for what persists this instant
- **THEN** it rides in the manifest the object store already holds, whose shape this change is already versioning, and no relational column and no migration is added for it

#### Scenario: An artifact is acquired before anything is known about its releases
- **WHEN** an artifact is acquired from a source whose release facts live only in its content
- **THEN** its acquisition manifest is recorded carrying the jurisdiction and no partition, and a reference to it is returned

#### Scenario: Inspection fails before any release is established
- **WHEN** archive or schema inspection fails before a tax year or release kind is established
- **THEN** the acquired bytes still have a recorded acquisition manifest, and no partition is invented to produce one

#### Scenario: A release established by parsing is attached
- **WHEN** parsing establishes a logical release for an already-recorded acquisition
- **THEN** its partition is associated with the artifact in the object store and with the acquisition in the queryable index, and the recorded acquisition manifest is unaltered

#### Scenario: An acquisition manifest is written to durable storage
- **WHEN** an acquisition manifest carrying no partition is written
- **THEN** the written record carries the jurisdiction, so the county is recoverable without a partition to read it from

#### Scenario: A consumer identifies the manifest shape
- **WHEN** a written manifest is inspected
- **THEN** its pinned version distinguishes the shape carrying an explicit jurisdiction and possibly no partition from the earlier shape whose county was recoverable only from a non-empty partition tuple

#### Scenario: A partition disagrees with its acquisition
- **WHEN** a partition naming a different jurisdiction than its acquisition manifest is offered
- **THEN** it is refused

### Requirement: An acquisition manifest is stored at acquisition grain
An acquisition manifest SHALL be stored so that it is identified by the acquisition it records, not by the artifact that acquisition obtained. Artifact identity is content alone, and the same bytes may legitimately be acquired from different jurisdictions, different source locations, and at different instants; storing one manifest per artifact would let the first such acquisition silently discard the provenance of every later one.

Two recordings SHALL be the same acquisition exactly when their retained acquisition evidence is equal. That evidence is the jurisdiction, the artifact content identity, the acquisition instant, the source location, the response metadata, the redirect chain, the serialized shape version, and the recorded tool versions. The partition tuple SHALL be excluded, because partitions are attached after an acquisition is recorded and including them would make an acquisition look new merely for having gained one.

The artifact SHALL take part in that comparison by its content identity alone. The storage locator, byte count, and media type SHALL NOT be acquisition-defining: each is artifact-grain evidence — the locator is where the bytes were stored, the byte count is integrity evidence about them, and the media type is metadata describing them — and each is recorded once per artifact rather than once per acquisition. Two recordings agreeing on every acquisition-defining component SHALL therefore remain one acquisition even where such artifact evidence differs between them, and that difference SHALL be treated as an artifact-consistency concern rather than as a second acquisition identity.

This rule SHALL be evaluated on the immutable manifest value alone. It SHALL NOT depend on a storage locator, an object key, a lock, a digest choice, a query, or any other adapter mechanism, and no acquisition identifier separate from that value SHALL be required. Every acquisition-defining component SHALL be one already retained at acquisition grain, so that a recorded acquisition can be recognised again from what was persisted rather than from state held elsewhere.

Recordings whose retained evidence differs SHALL be different acquisitions even where the artifact content is byte-identical. Artifact identity SHALL remain the content digest alone, so two such acquisitions SHALL name one artifact and two acquisitions.

Where two physical fetches produce identical retained evidence in every compared component, they SHALL be observationally equivalent and MAY coalesce into one acquisition. The model carries no independent physical-attempt identifier, and this contract SHALL NOT claim that a repeated fetch necessarily yields a distinct acquisition: a fixed or finite-resolution clock and an unchanged response can make two fetches indistinguishable in the evidence retained. This change SHALL NOT introduce an acquisition identifier, a schema migration, or a persistence column to distinguish them.

The storage contract SHALL therefore hold: recording the same acquisition again SHALL resolve to the same manifest, so a retry writes no duplicate; recording a different acquisition of the same artifact SHALL resolve to a different manifest, so neither displaces the other; and an already-recorded manifest SHALL NOT be overwritten.

A manifest already recorded in an earlier serialized shape SHALL remain immutable and SHALL NOT prevent a later acquisition of the same artifact from being recorded in the current shape. The artifact bytes themselves SHALL remain content-addressed, since artifact identity is unchanged by any of this.

The mechanism that satisfies these properties is an implementation decision and SHALL NOT be fixed by the port contract.

#### Scenario: One artifact is acquired by two jurisdictions
- **WHEN** the same bytes are acquired for two different jurisdictions from two different sources
- **THEN** two acquisition manifests are recorded, neither displacing the other, and both jurisdictions remain recoverable

#### Scenario: Registration of one completed acquisition is retried
- **WHEN** the same completed acquisition is registered again, carrying the same acquisition manifest value
- **THEN** it resolves to the manifest already stored, the same reference is returned, and no duplicate is written

#### Scenario: The same bytes are acquired again with differing evidence
- **WHEN** the source is fetched again, returns byte-identical content, and any component of the retained acquisition evidence differs
- **THEN** they are two acquisitions of one artifact and both are recorded, neither displacing the other

#### Scenario: Two fetches leave identical evidence
- **WHEN** two physical fetches produce retained acquisition evidence identical in every compared component
- **THEN** they are observationally equivalent and may coalesce, because nothing retained distinguishes them and no physical-attempt identifier exists

#### Scenario: Only artifact-grain evidence differs
- **WHEN** two recordings agree on every acquisition-defining component and differ only in storage locator, byte count, or media type
- **THEN** they remain one acquisition, and the difference is an artifact-consistency concern rather than a second acquisition identity

#### Scenario: A retry is distinguished from a re-acquisition without consulting storage
- **WHEN** two acquisition manifests are compared
- **THEN** whether they describe one acquisition is decided from the manifest values alone, with no locator, key, lock, or query consulted

#### Scenario: A partition is attached and the acquisition is registered again
- **WHEN** an acquisition that has since gained a partition is registered again
- **THEN** it is still the same acquisition, because partitions take no part in the comparison

#### Scenario: Each acquisition-defining component is mutated in turn
- **WHEN** exactly one declared acquisition-defining component is changed and every other is held equal
- **THEN** the recordings are different acquisitions, for every such component in turn

#### Scenario: Every acquisition-defining component has a retained home
- **WHEN** the declared components are compared against what is retained at acquisition grain
- **THEN** each one is already persisted there, so recognising a recorded acquisition requires no additional column and no state outside that record

#### Scenario: An artifact already carries a manifest in the earlier shape
- **WHEN** an artifact whose stored manifest predates the current shape is acquired again
- **THEN** the earlier manifest is left untouched and the new acquisition is still recorded in the current shape

#### Scenario: Artifact storage is examined
- **WHEN** the stored artifact bytes are examined
- **THEN** they remain identified by content alone, unaffected by how many acquisitions reference them

### Requirement: A manifest reference is produced by manifest persistence
The system SHALL provide an application-owned reference identifying a recorded acquisition manifest, produced where that manifest is recorded, and SHALL NOT require a caller to derive it from an object-store locator, a checksum, or any other evidence.

Recording the same acquisition again SHALL yield the same reference, so that several logical releases carried by one artifact bind their runs to one acquisition rather than to duplicates of it. The reference SHALL be an opaque locator on the same terms as any other persistence-generated handle.

**The index SHALL offer a read path for what it recorded, not only writes.** Given a manifest
reference and a logical release, it SHALL return the partition evidence recorded for that release —
the source as-of instant among it — or state that no partition was attached for it. Without this
the instant has a durable *location* and no boundary able to retrieve it, and a publication
resuming with only the run's reference would have to record absence or rediscover a mutable page:
exactly the two outcomes recording it was meant to prevent.

The lookup SHALL be acquisition-scoped and SHALL take the reference rather than any locator,
checksum, or storage path, so a caller never reconstructs an identity it was handed. It SHALL
distinguish *no partition attached for that release* from *a partition attached that established no
instant*, because those are different facts and a publication records them differently: the first
means the release is not part of this acquisition, the second that the source established no
freshness. Returning `None` for both would make a missing attachment look like a source that said
nothing.

Reading SHALL change nothing. The index remains the relational counterpart of the object-store
record, and this operation SHALL NOT be a second way to write one.

#### Scenario: Recorded freshness is read back for a release
- **WHEN** a caller holding a manifest reference asks for the partition evidence of one logical release of that acquisition
- **THEN** it receives the evidence recorded for that release, the source as-of instant included, without a candidate in memory and without reading the source page

#### Scenario: A release was never attached to that acquisition
- **WHEN** the lookup names a logical release for which no partition was attached
- **THEN** it says so, distinguishably from a partition that was attached and established no instant, because a release that is not part of the acquisition and a source that published no freshness are different facts

#### Scenario: The read path is examined for writes
- **WHEN** the lookup is examined
- **THEN** it changes nothing it reads, and it is not a second way to record or attach

#### Scenario: A manifest is recorded and referenced
- **WHEN** an acquisition manifest is recorded
- **THEN** a reference to it is returned, and no caller derives that reference from a storage locator or a checksum

#### Scenario: One artifact carries two releases
- **WHEN** two runs process two logical releases carried by one artifact
- **THEN** both bind to the same manifest reference

#### Scenario: The same acquisition is recorded again
- **WHEN** an acquisition already recorded is recorded again
- **THEN** the same reference is returned and no duplicate acquisition is created
