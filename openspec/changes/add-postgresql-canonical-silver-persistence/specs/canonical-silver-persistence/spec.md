## ADDED Requirements

### Requirement: Canonical persistence is separate from adapter-grain persistence
The system SHALL persist canonical appraisal records in a schema distinct from the adapter-grain source-record schema, and SHALL NOT reinterpret an adapter-grain relation as a canonical one. Adapter-grain persistence — one row per physical source row, with identifiers and values under their exact source names — SHALL remain, SHALL keep its own lineage, and SHALL NOT be removed, narrowed, or rewritten because canonical relations exist.

The two SHALL be separable by inspection rather than by convention: a canonical relation SHALL be reachable only through the canonical schema, and the privileges of one SHALL NOT be inherited by the other.

#### Scenario: An adapter-grain row has no canonical counterpart
- **WHEN** a source row is persisted at adapter grain for a release whose canonical identity cannot be constructed
- **THEN** the adapter-grain row and its lineage are retained and no canonical record is created for it

#### Scenario: The two models are inspected
- **WHEN** the persisted schemas are enumerated
- **THEN** the canonical relations and the adapter-grain relations are in different schemas, and neither schema's default privileges apply to the other

### Requirement: Canonical release identity is persisted with its full contract
The system SHALL persist a canonical logical release as jurisdiction, tax year, release kind, and the source-supplied release identifier, and SHALL enforce each component's accepted rule at the database: the jurisdiction rule of the requirement below, a tax year from 1900 through 2200, the closed release-kind vocabulary of exactly `proposed`, `certified`, `supplemental`, and `current`, and the accepted identifier alphabet of 1 through 128 characters of `[A-Za-z0-9._-]` not beginning with `.` or `-`.

Those four components together SHALL be the persisted business identity, expressed as a uniqueness constraint. Any generated key SHALL be a persistence locator only.

The system SHALL NOT derive or fabricate a release identifier from a filename, an archive member name, an artifact digest, a tax year, a release kind, row order, an acquisition time, or any other available field. Where persisted evidence does not supply every component within its accepted rule, the system SHALL create no canonical release and SHALL therefore create no canonical record for it.

#### Scenario: A release kind outside the canonical vocabulary is presented
- **WHEN** persistence is offered a release whose kind is a county-native label the canonical vocabulary does not contain
- **THEN** no canonical release is created, the acquisition evidence is retained, and no nearest-looking kind is substituted

#### Scenario: A release identifier is outside the accepted alphabet
- **WHEN** a release identifier carrying whitespace, a path separator, or more than 128 characters is presented
- **THEN** the canonical release is refused and the identifier is not trimmed, truncated, or rewritten to be accepted

#### Scenario: Two counties reuse one release label
- **WHEN** two jurisdictions publish the same release identifier for the same tax year and kind
- **THEN** they are two distinct canonical releases, because the jurisdiction is part of the identity

### Requirement: A persisted jurisdiction is one the registry describes
The promoted jurisdiction contract identifies a jurisdiction by its state code and county slug and rejects construction where the version-controlled registry describes no such slug. The system SHALL make that rule structural in persistence rather than leaving it to the writer: a canonical relation SHALL NOT record a jurisdiction the registry does not describe, and matching the state-and-county grammar SHALL NOT by itself be sufficient.

The registry SHALL be persisted as its own relation keyed by the jurisdiction, carrying the validated county FIPS as metadata, and seeded from the same version-controlled source the domain validates against. County FIPS SHALL appear only there: no canonical record relation SHALL carry a FIPS column, because it is metadata keyed by the identity and not a second, independent county identity.

The persisted registry and the version-controlled registry are one fact recorded twice, and the system SHALL assert their agreement rather than assume it.

#### Scenario: A well-formed but unknown county is offered
- **WHEN** a canonical release or account is written for a county slug matching the grammar that the registry does not describe
- **THEN** the write is refused, because no domain jurisdiction could be constructed for it either

#### Scenario: The registries are compared
- **WHEN** the persisted registry is compared with the version-controlled county registry
- **THEN** the jurisdiction and FIPS pairs are equal, and adding a county to one without the other fails

#### Scenario: County FIPS is sought on a record
- **WHEN** the canonical record relations are inspected for a county FIPS column
- **THEN** none exists, and the FIPS is reachable only through the registry keyed by the jurisdiction

### Requirement: Canonical release identity binds to the acquisition and processing evidence it rests on
The system SHALL relate a canonical release to the processing run that observed it, and SHALL enforce that the run's jurisdiction, tax year, release kind, and release identifier are the canonical release's own rather than a second, independently supplied set of values.

That relation SHALL additionally name the artifact the run read, and SHALL enforce that it is the artifact of the acquisition the run processed **and** an artifact bound to the release it claims. A load naming a run that read different bytes SHALL be refused.

The system SHALL relate artifacts and canonical releases through an association supporting one artifact carrying several releases and one release observed in several artifacts, and observing an additional artifact SHALL NOT change the release's identity.

#### Scenario: A run is bound to another county's release
- **WHEN** a canonical release for one jurisdiction is bound to a processing run that read another jurisdiction's bytes
- **THEN** the binding is refused by the database rather than accepted and later detected

#### Scenario: A run is bound to an artifact it did not read
- **WHEN** a canonical load names a processing run together with an artifact other than the one that run's acquisition carried
- **THEN** the binding is refused

#### Scenario: A release observed in two artifacts is loaded
- **WHEN** two runs each process one of two artifacts carrying the same logical release
- **THEN** two loads exist, one per run and artifact, and both persist

#### Scenario: A run is bound to a release it did not process
- **WHEN** a run that processed the certified partition of an artifact is bound to the proposed release of the same artifact
- **THEN** the binding is refused

#### Scenario: One artifact carries two releases
- **WHEN** one artifact holds current values for one tax year and certified values for another
- **THEN** two canonical releases bind to one unchanged artifact identity

### Requirement: Canonical provenance is complete, single-authority, and not cross-wireable
The system SHALL persist canonical provenance as the composition of a canonical release, an artifact identity, a source member name meeting the accepted identifier rule, an optional one-based source row number, a parser contract version of at least one, and an optional layout fingerprint of exactly 64 lowercase hexadecimal characters.

Every persisted snapshot, observation, association, allocation, and enrichment SHALL reference provenance, and its complete lineage — jurisdiction, tax year, release kind, release identifier, artifact digest, source member, row position, parser contract version, and layout identity — SHALL be recoverable when that record is examined without its parent.

Provenance SHALL be the single authority for the release a record belongs to. No canonical record SHALL carry a release identifier, tax year, or release kind of its own, and any release reference a record carries for constraint purposes SHALL be constrained by key to equal its provenance's, so it cannot name a different release.

Provenance SHALL be constrained to the release, artifact, and jurisdiction of the load it belongs to, so that a record's artifact is the artifact its processing run actually read. A provenance naming an artifact other than its load's SHALL be refused.

#### Scenario: A child is examined without its parent
- **WHEN** a single canonical child record is read with no reference to its snapshot
- **THEN** its jurisdiction, release, artifact, source member, row position, parser contract version, and layout identity are all recoverable from it

#### Scenario: Provenance names a release of another jurisdiction
- **WHEN** provenance is written whose jurisdiction differs from the jurisdiction of the release it names
- **THEN** the write is refused

#### Scenario: Provenance claims an artifact its load did not read
- **WHEN** provenance is written under one load while naming the artifact of a different load of the same release
- **THEN** the write is refused

#### Scenario: A record is pointed at another release
- **WHEN** a persisted record's release reference is changed to a release other than the one its provenance names
- **THEN** the change is refused

### Requirement: Canonical account identity is county-qualified and never a surrogate
The system SHALL persist a canonical account as exactly its jurisdiction and its source account identifier, and SHALL express that pair as the uniqueness constraint representing stable account identity. The source account identifier SHALL meet the accepted identifier rule.

A generated database key MAY exist as a persistence locator and SHALL NOT be, or be documented as, business identity. The jurisdiction SHALL be one the registry describes. County FIPS SHALL NOT be persisted on the canonical account as a second, independent county identity. No object-store location, source filename, or orchestration identifier SHALL participate in account identity.

#### Scenario: Two counties publish one account identifier
- **WHEN** two jurisdictions each persist an account carrying the same source account identifier
- **THEN** two distinct accounts exist and neither collides with the other

#### Scenario: The uniqueness basis is inspected
- **WHEN** the uniqueness constraints on the canonical account relation are enumerated
- **THEN** the jurisdiction and source account identifier appear together as a constraint, and no constraint makes the source account identifier unique on its own

### Requirement: Snapshot grain admits divergent evidence
The system SHALL persist an account snapshot at the grain of its account identity and the release its provenance names, and SHALL preserve two snapshots that share that grain while carrying different provenance.

That grain SHALL NOT be expressed as a uniqueness constraint, because a constraint over it would collapse the divergence case the canonical record contract preserves. It SHALL be expressed as a non-unique access path.

Apart from its surrogate primary key and the composite key required as a foreign-key target, the snapshot relation SHALL carry no additional `UNIQUE` constraint. Snapshot equality is structural over every field except the source as-of value, so two snapshots sharing an account, a release, and a provenance while differing in a composed situs address or legal description are distinct values at one grain, and persistence SHALL retain both. Any uniqueness over the load, account, and provenance together would refuse the second and SHALL NOT be introduced; the retry key already answers, once and at the load, the question such a constraint would be asking a second time.

The system SHALL NOT permit an existing snapshot to be overwritten or removed by the loading role. Where the shape alone cannot prevent it, the privilege SHALL: the loading role SHALL be granted insert and select and SHALL NOT be granted update or delete, so a conflicting write that would overwrite divergent evidence fails rather than succeeding silently.

The snapshot's account jurisdiction SHALL equal the jurisdiction of the release its provenance names, enforced by key at the root rather than by a check that every child then agrees with.

#### Scenario: One account in one release is observed in two artifacts
- **WHEN** two snapshots are persisted sharing an account and a release and carrying different provenance
- **THEN** both are retained, each keeps its own lineage, and neither overwrites nor excludes the other

#### Scenario: Two snapshots differ only in a composed value object
- **WHEN** two snapshots sharing one load, account, release, and provenance are persisted, differing only in a valid situs address, and again differing only in a valid legal description
- **THEN** both persist each time, because they are unequal values at one grain

#### Scenario: A conflicting write attempts to overwrite a snapshot
- **WHEN** the loading role attempts to update an existing snapshot, or to resolve an insert conflict by updating it
- **THEN** the attempt is refused for want of privilege

#### Scenario: An account is paired with another county's release
- **WHEN** a snapshot is written whose account jurisdiction differs from the jurisdiction of its provenance's release
- **THEN** the write is refused at the snapshot rather than accepted and agreed with by its children

### Requirement: Parented records stay one-to-many
The system SHALL persist owner observations, owner associations, owner value allocations, appraisal value observations, taxing unit observations, taxable value observations, exemption observations, land observations, improvement observations, and geometry enrichments as one-to-many relative to their parents, and SHALL NOT constrain any of them to at most one, one per kind, or one per parent, because no accepted contract establishes such a rule.

The system SHALL NOT deduplicate source observations by resemblance. No uniqueness constraint on a parented relation SHALL include an observed value; uniqueness SHALL be composed only of persistence locators and lineage references.

#### Scenario: Several children of one kind arrive
- **WHEN** several owner observations, owner associations, allocations, land records, improvements, and geometries are persisted under one snapshot
- **THEN** every one is retained and none replaces or excludes another

#### Scenario: The uniqueness constraints are inspected
- **WHEN** the uniqueness constraints on the parented relations are enumerated
- **THEN** none includes an observed value such as a value kind, an amount, a classification, an owner name, or a geometry payload

#### Scenario: Two identical-looking children arrive
- **WHEN** two child records carrying equal observed values arrive with distinct lineage
- **THEN** both are persisted, because resemblance is not identity

### Requirement: A child's lineage agrees with its parent at release grain
The system SHALL enforce by key, rather than by trigger or by loader discipline, that a persisted child's provenance names the same release as its parent's provenance, and that a reference from one record to another — an association to its owner observation, an allocation to its association, a taxable value to its taxing unit, an owner-scoped exemption to its association — stays within the same snapshot or parent release as its domain relationship requires.

Each record's own provenance SHALL additionally be tied to that record's own load, so its artifact is the artifact its run read. Parent and child SHALL NOT be required to share one load or artifact: the accepted canonical contract permits enrichment or another child observation from a second artifact of the same release.

Both directions of a cross-release attempt SHALL be closed: a child SHALL NOT retain its parent's release while naming provenance from another release, and SHALL NOT change its release to match that provenance while retaining a parent from the first release.

#### Scenario: A child names another release
- **WHEN** a child record under a release-A parent names release-B provenance, or changes its release to B to match that provenance
- **THEN** both writes are refused

#### Scenario: A child arrives from another artifact of the same release
- **WHEN** a geometry enrichment or another child carries provenance from a second load and artifact of its parent's same release
- **THEN** it is retained with its own artifact lineage and is not forced onto the parent's load

#### Scenario: A reference crosses snapshots
- **WHEN** a taxable value references a taxing unit observed on a different snapshot, or an owner association references an owner observation of a different snapshot
- **THEN** the write is refused

### Requirement: A taxable value cannot exist without its taxing unit
The system SHALL persist a taxable value only as qualified by a taxing unit observation, expressed as a required reference so that an unqualified, property-wide taxable value has no representable form rather than being rejected by a check.

The system SHALL NOT persist a taxable value kind within the canonical appraisal value vocabulary, a default taxing unit, or an appraisal jurisdiction standing in for a taxing unit. Where several taxing units apply to one account, each taxable value SHALL retain its own unit and its source-native basis, and none SHALL be selected to represent the account.

#### Scenario: A property-wide taxable value is attempted
- **WHEN** a taxable value is written with no taxing unit
- **THEN** the write is refused because the reference is required

#### Scenario: One account carries several taxable values
- **WHEN** taxable values for several taxing units are persisted for one account
- **THEN** each is retained with its unit and basis and none is chosen as a single property-wide value

### Requirement: Owner allocations are never rolled up
The system SHALL persist owner observations without cross-release or cross-county person or entity identity, owner associations as their own relation, and owner-scoped value allocations parented by the association rather than by the account snapshot.

No column, generated column, view, materialized view, trigger, or default in the canonical schema SHALL produce an account-level total assembled from owner allocations. The owner discriminator SHALL remain optional wherever a county contract has approved none.

#### Scenario: An account total is sought
- **WHEN** the canonical schema is inspected for a column, generated column, view, or trigger that sums owner allocations to an account level
- **THEN** none exists

#### Scenario: A county approves no owner discriminator
- **WHEN** owner rows arrive from a county whose accepted contract approves no owner discriminator
- **THEN** the associations persist and the discriminator is absent rather than fabricated

### Requirement: Closed vocabularies are exact and falsifiable
The system SHALL persist the canonical release kind, appraisal value kind, exemption scope, and geometry encoding vocabularies as closed sets enforced by the database, admitting exactly the accepted members and no others, and SHALL express the admitted set so that it is readable from the database catalog and changeable only by a reviewed migration.

The system SHALL NOT define a canonical exemption vocabulary or a canonical cross-county taxing-unit registry. Source-native labels that a canonical observation is defined to carry SHALL be persisted verbatim as bounded source-native text with no vocabulary constraint. Those labels are exactly six — exemption classification, taxing unit code, taxing unit name, taxable basis, land classification, and improvement classification — and the openness of each SHALL be asserted individually, because a vocabulary added to any one of them is the same defect whichever one it is.

#### Scenario: A value outside a closed set is offered
- **WHEN** a value kind, exemption scope, geometry encoding, or release kind outside its accepted set is written
- **THEN** the write is refused

#### Scenario: The admitted set is read
- **WHEN** the admitted members of a closed vocabulary are read from the database catalog
- **THEN** they are exactly the accepted members, and widening them requires a migration

#### Scenario: An unknown county label arrives in any carried field
- **WHEN** a previously unseen county value is persisted into each of the six carried source-native label fields in turn
- **THEN** every one is stored verbatim, and none of those columns carries a vocabulary constraint

### Requirement: Scalar values are stored exactly and absence is preserved
The system SHALL persist canonical scalar values so that no value is altered to fit:

| kind | rule the database SHALL enforce |
| --- | --- |
| identifier | 1 through 128 characters of `[A-Za-z0-9._-]`, not beginning with `.` or `-` |
| label | 1 through 256 characters, no control character, at least one non-whitespace character |
| address component | as label, bounded at 128 characters |
| amount | an exact decimal that is finite; not-a-number and both infinities refused; no sign constraint; zero accepted |
| magnitude | an exact decimal that is finite and not negative |
| percentage | an exact decimal that is finite and from 0 through 100 inclusive |
| instant | a timestamp-with-time-zone column, never a wall-clock one |
| year | an integer from 1600 through 2200 |

The system SHALL NOT introduce a floating-point column for any canonical value, and SHALL NOT impose a decimal precision or scale bound that no accepted contract establishes. Absence SHALL be null. A value outside its rule SHALL be refused rather than trimmed, padded, case-folded, rounded, or coerced. Every column carrying a kind SHALL enforce that kind's rule; the rules SHALL be asserted over every such column rather than over one representative of each.

Timezone-awareness is the one rule the database cannot enforce, and the system SHALL state that rather than claim it. PostgreSQL accepts a value with no offset into a timestamp-with-time-zone column and interprets it in the session time zone, so refusing a naive value SHALL remain the obligation of the domain constructor and of the writing boundary, which SHALL supply an offset-bearing value. What persistence SHALL guarantee is that the column type is timestamp-with-time-zone and that a supplied instant is stored and returned unchanged regardless of session time zone.

#### Scenario: An exact decimal round-trips
- **WHEN** a monetary amount with more significant digits than a floating-point type can hold, and one carrying a trailing zero, are persisted and read back
- **THEN** both return unchanged, including their scale

#### Scenario: An instant survives a change of session time zone
- **WHEN** an offset-bearing instant is persisted and read back under a different session time zone
- **THEN** it denotes the same instant, and the column's type is timestamp-with-time-zone rather than a wall-clock type

#### Scenario: Every column of a kind is exercised
- **WHEN** the columns carrying each lexical or numeric kind are enumerated from the catalog and each is offered a value outside its rule
- **THEN** every one refuses it, so a bound omitted from a single column fails

#### Scenario: A non-finite amount is offered
- **WHEN** not-a-number or an infinity is written to an amount column
- **THEN** the write is refused

#### Scenario: A negative magnitude is offered
- **WHEN** a negative area is written
- **THEN** the write is refused, while zero and positive areas are accepted

#### Scenario: The canonical column types are inspected
- **WHEN** the column types of the canonical schema are enumerated
- **THEN** no floating-point column exists and no decimal column carries a precision or scale bound

### Requirement: Composed value objects have no independent identity
The system SHALL persist situs address, mailing address, and legal description as named columns on the record that composes them, and SHALL NOT give them their own relation, generated key, or grain. Each named field SHALL carry its own bound; none SHALL be stored in a document, array, or other general-purpose column.

Where a composed value object has a required field, the database SHALL refuse a state in which another of its fields is present and the required one is absent.

#### Scenario: A composed value object is sought as a record
- **WHEN** the canonical relations are enumerated
- **THEN** no relation represents a situs address, mailing address, or legal description on its own, and none carries a key for one

#### Scenario: A legal description is partly present
- **WHEN** a legal subdivision, block, or lot is written with no legal description text
- **THEN** the write is refused

### Requirement: Geometry is persisted without a geospatial dependency
The system SHALL persist geometry as an enrichment carrying an encoding of exactly `wkb` or `wkt`, a payload that is non-empty and at most 8 MiB measured as bytes for `wkb` and as UTF-8 bytes for `wkt`, a required coordinate reference of 1 through 64 characters carrying no control character and at least one non-whitespace character, and its own provenance.

No geospatial database extension, spatial type, or spatial index SHALL be introduced. The system SHALL NOT convert one encoding to the other, reproject, validate topology, or infer a coordinate reference. Where the physical schema uses more than one payload column to preserve typing, the database SHALL enforce that exactly one is populated and that it is the one the encoding names, and the relation SHALL document that those columns expose a single logical payload.

A snapshot MAY carry several geometry enrichments and geometry SHALL NOT be constrained to at most one per snapshot.

#### Scenario: A payload disagrees with its encoding
- **WHEN** a `wkb` row carries a text payload, a `wkt` row carries a binary payload, or a row populates both payload columns
- **THEN** each write is refused

#### Scenario: A payload sits at and past its bound
- **WHEN** a payload measures exactly 8 MiB, and when it measures one byte more, with the text case measured as UTF-8
- **THEN** the first is accepted and the second is refused

#### Scenario: A coordinate reference is missing or blank
- **WHEN** geometry is written with no coordinate reference, or with one consisting only of whitespace
- **THEN** the write is refused rather than a default being assumed

#### Scenario: The installed extensions are inspected
- **WHEN** the database extensions and the canonical column types are enumerated
- **THEN** no geospatial extension is installed and no canonical column carries a spatial type

### Requirement: Unmapped source-native value fields have no canonical destination
The system SHALL provide no canonical column, document column, array column, or other general-purpose destination able to receive a source-native value field whose meaning no accepted contract has established. Such values SHALL remain at adapter grain with their lineage.

The existence of a canonical column SHALL NOT constitute permission to map an unresolved source field into it.

#### Scenario: A general-purpose destination is sought
- **WHEN** the canonical schema is inspected for a document, array, or arbitrary-value column, or for a column named after a source field
- **THEN** none exists, and every canonical column is a named fact with a declared type and bound

#### Scenario: An unresolved source total is presented
- **WHEN** a source-native total whose meaning no accepted contract has established is presented for canonical persistence
- **THEN** no canonical value is written and the value remains at adapter grain with its lineage

### Requirement: Canonical representation confers no publication permission
No canonical relation SHALL carry a publication, visibility, permission, sensitivity, suppression, or redaction-override column. The reviewed, default-deny, field-level publication policy SHALL remain the authority over what may be published, and SHALL NOT be affected by the existence of a canonical representation.

The consuming read role SHALL be granted nothing on the canonical schema, including schema usage, because the canonical relations hold owner names, mailing addresses, situs addresses, and legal descriptions that no view, row policy, or privilege currently filters. Any later read access SHALL be justified against the published-product boundary rather than granted because the relations exist.

#### Scenario: A publication flag is sought
- **WHEN** the canonical schema is inspected for a column marking a record publishable, visible, permitted, sensitive, suppressed, or redacted
- **THEN** none exists

#### Scenario: The read role queries a canonical relation
- **WHEN** the consuming read role selects from a canonical relation
- **THEN** the query is refused, and the refusal comes from the schema rather than from a table grant that was forgotten

### Requirement: The loading role holds the narrowest privilege that works
The system SHALL grant the loading role usage on the canonical schema and select and insert on canonical evidence relations, and SHALL NOT grant it update or delete. Default privileges for the canonical schema SHALL grant exactly select and insert, so a relation added by a later migration is reachable without inheriting the ability to overwrite.

The jurisdiction registry SHALL be the one read-only exception: its creating migration SHALL revoke the insert privilege inherited from the schema default, leaving the loading role select only. Merely granting select SHALL NOT be treated as removing the inherited insert privilege.

Every canonical object SHALL have its final privileges established in the migration that creates it. No canonical migration SHALL require superuser.

#### Scenario: The loading role attempts to overwrite
- **WHEN** the loading role attempts an update, a delete, or an insert that resolves a conflict by updating
- **THEN** each is refused for want of privilege, while an insert that resolves a conflict by doing nothing succeeds

#### Scenario: A relation is added by a later migration
- **WHEN** a canonical relation created by a later migration is queried by the loading role
- **THEN** it is readable and insertable and not updatable, without a further grant

#### Scenario: The loading role attempts to modify the registry
- **WHEN** the loading role attempts to insert a jurisdiction that the migrator did not seed
- **THEN** the attempt is refused because the registry's inherited insert privilege was explicitly revoked

### Requirement: Existing diagnostic, quality, and publication models are reused rather than replaced
The system SHALL evaluate quality, record processing outcomes, and record publication for canonical data through the existing run-bound models, and SHALL NOT create a parallel diagnostic, quality, or publication model for canonical records.

Release-rejection diagnostics SHALL remain bounded, structured, release-atomic, and free of complete rows, arbitrary source values, owner names, addresses, credentials, and host-local paths.

A canonical load SHALL be admissible only for a processing run whose outcome is accepted, enforced by the database at commit rather than by the loader, so that a rejected release leaves no canonical record.

#### Scenario: A rejected release is loaded
- **WHEN** canonical records are written in a transaction whose run's outcome is rejected
- **THEN** the transaction fails at commit and no canonical record persists

#### Scenario: Quality is evaluated for canonical data
- **WHEN** a data-quality rule is evaluated against canonical data for a release
- **THEN** the result is recorded against the processing run through the existing evaluation model, and no parallel quality relation exists

### Requirement: Retry is release-scoped and manufactures no natural key
The system SHALL distinguish four concepts and SHALL NOT collapse them: the domain grain of a record, the evidence identity its provenance carries, the persistence locator a generated key provides, and the retry key that decides whether work has already been done.

The retry key SHALL be the pairing of a canonical release with the processing run that loaded it. Re-running a load for that pairing SHALL persist nothing further and SHALL fail no constraint the caller must interpret. A retry SHALL NOT lose divergent evidence, deduplicate a legitimate child record, or require a natural key over observed values.

Where two distinct runs load one canonical release, both loads and both sets of records SHALL be retained, and selecting between them SHALL be the published-product boundary's decision rather than a value stored here.

#### Scenario: A load is retried
- **WHEN** a canonical load is run again for the same release and the same processing run
- **THEN** nothing further is persisted, no existing record is altered, and the caller can tell that the load had already happened

#### Scenario: A release is reprocessed by a second run
- **WHEN** a second processing run loads a release that a first run already loaded
- **THEN** both loads and both record sets are retained and neither overwrites the other

#### Scenario: The retry key is inspected
- **WHEN** the retry key is examined
- **THEN** it is composed of a release and a run, and not of any observed value

### Requirement: Canonical migrations are forward-only and safe on a populated cluster
Every canonical migration SHALL be forward-only with no inverse script, SHALL carry one logical concern, SHALL run as a single transaction, SHALL refuse to run without its file digest, SHALL refuse to apply twice, SHALL refuse to apply when its prerequisite has not been applied, SHALL record itself in the migration ledger with that digest, and SHALL set a lock timeout and a statement timeout wherever it touches or references a relation that may hold rows.

Applying the canonical migrations to an empty database and applying them to a database already carrying the earlier migrations and their rows SHALL produce the same schema. No canonical migration SHALL establish over pre-existing rows a constraint those rows could violate, and no data backfill SHALL canonicalize an existing source-native value by inference. Where a canonical migration must alter a pre-existing relation to provide a key target, it SHALL add only a constraint that cannot fail against existing rows, and SHALL alter no row.

#### Scenario: A migration is applied twice
- **WHEN** a canonical migration is applied to a database that already records it
- **THEN** it raises that it is already applied and changes nothing

#### Scenario: A migration is applied out of order
- **WHEN** a canonical migration is applied before its prerequisite
- **THEN** it raises that the prerequisite must be applied first and changes nothing

#### Scenario: An upgrade meets a populated database
- **WHEN** the canonical migrations are applied to a database already carrying the earlier migrations with rows in them
- **THEN** every migration succeeds, no existing row is altered, and no pre-existing row acquires a canonical counterpart by inference

#### Scenario: Two build paths are compared
- **WHEN** a database built from empty through every migration is compared with one upgraded from the earlier migrations
- **THEN** the canonical relations, columns, types, constraints, indexes, triggers, and privileges are identical
