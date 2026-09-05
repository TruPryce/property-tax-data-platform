## ADDED Requirements

### Requirement: The application owns the port boundary and depends on no infrastructure
The application package SHALL own every port the ingestion, persistence, quality, publication, and time responsibilities are coordinated through, expressed as Protocols together with the value types that cross them. No public port contract SHALL name an object-store SDK type, a database driver type, a connection, a cursor, a SQL transaction, a database schema or table name, a bulk-load mechanism, a conflict clause, an orchestrator type, or a county implementation.

The application package SHALL remain importable and its ports constructible without any of those dependencies installed.

#### Scenario: A port contract is inspected for infrastructure vocabulary
- **WHEN** the public surface of any application port is examined
- **THEN** it names only domain types, application-owned value types, and standard-library types

#### Scenario: The application is imported in isolation
- **WHEN** the application package is imported with no object-store SDK, database driver, or orchestrator available
- **THEN** the import succeeds and every port remains usable as a type

### Requirement: Source resolution fails before network acquisition and describes expected media
Source resolution SHALL resolve a jurisdiction to its registered source definition without performing network access, and SHALL fail with a named, actionable error where the jurisdiction is not registered.

A requested release kind SHALL be optional. Where a caller supplies one, resolution SHALL reject an unregistered kind before any network acquisition. Where a caller cannot supply one — because the source establishes its release kinds only in acquired content — resolution SHALL succeed on the jurisdiction alone rather than requiring the caller to name a kind it has not yet learned.

The system SHALL additionally provide validation of a release kind once it is known, and a kind established only by parsing SHALL be validated after parsing and before promotion. Rejecting such a kind before network acquisition is not possible, and the boundary SHALL NOT require a caller to invent one to proceed.

A resolved definition SHALL describe the expected media types of the source, and SHALL NOT carry a credential or a secret value.

#### Scenario: A registered jurisdiction is resolved without a kind
- **WHEN** a caller resolves a registered jurisdiction without naming a release kind
- **THEN** its source definition is returned and no network access is performed

#### Scenario: An unregistered jurisdiction is requested
- **WHEN** a caller requests a jurisdiction that is not registered
- **THEN** resolution fails before network acquisition with a named error identifying what was requested

#### Scenario: An unregistered release kind is requested
- **WHEN** a caller requests a registered jurisdiction together with a release kind that is not registered for it
- **THEN** resolution fails before network acquisition with a named error

#### Scenario: A release kind is established only by content
- **WHEN** a source's release kinds are established only in acquired content
- **THEN** the jurisdiction resolves without one, and the kind is validated after parsing establishes it and before promotion

#### Scenario: A resolved definition is inspected
- **WHEN** a source definition is resolved
- **THEN** it describes the expected media types of the source and carries no credential

### Requirement: Discovery carries bounded evidence and distinguishes a new release from an unchanged one
Release discovery SHALL return, for each observed source, either a source candidate or a no-change result. A source candidate SHALL carry the jurisdiction, the source locator, the remote metadata, the source as-of evidence, and the page evidence the source published. A no-change result SHALL be returned where remote metadata and content identity match a release already acquired, and SHALL NOT require the artifact to be downloaded again.

Discovery SHALL NOT be required to establish a tax year or a release kind. Where the publisher's page establishes those facts, the source candidate SHALL carry the resulting logical release evidence, one entry per logical release; where they are established only by verified source content, the candidate SHALL carry none and that evidence SHALL be produced during parsing instead. One source candidate SHALL therefore be able to yield several logical releases backed by one artifact.

Every evidence carrier SHALL be bounded. Discovery SHALL NOT return credentials, arbitrary source content, or an unbounded payload, and SHALL NOT perform county parsing or county field mapping.

#### Scenario: A new release is observed
- **WHEN** discovery observes a release not already acquired
- **THEN** a candidate is returned carrying its locator, remote metadata, source as-of evidence, and page evidence, and carrying no credential and no source row

#### Scenario: An unchanged release is observed
- **WHEN** remote metadata and content identity match a release already acquired successfully
- **THEN** a no-change result is returned, distinguishable from a candidate, and no download is required

#### Scenario: A source establishes only partial release facts
- **WHEN** the source's page establishes a jurisdiction, tax year, and release kind but no release identifier
- **THEN** the evidence records exactly what was established and does not manufacture the missing component

#### Scenario: Release facts live only in source content
- **WHEN** a publisher offers one mutable export whose tax years and release kinds appear only in its content
- **THEN** discovery returns one source candidate carrying no logical release evidence, and is not required to invent a tax year or a release kind

#### Scenario: One artifact carries two logical releases
- **WHEN** parsing an acquired artifact establishes a current release for one tax year and a certified release for another
- **THEN** two logical release evidences are produced from that one artifact, and neither requires re-acquiring it

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

No partition SHALL be fabricated to make an acquisition recordable, and an artifact that fails inspection before any release is established SHALL still have a durable record of what was acquired.

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

Two recordings SHALL be the same acquisition exactly when their retained acquisition evidence is equal. That evidence is the jurisdiction, the complete stored-artifact evidence, the acquisition instant, the source location, the response metadata, the redirect chain, the serialized shape version, and the recorded tool versions. The partition tuple SHALL be excluded, because partitions are attached after an acquisition is recorded and including them would make an acquisition look new merely for having gained one.

The stored-artifact evidence SHALL be compared in full — its locator, content digest, byte count, and media type — and not by content digest alone. Byte identity alone SHALL NOT collapse two recordings whose remaining retained evidence differs.

This rule SHALL be evaluated on the immutable manifest value alone. It SHALL NOT depend on a storage locator, an object key, a lock, a digest choice, a query, or any other adapter mechanism, and no acquisition identifier separate from that value SHALL be required.

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

#### Scenario: Only the media type differs
- **WHEN** two recordings carry the same content digest but differing stored-artifact evidence
- **THEN** they are different acquisitions, because byte identity alone does not collapse differing evidence

#### Scenario: A retry is distinguished from a re-acquisition without consulting storage
- **WHEN** two acquisition manifests are compared
- **THEN** whether they describe one acquisition is decided from the manifest values alone, with no locator, key, lock, or query consulted

#### Scenario: A partition is attached and the acquisition is registered again
- **WHEN** an acquisition that has since gained a partition is registered again
- **THEN** it is still the same acquisition, because partitions take no part in the comparison

#### Scenario: Each acquisition-defining component is mutated in turn
- **WHEN** exactly one declared acquisition-defining component is changed and every other is held equal
- **THEN** the recordings are different acquisitions, for every such component in turn

#### Scenario: An artifact already carries a manifest in the earlier shape
- **WHEN** an artifact whose stored manifest predates the current shape is acquired again
- **THEN** the earlier manifest is left untouched and the new acquisition is still recorded in the current shape

#### Scenario: Artifact storage is examined
- **WHEN** the stored artifact bytes are examined
- **THEN** they remain identified by content alone, unaffected by how many acquisitions reference them

### Requirement: A manifest reference is produced by manifest persistence
The system SHALL provide an application-owned reference identifying a recorded acquisition manifest, produced where that manifest is recorded, and SHALL NOT require a caller to derive it from an object-store locator, a checksum, or any other evidence.

Recording the same acquisition again SHALL yield the same reference, so that several logical releases carried by one artifact bind their runs to one acquisition rather than to duplicates of it. The reference SHALL be an opaque locator on the same terms as any other persistence-generated handle.

#### Scenario: A manifest is recorded and referenced
- **WHEN** an acquisition manifest is recorded
- **THEN** a reference to it is returned, and no caller derives that reference from a storage locator or a checksum

#### Scenario: One artifact carries two releases
- **WHEN** two runs process two logical releases carried by one artifact
- **THEN** both bind to the same manifest reference

#### Scenario: The same acquisition is recorded again
- **WHEN** an acquisition already recorded is recorded again
- **THEN** the same reference is returned and no duplicate acquisition is created

### Requirement: A processing run is created through the boundary
The system SHALL provide an application-owned contract that creates a processing run from the release identity and the manifest it will read, and returns the reference by which that run is named. A caller SHALL NOT be required to construct a run reference itself, because the value that identifies a run is generated where the run is recorded.

The contract SHALL also record that a run has finished.

#### Scenario: A run is started
- **WHEN** a use case begins processing a release it has acquired
- **THEN** it obtains a run reference from the boundary, and the reference identifies a run that has been recorded

#### Scenario: A run reference is required somewhere
- **WHEN** any port requiring a run reference is examined
- **THEN** it accepts the reference type and no raw persistence value in its place, so a caller is never required to invent one

#### Scenario: A reference that names no run is used
- **WHEN** a reference that does not resolve to a started run is passed to a port that requires one
- **THEN** the operation is refused rather than creating a run implicitly

### Requirement: Canonical release identity is promoted from evidence and fails closed
The system SHALL provide one promotion from logical release evidence to canonical release identity, and that promotion SHALL be the only place where an incomplete release becomes a complete one. That evidence SHALL be the single input to promotion whether it was established by the publisher's page during discovery or by verified source content during parsing, so there is one promotion seam rather than one per origin. Where fewer than all four canonical components were established, promotion SHALL fail with a named error naming what was missing.

Canonical release identity SHALL NOT be derived from a filename, a checksum, an acquisition instant, a source field name, a row ordering, or a persistence surrogate. The canonical persistence boundary SHALL accept only a complete canonical release identity, and SHALL NOT accept a Bronze release partition or a partition accompanied by a hint.

#### Scenario: Complete evidence is promoted
- **WHEN** logical release evidence whose four identity components are established is promoted
- **THEN** a canonical release identity is returned

#### Scenario: Evidence from parsing is promoted the same way
- **WHEN** logical release evidence established by source content rather than by a page is promoted
- **THEN** it passes through the same promotion and yields a canonical release identity on the same terms

#### Scenario: A release identifier was never established
- **WHEN** logical release evidence lacking a release identifier is promoted
- **THEN** promotion fails with a named error and no identifier is synthesised

#### Scenario: A Bronze partition is offered as canonical identity
- **WHEN** a caller offers a three-component Bronze release partition where canonical identity is required
- **THEN** the contract does not accept it

### Requirement: A canonical load is a bounded session with release-atomic completion
The canonical persistence boundary SHALL expose one logical release load as a session accepting successive bounded batches of canonical records, followed by exactly one completion or one abort. It SHALL NOT require a complete release to be held in memory, and it SHALL NOT make any batch durable before completion.

A session that aborts, or whose completion fails, SHALL leave zero canonical records for that load.

#### Scenario: A release is loaded in batches
- **WHEN** a caller writes several bounded batches and then completes the session
- **THEN** the records become durable together at completion and not before

#### Scenario: A load is abandoned partway
- **WHEN** a caller aborts after writing several batches
- **THEN** zero canonical records exist for that load

#### Scenario: A whole release is not materialised
- **WHEN** the session contract is examined
- **THEN** no operation requires a complete release as a single in-memory collection

### Requirement: Parent linkage is resolved by bounded, account-scoped correlation
The canonical persistence boundary SHALL allow one account's records to span more than one bounded batch, and SHALL provide a correlation mechanism by which a record names a parent written in an earlier batch.

That correlation SHALL be carried by the batch rather than by the canonical records, which hold their parents directly and SHALL NOT gain a correlation field. A batch entry SHALL pair one canonical record with the correlation value it can later be named by, where it may be a parent, and with the correlation value of its parent. A parent SHALL be named the same way whether it appears in the same batch or an earlier one, so there is one linkage mechanism rather than two.

A correlation value SHALL be unique within one load session. It SHALL be neither domain identity nor persistence identity, SHALL carry no meaning outside the session, and SHALL NOT appear in any persisted record as a business value. An implementation SHALL retain a mapping only for values still needed as parents, releasing those whose account is complete.

Validation authority SHALL be split according to what each party can know. A batch is an immutable value and knows only itself, so it SHALL validate its own shape alone: well-formed entries, no value introduced twice within it, parents named within it resolving within it, and at most one account named as continuing. Everything requiring session history SHALL be validated by the session on write and on account completion — whether a value duplicates one already live, whether a named parent was ever introduced, whether its account has since completed, and whether the continuing-account state is consistent with the previous batch. A batch SHALL NOT be required to know handles opened by earlier batches or accounts already completed, because it cannot.

Every account a batch introduces SHALL be complete at the end of that batch, except at most one, which the batch SHALL name as continuing into the next. An implementation SHALL therefore retain, beyond a single bounded batch, only the correlation values of one continuing account, and only for records actually named as parents. Correlation SHALL NOT require memory proportional to the release, to the number of accounts in it, or to a continuing account's complete descent.

A correlation value that duplicates one already live, that names a parent never introduced, or that names one whose account is complete, SHALL be refused by the session.

#### Scenario: A record is paired with its correlation
- **WHEN** a batch entry is examined
- **THEN** it pairs the canonical record with the value it may be named by and the value naming its parent, and the canonical record itself carries no correlation field

#### Scenario: One account spans several batches
- **WHEN** an account's owners are written in one batch and its allocations in a later batch of the same account
- **THEN** the later records name their parents by the values the earlier batch introduced

#### Scenario: A batch leaves two accounts incomplete
- **WHEN** a batch would leave more than one account continuing into the next
- **THEN** it is refused, so at most one account is ever open across a batch boundary

#### Scenario: A duplicate correlation value is introduced
- **WHEN** a batch introduces a correlation value already live in the session
- **THEN** the session refuses the write

#### Scenario: A batch is validated on its own
- **WHEN** a batch is constructed
- **THEN** it rejects only what it can see — a value introduced twice within it, a parent named within it that resolves nowhere in it, or more than one account named as continuing — and does not attempt to judge handles from earlier batches

#### Scenario: A batch names a parent from an earlier batch
- **WHEN** a batch names a parent it does not itself contain
- **THEN** the batch accepts it as well-formed, and the session decides whether that parent is live

#### Scenario: An account with very many children is loaded
- **WHEN** an account carries far more children than one batch should hold
- **THEN** it is written across several bounded batches, and neither the caller nor the implementation is required to hold the whole account

#### Scenario: A correlation value outlives its account
- **WHEN** a record names a correlation value whose account has been declared complete
- **THEN** the write is refused

#### Scenario: Correlation state is examined for growth
- **WHEN** the boundary is examined
- **THEN** nothing requires an implementation to retain correlation beyond one bounded batch except for the single continuing account, so the state grows with neither the release nor the number of accounts in it

### Requirement: The processing outcome and the canonical load complete as one unit of work
The canonical load session SHALL own the relationship between the processing run, its accepted or rejected outcome with bounded diagnostics and notices, and the canonical load, such that the outcome and the load become durable together at one completion point.

The boundary SHALL NOT require an implementation to make the accepted outcome durable in one unit of work and the canonical load in another.

#### Scenario: An accepted release is completed
- **WHEN** a session carrying an accepted outcome is completed
- **THEN** the outcome and the canonical load become durable together

#### Scenario: A rejected release is completed
- **WHEN** a run's outcome is rejected
- **THEN** the outcome is recorded and zero canonical records are committed for that release

#### Scenario: The contract is examined for independent commits
- **WHEN** the boundary is examined
- **THEN** no arrangement of its operations requires the outcome and the load to be committed separately

### Requirement: The outcome crossing the boundary is a lossless representation
The processing outcome the boundary accepts SHALL carry every fact the accepted outcome record requires: the disposition, the boundary contract version, the parser contract version and layout fingerprint where the release was prepared, the processed, staged, committed, and rejected counts, and the bounded diagnostics and notices with their totals and truncation flags.

A diagnostic code SHALL be one the accepted closed vocabulary admits. A notice code SHALL NOT be closed to that vocabulary; it SHALL satisfy the bounded lowercase identifier grammar the accepted notice contract admits. Either way a value valid at this boundary SHALL be a value that can be recorded.

An implementation SHALL be able to record the accepted outcome from this value alone, without obtaining any of those facts from outside the boundary. The paired invariants the accepted record enforces SHALL be enforced here, so a violation is refused at the boundary rather than at commit.

#### Scenario: A prepared release reports its parser evidence
- **WHEN** an outcome describes a release whose layout was prepared
- **THEN** it carries both the parser contract version and the layout fingerprint

#### Scenario: One prepared field is supplied without the other
- **WHEN** an outcome carries a parser contract version without a layout fingerprint, or the reverse
- **THEN** the outcome is refused

#### Scenario: An implementation records the outcome
- **WHEN** an implementation records the accepted outcome from the value the boundary supplied
- **THEN** every required fact is present and none is obtained from elsewhere

#### Scenario: A diagnostic carries a code outside the accepted vocabulary
- **WHEN** an outcome carries a diagnostic whose code is not one the accepted vocabulary admits
- **THEN** the outcome is refused at the boundary, rather than accepted here and rejected when written

#### Scenario: A notice carries a code outside the closed diagnostic vocabulary
- **WHEN** an outcome carries a notice whose code is a well-formed bounded lowercase identifier that the diagnostic vocabulary does not contain
- **THEN** the outcome is accepted, because the notice vocabulary is open where the diagnostic vocabulary is closed

#### Scenario: A notice carries a malformed code
- **WHEN** an outcome carries a notice whose code does not satisfy the bounded lowercase identifier grammar
- **THEN** the outcome is refused

### Requirement: Retry is scoped to one release and one processing run
The retry key SHALL be the pairing of a canonical release with the processing run that loaded it. Completing a load for a pairing that has already completed SHALL persist nothing further and SHALL return a bounded, machine-readable result stating that the load had already happened, rather than raising an error the caller must interpret.

Two distinct processing runs loading one canonical release SHALL be two loads, and the second SHALL NOT be treated as a retry of the first.

#### Scenario: A completed load is retried
- **WHEN** a load is completed again for the same release and the same run
- **THEN** the result reports that the load was already complete and nothing further is persisted

#### Scenario: A release is reprocessed by a second run
- **WHEN** a second processing run loads a release a first run already loaded
- **THEN** the result reports a new load rather than an already-complete one, and both loads are retained

#### Scenario: The retry key is inspected
- **WHEN** the retry key is examined
- **THEN** it is composed of a release and a run and of no observed value

### Requirement: The boundary defines no key over observed values
The canonical persistence boundary SHALL NOT define a natural key, a uniqueness rule, or a deduplication rule over observed canonical values. Submitting records that the canonical model admits SHALL NOT cause the boundary to discard, merge, or reject them on the basis of their values.

#### Scenario: Divergent evidence is submitted at one grain
- **WHEN** several account snapshots are submitted at one account and release grain, differing in provenance or in situs or legal description
- **THEN** all are accepted and retained, and none is treated as a duplicate of another

#### Scenario: Several children of one parent are submitted
- **WHEN** several children of an accepted one-to-many type, or several geometries, are submitted for one parent
- **THEN** all are accepted and none is collapsed

#### Scenario: Children arrive from another load of the same release
- **WHEN** children are submitted by a second load of the same logical release
- **THEN** they are retained alongside the first load's records

### Requirement: Persistence-generated handles are explicitly opaque locators
Where a persistence-generated handle crosses a port, the contract SHALL state that it is an opaque locator. Such a handle SHALL NOT be presented as canonical identity, SHALL NOT carry an ordering guarantee, and SHALL NOT be interpreted as a business fact.

#### Scenario: A run reference crosses a port
- **WHEN** a processing-run reference is passed between ports
- **THEN** its contract identifies it as an opaque locator rather than as identity

#### Scenario: Two run references are compared
- **WHEN** two run references are compared
- **THEN** the contract offers equality and no ordering, freshness, or precedence meaning

### Requirement: The quality boundary is run-bound and reuses the accepted model
The quality boundary SHALL read the configured rules, with their severity and thresholds, and SHALL record measured evaluations against the processing run that produced them. It SHALL NOT define a second quality model, SHALL NOT embed a county-specific threshold, and SHALL NOT require its consumer to express a rule in SQL or to name a stored relation.

A recorded failing evaluation SHALL carry the measured and expected values.

#### Scenario: Configured rules are evaluated
- **WHEN** a use case evaluates quality for a run
- **THEN** it obtains the configured rules and their severities through the port and contains no embedded threshold

#### Scenario: A failing evaluation is recorded
- **WHEN** a rule fails
- **THEN** the recorded evaluation carries its measured and expected values and is bound to the run

#### Scenario: The boundary is examined for a parallel model
- **WHEN** the quality boundary is examined
- **THEN** it records against the accepted rule and evaluation model rather than a second one

### Requirement: The publication boundary owns attempt, lineage, and activation
The publication boundary SHALL record a publication attempt, its lineage to the release and run it rests on, and its transition to current or to failed. Activation SHALL make the new publication current and record the publication it supersedes. A failed attempt SHALL NOT become current and SHALL NOT supersede the publication that is already current.

This boundary SHALL NOT construct the published product itself; the transaction that builds and promotes the published data is owned separately. The boundary SHALL NOT grant, imply, or require raw canonical read access, and SHALL NOT confer permission to publish a sensitive field, which the reviewed field policy continues to govern.

#### Scenario: An attempt fails
- **WHEN** a publication attempt fails
- **THEN** the previously current publication remains current and the failed attempt is not marked current

#### Scenario: An attempt is activated
- **WHEN** an attempt is activated
- **THEN** it becomes current and the publication it replaces is recorded as superseded

#### Scenario: The boundary is examined for scope
- **WHEN** the publication boundary is examined
- **THEN** it carries attempt, lineage, and activation, grants no canonical read privilege or sensitive-field permission, and does not claim to build the published product

### Requirement: One application-owned clock returns timezone-aware instants
The application SHALL own one time source, and every instant it returns SHALL be timezone-aware. A use case SHALL obtain the current instant through that port rather than by calling a wall-clock API directly, so that a use case can be exercised deterministically.

#### Scenario: The current instant is obtained
- **WHEN** a use case asks the clock for the current instant
- **THEN** it receives a timezone-aware instant

#### Scenario: A use case is exercised deterministically
- **WHEN** a test supplies a fixed time source
- **THEN** the use case observes the supplied instant and reads no wall clock
