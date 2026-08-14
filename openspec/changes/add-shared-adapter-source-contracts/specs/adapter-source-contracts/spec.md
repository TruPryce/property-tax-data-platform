## ADDED Requirements

### Requirement: Provide one vendor-neutral source contract module

The adapter layer SHALL provide exactly one module, `property_tax_adapters.sources.contracts`, holding the shared `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord`. Every county adapter that needs these types SHALL import them from that module.

The module SHALL contain no county name, no county field name, no county threshold, and no county policy, in the same way the shared PACS component does. It SHALL import from the standard library only, and SHALL NOT import from `property_tax_adapters.sources.texas`, `property_tax_domain`, or `property_tax_application`.

A county adapter SHALL NOT define a local `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`, whether unprefixed or under a county-prefixed name.

The module SHALL declare a `SOURCE_CONTRACT_VERSION` integer that every constructed provenance records, so a record can be attributed to the contract that produced it.

#### Scenario: A county imports the shared types rather than defining them
- **GIVEN** the adapter library on a branch where this change is implemented
- **WHEN** each module under `sources/texas/` is parsed and its class definitions collected
- **THEN** no module defines a class named `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`
- **THEN** no module defines a county-prefixed variant of one of those three names

#### Scenario: The shared module names no county
- **GIVEN** `sources/contracts.py` parsed with `ast` and its docstrings removed
- **WHEN** its identifiers and string literals are collected
- **THEN** no county name appears among them
- **THEN** no import resolves to `property_tax_adapters.sources.texas`, `property_tax_domain`, `property_tax_application`, or a third-party package

### Requirement: Carry the source field and the original text with every value

`SourceNativeValue` SHALL carry `source_field` naming the exact field or column the value was read from, `lexical_text` holding the original text before any decoding, `value` typed `str | int | Decimal | None`, and `classification` fixed to the literal `source-native`.

A blank or whitespace-only `source_field` SHALL be rejected at construction, because a value that cannot name its source cannot be traced to one.

Storage mechanics that describe how one county decoded a value — numeric precision, numeric scale, fixed-width positions, header vectors — SHALL NOT appear on the shared value type.

#### Scenario: Reject a value that cannot name its source
- **GIVEN** a `source_field` that is empty or whitespace only
- **WHEN** `SourceNativeValue` is constructed
- **THEN** `ValueError` is raised
- **THEN** no diagnostic is produced, because a trusted-code defect is not source data

#### Scenario: Preserve the original text alongside a decoded value
- **GIVEN** a source field whose text is `00123.40` and whose decoded value is `Decimal("123.40")`
- **WHEN** the value is constructed
- **THEN** `lexical_text` equals `00123.40` exactly
- **THEN** `value` equals `Decimal("123.40")`
- **THEN** `classification` equals `source-native`

#### Scenario: A null is representable without losing the field
- **GIVEN** a source field present in the layout whose text is empty
- **WHEN** the value is constructed with `value` set to `None`
- **THEN** `source_field` still names the field
- **THEN** `value` is `None`

### Requirement: Carry only the provenance every county shares

`SourceProvenance` SHALL carry `jurisdiction_code`, `release_identifier`, `source_member_name`, `source_row_number`, `parser_contract_version`, and `layout_fingerprint`, and no other field.

`source_row_number` SHALL be a positive integer, and a nonpositive value SHALL be rejected at construction.

`jurisdiction_code` SHALL be a lowercase two-letter state prefix, a hyphen, and a county slug, and a value not matching that shape SHALL be rejected at construction.

County-specific provenance SHALL be recorded in a county-local type that holds a shared `SourceProvenance` as a field. A county type SHALL NOT subclass `SourceProvenance`, so that one county's mechanism does not become every county's obligation.

#### Scenario: Reject a nonpositive row number
- **GIVEN** a `source_row_number` of `0`
- **WHEN** `SourceProvenance` is constructed
- **THEN** `ValueError` is raised

#### Scenario: Reject a malformed jurisdiction code
- **GIVEN** a `jurisdiction_code` of `TX_Dallas`
- **WHEN** `SourceProvenance` is constructed
- **THEN** `ValueError` is raised

#### Scenario: A county records more without widening the shared type
- **GIVEN** a county that must record observed and normalized header vectors
- **WHEN** its county provenance type is constructed
- **THEN** the header vectors are attributes of the county type
- **THEN** the shared provenance it holds carries none of them
- **THEN** the county type is not a subclass of `SourceProvenance`

### Requirement: Key an appraisal source record by text

`AppraisalSourceRecord` SHALL carry `jurisdiction_code`, `source_account_id` typed `str`, `appraisal_year`, `source_family`, `source_status`, `parcel_reference` typed `str | None`, `source_native_identifiers`, `source_native_values`, and `provenance`.

`source_account_id` SHALL be text even where a county stores the identifier as an integer, so that identifiers differing only in leading zeroes or punctuation remain distinct. A blank identifier SHALL be rejected at construction.

`provenance` SHALL be required. A record SHALL NOT be constructible without it, because a source-native record whose origin is unknown is not evidence.

Each key of `source_native_values` SHALL equal the `source_field` of the value it maps to, and a disagreement SHALL be rejected at construction.

`jurisdiction_code` SHALL equal the `jurisdiction_code` of the record's provenance, and a disagreement SHALL be rejected at construction.

`source_family` and `source_status` SHALL be strings the county supplies rather than members of a shared enumeration, because the observed families are county products.

#### Scenario: Leading zeroes remain meaningful
- **GIVEN** two records for the accounts `000123` and `123` in the same release
- **WHEN** both are constructed
- **THEN** their `source_account_id` values are unequal

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

All three shared types SHALL refuse attribute assignment and attribute deletion after construction, including to private attributes.

`source_native_values` and `source_native_identifiers` SHALL be stored so that mutating the mapping the caller passed does not change the constructed record, and so that the record's mappings cannot be mutated through the record.

#### Scenario: Refuse assignment after construction
- **GIVEN** a constructed `AppraisalSourceRecord`
- **WHEN** any attribute is assigned or deleted, including one whose name begins with an underscore
- **THEN** the operation raises
- **THEN** the record's observed values are unchanged

#### Scenario: A caller's dictionary cannot reach inside a record
- **GIVEN** a dictionary passed as `source_native_values` to a constructed record
- **WHEN** the caller adds an entry to that dictionary afterwards
- **THEN** the record's `source_native_values` does not contain the added entry

### Requirement: Exclude identity and canonical meaning from shared records

The shared types SHALL NOT be able to carry an owner name, a mailing address, or a situs address. No field SHALL admit one, and the types SHALL expose no free-form payload, extras mapping, or untyped attribute through which one could be carried.

The shared types SHALL NOT introduce canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement semantics. They are source-native containers, and a value's meaning remains the county's until a later canonical layer assigns one.

#### Scenario: No field admits an identity value
- **GIVEN** the three shared types and their annotations
- **WHEN** their fields are enumerated
- **THEN** no field name or annotation admits an owner name, mailing address, or situs address
- **THEN** no field accepts an arbitrary payload, extras mapping, or untyped attribute

#### Scenario: No canonical vocabulary is introduced
- **GIVEN** `sources/contracts.py` parsed with its docstrings removed
- **WHEN** its identifiers and string literals are collected
- **THEN** no canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement vocabulary appears among them

### Requirement: Migrate existing counties without changing what they accept

Collin and Dallas SHALL be migrated onto the shared contracts, and their local copies SHALL be deleted.

Each migration SHALL preserve observable behaviour exactly: the same rows accepted, the same rows rejected, the same diagnostic codes in the same order, and the same counts. The migrated county's existing tests SHALL change only where a type name or attribute path moved, and no expectation SHALL be relaxed, deleted, or rewritten.

Before a local type is deleted, its importers SHALL be searched for. If an importer outside `libs/property-tax-adapters` exists, the migration SHALL stop and report it rather than rewrite it.

Collin's dual current and certified observation model SHALL remain county-local. One Collin account SHALL produce one shared record per observed family, so the two families remain distinct rather than merged.

#### Scenario: A behaviour change surfaces as a test failure
- **GIVEN** a migrated county whose parser now accepts a row it previously rejected
- **WHEN** that county's existing test suite runs unmodified
- **THEN** it fails
- **THEN** the migration is not complete

#### Scenario: Collin families stay separate
- **GIVEN** one Collin account observed in both the current and the certified family
- **WHEN** shared records are produced for it
- **THEN** two records exist with the same `source_account_id`
- **THEN** their `source_family` values differ
- **THEN** no value is copied between them

#### Scenario: An outside importer stops the migration
- **GIVEN** a module outside `libs/property-tax-adapters` importing a county-local shared-type copy
- **WHEN** the migration reaches the deletion step
- **THEN** the importer is reported
- **THEN** the local type is not deleted and the importer is not rewritten

### Requirement: State the boundary this change does not cross

Documentation for the shared contracts SHALL state what Issue #43 also describes and this change deliberately excludes: bounded release processing, streaming and memory bounds, and the atomic stage contract.

It SHALL state that the tasks blocked in the accepted Tarrant, Denton, and Ellis changes are unblocked by these contracts but completed in those changes rather than here.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, archive locations, or vendor licensing material.

#### Scenario: The excluded scope is named
- **GIVEN** the shared contracts document
- **WHEN** it is read
- **THEN** bounded release processing, streaming and memory bounds, and the atomic stage are each named as excluded
- **THEN** the deferred county tasks are described as unblocked here and completed elsewhere

#### Scenario: Documentation carries no source material
- **GIVEN** the shared contracts document
- **WHEN** its content is inspected
- **THEN** it contains no county bytes, production rows, owner values, addresses, layouts, credentials, archive locations, or vendor licensing material
