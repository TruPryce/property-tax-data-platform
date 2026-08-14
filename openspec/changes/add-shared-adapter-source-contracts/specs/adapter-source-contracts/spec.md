## ADDED Requirements

### Requirement: Provide one vendor-neutral source contract module

The adapter layer SHALL provide exactly one module, `property_tax_adapters.sources.contracts`, holding the shared `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord`. Every county adapter that needs these types SHALL import them from that module.

The module SHALL contain no county name, no county field name, no county threshold, and no county policy. It SHALL import from the standard library only, and SHALL NOT import from `property_tax_adapters.sources.texas`, `property_tax_domain`, or `property_tax_application`.

No module under `sources/texas/` SHALL define a class named exactly `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`.

County-native types SHALL remain permitted and are required by the accepted county contracts. `DallasSourceProvenance`, `DallasAppraisalSourceRecord`, `CollinAppraisalSourceRecord`, `CollinObservationProvenance`, and `CollinAppraisalObservation` are existing examples that SHALL continue to exist. What is prohibited is a second definition of a shared shape, not a county-prefixed name.

The module SHALL declare a `SOURCE_CONTRACT_VERSION` integer, and `SourceProvenance` SHALL carry a `source_contract_version` field defaulted to it, so a record can be attributed to the contract that produced it.

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

### Requirement: Carry the source field with every value and the source text where one exists

`SourceNativeValue` SHALL carry `source_field` naming the exact field or column the value was read from, `lexical_text` typed `str | None`, `value` typed `str | int | Decimal | None`, and `classification` fixed to the literal `source-native`.

A blank or whitespace-only `source_field` SHALL be rejected at construction, because a value that cannot name its source cannot be traced to one.

`lexical_text` SHALL hold the original text where the source is textual. It SHALL be `None` only where the source has no text to preserve, as when a value is decoded from a binary wrapper. It SHALL NOT be an empty string standing in for absence.

Storage mechanics describing how one county decoded a value — numeric precision, numeric scale, fixed-width positions, header vectors — SHALL NOT appear on the shared value type.

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

#### Scenario: A binary-sourced value has no lexical text
- **GIVEN** a value decoded from a fixed-width binary numeric wrapper carrying no source text
- **WHEN** the value is constructed with `lexical_text` set to `None`
- **THEN** construction succeeds
- **THEN** `source_field` still names the field the wrapper occupied

#### Scenario: Absence is not an empty string
- **GIVEN** a `lexical_text` of `""`
- **WHEN** the value is constructed
- **THEN** `ValueError` is raised

### Requirement: Carry only the provenance every county shares

`SourceProvenance` SHALL carry `jurisdiction_code`, `release_identifier`, `source_member_name`, `source_row_number`, `parser_contract_version`, `layout_fingerprint`, and `source_contract_version`, and no other field.

`source_row_number` SHALL be a positive integer, and a nonpositive value SHALL be rejected at construction.

`jurisdiction_code` SHALL be a lowercase two-letter state prefix, a hyphen, and a county slug, and a value not matching that shape SHALL be rejected at construction. It SHALL NOT be pinned to a single county by type.

County-specific provenance SHALL be recorded in a county-native type holding a shared `SourceProvenance` as a field. A county type SHALL NOT subclass `SourceProvenance`, so that one county's mechanism does not become every county's obligation.

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
- **WHEN** its county-native provenance type is constructed
- **THEN** the header vectors are attributes of the county type
- **THEN** the shared provenance it holds carries none of them
- **THEN** the county type is not a subclass of `SourceProvenance`

### Requirement: Identify an appraisal source record without forcing an unapproved key

`AppraisalSourceRecord` SHALL carry `jurisdiction_code`, `source_account_id` typed `str | None`, `appraisal_year`, `source_family` typed `str | None`, `source_status` typed `str | None`, `parcel_reference` typed `str | None`, `source_native_identifiers`, `source_native_values`, and `provenance`.

Where a county has an approved account identifier, `source_account_id` SHALL be text even if the county stores it as an integer, so identifiers differing only in leading zeroes or punctuation remain distinct.

Where a county's accepted contract does not approve an account key, `source_account_id` SHALL be `None`, and the county's candidate identifiers SHALL be preserved in `source_native_identifiers` under their exact source names as distinct entries with no equivalence asserted between them. A record SHALL NOT promote an identifier its county contract prohibits promoting.

An empty string SHALL be rejected in every nullable text field, so absence is expressed as `None` and never as `""`.

`provenance` SHALL be required. A record SHALL NOT be constructible without it, because a source-native record whose origin is unknown is not evidence.

Each key of `source_native_values` SHALL equal the `source_field` of the value it maps to, and a disagreement SHALL be rejected at construction.

`jurisdiction_code` SHALL equal the `jurisdiction_code` of the record's provenance, and a disagreement SHALL be rejected at construction.

`source_family` and `source_status` SHALL be county-supplied strings rather than members of a shared enumeration, and SHALL be `None` where the county classifies neither.

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

### Requirement: Migrate existing counties without changing what they accept

Dallas and Collin SHALL be migrated onto the shared contracts, and their duplicate definitions SHALL be deleted.

Each migration SHALL preserve observable behaviour exactly: the same rows accepted, the same rows rejected, the same diagnostic codes in the same order, and the same counts. The migrated county's existing tests SHALL change only where a type name or attribute path moved, and no expectation SHALL be relaxed, deleted, or rewritten. No existing Dallas contract case SHALL be lost.

Before a duplicate definition is deleted, its importers SHALL be searched for. If an importer outside `libs/property-tax-adapters` exists, the migration SHALL stop and report it rather than rewrite it.

Collin's dual current and certified observation model SHALL remain county-local. One Collin account SHALL produce one shared record per observed family, with no deduplication and no value copied between families.

#### Scenario: A behaviour change surfaces as a test failure
- **GIVEN** a migrated county whose parser now accepts a row it previously rejected
- **WHEN** that county's existing test suite runs unmodified
- **THEN** it fails
- **THEN** the migration is not complete

#### Scenario: Collin families stay separate
- **GIVEN** one Collin account observed in both the current and the certified family
- **WHEN** shared records are produced for it
- **THEN** two separate records exist
- **THEN** their `source_family` values differ
- **THEN** no value is copied between them

#### Scenario: An outside importer stops the migration
- **GIVEN** a module outside `libs/property-tax-adapters` importing a duplicate definition
- **WHEN** the migration reaches the deletion step
- **THEN** the importer is reported
- **THEN** the definition is not deleted and the importer is not rewritten

### Requirement: State the boundary this change does not cross

Documentation for the shared contracts SHALL state that this change implements Issue #43 required decision 7 only, and that required decisions 1 through 6 and 8 remain open in that issue: the bounded production input contract, validation ordering, the release-rejection boundary, bounded cross-row checks, `LocalExecutor` resource limits, the disposition of the small-input `bytes | str` helper, and the progress-event contract.

It SHALL state that the tasks blocked in the accepted Tarrant, Denton, and Ellis changes are unblocked by these contracts but completed in those changes rather than here.

It SHALL record the open tension that an accepted county contract requires retaining unknown source columns, so unknown columns reach vendor-neutral records, and that closing this belongs to that county's contract.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, archive locations, or vendor licensing material.

#### Scenario: The excluded scope is named
- **GIVEN** the shared contracts document
- **WHEN** it is read
- **THEN** it states that required decision 7 alone is implemented
- **THEN** required decisions 1 through 6 and 8 are each named as still open
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
