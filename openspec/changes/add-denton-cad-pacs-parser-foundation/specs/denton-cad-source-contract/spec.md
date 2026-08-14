## ADDED Requirements

### Requirement: Provide a reusable PACS fixed-width serialization component

The adapter layer SHALL provide one reusable fixed-width serialization component in `property_tax_adapters.sources.pacs` containing serialization mechanics only. It MUST NOT contain county discovery, release policy, privacy policy, thresholds, or any county field name, and Ellis and later PACS counties SHALL bind to this component rather than fork it.

A field SHALL declare a name, a 1-indexed inclusive `start` and `end` position, and whether it is required. `end` SHALL be greater than or equal to `start`, and the declared length SHALL be `end - start + 1`.

A layout SHALL declare a layout identifier, a layout version, and an ordered tuple of fields. The component SHALL reject a layout whose fields are not in ascending `start` order, whose fields overlap, or whose declared length disagrees with its positions. Those are authoring defects in trusted repository code rather than source data, so they SHALL raise `ValueError` at construction and produce no diagnostic.

The component SHALL compute a layout fingerprint as the lowercase SHA-256 hexadecimal digest of one canonical JSON document with exactly these five keys: `component_contract_version` (the integer `1`), `layout_id`, `layout_version`, `field_count`, and `fields`, where `fields` is the ordered list of `[name, start, end, required]` entries. The document SHALL be serialized with keys sorted by Unicode code point, the separators `,` and `:` and no other whitespace, literal non-ASCII characters, and UTF-8 encoding.

The layout fingerprint SHALL be versioned separately from any export-header version, so a county may accept a known layout against an unknown export version and record both.

#### Scenario: Reject an overlapping layout at construction
- **GIVEN** two declared fields whose position ranges overlap
- **WHEN** the layout is constructed
- **THEN** `ValueError` is raised
- **THEN** no diagnostic is produced, because a trusted-code defect is not source data

#### Scenario: Produce a stable layout fingerprint
- **GIVEN** one layout declared twice in separate processes with identical fields
- **WHEN** the component computes each fingerprint
- **THEN** both are the same lowercase SHA-256 hexadecimal digest
- **THEN** changing any field position, name, requiredness, or the layout version changes the digest

### Requirement: Slice fixed-width records without emitting partial values

The component SHALL slice a record using 1-indexed inclusive positions. A field whose `end` exceeds the observed record width MUST NOT be emitted as a valid truncated value: when the field is required the component SHALL name it in `truncated_required`, and when the field is optional it SHALL name it in `absent_optional`. The component reports; it does not diagnose, because diagnostic vocabularies are county policy.

A county binding gates the observed width against the declared width before slicing, so a required field cannot end beyond the width a county accepts. `truncated_required` is therefore reachable only by a caller slicing directly, and no county diagnostic corresponds to it.

A record wider than the layout's greatest declared `end` SHALL retain a structural fingerprint of the unknown trailing region — its byte length and a SHA-256 digest of that region's bytes in the member's own encoding — and SHALL emit no inferred field from it. The trailing region's content MUST NOT appear in a report or diagnostic.

A layout SHALL be immutable once constructed. Its fingerprint is computed at construction, so a layout whose identifier or version could be reassigned afterwards would report an approved digest beside an unapproved label.

Every sliced value SHALL retain its exact source text, and the component SHALL NOT trim, pad, case-fold, or coerce it. Trimming is a county rule applied by the binding, not a serialization mechanic.

#### Scenario: Refuse to emit a truncated required field
- **GIVEN** a layout whose required field ends at position 40
- **GIVEN** an observed record 30 characters wide
- **WHEN** the component slices that record
- **THEN** the field name appears in `truncated_required`
- **THEN** no partial slice is emitted as a value

#### Scenario: Refuse to relabel a fingerprinted layout
- **GIVEN** a constructed layout and its fingerprint
- **WHEN** a caller assigns a new layout version
- **THEN** the assignment fails
- **THEN** the fingerprint continues to describe the layout it was computed from

#### Scenario: Fingerprint an undocumented trailing region
- **GIVEN** a layout whose greatest declared end is position 60
- **GIVEN** an observed record 80 characters wide
- **WHEN** the component slices that record
- **THEN** the trailing region is recorded as a byte length and a digest
- **THEN** no field is inferred from the trailing region
- **THEN** the trailing content is absent from the report and its diagnostics

#### Scenario: Reject a member carrying undocumented trailing bytes
- **GIVEN** a synthetic member whose records are uniformly wider than the declared width
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `undocumented_trailing_region` is recorded
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0
- **THEN** the retained byte count describes the region without carrying its content

### Requirement: Decode a Denton PACS member without acquiring it

The Denton adapter MUST parse one already-selected, caller-supplied PACS member and MUST NOT discover, request, download, open an archive, or perform any network operation. Byte input SHALL be decoded strictly as ISO-8859-1 and string input SHALL round-trip through it; text that cannot be decoded SHALL be rejected with `invalid_encoding`, and a UTF-8, UTF-16, or UTF-32 byte-order mark SHALL be rejected with `unexpected_bom`.

LF and CRLF record boundaries SHALL both be accepted and one trailing line ending SHALL be allowed. A bare CR SHALL NOT be a record boundary. Physical row numbers SHALL be one-based in file order. A PACS member carries no header row, so row 1 SHALL be the first data record.

Every record SHALL match the layout's expected observed width, and that width SHALL be at least the layout's declared width. A record differing from the others SHALL be rejected with `record_width_mismatch`, and a member whose records agree with one another but fall short of the declared width SHALL be rejected the same way: uniformity is not evidence that the member is the declared layout. A member whose records disagree SHALL be rejected rather than parsed at a guessed width.

#### Scenario: Parse a valid synthetic Denton member
- **GIVEN** an independently authored ISO-8859-1 synthetic property member with no byte-order mark
- **GIVEN** two records at physical rows 1 and 2, each matching the expected observed width
- **GIVEN** caller-supplied release identifier, source member name, and expected tax year
- **WHEN** the caller invokes `validate_property_member`
- **THEN** one `DentonValidationReport` is returned with `release_accepted` true
- **THEN** `accepted_row_count` is 2
- **THEN** no network, archive, or discovery operation is performed

#### Scenario: Reject a record of unexpected width
- **GIVEN** a synthetic member whose second record is three characters narrower than the layout expects
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `record_width_mismatch` is recorded with physical row number 2
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

### Requirement: Bind Denton fields through a versioned county mapping

The Denton adapter SHALL declare a versioned Denton mapping that uses the shared component and SHALL NOT introduce PACS or Denton vocabulary into `property_tax_domain` or `property_tax_application`. The existing `DENTON_SOURCE` registry definition already imports both packages and SHALL be preserved unchanged, so the boundary is that neither package is modified and neither gains PACS or Denton parser vocabulary.

`prop_id` SHALL be the Denton account identifier: trimmed of surrounding ASCII whitespace, 1 through 32 visible ASCII characters, preserved as text with leading zeroes and punctuation intact, and never parsed numerically. A blank `prop_id` SHALL be rejected with `blank_required_key`.

`owner_sequence` SHALL be a required non-negative integer of one to four ASCII digits, retaining its exact source text. Monetary fields SHALL match `[0-9]+(?:\.[0-9]{1,2})?`, parse with `decimal.Decimal`, fall from zero through `10**26 - 1` inclusive, and retain their exact source text; a violation SHALL be rejected with `invalid_monetary_value`. `ownership_percentage` SHALL match `[0-9]{1,3}(?:\.[0-9]{1,6})?`, fall from 0 through 100 inclusive, and be rejected with `invalid_ownership_percentage` otherwise. A tax year SHALL be four ASCII digits from 1900 through 2100 and SHALL equal the caller-supplied expected tax year, rejected with `invalid_tax_year` or `tax_year_mismatch`.

Empty text after permitted trimming SHALL be the only null. The literals `NULL`, `N/A`, and `None` SHALL NOT be treated as null.

#### Scenario: Preserve an account identifier as text
- **GIVEN** two synthetic records whose `prop_id` values are `000123` and `123`
- **GIVEN** distinct owner sequences on each
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 2
- **THEN** no duplicate or conflict diagnostic is recorded, because the identifiers are compared as text

#### Scenario: Reject a blank required key
- **GIVEN** a synthetic record whose `prop_id` is blank after trimming
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `blank_required_key` is recorded with the field name and physical row number
- **THEN** `release_accepted` is false

### Requirement: Preserve owner-row grain without deriving an account roll-up

`(prop_id, owner_sequence)` SHALL be the physical owner-row grain. The adapter SHALL preserve every owner row distinctly and MUST NOT deduplicate rows, sum owner-scoped values, or select an arbitrary row as an account total. No account-level roll-up SHALL be derived until an approved rule exists.

Two records sharing both `prop_id` and `owner_sequence` SHALL be rejected with `duplicate_owner_row`. Records sharing `prop_id` with different owner sequences SHALL be accepted as an owner allocation.

Records sharing `prop_id` that disagree on a declared account-level fact SHALL be rejected with `conflicting_account_facts`, since no approved discriminator resolves the conflict.

#### Scenario: Accept an undivided-interest allocation
- **GIVEN** three synthetic records sharing one `prop_id` with owner sequences 1, 2, and 3
- **GIVEN** ownership percentages that differ and identical account-level facts
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `release_accepted` is true
- **THEN** `accepted_row_count` is 3
- **THEN** no account-level total is derived from the three rows

#### Scenario: Reject a repeated owner row
- **GIVEN** two synthetic records sharing one `prop_id` and one `owner_sequence`
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `duplicate_owner_row` is recorded for the second occurrence
- **THEN** `release_accepted` is false

#### Scenario: Reject conflicting account facts
- **GIVEN** two synthetic records sharing one `prop_id` with different owner sequences
- **GIVEN** different `market_value` values on those two records
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `conflicting_account_facts` is recorded with the disagreeing field name
- **THEN** `release_accepted` is false

### Requirement: Preserve ten_percent_cap as a source-native cap amount

`ten_percent_cap` SHALL be validated as a monetary amount and preserved as a source-native cap amount. The adapter MUST NOT treat it as a capped value, MUST NOT substitute it for market, appraised, or assessed value, and MUST NOT derive any canonical value from it, solely because of its name or until its exact product mapping is approved.

#### Scenario: Carry the cap without interpreting it
- **GIVEN** a synthetic record whose `ten_percent_cap` is a valid monetary amount below its `market_value`
- **WHEN** the caller invokes `validate_property_member`
- **THEN** the record is accepted
- **THEN** no canonical capped, assessed, or taxable value is derived from the cap amount

### Requirement: Classify child relationships by table type

The Denton adapter SHALL validate child records against a caller-supplied set of accepted `prop_id` values and SHALL apply relationship rules by child type rather than one county-wide orphan rule.

A core appraisal child — land, improvement, or mobile home — that does not resolve to an accepted account SHALL be rejected with `core_child_orphaned`. A legal child — ARB or lawsuit — that does not resolve SHALL record the non-fatal `legal_child_orphaned` and SHALL NOT reject the release.

#### Scenario: Block a core appraisal orphan
- **GIVEN** an accepted property set containing one `prop_id`
- **GIVEN** a synthetic land child record referencing a different `prop_id`
- **WHEN** the caller invokes `validate_child_member` for the land table
- **THEN** `core_child_orphaned` is recorded with the physical row number
- **THEN** `release_accepted` is false

#### Scenario: Warn on a legal orphan without blocking
- **GIVEN** an accepted property set containing one `prop_id`
- **GIVEN** a synthetic ARB child record referencing a different `prop_id`
- **WHEN** the caller invokes `validate_child_member` for the ARB table
- **THEN** `legal_child_orphaned` is recorded
- **THEN** `release_accepted` is true

### Requirement: Emit only the closed Denton diagnostic vocabulary

The adapter SHALL emit only these diagnostic codes: `invalid_encoding`, `unexpected_bom`, `record_width_mismatch`, `unsupported_layout_fingerprint`, `undocumented_trailing_region`, `blank_required_key`, `invalid_account_id`, `invalid_owner_sequence`, `invalid_monetary_value`, `invalid_ownership_percentage`, `invalid_tax_year`, `tax_year_mismatch`, `invalid_source_text`, `duplicate_owner_row`, `conflicting_account_facts`, `core_child_orphaned`, and `legal_child_orphaned`.

Every code in this vocabulary SHALL be reachable. `truncated_required_field` is deliberately absent: once the observed width is required to reach the declared width, a required field can never end beyond it, so a county emitting that code would be declaring something no input can produce. Truncation remains a shared-component concept, reported by `slice_record` for callers that slice directly.

A diagnostic SHALL carry only its stable code and, where applicable, an approved field name, the one-based physical row number, and the layout fingerprint. Those four fields SHALL be the whole type, so there is nowhere to put a complete record, an arbitrary value, an account value, release or member text, an owner name, an address, a credential, exception text, or a host-local path.

`legal_child_orphaned` SHALL be non-fatal. Every other code, including `undocumented_trailing_region`, SHALL reject the logical release: the governing issue requires unknown trailing bytes to fail closed, and the region's structural fingerprint is retained so the rejection carries evidence of what was found. At most 100 diagnostics SHALL be retained, the total count SHALL be preserved, and truncation SHALL be marked deterministically.

#### Scenario: Truncate a large diagnostic set deterministically
- **GIVEN** a synthetic member producing 130 blocking diagnostics
- **WHEN** the caller invokes `validate_property_member`
- **THEN** exactly 100 diagnostics are retained
- **THEN** the preserved total count is 130
- **THEN** the result is marked as truncated
- **THEN** repeating the same run retains the same 100 diagnostics in the same order

### Requirement: Reject a logical release atomically

When any blocking diagnostic occurs the report SHALL carry `release_accepted` false and `accepted_row_count` zero. There SHALL be no row-continues quarantine path and no partially accepted release.

#### Scenario: Return nothing when one record of many fails
- **GIVEN** a synthetic member of 40 records where record 22 carries an invalid monetary value
- **WHEN** the caller invokes `validate_property_member`
- **THEN** `invalid_monetary_value` is recorded for physical row 22
- **THEN** `release_accepted` is false
- **THEN** `accepted_row_count` is 0

### Requirement: Exclude owner and address values from every output

Owner names, mailing addresses, and situs addresses SHALL be classified as sensitive. Their declared field positions MAY participate in layout provenance, and their values MUST NOT enter a report, a diagnostic, a fixture, a log, or any output. Publisher omissions SHALL be preserved and MUST NOT be reconstructed, enriched, joined, or inferred from another field.

Values sliced from the undocumented trailing region SHALL also be discarded, because an unknown region may carry identity or address data.

#### Scenario: Carry a sensitive field position without its value
- **GIVEN** a Denton layout declaring `owner_name` and `owner_address` positions
- **GIVEN** a synthetic record carrying invented placeholder text in both
- **WHEN** the caller invokes `validate_property_member`
- **THEN** the release is accepted
- **THEN** neither placeholder appears in the report or its diagnostics

### Requirement: Expose the bounded Denton validation result

Until the shared adapter contracts owned by Issue #43 are accepted and implemented, the adapter cannot return a row-shaped result without inventing a substitute for a contract that issue owns. The interim scope is therefore a validator, and its complete public surface SHALL be `validate_property_member` and `validate_child_member`, each returning one `DentonValidationReport`.

`DentonValidationReport` SHALL be a frozen dataclass with exactly these fields: `parser_contract_version: int`, `release_accepted: bool`, `layout_fingerprint: str`, `layout_version: str`, `accepted_row_count: int`, `owner_row_count: int`, `trailing_region_bytes: int`, `diagnostics: tuple[DentonDiagnostic, ...]`, `total_diagnostic_count: int`, and `diagnostics_truncated: bool`.

The report SHALL NOT carry parsed field values, records, or any per-row payload. It MUST NOT be persisted, cached, or logged, its lifetime SHALL end with the caller that received it, and it is not a substitute for `SourceNativeValue`, `SourceProvenance`, or `AppraisalSourceRecord`. The adapter MUST NOT define a county-local replacement for any of those three.

#### Scenario: Validate without constructing a record
- **GIVEN** the shared Issue #43 contracts are absent from the repository
- **GIVEN** a valid synthetic member and complete caller-supplied release identity
- **WHEN** the caller invokes `validate_property_member`
- **THEN** one `DentonValidationReport` is returned
- **THEN** no typed Denton or vendor-neutral record is constructed
- **THEN** no county-local replacement for a shared contract is defined

### Requirement: Keep the Denton foundation adapter-local and non-production

The implementation MUST remain limited to the shared PACS component, the existing Denton adapter module, Denton-local synthetic fixtures and tests, and directly related Denton source documentation. It MUST NOT add discovery, network access, archive handling, services, DAGs, persistence, migrations, Bronze, Silver, Gold, workflows, infrastructure, deployment, owner publication, or new dependencies.

The documentation SHALL state that live-release compatibility and production readiness remain unproved, and that discovery, conditional observation, archive validation, roll precedence, the evidence manifest, and account roll-up remain outside this change.

#### Scenario: Inspect the bounded implementation diff
- **GIVEN** an implementation diff derived from this accepted plan
- **WHEN** a maintainer reviews the diff
- **THEN** no discovery, network, archive, service, DAG, persistence, or deployment component is present
- **THEN** the `property_tax_domain` and `property_tax_application` packages are unchanged
- **THEN** the dependency manifests are unchanged
- **THEN** the Denton source documentation states that live compatibility and production readiness are unproved
