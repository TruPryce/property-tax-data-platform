## ADDED Requirements

<!-- Owns: `SourceRegistry`, `UnsupportedSource`, expected media types on
     `CountySourceDefinition`; `ReleaseDiscovery`, `SourceCandidate`,
     `PageEvidence`, `LogicalReleaseEvidence`, `UnchangedRelease`; and the one
     promotion from evidence to `ReleaseIdentity` with
     `IncompleteReleaseIdentity`.
     Cites: the accepted `canonical-identity-and-provenance` spec for
     `ReleaseIdentity`; the bootstrap `source-release-ingestion` delta for the
     registry and discovery requirements this spec refines. -->

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
