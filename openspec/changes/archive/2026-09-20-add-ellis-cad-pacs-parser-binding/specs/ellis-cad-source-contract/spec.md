## ADDED Requirements

### Requirement: Bind Ellis to the shared PACS component without forking it

The Ellis adapter SHALL declare a versioned Ellis mapping using the shared component in `property_tax_adapters.sources.pacs` and MUST NOT copy, fork, or reimplement its position slicing, layout validation, or fingerprint. It MUST NOT introduce PACS or Ellis vocabulary into `property_tax_domain` or `property_tax_application`.

The existing `ELLIS_SOURCE` registry definition already imports both packages and SHALL be preserved unchanged, so the boundary is that neither package is modified and neither gains PACS or Ellis parser vocabulary.

#### Scenario: Reuse the shared slicing mechanics
- **GIVEN** the shared PACS component and the Ellis mapping
- **WHEN** a maintainer reviews the Ellis adapter module
- **THEN** the module constructs its layout from the shared field and layout types
- **THEN** the module defines no position-slicing, layout-validation, or fingerprint logic of its own

### Requirement: Establish Ellis compatibility by its own fingerprint

Ellis compatibility SHALL be established by an explicit Ellis layout fingerprint rather than by PACS naming, by filename, or by equivalence with Denton. The adapter SHALL carry an expected Ellis fingerprint and SHALL compare the declared mapping against it before parsing.

A layout whose fingerprint does not match the expected Ellis value SHALL be rejected with `unsupported_layout_fingerprint`. Sharing a vendor with Denton SHALL NOT be treated as evidence of schema compatibility, and the Ellis and Denton fingerprints SHALL be independent values that MUST NOT be assumed equal.

#### Scenario: Accept the approved Ellis fingerprint
- **GIVEN** the declared Ellis mapping
- **WHEN** the adapter compares its fingerprint with the expected Ellis value
- **THEN** the two match
- **THEN** parsing proceeds

#### Scenario: Refuse a layout carrying another county's fingerprint
- **GIVEN** a caller-supplied expected fingerprint taken from the Denton layout
- **WHEN** the caller invokes `validate_property_member` with it
- **THEN** `unsupported_layout_fingerprint` is recorded
- **THEN** `release_accepted` is false
- **THEN** no record is parsed at the mismatched layout

#### Scenario: Ellis and Denton fingerprints are independent
- **GIVEN** the declared Ellis mapping and the declared Denton mapping
- **WHEN** a maintainer compares their fingerprints
- **THEN** the two values differ
- **THEN** neither is derived from the other

### Requirement: Identify the layout package by content rather than filename

The adapter SHALL identify an appraisal layout package by its content and validated structure rather than its filename extension. An OpenDocument Spreadsheet package SHALL be recognised by parsing its ZIP local file header, not by searching for a marker. The header SHALL carry compression method `0` (stored), a file-name length of exactly eight, the first member name `mimetype`, and a compressed and uncompressed size each equal to the length of the media type. The bytes following the header and any extra field SHALL be exactly `application/vnd.oasis.opendocument.spreadsheet`.

Declared sizes SHALL be validated rather than ignored: a header claiming zero bytes while carrying a media type describes a package that does not exist, and accepting it would let a hand-assembled prefix pass as a real one.

A package whose name ends in `.xlsx.ods`, or in any other misleading compound extension, SHALL be classified from its content alone. A package whose signature is absent, truncated, or ambiguous SHALL fail closed and SHALL NOT be parsed by a format chosen from its name.

Recognition SHALL be a bounded signature check on caller-supplied bytes. The adapter MUST NOT extract the package, enumerate its members, decompress its content, or read a layout from it.

#### Scenario: Recognise an ODS package behind a misleading name
- **GIVEN** a synthetic package whose filename ends in `.xlsx.ods`
- **GIVEN** package bytes carrying a valid ODS signature
- **WHEN** the caller invokes `classify_layout_package`
- **THEN** the package is classified as OpenDocument Spreadsheet
- **THEN** the classification does not consult the filename
- **THEN** no member is extracted or decompressed

#### Scenario: Fail closed on an ambiguous package
- **GIVEN** a synthetic package whose bytes carry a ZIP signature but no `mimetype` member
- **WHEN** the caller invokes `classify_layout_package`
- **THEN** the package is classified as unrecognised
- **THEN** no format is selected from the filename

#### Scenario: Refuse a truncated signature
- **GIVEN** package bytes shorter than the ODS signature
- **WHEN** the caller invokes `classify_layout_package`
- **THEN** the package is classified as unrecognised

### Requirement: Reject unsupported Ellis scenario labels

The adapter SHALL accept only a certified all-property release label and SHALL classify a hypothetical, potential-exemption, mineral-only, or otherwise labelled scenario release as unsupported for certified all-property parsing.

A caller-supplied release label outside the approved certified set SHALL be rejected with `unsupported_scenario_label` before any record is read. An ambiguous label SHALL be rejected rather than resolved by filename or date.

#### Scenario: Accept the certified all-property label
- **GIVEN** a caller-supplied release label of `certified-all-property`
- **WHEN** the caller invokes `validate_property_member`
- **THEN** parsing proceeds

#### Scenario: Reject a potential-exemption scenario label
- **GIVEN** a caller-supplied release label identifying an `RC2 Potential` exemption scenario
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `unsupported_scenario_label` is recorded
- **THEN** `release_accepted` is false
- **THEN** no record is read

#### Scenario: Reject a mineral-only scenario label
- **GIVEN** a caller-supplied release label identifying a mineral-only release
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `unsupported_scenario_label` is recorded
- **THEN** `release_accepted` is false

### Requirement: Validate Ellis records and preserve owner-row grain

The Ellis adapter MUST parse one already-selected, caller-supplied member and MUST NOT discover, request, download, or open an archive. Byte input SHALL be decoded strictly as ISO-8859-1 with byte-order marks rejected, LF and CRLF boundaries accepted with one trailing ending allowed, a bare CR that is not a boundary, one-based physical row numbers with no header row, and an observed width that SHALL be uniform across records and SHALL reach the layout's declared width, with any violation rejected as `record_width_mismatch`.

The adapter SHALL also validate child members against a caller-supplied set of accepted `prop_id` values, applying the same label, fingerprint, control-character, and width gates, rejecting an unresolved core appraisal child with `core_child_orphaned` and recording the non-fatal `legal_child_orphaned` for an unresolved legal child.

A child record's `child_sequence` SHALL be required and one to four ASCII digits. A blank `child_sequence` SHALL be rejected with `blank_required_key` and one outside that grammar with `invalid_child_sequence`, which names the child field rather than borrowing the owner code: the two sequences are separate facts even where their grammars agree. Its `child_value` MAY be blank as source absence, and a nonblank value SHALL match `[0-9]+(?:\.[0-9]{1,2})?`, parse with `decimal.Decimal`, and fall from zero through `10**26 - 1` inclusive; a violation SHALL be rejected with `invalid_monetary_value`. Empty text after trimming SHALL be the only null.

An unresolved legal child SHALL still be counted and materialized. A warning SHALL NOT delete the row it warns about, and dropping it would lose a child the county published from a release that was accepted. An unresolved core child needs no separate rule: its code is blocking, and a rejected release publishes no records at all.

A validator and its materializing sibling SHALL share one traversal, for property members and child members alike, so that a record exists for exactly the rows the report counted as accepted and the two can never disagree about what a valid Ellis row is.

`prop_id` SHALL be the Ellis account identifier, trimmed, 1 through 32 visible ASCII characters, preserved as text and never parsed numerically. `owner_sequence` SHALL be one to four ASCII digits. `(prop_id, owner_sequence)` SHALL be the physical owner-row grain, preserved distinctly with no deduplication, no summing, and no arbitrary-row selection, and no account-level roll-up SHALL be derived.

Two records sharing both key parts SHALL be rejected with `duplicate_owner_row`. Records sharing `prop_id` that disagree on a declared account-level fact SHALL be rejected with `conflicting_account_facts`.

Monetary fields SHALL match `[0-9]+(?:\.[0-9]{1,2})?` and fall from zero through `10**26 - 1`. `ownership_percentage` SHALL match `[0-9]{1,3}(?:\.[0-9]{1,6})?` and fall from 0 through 100. The tax year SHALL be four digits from 1900 through 2100 and SHALL equal the caller-supplied expected tax year.

#### Scenario: Accept a valid Ellis member
- **GIVEN** an independently authored ISO-8859-1 synthetic member with two records of uniform width
- **GIVEN** a certified all-property label and complete caller-supplied release identity
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 2
- **THEN** no network, archive, or discovery operation is performed

#### Scenario: Preserve an Ellis owner allocation
- **GIVEN** three synthetic records sharing one `prop_id` with owner sequences 1, 2, and 3
- **GIVEN** ownership percentages that differ and identical account-level facts
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 3
- **THEN** no account-level total is derived

#### Scenario: Reject conflicting Ellis account facts
- **GIVEN** two synthetic records sharing one `prop_id` with different owner sequences
- **GIVEN** different `market_value` values on those records
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `conflicting_account_facts` is recorded
- **THEN** `release_accepted` is false

### Requirement: Emit only the closed Ellis diagnostic vocabulary

The adapter SHALL emit only these diagnostic codes: `invalid_encoding`, `unexpected_bom`, `record_width_mismatch`, `unsupported_layout_fingerprint`, `undocumented_trailing_region`, `unsupported_scenario_label`, `blank_required_key`, `invalid_account_id`, `invalid_owner_sequence`, `invalid_child_sequence`, `invalid_monetary_value`, `invalid_ownership_percentage`, `invalid_tax_year`, `tax_year_mismatch`, `invalid_source_text`, `duplicate_owner_row`, `conflicting_account_facts`, `core_child_orphaned`, and `legal_child_orphaned`.

Every code in this vocabulary SHALL be reachable, and reachability SHALL be established by driving inputs through the public entry points rather than by comparing the vocabulary with itself. `truncated_required_field` is deliberately absent for the reason the Denton contract gives, and `unrecognised_layout_package` likewise: `classify_layout_package` returns a `LayoutPackageKind`, which is the reportable outcome, so a diagnostic code for it would promise a report that no entry point produces.

The layout gate SHALL compare the declared layout against the pinned constant before comparing the caller-supplied value against it. Comparing the caller's value against the live layout digest would make the pinned constant decorative, because a drifted mapping moves that digest with it.

A child member wider than its declared layout SHALL be rejected with `undocumented_trailing_region`, as a property member is.

A diagnostic SHALL carry only its stable code and, where applicable, an approved field name, the one-based physical row number, and the layout fingerprint, and those four fields SHALL be the whole type. `legal_child_orphaned` SHALL be the only non-fatal code. Every other code, including `undocumented_trailing_region`, SHALL reject the logical release, because the governing issue requires unknown trailing bytes to fail closed; the region's structural fingerprint is retained so the rejection carries evidence of what was found. At most 100 diagnostics SHALL be retained, the total SHALL be preserved, and truncation SHALL be marked deterministically.

#### Scenario: Truncate a large diagnostic set deterministically
- **GIVEN** a synthetic member producing 120 blocking diagnostics
- **WHEN** the caller invokes `validate_property_member`
- **THEN** exactly 100 diagnostics are retained
- **THEN** the preserved total count is 120
- **THEN** the result is marked as truncated
- **THEN** repeating the same run retains the same 100 diagnostics in the same order

### Requirement: Exclude Ellis owner and address values from every output

Owner names, mailing addresses, and situs addresses SHALL be classified as sensitive. Their declared field positions MAY participate in layout provenance, and their values MUST NOT enter a report, a diagnostic, a fixture, a log, or any output. Values from an undocumented trailing region SHALL likewise be discarded.

#### Scenario: Carry a sensitive field position without its value
- **GIVEN** an Ellis layout declaring `owner_name` and `owner_address` positions
- **GIVEN** a synthetic record carrying invented placeholder text in both
- **WHEN** the caller invokes `validate_property_member`
- **THEN** the release is accepted
- **THEN** neither placeholder appears in the report or its diagnostics

### Requirement: Expose the bounded Ellis validation result

The shared adapter contracts owned by Issue #43 are accepted and implemented, so the scope is no longer validation alone. The public surface SHALL be `classify_layout_package`, `validate_property_member` and `validate_child_member` each returning one `EllisValidationReport`, `materialize_property_member` and `materialize_child_member` each returning that same report alongside typed records, and `convert_ellis_record`. The adapter SHALL NOT define a county-local substitute for `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`; that prohibition does not lift with the wait.

Materialization SHALL be atomic with validation: a release rejected for any blocking reason SHALL yield zero records, never a partial set, including when other rows in the same member were valid. Every record SHALL carry the release label it was accepted under, because a record without it could not be distinguished from one accepted under a different label.

Only the documented Ellis monetary facts and the ownership percentage SHALL normalize to `decimal.Decimal`, and the tax year to `int`. Any other value SHALL retain its source text, because normalizing an undocumented field would assert a type this contract has not approved.

`EllisValidationReport` SHALL be a frozen dataclass with exactly these fields: `parser_contract_version: int`, `release_accepted: bool`, `layout_fingerprint: str`, `layout_version: str`, `release_label: str`, `accepted_row_count: int`, `owner_row_count: int`, `trailing_region_bytes: int`, `diagnostics: tuple[EllisDiagnostic, ...]`, `total_diagnostic_count: int`, and `diagnostics_truncated: bool`.

The report SHALL NOT carry parsed field values, records, or any per-row payload, and the adapter MUST NOT define a county-local replacement for `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`.

#### Scenario: The validator stays record-free
- **GIVEN** a valid synthetic member and a certified all-property label
- **WHEN** the caller invokes `validate_property_member`
- **THEN** one `EllisValidationReport` is returned and nothing else
- **THEN** the report exposes no record, row, or per-row payload field
- **THEN** no county-local replacement for a shared contract is defined

#### Scenario: The materializer returns the same report alongside typed records
- **GIVEN** the same member and label
- **WHEN** the caller invokes `materialize_property_member`
- **THEN** the report equals the one `validate_property_member` returned
- **THEN** the record count equals the report's `accepted_row_count`
- **THEN** each record carries the release label it was accepted under

#### Scenario: A rejected release yields no records
- **GIVEN** a member whose first row is valid and whose second row is rejected
- **WHEN** the caller invokes `materialize_property_member`
- **THEN** `release_accepted` is false
- **THEN** no record is returned, including for the row that was valid

#### Scenario: A scenario roll yields no records
- **GIVEN** a valid synthetic member and a mineral-only label
- **WHEN** the caller invokes `materialize_property_member`
- **THEN** `unsupported_scenario_label` is recorded before any record is read
- **THEN** no record is returned

#### Scenario: Only documented facts change type
- **GIVEN** a valid synthetic member
- **WHEN** the caller materializes it
- **THEN** each monetary value and the ownership percentage is a `decimal.Decimal`
- **THEN** the tax year is an `int`
- **THEN** every other value retains its source text

#### Scenario: A child sequence outside its grammar is rejected
- **GIVEN** a child member whose `child_sequence` is not one to four ASCII digits
- **WHEN** the caller invokes `validate_child_member` or `materialize_child_member`
- **THEN** `invalid_child_sequence` is recorded with the physical row number
- **THEN** a blank `child_sequence` records `blank_required_key` instead
- **THEN** `release_accepted` is false and no child record is returned

#### Scenario: A child value outside its grammar is rejected
- **GIVEN** a child member whose nonblank `child_value` is negative, carries three decimal places, or is otherwise malformed
- **WHEN** the caller invokes `materialize_child_member`
- **THEN** `invalid_monetary_value` is recorded
- **THEN** no child record is returned

#### Scenario: An empty child value is absence rather than a malformed amount
- **GIVEN** a child member whose `child_value` is empty after trimming
- **WHEN** the caller materializes it
- **THEN** the release is accepted
- **THEN** the child record's value is absent rather than an amount

#### Scenario: An unresolved legal child is kept
- **GIVEN** an accepted property set and an ARB child referencing a different `prop_id`
- **WHEN** the caller invokes `materialize_child_member` for the ARB table
- **THEN** `legal_child_orphaned` is recorded and `release_accepted` is true
- **THEN** the child is counted in `accepted_row_count`
- **THEN** one child record is returned, because a warning does not delete the row it warns about

#### Scenario: An unresolved core child is withheld
- **GIVEN** the same accepted property set and a land child referencing a different `prop_id`
- **WHEN** the caller invokes `materialize_child_member` for the land table
- **THEN** `core_child_orphaned` is recorded and `release_accepted` is false
- **THEN** no child record is returned

### Requirement: Keep the Ellis foundation adapter-local and non-production

The implementation MUST remain limited to the existing Ellis adapter module, Ellis-local synthetic fixtures and tests, and directly related Ellis source documentation. It MUST NOT add discovery, rendered-page retrieval, redirect handling, network access, archive extraction, services, DAGs, persistence, migrations, Bronze, Silver, Gold, workflows, infrastructure, deployment, owner publication, or new dependencies.

The documentation SHALL state that live-release compatibility and production readiness remain unproved, and that discovery, historical release modelling, the evidence manifest, and account roll-up remain outside this change.

#### Scenario: Inspect the bounded implementation diff
- **GIVEN** an implementation diff derived from this accepted plan
- **WHEN** a maintainer reviews the diff
- **THEN** no discovery, network, archive-extraction, service, DAG, persistence, or deployment component is present
- **THEN** the `property_tax_domain` and `property_tax_application` packages are unchanged
- **THEN** the dependency manifests are unchanged
- **THEN** the Ellis source documentation states that live compatibility and production readiness are unproved
