## ADDED Requirements

### Requirement: Shared lexical rules for canonical appraisal records
The system SHALL apply these rules wherever the requirements below name the corresponding kind, so that no bound is invented at implementation time.

| kind | rule |
|---|---|
| **identifier** | `str` of 1 through 128 characters drawn from `[A-Za-z0-9._-]`, not beginning with `.` or `-`, matching the alphabet already accepted across the repository |
| **label** | `str` of 1 through 256 characters, containing no control character and at least one non-whitespace character, preserved verbatim including case |
| **address component** | `str` of 1 through 128 characters, containing no control character and at least one non-whitespace character |
| **amount** | `Decimal` that is finite; `float`, `bool`, `NaN`, and infinity SHALL be rejected. No sign constraint is imposed, because no accepted contract establishes one and some rolls carry negative adjustments. `Decimal(0)` is a valid amount: counties publish zero values, and a constructor receiving a decimal cannot know whether a caller meant zero or meant absent |
| **magnitude** | `Decimal` that is finite and not negative, for a physical quantity such as an area; `float`, `bool`, `NaN`, and infinity SHALL be rejected. Distinct from **amount** because a monetary figure may legitimately be negative and a measured area may not |
| **percentage** | `Decimal` that is finite and from 0 through 100 inclusive; `float` and `bool` SHALL be rejected |
| **instant** | timezone-aware `datetime`; a naive value SHALL be rejected |
| **year** | `int` from 1600 through 2200 inclusive; `bool` SHALL be rejected |

A value outside its kind SHALL be rejected at construction rather than truncated, padded, case-folded, stripped, or otherwise coerced. Absence SHALL be `None`. An empty string and a zero **year** SHALL be rejected because neither is a value any source publishes, but a zero **amount** SHALL be accepted, because zero is a figure counties do publish and asking a constructor to distinguish an intended zero from an intended absence is asking it to read intent it cannot see.

#### Scenario: A bounded value exceeds its rule
- **WHEN** a value longer than its bound, outside its alphabet, carrying a control character, or of the wrong type is supplied
- **THEN** construction fails and the value is not altered to fit

#### Scenario: Absence is offered as a placeholder
- **WHEN** an empty string or a zero year is supplied for an absent fact
- **THEN** construction fails, because absence is `None`

#### Scenario: A county publishes a zero value
- **WHEN** an amount of zero is recorded
- **THEN** it is accepted as the figure the county published and is not treated as an absent value

### Requirement: Canonical account identity
The system SHALL identify a canonical appraisal account with an `AccountIdentity` of exactly two components: the canonical `Jurisdiction`, and a `source_account_id` meeting the **identifier** rule. Two account identities SHALL compare equal when and only when both components are equal, so equal source account identifiers from different jurisdictions SHALL NOT be equal accounts. County FIPS SHALL NOT form a second, independent county identity, and no database identifier, object-store location, source filename, or orchestration identifier SHALL participate.

Whether a given source field is an **approved** account key is a fact about a county contract. The domain SHALL validate the identifier's lexical contract and SHALL NOT attempt to determine which source field supplied it: a generic constructor receiving a jurisdiction and a string cannot distinguish an approved account key from an owner-row discriminator carrying the same characters, and a rule it cannot enforce is not a rule.

Whether a given source field is an approved account key is county-specific knowledge, and county-specific knowledge stops at the adapter boundary. That decision therefore belongs to the county adapter under its accepted county contract, which this capability does not restate and does not assert scenarios about. There SHALL be no provisional, partial, or nullable form of an account identity, so an adapter that cannot construct one produces none.

#### Scenario: Two counties publish one account identifier
- **WHEN** two county adapters emit the same source account identifier
- **THEN** the resulting account identities are not equal, because their jurisdictions differ

#### Scenario: An identifier of unknown provenance reaches the domain
- **WHEN** a well-formed identifier is supplied to the domain constructor
- **THEN** it is accepted on its lexical contract alone, because a jurisdiction and a string carry no evidence of which source field produced them

### Requirement: One release authority per record
Where a record carries lineage, its `DomainProvenance` SHALL be the single authority for the release it belongs to, and the record SHALL NOT carry a second `ReleaseIdentity` beside it. A record needing its release SHALL derive it from its provenance.

Where a record carries both a parent and its own provenance, construction SHALL require that the record's provenance release equals its parent's provenance release, and SHALL fail otherwise. Two representations of one fact that a constructor does not reconcile are two representations that will eventually disagree.

#### Scenario: A record's release is required
- **WHEN** the release, tax year, or release kind of any canonical appraisal record is needed
- **THEN** it is reached through that record's provenance and is not stored a second time

#### Scenario: A child disagrees with its parent
- **WHEN** a child observation is constructed whose provenance names a different release than its parent snapshot's provenance
- **THEN** construction fails

### Requirement: Account snapshot grain
The system SHALL represent one account as one logical release observed it, as an `AccountSnapshot`. Its grain SHALL be exactly its `AccountIdentity` and the release its provenance names. The same account observed in two releases SHALL yield one account identity and two distinct snapshots, and neither SHALL overwrite the other.

The snapshot's account identity jurisdiction SHALL equal the jurisdiction of the release its provenance names, and construction SHALL fail otherwise. Without that invariant an account identity from one county is constructible under another county's release provenance, and every child then agrees with that invalid parent and satisfies the release-agreement rule — an internally consistent account tree that is wrong at its root.

Snapshot **equality** SHALL be structural over every field except `source_as_of`. The **grain** SHALL be published as a read-only property named `grain` returning the tuple `(AccountIdentity, ReleaseIdentity)` in that order, exported on the package's public surface, so that consumers key on one published shape rather than each choosing an accessor. Equal grain SHALL NOT imply equal snapshot: two snapshots of one account in one release observed in two different artifacts share a grain and carry different lineage, which is the divergence case and SHALL remain expressible rather than collapsed. Consumers keying by grain SHALL use the published grain rather than object equality.

A `source_as_of` **instant** SHALL be recorded as optional observation metadata excluded from equality, hashing, and grain, because a source as-of value is a property of the release rather than of one account within it: including it would discriminate nothing while storing a second copy of a release-level fact.

A snapshot SHALL compose an optional `SitusAddress` and an optional `LegalDescription`, which have no independent grain.

#### Scenario: One account appears in two releases
- **WHEN** an account is present in a proposed release and a certified release
- **THEN** both snapshots exist, share one account identity, and are not equal to each other

#### Scenario: Two snapshots differ only by source as-of
- **WHEN** two snapshots share an account identity and a release and differ only in recorded source as-of value
- **THEN** they are equal, because the as-of value is observation metadata and the release already fixes which observation this is

#### Scenario: Two snapshots share a grain but not an artifact
- **WHEN** one account in one release is observed in two different artifacts
- **THEN** the two snapshots share a published grain, are not equal, and each retains its own lineage

#### Scenario: An identity is paired with another county's release
- **WHEN** an account identity from one jurisdiction is supplied with provenance naming a release of another
- **THEN** construction fails at the snapshot rather than being accepted and agreed with by its children

### Requirement: Owner observations carry no independent identity
The system SHALL represent an owner as an `OwnerObservation` carrying an `owner_name` meeting the **label** rule, an optional composed `MailingAddress`, its parent `AccountSnapshot`, and `DomainProvenance`. It SHALL NOT derive an independently identifiable person or entity from an owner name, a mailing address, or any combination of them, and SHALL NOT perform cross-release or cross-county person or entity resolution.

#### Scenario: Two releases publish one owner name
- **WHEN** the same owner name and mailing address appear in two releases
- **THEN** they remain two observations, and no identity links them

### Requirement: Owner associations hold allocations, and allocations never become account totals
The system SHALL relate an owner observation to an account snapshot through an `OwnerAssociation` carrying its parent `AccountSnapshot`, the `OwnerObservation`, an optional `ownership_percentage` meeting the **percentage** rule, an optional `source_discriminator` meeting the **identifier** rule, and `DomainProvenance`. The owner observation's parent snapshot SHALL equal the association's.

The source discriminator SHALL be optional, because a county whose owner-row grain its accepted contract leaves unresolved must remain representable and no constructor may demand evidence a contract has not established.

Owner-scoped value allocations SHALL be represented as `OwnerValueAllocation`, carrying its parent `OwnerAssociation`, a canonical `ValueKind`, an **amount**, and `DomainProvenance`. Owner-scoped exemption allocations SHALL be represented as exemption observations scoped to the association. Neither SHALL be carried on the account snapshot.

The system SHALL NOT deduplicate owner associations, sum their allocations, or select one as an account total. No field on an account snapshot, an association, or an allocation SHALL hold an account-level total derived from allocations, so that producing one has no representation rather than being merely prohibited.

#### Scenario: Undivided-interest rows allocate values by owner
- **WHEN** rows sharing an approved account key differ by owner sequence, ownership percentage, or owner-scoped values or exemptions
- **THEN** each becomes a distinct association with its own allocations and lineage, and none is deduplicated, summed, or selected as the account total

#### Scenario: An account total is sought from allocations
- **WHEN** a caller looks for a field holding an account-level total assembled from owner allocations
- **THEN** no such field exists on the snapshot, the association, or the allocation

#### Scenario: A county has no approved owner discriminator
- **WHEN** owner rows arrive from a county whose accepted contract approves no owner discriminator
- **THEN** the associations are constructible and the discriminator is absent rather than fabricated

### Requirement: Canonical appraisal values
The system SHALL define a closed canonical value vocabulary of exactly `market`, `appraised`, and `assessed`, and SHALL represent an account-level value as an `AppraisalValueObservation` carrying its parent `AccountSnapshot`, a `ValueKind`, an **amount**, and `DomainProvenance`.

A source-native value SHALL be mapped to a canonical kind only where an accepted county contract establishes semantic equivalence. A field name, an observed inequality, or a resemblance between labels SHALL NOT establish it, and the domain SHALL expose no function, mapping, or constructor translating a source-native label into a kind. Where equivalence is not established the canonical value SHALL be absent and the source-native value SHALL remain at the adapter boundary with its lineage.

Land, improvement, agricultural, timber, productivity, and homestead-cap values SHALL NOT be canonical kinds, and a cap amount SHALL NOT be treated as a capped value.

#### Scenario: An unmapped source total is presented
- **WHEN** a source-native total whose meaning no accepted contract has established is presented for canonicalization
- **THEN** no canonical value is produced and the canonical market, appraised, and assessed values remain absent

#### Scenario: Three kinds stay distinct
- **WHEN** market, appraised, and assessed values are recorded for one snapshot
- **THEN** each remains a separate observation and none is derived from another

#### Scenario: A kind outside the vocabulary is supplied
- **WHEN** a value kind outside the closed vocabulary is supplied
- **THEN** construction fails rather than accepting an open string

### Requirement: A taxable value exists only for a taxing unit
The system SHALL represent a taxable value as a `TaxableValueObservation` carrying its parent `AccountSnapshot`, the `TaxingUnitObservation` it applies to, an **amount**, a `basis` meeting the **label** rule and preserved source-native, and `DomainProvenance`. The taxing unit's parent snapshot SHALL equal the taxable value's.

Taxable SHALL NOT be a member of the canonical value vocabulary, and a property-wide taxable value not qualified by a taxing unit SHALL have no representation. Where several taxing units apply to one account, each taxable value SHALL retain its unit and basis, and no unit SHALL be selected to stand for the account as a whole.

#### Scenario: One account has several taxable values
- **WHEN** a county supplies taxable values for several taxing units on one account
- **THEN** each is retained with its taxing unit and basis, and none is chosen as a single property-wide taxable value

#### Scenario: A property-wide taxable value is attempted
- **WHEN** a caller records a taxable value without a taxing unit
- **THEN** no shape accepts it

### Requirement: Taxing units are observations, distinct from the appraisal jurisdiction
The system SHALL represent a taxing entity — a school district, city, county tax unit, or similar — as a `TaxingUnitObservation` carrying its parent `AccountSnapshot`, a `unit_code` meeting the **identifier** rule, an optional `unit_name` meeting the **label** rule, and `DomainProvenance`, all preserved source-native.

It SHALL NOT reuse the canonical `Jurisdiction`, which identifies the appraisal district that publishes a roll, and no type in the appraisal record model SHALL be named so as to be confusable with it. No canonical cross-county taxing-unit registry or code vocabulary SHALL be defined, because none is established by an accepted contract.

#### Scenario: A taxing unit is recorded
- **WHEN** a taxing entity applies to an account
- **THEN** it is recorded as an observation with the county's own code and name, not as a canonical jurisdiction

#### Scenario: The two concepts are compared
- **WHEN** the appraisal jurisdiction and a taxing unit of one account are inspected
- **THEN** they are different types and neither is substitutable for the other

### Requirement: Exemptions are observations with source-native classification and explicit scope
The system SHALL represent an exemption as an `ExemptionObservation` carrying its parent `AccountSnapshot`, a `classification` meeting the **label** rule and preserved verbatim source-native, an optional **amount**, an explicit `ExemptionScope` of exactly `account` or `owner_association`, an `association` reference, and `DomainProvenance`.

The association reference SHALL be present when and only when the scope is `owner_association`, and its parent snapshot SHALL equal the exemption's. The scope SHALL be stated explicitly rather than inferred from whether the reference is present, so an exemption whose scope was never determined cannot be constructed by omission.

No canonical exemption vocabulary SHALL be defined, and a county label SHALL NOT be canonicalized without an accepted contract establishing equivalence. The system SHALL NOT derive a taxable value from exemptions.

#### Scenario: An unknown county label arrives
- **WHEN** an exemption label no accepted contract classifies is recorded
- **THEN** it is retained verbatim as source-native and no canonical vocabulary is widened to admit it

#### Scenario: Scope and reference disagree
- **WHEN** an account-scoped exemption carries an association reference, or an owner-scoped exemption carries none
- **THEN** construction fails

### Requirement: Land and improvement children survive without invented identity
The system SHALL represent land and improvement records as separate child observations — `LandObservation` and `ImprovementObservation` — each carrying its parent `AccountSnapshot`, an optional `source_discriminator` meeting the **identifier** rule, an optional source-native `classification` meeting the **label** rule, an optional `area` meeting the **magnitude** rule with an `area_unit` meeting the **label** rule, and `DomainProvenance`. An improvement SHALL additionally carry an optional `year_built` meeting the **year** rule. An area SHALL be unconstructible without its unit, and a unit without an area SHALL be rejected.

No universal land or improvement natural key SHALL be invented. A sequence number, row number, building number, or physical ordering SHALL NOT be treated as a stable business identity unless an accepted county contract establishes it. Where a source child key is unresolved the observation SHALL remain valid and its discriminator SHALL be absent rather than fabricated.

#### Scenario: An account has several improvements
- **WHEN** a source account carries several improvement records
- **THEN** each is retained as its own observation at child grain and none is merged into the account snapshot

#### Scenario: A child key is unresolved
- **WHEN** a county publishes child records whose stable key no accepted contract has established
- **THEN** the observations are constructible, carry lineage, and assert no cross-release business identity

#### Scenario: An area arrives without a unit
- **WHEN** an area magnitude is recorded with no unit, or a unit with no magnitude
- **THEN** construction fails rather than assuming either

#### Scenario: A negative area is offered
- **WHEN** a negative area is recorded
- **THEN** construction fails, while zero and positive areas are accepted, because a measured extent has no negative value even where a monetary adjustment does

### Requirement: Geometry is enrichment carried without a geospatial dependency
The system SHALL represent geometry as a `GeometryObservation` enrichment carrying its parent `AccountSnapshot`, a `GeometryEncoding` of exactly `wkb` or `wkt`, a payload of `bytes` for `wkb` or `str` for `wkt` that is non-empty and at most 8 MiB measured as the length of the `bytes` or of the `str` encoded as UTF-8, a required `crs` of 1 through 64 characters containing no control character and at least one non-whitespace character and stated as the source stated it, and `DomainProvenance`.

A snapshot MAY carry several geometry observations; geometry SHALL NOT be constrained to at most one per snapshot, because no accepted contract establishes that a county publishes only one. The domain SHALL NOT parse, validate, reproject, or otherwise interpret geometry, and SHALL NOT import a geospatial library, a spatial database extension, or an object-store client. A coordinate reference SHALL be required, because geometry whose coordinate system is unknown cannot be placed. The presence of geometry for an account SHALL NOT be treated as evidence that a complete appraisal record exists for it.

#### Scenario: Geometry arrives without a coordinate reference
- **WHEN** a geometry payload is recorded with no coordinate reference identifier
- **THEN** construction fails rather than assuming a default

#### Scenario: A coordinate reference is blank
- **WHEN** a coordinate reference consisting only of whitespace is supplied
- **THEN** construction fails, because a required identifier that names nothing is not one

#### Scenario: A payload sits at and past its bound
- **WHEN** a payload measures exactly the maximum, and when it measures one unit more, with the text case measured as UTF-8
- **THEN** the first is accepted and the second is refused

#### Scenario: A payload disagrees with its encoding
- **WHEN** a `wkb` encoding carries a `str` payload, or `wkt` carries `bytes`
- **THEN** construction fails

#### Scenario: A partial GIS source supplies geometry
- **WHEN** geometry arrives from a source that is a GIS subset rather than a full appraisal roll
- **THEN** the enrichment is recorded and no completeness of the appraisal record is implied by it

### Requirement: Situs, legal description, and mailing address are bounded, and representation is not permission
The system SHALL represent these as composed value objects with named fields, each an optional **address component** except where stated, and no free-form payload:

| value object | fields |
|---|---|
| `SitusAddress` | `street_address`, `unit`, `city`, `state_code`, `postal_code` |
| `MailingAddress` | `addressee`, `street_address`, `unit`, `city`, `state_code`, `postal_code`, `country_code` |
| `LegalDescription` | `text` as a required **label**, `subdivision`, `block`, `lot` |

At least one field SHALL be present in each; an object with every field absent SHALL be rejected rather than recording nothing. `MailingAddress` SHALL compose onto an owner observation; `SitusAddress` and `LegalDescription` SHALL compose onto an account snapshot. They have no independent grain and are not records.

Representing these fields SHALL NOT constitute permission to publish them. No type in the appraisal record model SHALL carry a publication flag, permission, visibility, or redaction-override field. Publication SHALL remain governed by the reviewed field-level policy, which is default-deny and requires a named approver, an approval time, and a review reference, and SHALL NOT be affected by the existence of a canonical representation.

#### Scenario: A sensitive field is represented
- **WHEN** an owner name, mailing address, or situs address is recorded canonically
- **THEN** no publication permission is conferred and the field-level policy still governs whether it may be published

#### Scenario: A publication flag is sought
- **WHEN** a caller looks for a field on a canonical record marking it publishable
- **THEN** no such field exists

### Requirement: Provenance attaches to observations, not to identities
The system SHALL carry the canonical `DomainProvenance` on every snapshot, observation, association, allocation, and enrichment, and SHALL NOT carry it on a stable identity or a composed value object, which name or describe rather than record an observation. No separate lineage model SHALL be introduced.

Several canonical facts derived from one source row SHALL each carry their own provenance, whose values are equal, so that a child reached without its parent still carries its own lineage.

#### Scenario: A child observation is examined alone
- **WHEN** a child observation is inspected without its parent snapshot
- **THEN** its originating jurisdiction, release, artifact, source member, row position, parser contract version, and layout identity are all recoverable from it

### Requirement: Every record declares its identity classification
Every canonical appraisal **record** type SHALL be classified by a published `RecordClassification` as exactly one of a stable business identity, a release-scoped snapshot, a child observation, an association or allocation, or an enrichment.

The classification SHALL be published as a module-level mapping named `RECORD_CLASSIFICATIONS` of type `Mapping[type[object], RecordClassification]`, exported from the package root, and backed by a read-only mapping so that a consumer can neither add, replace, nor delete an entry. Naming the shape here rather than requiring "a mapping" leaves no accessor for an implementer to choose, which is the same choice already removed from the snapshot's grain.

Composed value objects — situs address, mailing address, and legal description — are not records: they have no grain, carry no provenance, and SHALL be excluded from the classification consistently in the published mapping and in the tests that assert it. The mapping SHALL cover every record type and no non-record.

#### Scenario: A consumer asks whether a record has stable identity
- **WHEN** the classification of a canonical appraisal record type is inspected
- **THEN** exactly one classification is returned, and a record classified as an observation asserts no stable cross-release identity

#### Scenario: A consumer attempts to change a classification
- **WHEN** a caller assigns, replaces, or deletes an entry in the published mapping
- **THEN** the attempt fails, because a published classification a consumer can edit is not published

#### Scenario: A value object is offered for classification
- **WHEN** a composed value object is looked up in the classification mapping
- **THEN** it is absent, because it is not a record

### Requirement: The appraisal record model stays infrastructure-free
The canonical appraisal record model SHALL import no adapter, infrastructure, object-store, database, orchestration, geospatial, or county-specific module, and SHALL be constructible and testable without them. Adapter and source vocabulary SHALL remain outside it, including table names, source families, source statuses, observed-field vectors, normalized-field vectors, and county-native field names.

No record SHALL carry a generic payload, detail, extra, metadata, or annotation field, no mapping of arbitrary values, and no sequence of arbitrary values.

#### Scenario: The model is exercised alone
- **WHEN** the canonical appraisal records are constructed and compared
- **THEN** no database driver, object-store client, orchestration package, geospatial library, or county adapter is imported

#### Scenario: A general-purpose field is sought
- **WHEN** a caller seeks a field on a canonical appraisal record for an arbitrary source value or payload
- **THEN** no general-purpose field exists, and every field present is a named fact with a declared type and bound
