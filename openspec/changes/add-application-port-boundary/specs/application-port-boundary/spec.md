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

### Requirement: Source resolution fails before network acquisition
The system SHALL resolve a supported county and release kind to a source definition without performing network acquisition, and SHALL represent an unregistered county or release kind as a named, actionable unsupported-source failure rather than an absent result or a generic error.

A consumer of this resolution SHALL NOT require a county-specific branch.

#### Scenario: A registered source is resolved
- **WHEN** a run requests a registered county and release kind
- **THEN** a source definition carrying its endpoint, acquisition method, and parser identifier is returned, and no network request has been made

#### Scenario: An unregistered source is requested
- **WHEN** a run requests a county or release kind the registry does not describe
- **THEN** a named unsupported-source failure is raised before acquisition, identifying what was requested

#### Scenario: A consumer resolves several counties
- **WHEN** a caller resolves sources for more than one county
- **THEN** it does so through one uniform call and contains no county-specific branch

### Requirement: Discovery carries bounded evidence and no secrets
Release discovery SHALL return candidates carrying the source locator, remote metadata, source as-of evidence, and the release facts the source has established, in bounded form. A candidate SHALL NOT carry credentials, arbitrary source content, or an unbounded payload.

Discovery SHALL NOT perform county parsing or county field mapping.

#### Scenario: A candidate is returned
- **WHEN** discovery observes an available release
- **THEN** the candidate carries its locator, remote metadata, and established release facts, and carries no credential and no source row

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

### Requirement: Canonical persistence uses canonical release identity
The canonical persistence boundary SHALL identify a release by the promoted canonical release identity, comprising jurisdiction, tax year, release kind, and release identifier. It SHALL NOT accept a Bronze release partition, a filename, a checksum, an acquisition instant, a source field name, or a persistence surrogate as canonical release identity, and SHALL NOT derive a missing release identifier from any of them.

Where the source has not established all four components, opening a canonical load SHALL fail with a named error.

#### Scenario: A release is loaded with complete identity
- **WHEN** a load is opened for a release whose four identity components are established
- **THEN** the load proceeds under that identity

#### Scenario: A release identifier was never established
- **WHEN** a load is opened for a release whose identifier the source did not establish
- **THEN** the load is refused with a named error and no identifier is synthesised

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

### Requirement: Publication is atomic and confers no read permission
The publication boundary SHALL expose a build that either becomes current atomically or fails without replacing the publication that is already current. A failed build SHALL NOT be marked current and SHALL NOT supersede the previous publication.

The boundary SHALL NOT grant, imply, or require raw canonical read access, and SHALL NOT confer permission to publish a sensitive field; field-level publication permission remains governed by the reviewed field policy.

#### Scenario: A build fails midway
- **WHEN** a publication build fails after writing intermediate data
- **THEN** the previously current publication remains current and the incomplete build is not marked current

#### Scenario: A build is activated
- **WHEN** a build completes and is activated
- **THEN** it becomes current and the publication it replaces is recorded as superseded

#### Scenario: The boundary is examined for read access
- **WHEN** the publication boundary is examined
- **THEN** it carries publication decisions and lineage and grants no canonical read privilege or sensitive-field permission

### Requirement: One application-owned clock returns timezone-aware instants
The application SHALL own one time source, and every instant it returns SHALL be timezone-aware. A use case SHALL obtain the current instant through that port rather than by calling a wall-clock API directly, so that a use case can be exercised deterministically.

#### Scenario: The current instant is obtained
- **WHEN** a use case asks the clock for the current instant
- **THEN** it receives a timezone-aware instant

#### Scenario: A use case is exercised deterministically
- **WHEN** a test supplies a fixed time source
- **THEN** the use case observes the supplied instant and reads no wall clock
