## Why

Tarrant is an evidence-backed, header-driven pipe-delimited certified-roll source, but the frozen packet supplies no authoritative decisions for its exact header fingerprint, physical and lexical rules, field mappings, or provenance and diagnostic contract. Those material choices must be resolved before a deterministic synthetic parser foundation can be specified without inventing county behavior. [source_ids: a8d0164e015d086c00140812, 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

## Outcome

Produce an issue-linked OpenSpec change that, after the blocking decisions are resolved, defines an adapter-local, synthetic-only Tarrant certified-core parser foundation with typed Tarrant records, fail-closed validation, approved conversion through separately owned shared adapter contracts, source-native value preservation, bounded provenance and diagnostics, privacy controls, and explicit non-production limits. [source_ids: 120cbcad362436f6c106e146, 19ae7f81f3d5cded5e1b39ab, c83b55e968e3981f0030935d]

## Scope

- Originating issue: #19
- CountyForge planning run: `gh-1835c4f6ab4786202b00f55b-a1`
- Affected capability: tarrant-cad-source-contract (ADDED)

## Constraints

- Source-license and redistribution approval for a live Tarrant release is not established by this synthetic foundation. No Tarrant endpoint may be contacted and no county byte or record may be committed. [source_ids: 120cbcad362436f6c106e146, 7676ed46a8bb877ba7fdaac0]
- Owner and mailing-address publication remains default-deny, protected identities must not be reconstructed, and fixtures, records, outputs, and diagnostics must exclude owner and mailing values. [source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812]
- Diagnostics must contain only approved bounded metadata and exclude complete rows, arbitrary source values, identifiers, identities, addresses, credentials, secrets, and host-local paths. [source_ids: 19ae7f81f3d5cded5e1b39ab, 2bb2aeef90fe3cb9c5436a88]
- The change adds no network access, production credentials, provider configuration, authentication, workflow, infrastructure, deployment, or production configuration. [source_ids: 120cbcad362436f6c106e146]

## Non-goals

- Live Tarrant source discovery, HTTP contact, download, conditional requests, or archive acquisition. [source_ids: 120cbcad362436f6c106e146]
- Mutable current-roll, certified-exemption, companion-source, jurisdiction-taxable, or same-year replacement processing. [source_ids: 120cbcad362436f6c106e146]
- Database migrations, Bronze storage, Silver loading, Gold publication, backfill, services, APIs, Airflow DAGs, workflows, infrastructure, deployment, or production configuration. [source_ids: 120cbcad362436f6c106e146]
- Changes to property_tax_domain or property_tax_application and any Tarrant or PACS domain abstraction. [source_ids: 120cbcad362436f6c106e146, c83b55e968e3981f0030935d]
- Owner or mailing-address publication, protected-identity reconstruction, or owner-bearing fixtures and diagnostics. [source_ids: 120cbcad362436f6c106e146]
- Canonical market-value, taxable-value, tax-bill, payment, delinquency, penalty, interest, or replacement interpretations not explicitly approved by an accepted contract. [source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812]
- Modification or duplication of shared contracts owned by Issue 43. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f]

## Decisions

- **D1** (blocked, requires human merge): A maintainer must approve the exact required header names and spelling, ordering policy, duplicate and unknown-column behavior, row-width contract, and deterministic layout-fingerprint input. The packet establishes only that the source is header-driven and pipe-delimited, so drafting concrete values would invent unsupported behavior.
- **D2** (blocked, requires human merge): A maintainer must approve encoding and BOM handling, accepted line endings, delimiter and quoting behavior, null and whitespace rules, and exact lexical forms for Account_Num, division, identifiers, dates, numeric fields, and duplicate-account detection.
- **D3** (blocked, requires human merge): A maintainer must enumerate which certified-core fields may populate accepted shared adapter records, which remain source-native, and how absent current, certified, exemption, companion, jurisdiction-taxable, and same-year replacement facts are represented. No field name alone may establish canonical market or tax semantics.
- **D4** (blocked, requires human merge): A maintainer must approve required provenance fields, release and row grain, atomic failure behavior, a closed diagnostic vocabulary, permitted bounded diagnostic metadata, and exact privacy-redaction rules.
- **D5** (resolved_for_draft, requires human merge): Keep Tarrant-native parsing, physical records, conversion logic, diagnostics, fixtures, tests, and documentation adapter-local. Consume accepted shared adapter records, provenance, and source-native-value contracts without modifying or duplicating the shared families owned by Issue 43.

## Unresolved decisions

- D1: The authoritative certified-core header vector, spelling, ordering compatibility, duplicate and unknown-column behavior, row-width contract, and layout fingerprint input are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]
- D2: Encoding, BOM, line-ending, delimiter, quoting, null, whitespace, identifier, numeric, date, division, and duplicate-account lexical rules are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]
- D3: The approved field-by-field shared mappings and the treatment of source-native, current, certified, exemption, companion, jurisdiction-taxable, and replacement facts are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]
- D4: The complete provenance schema, release and row grain, atomic failure behavior, closed diagnostic vocabulary, permitted metadata, and redaction rules are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

## Cross-issue boundaries

- #43 (blocked_by): out of scope here and owned there: Shared vendor-neutral appraisal source-record contracts must be implemented by Issue 43 before Tarrant conversion tasks consume them. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f], Shared source-provenance and source-native-value contracts belong to Issue 43 and must not be redefined by the Tarrant change. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f], Bounded release streaming, production release processing, and future county DAG integration remain owned by Issue 43 and outside this foundation. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f]

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
