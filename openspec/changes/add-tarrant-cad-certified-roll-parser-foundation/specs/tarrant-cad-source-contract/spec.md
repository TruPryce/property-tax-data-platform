## ADDED Requirements

### Requirement: Validate one approved physical layout

The Tarrant certified-core parser MUST validate the maintainer-approved encoding, delimiter, quoting, line-ending, header spelling, header compatibility policy, row width, null representation, parser-contract version, and layout-fingerprint algorithm before accepting any record, and MUST reject incompatible or ambiguous input without returning partial accepted records.

#### Scenario: Reject a header that differs from the approved contract
- **GIVEN** an independently authored synthetic Tarrant byte fixture
- **GIVEN** a header whose normalized structure differs by one required field from the maintainer-approved certified-core contract
- **WHEN** the Tarrant parser validates the fixture layout and attempts to create records only if validation succeeds; an incompatible layout produces the approved bounded diagnostic, is classified as unsupported, and emits no source or normalized record.
- **THEN** the Tarrant parser validates the fixture layout and attempts to create records only if validation succeeds; an incompatible layout produces the approved bounded diagnostic, is classified as unsupported, and emits no source or normalized record.

[source_ids: a8d0164e015d086c00140812, 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

### Requirement: Preserve account identity and division separately

The parser MUST preserve the approved account field as nonblank source text, MUST reject a duplicate account at the approved release grain, and MUST retain division code and its provenance separately without appending division to or substituting division for account identity.

#### Scenario: Reject a repeated account without altering identity
- **GIVEN** a synthetic certified-core fixture containing two otherwise valid rows
- **GIVEN** both rows contain the same nonblank account text and different division text
- **WHEN** the parser processes the fixture as one release; the duplicate produces the approved bounded diagnostic, division remains separate, and no partially accepted release is returned.
- **THEN** the parser processes the fixture as one release; the duplicate produces the approved bounded diagnostic, division remains separate, and no partially accepted release is returned.

[source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

### Requirement: Apply exact lexical validation

The parser MUST apply maintainer-approved lexical and range rules to every supported identifier, division, numeric, and date field before constructing typed records, and MUST NOT use permissive coercion, floating-point conversion, field truncation, row padding, or delimiter sniffing to repair malformed input.

#### Scenario: Reject malformed numeric text deterministically
- **GIVEN** a synthetic row with the exact approved header and row width
- **GIVEN** one supported appraisal-value field containing a numeric literal prohibited by the approved lexical grammar
- **WHEN** the parser converts the row into a typed source record; it emits the approved field-specific diagnostic and logical row number, performs no float conversion, and emits no typed record for the malformed release.
- **THEN** the parser converts the row into a typed source record; it emits the approved field-specific diagnostic and logical row number, performs no float conversion, and emits no typed record for the malformed release.

[source_ids: 120cbcad362436f6c106e146, 2bb2aeef90fe3cb9c5436a88, b38e4cc61a61f93f7ce304e3]

### Requirement: Keep unapproved appraisal values source-native

The adapter MUST preserve every supported Tarrant value field with its approved source-field identity and source-native classification, and MUST NOT label Total_Value or another field as canonical market, appraised, assessed, taxable, bill, payment, delinquency, penalty, or interest data unless that exact mapping is approved in this change.

#### Scenario: Preserve Total Value without inventing market value
- **GIVEN** a valid synthetic Tarrant record containing an approved Total_Value literal
- **GIVEN** no maintainer-approved mapping from that field to canonical market value
- **WHEN** the adapter converts the Tarrant source record; the Total_Value fact remains source-native, no canonical market value is populated, and no tax-collection interpretation is emitted.
- **THEN** the adapter converts the Tarrant source record; the Total_Value fact remains source-native, no canonical market value is populated, and no tax-collection interpretation is emitted.

[source_ids: a8d0164e015d086c00140812, fc02f32a50f16c9ec430bd1b, 120cbcad362436f6c106e146]

### Requirement: Do not infer absent companion semantics

The adapter MUST leave current-roll, certified-exemption, jurisdiction-taxable, companion-file, and same-year replacement facts absent when they are not present in the approved certified-core input, and MUST NOT infer them from filenames, value comparisons, missing columns, or release timing.

#### Scenario: Leave exemption and replacement facts absent
- **GIVEN** a valid synthetic certified-core record
- **GIVEN** the fixture contains no approved exemption companion fields or replacement evidence
- **WHEN** the adapter creates its normalized output; it creates no exemption observation, current-roll classification, jurisdiction-taxable observation, companion relationship, or same-year replacement assertion.
- **THEN** the adapter creates its normalized output; it creates no exemption observation, current-roll classification, jurisdiction-taxable observation, companion relationship, or same-year replacement assertion.

[source_ids: a8d0164e015d086c00140812, 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

### Requirement: Use identity-free fixtures and bounded diagnostics

Fixtures, expected outputs, and diagnostics MUST contain only independently authored synthetic data and approved bounded metadata, and MUST NOT contain or reconstruct owner names, mailing addresses, protected identities, complete source rows, arbitrary source values, credentials, county artifacts, or production records.

#### Scenario: Report an invalid identifier without echoing source values
- **GIVEN** a synthetic row containing a deliberately invalid account literal
- **GIVEN** additional sentinel text representing prohibited owner and mailing content
- **WHEN** the parser reports the invalid account; the diagnostic contains only its approved stable code and bounded location metadata and excludes the account literal, sentinel identity text, mailing text, and complete row.
- **THEN** the parser reports the invalid account; the diagnostic contains only its approved stable code and bounded location metadata and excludes the account literal, sentinel identity text, mailing text, and complete row.

[source_ids: 7676ed46a8bb877ba7fdaac0, fc02f32a50f16c9ec430bd1b, 120cbcad362436f6c106e146]

### Requirement: Keep records and provenance adapter-local

The implementation MUST keep Tarrant source records, conversion records, provenance, layout metadata, and diagnostics inside property_tax_adapters, MUST retain approved caller-supplied release and source-member evidence on every accepted record, and MUST NOT add network acquisition, domain or application types, persistence, publication, services, or DAG behavior.

#### Scenario: Create an adapter-local record with caller provenance
- **GIVEN** a valid synthetic Tarrant certified-core fixture
- **GIVEN** caller-supplied release identity and source-member identity
- **WHEN** the adapter parses and converts the fixture; each record retains approved release, member, row, and layout evidence while no domain object, network request, database action, publication action, service call, or DAG action occurs.
- **THEN** the adapter parses and converts the fixture; each record retains approved release, member, row, and layout evidence while no domain object, network request, database action, publication action, service call, or DAG action occurs.

[source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812, b38e4cc61a61f93f7ce304e3]
