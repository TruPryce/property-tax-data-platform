## ADDED Requirements

### Requirement: Canonical account identity
The system SHALL identify a canonical appraisal account by its canonical `Jurisdiction` and a source account identifier that an accepted county contract has approved as an account key, and by nothing else. Two accounts SHALL compare equal when and only when both components are equal, so equal source account identifiers from different jurisdictions SHALL NOT be equal accounts. County FIPS SHALL NOT form a second, independent county identity.

An account identity SHALL NOT be constructed from a source identifier no accepted county contract has approved as an account key. Where a county's account key is unapproved, the system SHALL produce no canonical account and no account snapshot for that county, and its records SHALL remain at source grain with their lineage. There SHALL be no provisional, partial, or nullable form of an account identity.

A physical source row position, an owner-row discriminator, an object-store location, a database identifier, a source filename, or an orchestration identifier SHALL NOT participate in account identity.

#### Scenario: Two counties publish one account identifier
- **WHEN** two county adapters emit the same source account identifier
- **THEN** the resulting account identities are not equal, because their jurisdictions differ

#### Scenario: A county's account key is unapproved
- **WHEN** records arrive from a county whose accepted contract has not approved an account key
- **THEN** no canonical account identity is constructed, no snapshot is produced, and the records remain at source grain with their lineage

#### Scenario: A row position is offered as identity
- **WHEN** a source row number or owner-row discriminator is supplied as the account identifier
- **THEN** it is refused rather than accepted as a business identity

### Requirement: Account snapshot grain
The system SHALL represent one account as one logical release observed it, at the grain of its account identity and its `ReleaseIdentity`. A snapshot SHALL NOT restate the jurisdiction, tax year, release kind, or source-supplied release identifier as independent fields, because `ReleaseIdentity` already carries them.

A source as-of value SHALL be recorded as observation metadata on the snapshot rather than as part of its grain. The same account observed in two releases SHALL yield one account identity and two distinct snapshots, and neither SHALL overwrite the other.

#### Scenario: One account appears in two releases
- **WHEN** an account is present in a proposed release and a certified release
- **THEN** both snapshots exist, share one account identity, and are not equal to each other

#### Scenario: Release components are sought on a snapshot
- **WHEN** the tax year, release kind, or release identifier of a snapshot is required
- **THEN** it is reachable through the snapshot's release identity and is not stored a second time

### Requirement: Owner observations carry no independent identity
The system SHALL represent an owner as an observation of what a county published, and SHALL NOT derive an independently identifiable person or entity from an owner name, a mailing address, or any combination of them. Cross-release and cross-county person or entity resolution SHALL NOT be performed.

#### Scenario: Two releases publish one owner name
- **WHEN** the same owner name and mailing address appear in two releases
- **THEN** they remain two observations and no single owner identity is created linking them

### Requirement: Owner associations hold allocations, and allocations never become account totals
The system SHALL relate an owner observation to an account snapshot through an association carrying an optional ownership percentage as an exact decimal and an optional source discriminator where an accepted county contract approves one. Owner-scoped value and exemption allocations SHALL be carried on the association and SHALL NOT be carried on the account snapshot.

The system SHALL NOT deduplicate owner associations, sum their allocations, or select one as an account total. An account-level total derived from owner allocations SHALL have no representation, so that producing one is not possible rather than merely prohibited.

The source discriminator SHALL be optional, because a county whose owner-row grain its contract leaves unresolved must still be representable.

#### Scenario: Undivided-interest rows allocate values by owner
- **WHEN** rows sharing an approved account key differ by owner sequence, ownership percentage, or owner-scoped values or exemptions
- **THEN** each becomes a distinct owner association with its own allocations and lineage, and none is deduplicated, summed, or selected as the account total

#### Scenario: An account total is sought from allocations
- **WHEN** a caller looks for a field holding an account-level total assembled from owner allocations
- **THEN** no such field exists on the snapshot or the association

#### Scenario: A county has no approved owner discriminator
- **WHEN** owner rows arrive from a county whose accepted contract approves no owner discriminator
- **THEN** the associations are still constructible and the discriminator is absent rather than fabricated

### Requirement: Canonical appraisal values
The system SHALL define a closed canonical value vocabulary of exactly `market`, `appraised`, and `assessed`, and SHALL carry a value observation at account-snapshot grain with an exact decimal amount. Monetary amounts SHALL be represented exactly and SHALL NOT use binary floating point.

A source-native value SHALL be mapped to a canonical kind only where an accepted county contract establishes semantic equivalence. A field name, an observed inequality, or a resemblance between labels SHALL NOT establish it, and the system SHALL provide no route from an unmapped source label to a canonical kind. Where equivalence is not established, the canonical value SHALL be absent and the source-native value SHALL remain at the adapter boundary with its lineage.

Land, improvement, agricultural, timber, productivity, and homestead-cap values SHALL NOT be canonical value kinds, and a cap amount SHALL NOT be treated as a capped value.

#### Scenario: An unmapped source total is presented
- **WHEN** a source-native total whose meaning an accepted contract has not established is presented for canonicalization
- **THEN** no canonical value is produced and the canonical market, appraised, and assessed values remain absent

#### Scenario: Three kinds stay distinct
- **WHEN** market, appraised, and assessed values are recorded for one snapshot
- **THEN** each remains a separate observation and none is derived from another

#### Scenario: A kind outside the vocabulary is supplied
- **WHEN** a value kind outside the closed vocabulary is supplied
- **THEN** construction fails rather than accepting an open string

### Requirement: A taxable value exists only for a taxing unit
The system SHALL represent a taxable value as an observation at the grain of an account snapshot and the taxing unit it applies to, carrying its exact decimal amount and its source-native basis. Taxable SHALL NOT be a member of the canonical value vocabulary, and a property-wide taxable value not qualified by a taxing unit SHALL have no representation.

Where several taxing units apply to one account, each taxable value SHALL retain its taxing unit and basis, and no taxing unit SHALL be selected to stand for the account as a whole.

#### Scenario: One account has several taxable values
- **WHEN** a county supplies taxable values for several taxing units on one account
- **THEN** each is retained with its taxing unit and basis, and none is chosen as a single property-wide taxable value

#### Scenario: A property-wide taxable value is attempted
- **WHEN** a caller records a taxable value without a taxing unit
- **THEN** no shape accepts it

### Requirement: Taxing units are observations, distinct from the appraisal jurisdiction
The system SHALL represent a taxing entity — a school district, city, county tax unit, or similar — as an observation at account-snapshot grain carrying the source-native unit code and name. It SHALL NOT reuse the canonical `Jurisdiction` type, which identifies the appraisal district that publishes a roll, and no type in the appraisal record model SHALL be named so as to be confusable with it.

No canonical cross-county taxing-unit registry or code vocabulary SHALL be defined, because none is established by an accepted contract.

#### Scenario: A taxing unit is recorded
- **WHEN** a taxing entity applies to an account
- **THEN** it is recorded as an observation with the county's own code and name, and not as a canonical jurisdiction

#### Scenario: The two concepts are compared
- **WHEN** the appraisal jurisdiction and a taxing unit of one account are inspected
- **THEN** they are different types and neither is substitutable for the other

### Requirement: Exemptions are observations with source-native classification and explicit scope
The system SHALL represent an exemption as an observation carrying the county's own classification label verbatim, an optional exact decimal amount where a source supplies one, and an explicit scope of either the account or a named owner association. No canonical exemption vocabulary SHALL be defined, and a county label SHALL NOT be canonicalized without an accepted contract establishing equivalence.

The scope SHALL be stated explicitly rather than inferred from whether an association reference is present, so an exemption whose scope was never determined cannot be constructed by omission. The system SHALL NOT derive a taxable value from exemptions.

#### Scenario: An unknown county label arrives
- **WHEN** an exemption label no accepted contract classifies is recorded
- **THEN** it is retained verbatim as source-native and no canonical vocabulary is widened to admit it

#### Scenario: An owner-scoped exemption is recorded
- **WHEN** an exemption applies to one owner association rather than to the account
- **THEN** its scope names that association and it is not attached to the account snapshot

### Requirement: Land and improvement children survive without invented identity
The system SHALL represent land and improvement records as separate child observations of an account snapshot, each carrying an optional source discriminator that an accepted county contract approves, optional source-native classification, and lineage. Where an area is recorded it SHALL carry an exact decimal magnitude and a source-native unit, and an area SHALL NOT be representable without its unit.

No universal land or improvement natural key SHALL be invented. A sequence number, row number, building number, or physical ordering SHALL NOT be treated as a stable business identity unless an accepted county contract establishes it. Where a source child key is unresolved, the observation SHALL remain valid and its discriminator SHALL be absent rather than fabricated.

#### Scenario: An account has several improvements
- **WHEN** a source account carries several improvement records
- **THEN** each is retained as its own observation at child grain and none is merged into the account snapshot

#### Scenario: A child key is unresolved
- **WHEN** a county publishes child records whose stable key no accepted contract has established
- **THEN** the observations are constructible, carry lineage, and assert no cross-release business identity

#### Scenario: An area arrives without a unit
- **WHEN** an area magnitude is recorded with no unit
- **THEN** construction fails rather than assuming one

### Requirement: Geometry is enrichment carried without a geospatial dependency
The system SHALL represent geometry as an enrichment observation carrying an encoding, an opaque payload, a required coordinate reference identifier as the source stated it, and lineage. The domain SHALL NOT parse, validate, reproject, or otherwise interpret geometry, and SHALL NOT import a geospatial library, a spatial database extension, or an object-store client.

A coordinate reference identifier SHALL be required, because geometry whose coordinate system is unknown cannot be placed. The presence of geometry for an account SHALL NOT be treated as evidence that a complete appraisal record exists for it.

#### Scenario: Geometry arrives without a coordinate reference
- **WHEN** a geometry payload is recorded with no coordinate reference identifier
- **THEN** construction fails rather than assuming a default

#### Scenario: A partial GIS source supplies geometry
- **WHEN** geometry arrives from a source that is a GIS subset rather than a full appraisal roll
- **THEN** the enrichment is recorded and no completeness of the appraisal record is implied by it

### Requirement: Situs, legal description, and mailing address are bounded, and representation is not permission
The system SHALL represent situs address, legal description, and mailing address as bounded value objects with named fields and no free-form payload. A mailing address SHALL compose onto an owner observation; a situs address and legal description SHALL compose onto an account snapshot.

Representing these fields SHALL NOT constitute permission to publish them. No type in the appraisal record model SHALL carry a publication flag, permission, visibility, or redaction-override field. Publication SHALL remain governed by the reviewed field-level policy, which is default-deny and requires a named approver, an approval time, and a review reference, and SHALL NOT be affected by the existence of a canonical representation.

#### Scenario: A sensitive field is represented
- **WHEN** an owner name, mailing address, or situs address is recorded canonically
- **THEN** no publication permission is conferred and the field-level policy still governs whether it may be published

#### Scenario: A publication flag is sought
- **WHEN** a caller looks for a field on a canonical record marking it publishable
- **THEN** no such field exists

### Requirement: Provenance attaches to observations, not to identities
The system SHALL carry the canonical `DomainProvenance` on every snapshot, observation, association, and enrichment, and SHALL NOT carry it on a stable identity, which names a thing rather than recording one. No separate lineage model SHALL be introduced, and no record SHALL restate the jurisdiction, tax year, release kind, or release identifier that the provenance's release identity already carries.

Several canonical facts derived from one source row SHALL each carry their own provenance, whose values are equal, so that a child observation reached without its parent still carries its own lineage.

#### Scenario: A child observation is examined alone
- **WHEN** a child observation is inspected without its parent snapshot
- **THEN** its originating jurisdiction, release, artifact, source member, row position, parser contract version, and layout identity are all recoverable from it

#### Scenario: Release components are sought on a record
- **WHEN** a record's tax year or release kind is required
- **THEN** it is reached through the release identity its provenance composes and is not stored beside it

### Requirement: Every record declares its identity classification
Every canonical appraisal record type SHALL be classified as exactly one of a stable business identity, a release-scoped snapshot, a child observation, an association or allocation, or an enrichment. The classification SHALL be published as part of the model and SHALL be assertable directly rather than described in commentary, so that a consumer deciding whether a record needs a stable key can read the answer rather than infer it from a storage layout.

#### Scenario: A consumer asks whether a record has stable identity
- **WHEN** the classification of a canonical appraisal record type is inspected
- **THEN** exactly one classification is returned, and a record classified as an observation asserts no stable cross-release identity

### Requirement: The appraisal record model stays infrastructure-free
The canonical appraisal record model SHALL import no adapter, infrastructure, object-store, database, orchestration, geospatial, or county-specific module, and SHALL be constructible and testable without them. Adapter and source vocabulary SHALL remain outside it, including table names, source families, source statuses, observed-field vectors, normalized-field vectors, and county-native field names.

No record SHALL carry a generic payload, detail, extra, metadata, or annotation field, no mapping of arbitrary values, and no sequence of arbitrary values.

#### Scenario: The model is exercised alone
- **WHEN** the canonical appraisal records are constructed and compared
- **THEN** no database driver, object-store client, orchestration package, geospatial library, or county adapter is imported

#### Scenario: A general-purpose field is sought
- **WHEN** a caller seeks a field on a canonical appraisal record for an arbitrary source value or payload
- **THEN** no general-purpose field exists, and every field present is a named fact with a declared type
