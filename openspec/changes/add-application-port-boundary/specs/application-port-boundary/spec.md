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
The system SHALL resolve a supported county and release kind to a source definition without performing network acquisition, and SHALL represent an unregistered county or release kind as a named, actionable unsupported-source failure rather than an absent result or a generic error.

That definition SHALL carry the expected media types for the source, so acquisition can reject an unexpected representation without a county-specific branch in its caller.

#### Scenario: A registered source is resolved
- **WHEN** a run requests a registered county and release kind
- **THEN** a source definition carrying its endpoint, acquisition method, parser identifier, and expected media types is returned, and no network request has been made

#### Scenario: An unregistered source is requested
- **WHEN** a run requests a county or release kind the registry does not describe
- **THEN** a named unsupported-source failure is raised before acquisition, identifying what was requested

#### Scenario: A consumer resolves several counties
- **WHEN** a caller resolves sources for more than one county
- **THEN** it does so through one uniform call and contains no county-specific branch

### Requirement: Discovery carries bounded evidence and distinguishes a new release from an unchanged one
Release discovery SHALL return, for each observed release, either a candidate or a no-change result. A candidate SHALL carry the source locator, the remote metadata, the source as-of evidence, the page evidence the source published, and the release facts the source established. A no-change result SHALL be returned where remote metadata and content identity match a release already acquired, and SHALL NOT require the artifact to be downloaded again.

Every evidence carrier SHALL be bounded. Discovery SHALL NOT return credentials, arbitrary source content, or an unbounded payload, and SHALL NOT perform county parsing or county field mapping.

#### Scenario: A new release is observed
- **WHEN** discovery observes a release not already acquired
- **THEN** a candidate is returned carrying its locator, remote metadata, source as-of evidence, and page evidence, and carrying no credential and no source row

#### Scenario: An unchanged release is observed
- **WHEN** remote metadata and content identity match a release already acquired successfully
- **THEN** a no-change result is returned, distinguishable from a candidate, and no download is required

#### Scenario: A source establishes only partial release facts
- **WHEN** the source's evidence establishes a jurisdiction, tax year, and release kind but no release identifier
- **THEN** the candidate records exactly what was established and does not manufacture the missing component

### Requirement: Existing artifact and manifest contracts are retained
The streaming artifact contract and the manifest contract SHALL be retained with their current behaviour. The distinction between streaming bytes and a durable object, between an artifact and a manifest, between one artifact and one or more logical release partitions, and between a read-time conflict classification and a persisted verdict SHALL be preserved.

No general-purpose object-store create/read/update/delete port SHALL be introduced.

#### Scenario: An acquisition is written and committed
- **WHEN** acquired bytes are written in chunks and committed
- **THEN** the artifact becomes durable only at commit, and an aborted acquisition leaves no partial object

#### Scenario: A repeat checksum is judged
- **WHEN** a checksum is classified against a release partition
- **THEN** the classification is returned to the caller and is not persisted as a verdict

### Requirement: A processing run is created through the boundary
The system SHALL provide an application-owned contract that creates a processing run from the release identity and the manifest it will read, and returns the reference by which that run is named. A caller SHALL NOT be required to construct a run reference itself, because the value that identifies a run is generated where the run is recorded.

The contract SHALL also record that a run has finished.

#### Scenario: A run is started
- **WHEN** a use case begins processing a release it has acquired
- **THEN** it obtains a run reference from the boundary, and the reference identifies a run that has been recorded

#### Scenario: A caller attempts to name a run it did not start
- **WHEN** the boundary is examined
- **THEN** no operation accepts a caller-constructed run reference as a substitute for starting a run

### Requirement: Canonical release identity is promoted from evidence and fails closed
The system SHALL provide one promotion from discovered release facts to canonical release identity, and that promotion SHALL be the only place where an incomplete release becomes a complete one. Where the source established fewer than all four canonical components, promotion SHALL fail with a named error naming what was missing.

Canonical release identity SHALL NOT be derived from a filename, a checksum, an acquisition instant, a source field name, a row ordering, or a persistence surrogate. The canonical persistence boundary SHALL accept only a complete canonical release identity, and SHALL NOT accept a Bronze release partition or a partition accompanied by a hint.

#### Scenario: Complete evidence is promoted
- **WHEN** a candidate whose four identity components are established is promoted
- **THEN** a canonical release identity is returned

#### Scenario: A release identifier was never established
- **WHEN** a candidate lacking a release identifier is promoted
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

### Requirement: A batch carries the complete ancestry of every record in it
A canonical batch SHALL be composed of whole account groups: one account snapshot together with every record that descends from it in that batch. A record whose parent is not present in the same batch SHALL be rejected by the boundary.

This SHALL hold so that an implementation can resolve every parent relationship within one batch, without correlating records across batches, without keying on observed values, and without retaining a release-wide mapping that would grow with the release.

#### Scenario: A complete account group is written
- **WHEN** a batch carries an account snapshot with its owners, associations, allocations, values, taxing units, exemptions, land, improvements, and geometries
- **THEN** the batch is accepted and every parent relationship is resolvable within it

#### Scenario: A child is separated from its parent
- **WHEN** a batch carries a record whose parent record is absent from that batch
- **THEN** the batch is rejected, naming the record whose ancestry is incomplete

#### Scenario: An account is split across batches
- **WHEN** the boundary is examined for whether one account's records may span two batches
- **THEN** the contract prohibits it structurally rather than leaving the correlation to the implementation

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
