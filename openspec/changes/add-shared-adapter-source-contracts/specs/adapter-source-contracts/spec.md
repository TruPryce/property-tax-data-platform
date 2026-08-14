## ADDED Requirements

### Requirement: Provide one vendor-neutral source contract module

The adapter layer SHALL provide exactly one module, `property_tax_adapters.sources.contracts`, holding the shared `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` that issue #43 decision D7 approves. Every county adapter that needs these types SHALL import them from that module.

`property_tax_domain` and `property_tax_application` SHALL NOT be modified, as D7 directs.

The module SHALL contain no county name, no county field name, no county threshold, and no county policy. It SHALL import from the standard library only, and SHALL NOT import from `property_tax_adapters.sources.texas`, `property_tax_domain`, or `property_tax_application`.

No module under `sources/texas/` SHALL define a class named exactly `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`.

County-native input records and county diagnostics SHALL remain in county modules, as D7 directs. `DallasSourceProvenance`, `DallasAppraisalSourceRecord`, `CollinAppraisalSourceRecord`, `CollinObservationProvenance`, and `CollinAppraisalObservation` SHALL continue to exist. What is prohibited is a second definition of a shared shape, not a county-prefixed name.

#### Scenario: A county imports the shared types rather than redefining them
- **GIVEN** the adapter library on a branch where this change is implemented
- **WHEN** each module under `sources/texas/` is parsed and its class definitions collected
- **THEN** no module defines a class named exactly `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`
- **THEN** `DallasAppraisalSourceRecord` and `CollinAppraisalSourceRecord` are still defined

#### Scenario: The shared module names no county
- **GIVEN** `sources/contracts.py` parsed with `ast` and its docstrings removed
- **WHEN** its identifiers and string literals are collected
- **THEN** no county name appears among them
- **THEN** no import resolves to `property_tax_adapters.sources.texas`, `property_tax_domain`, `property_tax_application`, or a third-party package

### Requirement: Carry an exact source-native value with its field and optional decode detail

`SourceNativeValue` SHALL carry the fields issue #43 D7 approves: an exact `value` typed `str | int | Decimal`, an optional `lexical_text`, an exact `source_field`, optional `precision` and `scale`, and a fixed `source-native` classification.

`value` SHALL NOT admit `None`. A source field whose value is absent SHALL be expressed by omitting its entry from the record's value mapping, or in a county-local structure, rather than by constructing a value that holds no value.

A blank or whitespace-only `source_field` SHALL be rejected at construction, because a value that cannot name its source cannot be traced to one.

`lexical_text` SHALL be `None` only where the source carries no text to preserve, as when a value is decoded from a binary wrapper. Where an empty text was genuinely observed, `lexical_text` SHALL be `""` and SHALL NOT be converted to `None`.

`precision` and `scale` SHALL be supplied together or not at all.

#### Scenario: Reject a value that cannot name its source
- **GIVEN** a `source_field` that is empty or whitespace only
- **WHEN** `SourceNativeValue` is constructed
- **THEN** `ValueError` is raised
- **THEN** no diagnostic is produced, because a trusted-code defect is not source data

#### Scenario: Preserve the original text alongside a decoded value
- **GIVEN** a textual source field whose text is `00123.40` and whose decoded value is `Decimal("123.40")`
- **WHEN** the value is constructed
- **THEN** `lexical_text` equals `00123.40` exactly
- **THEN** `value` equals `Decimal("123.40")`

#### Scenario: An observed empty text stays an empty text
- **GIVEN** a source column present in the release whose observed text is empty
- **WHEN** the value is constructed
- **THEN** `lexical_text` equals `""`
- **THEN** `value` equals `""`
- **THEN** neither is converted to `None`

#### Scenario: A binary-sourced value has no lexical text
- **GIVEN** a value decoded from a fixed-width binary numeric wrapper carrying no source text
- **WHEN** the value is constructed with `lexical_text` set to `None`
- **THEN** construction succeeds
- **THEN** `source_field` still names the field the wrapper occupied

#### Scenario: Decode detail travels with the value that needed it
- **GIVEN** a value decoded from a wrapper declaring a precision and a scale
- **WHEN** the value is constructed
- **THEN** `precision` and `scale` hold the declared values
- **THEN** a value constructed with only one of them raises `ValueError`

### Requirement: Carry the provenance issue #43 D7 approves and no more

`SourceProvenance` SHALL carry `jurisdiction_code`, the caller-supplied `release_identifier` and `source_member_name`, a one-based `source_row_number`, `parser_contract_version`, and `layout_fingerprint`, together with D7's six optional fields: `table_name`, `source_family`, `source_year`, `source_status`, `observed_fields`, and `normalized_fields`. It SHALL carry no field beyond that list.

`source_row_number` SHALL be a positive integer, and a nonpositive value SHALL be rejected at construction.

`jurisdiction_code` SHALL be a lowercase two-letter state prefix, a hyphen, and a county slug, and a value not matching that shape SHALL be rejected at construction. It SHALL NOT be pinned to a single county by type.

A county that keeps its own provenance type SHALL hold a shared `SourceProvenance` as a field rather than subclassing it, so that one county's mechanism does not become every county's obligation.

#### Scenario: The provenance matches the approved field list
- **GIVEN** the declared fields of `SourceProvenance`
- **WHEN** they are enumerated
- **THEN** they are exactly the six required and six optional fields issue #43 D7 approves
- **THEN** no additional field has been introduced

#### Scenario: Reject a nonpositive row number
- **GIVEN** a `source_row_number` of `0`
- **WHEN** `SourceProvenance` is constructed
- **THEN** `ValueError` is raised

#### Scenario: Reject a malformed jurisdiction code
- **GIVEN** a `jurisdiction_code` of `TX_Dallas`
- **WHEN** `SourceProvenance` is constructed
- **THEN** `ValueError` is raised

#### Scenario: A county records its own mechanism without subclassing
- **GIVEN** a county that keeps a county-native provenance type
- **WHEN** that type is constructed
- **THEN** it holds a shared `SourceProvenance` as a field
- **THEN** it is not a subclass of `SourceProvenance`

### Requirement: Identify an appraisal source record without forcing an unapproved key

`AppraisalSourceRecord` SHALL carry `jurisdiction_code`, an optional approved `source_account_id`, `source_native_identifiers`, `appraisal_year`, `source_family`, an optional `source_status`, an optional `parcel_reference`, `source_native_values`, and the shared `provenance`.

`source_family` SHALL be optional. Issue #43 D7 approves it as required; this change proposes it optional because no approved Dallas value exists and D7's own rules assign Dallas only its account identifier and parcel reference. Merging this change is what accepts that supersession.

Where a county has an approved account identifier, `source_account_id` SHALL be text even if the county stores it as an integer, so identifiers differing only in leading zeroes or punctuation remain distinct.

Where a county's accepted contract does not approve an account key, `source_account_id` SHALL be `None`, and the county's candidate identifiers SHALL be preserved in `source_native_identifiers` under their exact source names as distinct entries with no equivalence asserted between them. A record SHALL NOT promote an identifier its county contract prohibits promoting.

An empty string SHALL be rejected in `source_account_id`, `source_family`, `source_status`, and `parcel_reference`, so absence is expressed as `None` and never as `""`.

`provenance` SHALL be required. A record SHALL NOT be constructible without it, because a source-native record whose origin is unknown is not evidence.

Each key of `source_native_values` SHALL equal the `source_field` of the value it maps to, and a disagreement SHALL be rejected at construction.

`jurisdiction_code` SHALL equal the `jurisdiction_code` of the record's provenance, and a disagreement SHALL be rejected at construction.

#### Scenario: Leading zeroes remain meaningful
- **GIVEN** two records for the accounts `000123` and `123` in the same release
- **WHEN** both are constructed
- **THEN** their `source_account_id` values are unequal

#### Scenario: A county with no approved account key promotes neither candidate
- **GIVEN** a county whose accepted contract forbids declaring either candidate identifier an account key
- **WHEN** its record is constructed
- **THEN** `source_account_id` is `None`
- **THEN** both candidate identifiers appear in `source_native_identifiers` under their exact source names
- **THEN** the two entries are distinct and neither is recorded as equivalent to the other

#### Scenario: Reject an empty string where absence is meant
- **GIVEN** a `source_account_id` of `""`
- **WHEN** the record is constructed
- **THEN** `ValueError` is raised

#### Scenario: Reject a record whose value map disagrees with itself
- **GIVEN** a `source_native_values` entry keyed `Total_Value` whose value declares `source_field` of `Land_Value`
- **WHEN** the record is constructed
- **THEN** `ValueError` is raised

#### Scenario: Reject a record whose jurisdiction disagrees with its provenance
- **GIVEN** a record declaring `tx-ellis` and a provenance declaring `tx-denton`
- **WHEN** the record is constructed
- **THEN** `ValueError` is raised

#### Scenario: A record cannot be constructed without provenance
- **GIVEN** a record constructed with every field except `provenance`
- **WHEN** construction is attempted
- **THEN** it fails
- **THEN** no record instance is produced

### Requirement: Keep constructed records immutable

All three shared types SHALL refuse attribute assignment and attribute deletion after construction, including attributes whose names begin with an underscore.

`source_native_values` and `source_native_identifiers` SHALL be stored so that mutating the mapping the caller passed does not change the constructed record, and so the record's mappings cannot be mutated through the record.

#### Scenario: Refuse assignment after construction
- **GIVEN** a constructed `AppraisalSourceRecord`
- **WHEN** any attribute is assigned or deleted, including one whose name begins with an underscore
- **THEN** the operation raises
- **THEN** the record's observed values are unchanged

#### Scenario: A caller's mapping cannot reach inside a record
- **GIVEN** a dictionary passed as `source_native_values` to a constructed record
- **WHEN** the caller adds an entry to that dictionary afterwards
- **THEN** the record's `source_native_values` does not contain the added entry

### Requirement: State the privacy boundary the shared types can actually hold

The shared types SHALL define no field naming an owner, a mailing address, or a situs address, and SHALL expose no untyped or free-form payload attribute, extras mapping, or arbitrary metadata attribute.

This is the whole of the guarantee. The shared types SHALL NOT be documented or tested as preventing identity data from reaching a record, because `source_native_values` is keyed by county-chosen source fields and at least one accepted county contract requires retaining unknown source columns. Keeping identity out of records SHALL remain an obligation of each county contract, enforced where the county knows its columns.

The shared types SHALL NOT introduce canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement semantics. They are source-native containers, and a value's meaning remains the county's until a later canonical layer assigns one.

#### Scenario: No named identity field and no open payload
- **GIVEN** the three shared types and their annotations
- **WHEN** their fields are enumerated
- **THEN** no field name or annotation names an owner, mailing address, or situs address
- **THEN** no field accepts an arbitrary payload, extras mapping, or untyped attribute

#### Scenario: The weaker guarantee is not overstated
- **GIVEN** a county that places an unknown source column into `source_native_values`
- **WHEN** the record is constructed
- **THEN** construction succeeds, because the shared types cannot judge a county's source fields
- **THEN** no shared test or document claims that identity data cannot reach a record

#### Scenario: No canonical vocabulary is introduced
- **GIVEN** `sources/contracts.py` parsed with its docstrings removed
- **WHEN** its identifiers and string literals are collected
- **THEN** no canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement vocabulary appears among them

### Requirement: Migrate existing counties case-for-case

Dallas and Collin SHALL be migrated onto the shared contracts, and their duplicate definitions SHALL be deleted.

Each migration SHALL preserve observable behaviour exactly: the same rows accepted, the same rows rejected, the same diagnostic codes in the same order, and the same counts. The migrated county's existing tests SHALL change only where a type name or attribute path moved, and no expectation SHALL be relaxed, deleted, or rewritten. No existing Dallas or Collin case SHALL be lost, as issue #43 D6 and D7 both require.

Dallas SHALL populate its approved account identifier and parcel reference, SHALL carry its observed and normalized header vectors on the shared provenance, and SHALL continue to emit `""` for an extra column whose observed text is empty.

Before a duplicate definition is deleted, its importers SHALL be searched for. If an importer outside `libs/property-tax-adapters` exists, the migration SHALL stop and report it rather than rewrite it.

Collin's dual current and certified observation model SHALL remain county-local. One Collin account SHALL produce one shared record per observed family, with no deduplication, no family collapse, and no value copied between families.

#### Scenario: A behaviour change surfaces as a test failure
- **GIVEN** a migrated county whose parser now accepts a row it previously rejected
- **WHEN** that county's existing test suite runs unmodified
- **THEN** it fails
- **THEN** the migration is not complete

#### Scenario: An empty Dallas extra column survives migration unchanged
- **GIVEN** a Dallas release with an extra column whose observed text is empty
- **WHEN** the migrated parser produces a vendor-neutral record
- **THEN** that column's `lexical_text` is `""`
- **THEN** that column's `value` is `""`

#### Scenario: Collin families stay separate
- **GIVEN** one Collin account observed in both the current and the certified family
- **WHEN** shared records are produced for it
- **THEN** two separate records exist
- **THEN** no value is copied between them
- **THEN** neither `prop_id` nor `geo_id` appears as `source_account_id`

#### Scenario: An outside importer stops the migration
- **GIVEN** a module outside `libs/property-tax-adapters` importing a duplicate definition
- **WHEN** the migration reaches the deletion step
- **THEN** the importer is reported
- **THEN** the definition is not deleted and the importer is not rewritten

### Requirement: State the boundary this change does not cross

Documentation for the shared contracts SHALL map each field to the issue #43 D7 approved list, and SHALL state plainly that `source_family` on the record is the single field proposed as optional against that approved list, with the reason.

It SHALL state that this change implements D7 only, and that #43 decisions D1 through D6 and D8 remain open there: the bounded production input contract, validation ordering, the release-rejection boundary, bounded cross-row checks, `LocalExecutor` resource limits, the disposition of the small-input `bytes | str` helper, and the progress-event contract.

It SHALL state that the tasks blocked in the accepted Tarrant, Denton, and Ellis changes are unblocked by these contracts but completed in those changes rather than here.

It SHALL record the open tension that an accepted county contract requires retaining unknown source columns, so unknown columns reach vendor-neutral records, and that closing this belongs to that county's contract.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, archive locations, or vendor licensing material.

#### Scenario: The supersession is stated rather than buried
- **GIVEN** the shared contracts document
- **WHEN** it is read
- **THEN** each field is mapped to the issue #43 D7 approved list
- **THEN** the optional `source_family` is named as the single supersession, with its reason

#### Scenario: The excluded scope is named
- **GIVEN** the shared contracts document
- **WHEN** it is read
- **THEN** it states that D7 alone is implemented
- **THEN** #43 decisions D1 through D6 and D8 are each named as still open
- **THEN** the deferred county tasks are described as unblocked here and completed elsewhere

#### Scenario: The privacy tension is recorded rather than hidden
- **GIVEN** the shared contracts document
- **WHEN** its privacy section is read
- **THEN** it states the guarantee as no named identity field and no untyped payload
- **THEN** it records that retained unknown columns reach vendor-neutral records under an accepted county contract

#### Scenario: Documentation carries no source material
- **GIVEN** the shared contracts document
- **WHEN** its content is inspected
- **THEN** it contains no county bytes, production rows, owner values, addresses, layouts, credentials, archive locations, or vendor licensing material
