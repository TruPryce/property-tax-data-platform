## Current-state evidence

- `a8d0164e015d086c00140812`: Tarrant exposes a large, header-driven pipe-delimited certified roll.
- `b38e4cc61a61f93f7ce304e3`: The planning change must fail closed rather than inventing unresolved physical, lexical, mapping, provenance, diagnostic, and privacy behavior.
- `120cbcad362436f6c106e146`: Use synthetic fixtures only, preserve Account_Num as text, and do not infer unsupported value or companion semantics.
- `19ae7f81f3d5cded5e1b39ab`: Issue 43 owns shared source records, provenance, native values, bounded streaming, and production release-processing contracts.
- `075944dad107d34879b0d14f`: The Collin foundation intentionally avoids defining the production release-processing and bounded-streaming boundary owned by Issue 43.
- `c83b55e968e3981f0030935d`: Allowed dependency direction is dags and services to adapters to application to domain.
- `76e21fb4c68b6f87724edaac`: Adapters translate external formats, and source-specific fields stop at the adapter boundary.
- `7676ed46a8bb877ba7fdaac0`: Commit only small synthetic or redistribution-safe fixtures and never commit full county releases or protected owner data.
- `3ff4dd1258ffbf8403ca8eec`: Documentation under docs must use maintained links and run the repository documentation check.
- `2bb2aeef90fe3cb9c5436a88`: Synthetic fixtures do not prove compatibility with a production county release.
- `fc02f32a50f16c9ec430bd1b`: The bootstrap change identifies tarrant-cad-source-contract as the county capability for Tarrant certified-roll behavior.

## Proposed architecture

Produce an issue-linked OpenSpec change that, after the blocking decisions are resolved, defines an adapter-local, synthetic-only Tarrant certified-core parser foundation with typed Tarrant records, fail-closed validation, approved conversion through separately owned shared adapter contracts, source-native value preservation, bounded provenance and diagnostics, privacy controls, and explicit non-production limits. [source_ids: 120cbcad362436f6c106e146, 19ae7f81f3d5cded5e1b39ab, c83b55e968e3981f0030935d]

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- **D1** (blocked, requires human merge): A maintainer must approve the exact required header names and spelling, ordering policy, duplicate and unknown-column behavior, row-width contract, and deterministic layout-fingerprint input. The packet establishes only that the source is header-driven and pipe-delimited, so drafting concrete values would invent unsupported behavior.
- **D2** (blocked, requires human merge): A maintainer must approve encoding and BOM handling, accepted line endings, delimiter and quoting behavior, null and whitespace rules, and exact lexical forms for Account_Num, division, identifiers, dates, numeric fields, and duplicate-account detection.
- **D3** (blocked, requires human merge): A maintainer must enumerate which certified-core fields may populate accepted shared adapter records, which remain source-native, and how absent current, certified, exemption, companion, jurisdiction-taxable, and same-year replacement facts are represented. No field name alone may establish canonical market or tax semantics.
- **D4** (blocked, requires human merge): A maintainer must approve required provenance fields, release and row grain, atomic failure behavior, a closed diagnostic vocabulary, permitted bounded diagnostic metadata, and exact privacy-redaction rules.
- **D5** (resolved_for_draft, requires human merge): Keep Tarrant-native parsing, physical records, conversion logic, diagnostics, fixtures, tests, and documentation adapter-local. Consume accepted shared adapter records, provenance, and source-native-value contracts without modifying or duplicating the shared families owned by Issue 43.

- The input boundary is a Tarrant certified roll using a header-driven pipe-delimited format; mutable current-roll and companion exemption sources are outside this foundation. [source_ids: a8d0164e015d086c00140812, 120cbcad362436f6c106e146]
- Implementation remains within the Tarrant adapter area, adapter-local synthetic tests and fixtures, and directly related source documentation; domain, application, services, DAGs, persistence, publication, infrastructure, acquisition, and deployment remain unchanged. [source_ids: b38e4cc61a61f93f7ce304e3, c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac]
- Fixtures must be independently authored, small, identity-free, redistribution-safe, and free of county release bytes, production rows, owners, mailing addresses, protected identities, credentials, and secrets. [source_ids: 7676ed46a8bb877ba7fdaac0, 120cbcad362436f6c106e146]
- Issue 43 owns the future shared source-record, provenance, source-native-value, bounded-streaming, and production release-processing contracts; Tarrant may consume accepted shared contracts but may not create competing local shared families. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f]

## Cross-issue boundaries

- #43 (blocked_by): out of scope here and owned there: Shared vendor-neutral appraisal source-record contracts must be implemented by Issue 43 before Tarrant conversion tasks consume them. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f], Shared source-provenance and source-native-value contracts belong to Issue 43 and must not be redefined by the Tarrant change. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f], Bounded release streaming, production release processing, and future county DAG integration remain owned by Issue 43 and outside this foundation. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f]

## Unresolved decisions

- D1: The authoritative certified-core header vector, spelling, ordering compatibility, duplicate and unknown-column behavior, row-width contract, and layout fingerprint input are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]
- D2: Encoding, BOM, line-ending, delimiter, quoting, null, whitespace, identifier, numeric, date, division, and duplicate-account lexical rules are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]
- D3: The approved field-by-field shared mappings and the treatment of source-native, current, certified, exemption, companion, jurisdiction-taxable, and replacement facts are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]
- D4: The complete provenance schema, release and row grain, atomic failure behavior, closed diagnostic vocabulary, permitted metadata, and redaction rules are not supplied. [source_ids: 120cbcad362436f6c106e146, b38e4cc61a61f93f7ce304e3]

## Risks and compatibility

- Synthetic fixtures can prove only the accepted parser contract and cannot establish compatibility with an unobserved live Tarrant release; production readiness requires separately reviewed source evidence. [source_ids: 2bb2aeef90fe3cb9c5436a88, d6f1df2be541d1dcdefcc482, a8d0164e015d086c00140812]
- Inventing a header vector, lexical grammar, or unknown-column policy could make incompatible source bytes appear valid; D1 and D2 therefore remain blocking. [source_ids: b38e4cc61a61f93f7ce304e3]
- Mapping Total_Value or similarly named fields to canonical concepts without evidence could misstate appraisal or tax semantics; D3 therefore remains blocking. [source_ids: 120cbcad362436f6c106e146, a8d0164e015d086c00140812]
- Unbounded diagnostics could disclose identifiers, owner data, addresses, credentials, or host paths; D4 must establish a closed redacted diagnostic contract. [source_ids: 120cbcad362436f6c106e146, 19ae7f81f3d5cded5e1b39ab]
- Defining Tarrant-local shared types would conflict with Issue 43 and fragment cross-county adapter contracts. [source_ids: 19ae7f81f3d5cded5e1b39ab, 075944dad107d34879b0d14f]
- This is additive pre-production adapter work with no database schema migration, stored-data migration, or backfill. [source_ids: 120cbcad362436f6c106e146, 1b6acee37fd0a4979b5390da]
- Rollback consists of reverting the Tarrant adapter additions, adapter-local synthetic tests and fixtures, and related source documentation; no persisted release or published product requires repair. [source_ids: 2bb2aeef90fe3cb9c5436a88, 075944dad107d34879b0d14f]
- No new dependency is approved; implementation must use repository-supported facilities unless a separate maintainer decision explicitly changes that constraint. [source_ids: 120cbcad362436f6c106e146]
- Tarrant remains a distinct county pipe-delimited contract and must not be generalized into a PACS, Dallas, domain, or application abstraction. [source_ids: a8d0164e015d086c00140812, c83b55e968e3981f0030935d]
- The parser foundation does not authorize acquisition, archive handling, release streaming, persistence, publication, orchestration, owner publication, cross-county normalization, or a production-ready designation. [source_ids: 120cbcad362436f6c106e146, 37b0be1db5c2ff2ef21f3eae]

## Rollout and failure recovery

Validation commands: make check, make docs, openspec validate add-tarrant-cad-parser-foundation --strict. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
