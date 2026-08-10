## ADDED Requirements

### Requirement: Validate the approved Tarrant physical layout

The Tarrant adapter MUST validate the complete D1-approved header contract and deterministic layout fingerprint before converting rows, and it MUST reject missing, duplicate, incompatible, unexpected, or ragged structures with the D4-approved diagnostic and no partial accepted records. [source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812, b38e4cc61a61f93f7ce304e3]

#### Scenario: Reject a certified-core header mismatch
- **GIVEN** a synthetic pipe-delimited input with one header differing from the D1-approved header contract
- **GIVEN** caller-supplied release and source-member identities
- **GIVEN** an expectation that layout failure returns no native or shared record
- **WHEN** the adapter validates the input layout before row conversion begins [source_ids: 120cbcad362436f6c106e146]
- **THEN** layout validation fails with the D4-approved bounded diagnostic
- **THEN** no Tarrant source record or shared adapter record is returned

[source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812, b38e4cc61a61f93f7ce304e3]

### Requirement: Preserve account identity and separate division

The adapter SHALL preserve Account_Num as nonblank source text, MUST reject duplicate Account_Num values within one parsed release, SHALL retain division separately with provenance, and MUST NOT use division to manufacture a different account identity. [source_ids: 120cbcad362436f6c106e146]

#### Scenario: Reject a duplicate account within one release
- **GIVEN** two otherwise valid synthetic certified-core rows with the same nonblank Account_Num
- **GIVEN** different division values
- **GIVEN** one caller-supplied release identifier
- **GIVEN** an expectation that the release fails atomically
- **WHEN** the adapter encounters the second account occurrence [source_ids: 120cbcad362436f6c106e146]
- **THEN** the release fails with the D4-approved duplicate-account diagnostic
- **THEN** division is not used to create a distinct account identity
- **THEN** no partial accepted release is returned

[source_ids: 120cbcad362436f6c106e146]

### Requirement: Reject malformed physical and lexical values

The adapter MUST apply the D2-approved encoding, delimiter, quoting, null, whitespace, identifier, numeric, and date rules and MUST reject every malformed non-null value rather than coercing, truncating, padding, guessing, or converting it to absence. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

#### Scenario: Reject an invalid numeric literal
- **GIVEN** an otherwise valid synthetic certified-core row
- **GIVEN** a populated value field outside the D2-approved numeric grammar
- **GIVEN** an expectation that diagnostics do not echo the malformed source text
- **WHEN** the adapter converts the populated numeric field [source_ids: 120cbcad362436f6c106e146]
- **THEN** conversion fails deterministically with the D4-approved numeric diagnostic
- **THEN** the malformed value does not become null or a partial source-native value
- **THEN** the diagnostic does not echo the source value

[source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

### Requirement: Preserve values without semantic inflation

The adapter MUST preserve Total_Value, Appraised_Value, land, improvement, agricultural, and other D3-approved fields as distinct source-native values unless an accepted mapping assigns a shared meaning, and it MUST NOT infer canonical market value, taxable value, tax-bill, payment, delinquency, penalty, interest, or replacement semantics. [source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812]

#### Scenario: Preserve Total_Value without labeling market value
- **GIVEN** a valid synthetic Tarrant row with a populated Total_Value field
- **GIVEN** no accepted D3 mapping from Total_Value to canonical market value
- **GIVEN** an expectation that no tax-collection or replacement fact is synthesized
- **WHEN** the adapter converts the Tarrant source record [source_ids: 120cbcad362436f6c106e146]
- **THEN** the approved source-native representation is retained under its Tarrant field identity
- **THEN** no canonical market-value field is populated from Total_Value
- **THEN** no tax-collection or replacement fact is synthesized

[source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812, fc02f32a50f16c9ec430bd1b]

### Requirement: Consume shared contracts without redefining them

Tarrant conversion SHALL construct only accepted shared adapter records, provenance, and source-native values supplied by Issue 43, and this change MUST NOT define, modify, or duplicate those shared contract families. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f]

#### Scenario: Convert through existing shared adapter types
- **GIVEN** a valid typed Tarrant source record
- **GIVEN** implemented Issue 43 shared record, provenance, and source-native-value contracts
- **GIVEN** an expectation that Tarrant vocabulary remains inside the adapter boundary
- **WHEN** the Tarrant conversion boundary processes the source record [source_ids: 19ae7f81f3d5cded5e1b39ab]
- **THEN** approved Tarrant fields populate the existing shared contracts
- **THEN** Tarrant-specific vocabulary remains inside the adapter boundary
- **THEN** no competing shared record or provenance family is introduced

[source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f, c83b55e968e3981f0030935d]

### Requirement: Retain provenance and redact diagnostics

Every accepted Tarrant record and shared conversion SHALL retain the D4-approved caller-supplied release identity, source-member identity, layout identity, and row lineage, while diagnostics MUST use the approved closed vocabulary and MUST NOT contain complete rows, arbitrary source values, account values, owner or mailing data, protected identities, credentials, secrets, or host-local paths. [source_ids: 120cbcad362436f6c106e146, 19ae7f81f3d5cded5e1b39ab]

#### Scenario: Redact a malformed-row diagnostic
- **GIVEN** a malformed synthetic row containing sentinel account, owner, address, credential, and host-path text
- **GIVEN** caller-supplied provenance inputs
- **GIVEN** an expectation that only approved bounded metadata is reportable
- **WHEN** the adapter reports the row-conversion failure [source_ids: 120cbcad362436f6c106e146]
- **THEN** the diagnostic contains only its approved stable code and permitted bounded metadata
- **THEN** the complete row and every sentinel value are absent
- **THEN** no partial record is returned

[source_ids: 120cbcad362436f6c106e146, 2bb2aeef90fe3cb9c5436a88, 19ae7f81f3d5cded5e1b39ab, 7676ed46a8bb877ba7fdaac0]

### Requirement: Keep the foundation synthetic and non-production

The implementation MUST use only small independently authored synthetic fixtures and MUST NOT add county contact, network access, acquisition, archive handling, persistence, migrations, Bronze, Silver, Gold, services, DAGs, workflows, infrastructure, deployment, owner publication, or production-ready behavior. [source_ids: 120cbcad362436f6c106e146, 7676ed46a8bb877ba7fdaac0]

#### Scenario: Review the committed fixture boundary
- **GIVEN** the proposed Tarrant fixture manifest and fixture files
- **GIVEN** the repository fixture and privacy policies
- **GIVEN** an expectation that every fixture is identity-free and redistribution-safe
- **WHEN** a maintainer reviews the committed fixture corpus [source_ids: 7676ed46a8bb877ba7fdaac0]
- **THEN** every fixture is documented as synthetic, identity-free, and redistribution-safe
- **THEN** no county artifact, production row, owner value, mailing address, protected identity, credential, or network response is present
- **THEN** the adapter remains explicitly non-production

[source_ids: 120cbcad362436f6c106e146, 7676ed46a8bb877ba7fdaac0, 1b6acee37fd0a4979b5390da]
