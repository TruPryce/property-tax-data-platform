# Design: the canonical appraisal record model

## Context

Issue #106 lists twelve decisions that must be settled before implementation.
All are recorded here as D1 through D12, each with the evidence supporting it and
the alternatives rejected.

**None is accepted yet.** The repository's approval event is the human merge of
this planning pull request, so every decision below is proposed and requires that
merge.

Existing SQL, adapter dataclasses, and source column names are read here as
*existing representations*, never as the authority for canonical semantics.

## Decisions

### D1 (proposed by this change, requires human merge): an account identity is not an account snapshot, and one is constructible only where a county approved a key

`AccountIdentity` is a **stable business identity**: the canonical `Jurisdiction`
from task 2.1 and a county-contract-approved `source_account_id`. Nothing else.
Two counties emitting one source identifier produce two accounts, because the
jurisdiction is inside the identity.

`AccountSnapshot` is a **release-scoped snapshot**: an `AccountIdentity`, a
`ReleaseIdentity`, and the lineage that produced it. Its identity is exactly that
pair. Tax year, release kind, and the source-supplied release identifier are not
restated — `ReleaseIdentity` carries them, and a second copy of a fact is two
things that must agree.

`source_as_of` is recorded **observation metadata on the snapshot, not identity**.
Release and tax year are both inside `ReleaseIdentity`, and an as-of value is a
property of the release rather than of one account within it, so including it in
the snapshot key would discriminate nothing while storing a second copy of a
release-level fact.

The accepted normalization contract stated snapshot grain as "logical release,
tax year, and source as-of value", so this decision **amends it directly** rather
than contradicting it silently: the active bootstrap delta now states the grain
as the account identity and its logical release, records the as-of value as
observation metadata, gives this reason, and carries a scenario fixing the
relationship between two snapshots that differ only by it. A plan that changed
the rule while leaving the accepted contract asserting the old one would be the
two-representations defect in specification form.

If evidence later shows one release carrying several as-of values, that is a
change to this decision and not a gap in it.

The hard case is a county whose account key is not approved. Collin's accepted
contract is explicit: the system "MUST NOT approve `prop_id` as account identity
until duplicate groups are shown to contain consistent account-level facts."
Denton and Ellis have approved `prop_id`; Dallas has `ACCOUNT_NUM`; Tarrant has
`Account_Num`; Collin has nothing yet.

**Where that rule is enforced is not the domain, and an earlier revision of this
design put it there.** A generic constructor receives a jurisdiction and a
string. Collin's unapproved `prop_id` of `"123"`, a Denton owner sequence of
`"123"`, and Denton's approved `prop_id` of `"123"` arrive identically, and no
amount of validation distinguishes them without importing a county contract the
domain must not import. A rule the constructor cannot enforce is not a rule; it
is a sentence that will be believed.

This is the boundary already settled for Tarrant release discrimination, and the
same answer applies. The domain validates the identifier's lexical contract. The
county-aware mapping boundary, which knows the contract, decides whether a county
has an approved key and refuses to construct an identity where it does not — so a
county without one produces no canonical account and no snapshot, and its rows
stay at source grain with lineage. There is still no provisional or partial
identity to reach for; what changed is which layer refuses.

**Rejected — a nullable or provisional account identity for unresolved counties.**
It makes "we do not know this account's key" and "this account's key is X"
inhabit one type, and every consumer then has to remember which it holds.

**Rejected — the physical source row as identity.** `(prop_id, owner_sequence)` is
Denton's *owner-row* grain, and a row number is not a business identity. Making
one the account key is precisely the mistake the normalization contract's
duplicate-group scenarios exist to prevent. The mapping boundary enforces this,
for the reason above: the domain cannot see which field a string came from.

**Rejected — restating tax year on the snapshot.** It reads as convenient and is
a second copy of what `ReleaseIdentity` already fixes.

### D13 (proposed by this change, requires human merge): provenance is the only release authority, and a child must agree with its parent

A record carrying lineage carries no `ReleaseIdentity` beside it. `DomainProvenance`
already composes one, and an earlier revision of this design gave `AccountSnapshot`
both — in a change whose stated purpose is removing facts stored twice. A snapshot
whose direct release disagreed with its provenance release would have been
constructible, and nothing would have noticed.

The provenance is the authority. A record needing its release derives it from
there.

Where a record carries both a parent and its own provenance, construction requires
that the two provenance releases are equal. A child observed in a different release
than the snapshot it hangs from is not a child of that snapshot, and admitting one
would let a Silver load assemble an account from rows that never appeared together.

**Rejected — keeping both and documenting that they must agree.** Documentation is
the enforcement mechanism this whole model exists to replace.

**Rejected — deriving a child's provenance from its parent.** A child reached
without its parent would then have no lineage, and children are exactly what a
query selects.

### D2 (proposed by this change, requires human merge): there is no Owner, only an owner observation and an association

The domain has no independently identifiable person or entity. An owner name and
a mailing address are what a county printed, and treating them as identity would
invent cross-release and cross-county person resolution that no contract
establishes and that this change explicitly excludes.

Two types, both **child** shapes:

- `OwnerObservation` — a **child observation**: the owner name and mailing
  address as one release recorded them, with lineage. It has no identity beyond
  the observation.
- `OwnerAssociation` — an **association/allocation**: an `AccountSnapshot`, an
  `OwnerObservation`, the source discriminator where a county contract approves
  one, and `ownership_percentage` as an exact `Decimal | None`.

Owner-scoped value and exemption allocations hang off the **association**, never
off the snapshot. Denton requires "ownership percentage and owner-scoped value and
exemption allocations without deriving an account roll-up until an approved rule
exists"; Ellis requires the same and adds that the adapter "does not deduplicate,
sum, or select an arbitrary row as the account total."

Placing allocations on the association is what makes that structural. An account
total assembled from owner allocations has no field to occupy, so producing one
is not a rule an implementer must recall — it is a value with nowhere to go.

The source discriminator is optional because Collin has none approved. A
constructor requiring one would make the model unusable for exactly the county
whose contract says its grain is unresolved.

**Rejected — a global `Owner` keyed by normalized name and address.** It is the
one thing that would make deduplication look correct while being unfounded.

**Rejected — owner fields inlined on the snapshot.** It forces one-to-many source
records into one account row, which the normalization contract forbids in terms.

### D3 (proposed by this change, requires human merge): market, appraised, and assessed are account-snapshot observations; taxable is a separate record at taxing-unit grain

`ValueKind` is a closed vocabulary of exactly `market`, `appraised`, and
`assessed`. `AppraisalValueObservation` is a **child observation** of an
`AccountSnapshot` carrying a kind and an exact `Decimal` amount.

Taxable is deliberately not a fourth member. Dallas's accepted contract requires
that where it "supplies multiple jurisdiction-specific taxable values … each
published value retains its jurisdiction and basis and no arbitrary jurisdiction
is selected as a single property-wide taxable value." A taxable member on an
account-snapshot value would make that forbidden property-wide figure the easiest
value in the model to write.

`TaxableValueObservation` is therefore its own **child observation**, at
`(AccountSnapshot, TaxingUnitObservation)` grain, carrying its amount and its
source-native basis. A property-wide taxable value is not refused by a check; it
has no shape.

Amounts are `Decimal`, and binary floating point is rejected outright: a monetary
value that changes when it is summed is not the value the county published.

Nothing maps a source label into a kind. Tarrant must "preserve Tarrant total,
appraised, land, improvement, agricultural, and other value fields as
source-native values until official definitions and measured arithmetic approve
each canonical mapping," and adds that "an inequality or field name alone MUST
NOT establish semantic equivalence." Dallas must leave "canonical market,
appraised, assessed, and taxable value absent" while `TOT_VAL` is unresolved
under **#58**. Denton and Ellis may map only "separately documented" values "to
semantically matching canonical value types."

So the mapping lives at the county-aware adapter boundary, exactly as release-kind
mapping does, and the domain supplies the vocabulary without a route into it.
Land, improvement, agricultural, timber, productivity, and homestead-cap values
are **not** canonical kinds: no accepted contract establishes their cross-county
equivalence, and `ten_percent_cap` is named in Denton's contract as a cap amount
that must not be treated as a capped value "solely because of its name."

**Rejected — a `taxable` value kind on the snapshot.** It makes the one figure
Dallas's contract forbids the most natural thing to produce.

**Rejected — an open string kind.** It would unblock every county today by letting
an adapter write its own label through, which is the inference this refuses.

**Rejected — `float` amounts.** Rounding is not a property a source value has.

### D4 (proposed by this change, requires human merge): exemptions are observations with source-native classification and an explicit scope

No accepted contract establishes a cross-county exemption vocabulary. A search of
every county contract finds no approved exemption code list, so a canonical
exemption enum would be invented rather than derived.

`ExemptionObservation` is a **child observation** carrying the county's own label
verbatim, an optional exact `Decimal` amount where a source supplies one, and an
explicit `ExemptionScope` of `account` or `owner_association`. An owner-scoped
exemption references the association it belongs to; an account-scoped one does
not.

The scope is required rather than inferred from whether an association reference
is present, so an exemption whose scope nobody determined cannot be constructed
by omission.

Relationship to taxable values is deliberately **not** modelled as a computation.
No contract approves an arithmetic from exemptions to a taxable figure, and
deriving one would be exactly the inference #58 and #92 exist to prevent.

**Rejected — a canonical `ExemptionKind` enum.** Every county label would have to
be mapped on no evidence, and the enum would grow one county at a time.

**Rejected — an open-string canonical classification.** An open string that lives
in the domain reads as canonical while carrying county vocabulary, which is worse
than keeping the label plainly source-native.

### D5 (proposed by this change, requires human merge): the taxing entity is a `TaxingUnitObservation`, never a `Jurisdiction`

Task 2.1's `Jurisdiction` is the appraisal district that publishes a roll —
`tx-collin`. The child record the normalization contract calls "jurisdiction" is a
different thing entirely: a taxing entity such as a school district, city, or
county tax unit, several of which apply to one account.

Overloading one name for both is how a later reader concludes that a taxable
value's jurisdiction is the appraisal district. The taxing entity is named
`TaxingUnitObservation`, using the Texas statutory term, and no type in this model
is called `Jurisdiction` except the promoted one.

It is a **child observation**, not a stable identity: it carries the county's own
unit code and name, and no canonical cross-county taxing-unit registry is
proposed, because none is established. Its grain is per account snapshot, and a
`TaxableValueObservation` references one.

**Rejected — reusing `Jurisdiction`.** Two meanings in one type is the defect this
whole vocabulary exists to remove.

**Rejected — a canonical taxing-unit registry.** Texas has thousands, and no
accepted contract enumerates or classifies them.

### D6 (proposed by this change, requires human merge): land is a child observation with no business identity

`LandObservation` is a **child observation** of an `AccountSnapshot`. It carries
an optional source-approved discriminator, an optional exact `Decimal` area with
a required source-native unit where an area is present, an optional source-native
land classification, and provenance.

No universal land natural key is invented. No accepted contract approves one, and
#92 owns Dallas child keys. The discriminator is optional so a valid observation
survives without one, and its absence means the child has no stable cross-release
business identity — which is a true statement about the source rather than a gap.

An area without its unit is unconstructible: a bare number is not a measurement,
and units differ across counties.

**Rejected — a synthetic child key from row order.** A sequence number is a fact
about a file, and treating it as identity is what #92 exists to decide.

### D7 (proposed by this change, requires human merge): improvements follow the same discipline

`ImprovementObservation` is a **child observation** with an optional
source-approved discriminator, an optional source-native improvement type, an
optional year built, an optional exact `Decimal` area with a required unit, and
provenance.

A sequence number, row number, building number, or physical order is **not**
treated as stable business identity. No accepted county contract establishes one,
and inferring identity from ordering is the specific error that would make later
releases appear to renumber a county's buildings.

**Rejected — reusing one `ChildObservation` type for land and improvements.** They
carry different facts, and a shared shape with mostly-empty fields is the
mega-record this model exists to avoid.

### D8 (proposed by this change, requires human merge): geometry is enrichment, carried as bytes with a required CRS and no geospatial dependency

`GeometryObservation` is an **enrichment**: an encoding (`wkb` or `wkt`), the
payload as `bytes` or `str`, a required `crs` identifier as the source stated it,
and provenance. The domain parses no geometry, validates no topology, and imports
nothing — no PostGIS, GeoAlchemy, shapely, GDAL, or shapefile library.

The CRS is required because Rockwall's contract requires validating "coordinate
reference evidence" and quarantining a layer whose PRJ component is "absent,
mismatched, or unsafe." Geometry whose coordinate system is unknown is not
geometry; it is numbers.

It is classified as enrichment rather than as a child of the roll for a specific
reason. Rockwall's public source is a PACS-derived GIS shapefile subset and not a
full appraisal roll, and its contract keeps Rockwall out of the complete
six-county publication. A geometry attached to an account must not be read as
evidence that a complete appraisal record exists for it.

**Rejected — a typed geometry object.** It requires a library, and this change
adds no runtime dependency.

**Rejected — optional CRS.** It admits the exact ambiguity Rockwall's contract
requires quarantining.

### D9 (proposed by this change, requires human merge): situs, legal description, and mailing address are bounded value objects, and representation is not permission

`SitusAddress`, `MailingAddress`, and `LegalDescription` are bounded value
objects, each with named fields and no free-form payload.

`MailingAddress` composes onto `OwnerObservation`; `SitusAddress` and
`LegalDescription` compose onto `AccountSnapshot`. They are direct compositions
rather than separate child records because no contract gives any of them
independent grain — one snapshot has one situs and one legal description as
observed.

Modelling them enables nothing. Owner, mailing-address, and situs publication
policy is owned by **#92** and enforced by `silver.field_publication_policy`,
which is default-deny and requires a named approver, an approval time, and a
review reference. Dallas's `EXCLUDE_OWNER` marker and Denton's and Tarrant's
sensitivity classifications are unaffected by anything here. The capability states
that explicitly, and a test asserts that no type in this model carries a
publication flag, permission, or visibility field — because the way this decision
goes wrong is a `publishable: bool` that looks like a convenience.

**Rejected — deferring these entirely.** The normalization contract lists situs,
legal description, and mailing address among the data to normalize, and omitting
them would leave adapters with nowhere canonical to put facts they already hold.

**Rejected — a single free-form address string.** It is the payload field this
model refuses everywhere else.

### D10 (proposed by this change, requires human merge): every observation carries `DomainProvenance`; identities do not

`DomainProvenance` from task 2.1 is the only lineage model. This change adds none.

Identities do not carry provenance: an identity is a name, not something observed
at a moment. `AccountIdentity` and `ValueKind` have none. Every snapshot,
observation, association, and enrichment carries one directly.

Several canonical facts derived from one source row hold provenance values that
are *equal* — same release, same artifact, same member, same row number — so
sharing lineage costs nothing and no fact is ever orphaned from its own. Nothing
restates jurisdiction, tax year, release kind, or release identifier: those live
inside the `ReleaseIdentity` that `DomainProvenance` already composes.

**Rejected — provenance only on the snapshot, with children inheriting.** A child
observation reached without its parent then has no lineage, and children are
exactly what a Silver query selects.

### D11 (proposed by this change, requires human merge): every type is classified, and the classification is asserted

Each record is exactly one of: **stable business identity**, **release-scoped
snapshot**, **child observation**, **association/allocation**, or **enrichment**.

| type | classification |
|---|---|
| `AccountIdentity` | stable business identity |
| `AccountSnapshot` | release-scoped snapshot |
| `OwnerObservation` | child observation |
| `OwnerAssociation` | association/allocation |
| `AppraisalValueObservation` | child observation |
| `TaxableValueObservation` | child observation |
| `ExemptionObservation` | child observation |
| `TaxingUnitObservation` | child observation |
| `LandObservation` | child observation |
| `ImprovementObservation` | child observation |
| `GeometryObservation` | enrichment |
| `OwnerValueAllocation` | association/allocation |

`SitusAddress`, `MailingAddress`, and `LegalDescription` are **not records** and
are deliberately outside this classification. They have no grain, carry no
provenance, and exist only composed onto something that does. An earlier revision
listed them in the table as "composed value objects", which is not one of the five
members, so the classification contract could not be satisfied as written. The
exclusion is now explicit in the capability, the mapping, and the test that
asserts it.

The classification is exposed in the capability and asserted by a test rather
than left in a comment, because its purpose is to stop a Silver primary key from
becoming domain semantics later. A reader deciding whether a table needs a stable
key must be able to read the answer rather than infer it.

### D12 (proposed by this change, requires human merge): the mapping to task 3.4 is documented, and no SQL is chosen

Task 3.4 must be able to answer seven questions from this model without inventing
semantics. It is documented, not implemented: no table, column, surrogate key,
index, or DDL is chosen here.

| question | answer this model supplies |
|---|---|
| What is the parent key? | `AccountIdentity` — jurisdiction plus approved source account identifier |
| What is snapshot grain? | `(AccountIdentity, ReleaseIdentity)` |
| Which children are one-to-many? | owner associations, appraisal values, taxable values, exemptions, taxing units, land, improvements |
| Which identities are stable? | `AccountIdentity` alone; everything else is snapshot, observation, association, or enrichment |
| Which rows are observations only? | every `*Observation`, and every `OwnerAssociation` |
| Where does `DomainProvenance` attach? | every snapshot, observation, association, and enrichment; never an identity |
| What never enters canonical Silver? | unmapped source-native values and labels — Dallas `TOT_VAL` and components under #58, Tarrant's unapproved value fields, county exemption labels with no canonical classification, and any account whose county key is unapproved |

**Rejected — choosing surrogate keys or table shapes now.** That is task 3.4's
work, and doing it here would reintroduce the coupling this task exists to
prevent.

## Deliberately unresolved

None of these blocks implementation; each is encoded as conservative behaviour
the model already supports.

- **#58** — Dallas `TOT_VAL` and components stay source-native, and no route maps
  a source label into a `ValueKind`.
- **#92** — no Dallas child key, no PACS roll-up, no account total from owner
  allocations, no publication permission.
- **#59** — Collin produces no `AccountIdentity` until its key is approved, and no
  constructor demands a discriminator its contract has not established.
- **#60** — Dallas parent and child records are representable with provenance and
  without invented child identity.
