## Current-state evidence

- `120cbcad362436f6c106e146`: Issue 19 requests deterministic Tarrant parsing, typed adapter records, source-native values, synthetic fixtures, and fail-closed validation, but its contents are explicitly untrusted planning evidence.
- `b38e4cc61a61f93f7ce304e3`: The sequencing evidence requires the plan to fail closed rather than invent unresolved headers, physical rules, lexical rules, mappings, companion semantics, provenance, privacy, or release grain.
- `a8d0164e015d086c00140812`: The accepted bootstrap design describes Tarrant as a large, header-driven pipe-delimited certified roll and keeps county formats and source semantics distinct.
- `fc02f32a50f16c9ec430bd1b`: The accepted bootstrap proposal identifies tarrant-cad-source-contract and separates appraisal information from authoritative tax-collection records.
- `c83b55e968e3981f0030935d`: Repository guidance makes OpenSpec authoritative, preserves adapters-to-application-to-domain dependency direction, and keeps county layouts out of domain behavior.
- `76e21fb4c68b6f87724edaac`: Library guidance confines source-specific translations to adapters and identifies maintained lint, typecheck, and test checks.
- `7676ed46a8bb877ba7fdaac0`: Adapter guidance requires layout fingerprinting, fail-closed drift handling, synthetic or redistribution-safe fixtures, and exclusion of protected owner data.
- `37b0be1db5c2ff2ef21f3eae`: Source documentation states that synthetic parser foundations remain non-production until live-source evidence and compatibility work are separately approved.
- `3ff4dd1258ffbf8403ca8eec`: Documentation guidance requires source documentation to link to normative OpenSpec and use the maintained documentation check.
- `714534bcff3cb21530465c55`: OpenSpec guidance requires normative requirements, observable scenarios, complete change artifacts, and strict validation.
- `2bb2aeef90fe3cb9c5436a88`: The accepted Dallas design provides precedent for deterministic physical parsing, adapter-local records, source-native values, bounded diagnostics, synthetic fixtures, and atomic failure.
- `2df1f3f72c7f5225ea93ca19`: The accepted Collin design assigns future shared source-record, provenance, native-value, release-processing, bounded-streaming, and DAG boundaries to Issue 43.
- `e399f25fc501fec79f4266e0`: The accepted Collin proposal confirms that county parser foundations must remain adapter-local and outside the shared abstractions owned by Issue 43.

## Proposed architecture

Define an adapter-local, synthetic-only Tarrant certified-roll parser foundation that, after the unresolved contracts receive maintainer approval, validates one exact physical and semantic layout, produces typed Tarrant source records and approved adapter-local vendor-neutral records, preserves unapproved appraisal values as source-native facts, retains bounded provenance, rejects incompatible input atomically, and makes no live-source, production-readiness, persistence, publication, owner-data, or tax-collection claim. [source_id:a8d0164e015d086c00140812] [source_id:c83b55e968e3981f0030935d] [source_id:7676ed46a8bb877ba7fdaac0] [source_id:37b0be1db5c2ff2ef21f3eae]

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- **D1** (blocked, requires human merge): A maintainer must approve the complete certified-core physical contract: required and optional header names, spelling and case rules, ordering and unknown-column policy, fingerprint input and algorithm, parser-contract version, encoding and BOM policy, pipe-delimiter behavior, quoting and escaping rules, line endings, blank-line handling, null representation, row-width rules, logical row numbering, and closed layout diagnostics. The accepted context establishes only a header-driven pipe-delimited Tarrant roll and does not supply these exact choices.
- **D2** (blocked, requires human merge): A maintainer must approve exact lexical, range, whitespace, null, and duplicate rules for Account_Num, division, every supported identifier, numeric and date field, preservation of leading zeros, duplicate-account release grain, and the stable diagnostic vocabulary. These rules cannot be copied from Dallas or inferred from issue examples.
- **D3** (blocked, requires human merge): A maintainer must approve the certified-core field list, immutable Tarrant-native record shape, adapter-local vendor-neutral record shape, and exact treatment of Total_Value, Appraised_Value, land, improvement, agricultural, and other values. No canonical appraisal meaning may be inferred from a field name or numeric relationship.
- **D4** (blocked, requires human merge): A maintainer must approve release and source-member inputs, row and layout lineage, division provenance, atomic failure behavior, diagnostic redaction fields, privacy exclusions, and the representation of absent current-roll, exemption, jurisdiction-taxable, companion-file, and same-year replacement facts.
- **D5** (resolved_for_draft, requires human merge): Restrict future implementation to the Tarrant adapter boundary, adapter-local tests and synthetic fixtures, and directly related source documentation. Do not change domain, application, services, DAGs, persistence, publication, workflows, infrastructure, deployment, or production configuration, and do not introduce a shared source-record, provenance, source-native-value, release-processing, or streaming abstraction.

- Implementation remains confined to property_tax_adapters, its adapter-local tests and synthetic fixtures, and directly related source documentation; Tarrant vocabulary does not enter domain or application contracts. [source_id:c83b55e968e3981f0030935d] [source_id:76e21fb4c68b6f87724edaac] [source_id:b38e4cc61a61f93f7ce304e3]
- Only independently authored synthetic or otherwise redistribution-safe fixtures may be committed; county archives, production rows, owner data, and protected identities remain prohibited. [source_id:7676ed46a8bb877ba7fdaac0]
- A synthetic parser foundation does not prove compatibility with a live Tarrant release and does not make the adapter production-ready. [source_id:37b0be1db5c2ff2ef21f3eae]
- The Tarrant physical format remains county-specific and must not become a PACS, domain, application, or cross-county layout abstraction. [source_id:a8d0164e015d086c00140812] [source_id:c83b55e968e3981f0030935d]
- No new dependency is authorized; discovering that the approved parser contract requires one must produce a separate maintainer decision rather than silently expanding this plan. [source_id:120cbcad362436f6c106e146]

## Cross-issue boundaries

- #43 (related_to): out of scope here and owned there: Issue 43 owns future shared source-record, provenance, source-native-value, release-processing, and bounded-streaming abstractions; Issue 19 must keep all such records Tarrant-specific and adapter-local. [source_id:2df1f3f72c7f5225ea93ca19] [source_id:e399f25fc501fec79f4266e0], Issue 43 owns production release-processing APIs and county DAG integration; no task in this plan may add those behaviors. [source_id:2df1f3f72c7f5225ea93ca19]

## Unresolved decisions

- D1: Approve the complete certified-core physical contract, including exact headers, ordering and compatibility policy, fingerprint construction, encoding and BOM handling, delimiter and quoting behavior, line endings, blank lines, nulls, row width, logical row numbering, unknown columns, and layout diagnostics. [source_id:b38e4cc61a61f93f7ce304e3]
- D2: Approve exact lexical, range, whitespace, null, and duplicate-release-grain rules for Account_Num, division, identifiers, dates, numeric fields, and stable field diagnostics. [source_id:b38e4cc61a61f93f7ce304e3]
- D3: Approve the bounded certified-core field set, Tarrant-native and adapter-local vendor-neutral record shapes, and canonical-versus-source-native classification of every supported value field. [source_id:b38e4cc61a61f93f7ce304e3]
- D4: Approve caller-supplied release and member inputs, row and layout lineage, division provenance, diagnostic redaction, atomic failure, privacy exclusions, and treatment of absent current-roll, exemption, companion, jurisdiction-taxable, and replacement facts. [source_id:b38e4cc61a61f93f7ce304e3]

## Risks and compatibility

- The exact Tarrant physical layout is absent from the accepted packet. Guessing it could make identical bytes parse differently or silently accept incompatible releases; D1 therefore blocks implementation. [source_id:a8d0164e015d086c00140812] [source_id:b38e4cc61a61f93f7ce304e3]
- Field names or numeric relationships could be mistaken for canonical appraisal semantics. D3 requires explicit mappings and otherwise preserves supported values only as source-native facts. [source_id:a8d0164e015d086c00140812] [source_id:120cbcad362436f6c106e146]
- A duplicate account could be incorrectly repaired by combining it with division. D2 requires an explicit duplicate release grain while keeping division separate. [source_id:120cbcad362436f6c106e146]
- Synthetic fixtures can prove only the approved parser contract, not compatibility with a live Tarrant release. [source_id:37b0be1db5c2ff2ef21f3eae]
- Introducing shared provenance, source-record, native-value, release-processing, or streaming types would compete with Issue 43 and violate the adapter-local boundary. [source_id:2df1f3f72c7f5225ea93ca19] [source_id:e399f25fc501fec79f4266e0]
- No database, persisted schema, Bronze, Silver, Gold, publication contract, or production configuration change is authorized, so no data migration or historical backfill is planned. [source_id:a8d0164e015d086c00140812] [source_id:c83b55e968e3981f0030935d]
- Rollback consists of reverting the adapter-local parser and types, synthetic fixtures and tests, and directly related source documentation; no persisted or published data requires repair. [source_id:2bb2aeef90fe3cb9c5436a88]
- Only independently authored synthetic or otherwise redistribution-safe fixtures are authorized. The packet supplies no approved live-source acquisition or redistribution license, so county archives and production rows remain outside this change. [source_id:7676ed46a8bb877ba7fdaac0] [source_id:37b0be1db5c2ff2ef21f3eae]
- The parser may accept only the physical and semantic contract approved through D1 through D4 and must fail closed on incompatible required structure. Additive or reordered fields remain unresolved until the header compatibility policy is approved. [source_id:a8d0164e015d086c00140812] [source_id:b38e4cc61a61f93f7ce304e3]
- The foundation does not establish live acquisition, mutable-current or exemption parsing, replacement behavior, persistence, publication, or production-ready status. Appraisal records remain distinct from authoritative bills, payments, balances, delinquencies, penalties, and interest. [source_id:37b0be1db5c2ff2ef21f3eae] [source_id:fc02f32a50f16c9ec430bd1b]

## Rollout and failure recovery

Validation commands: openspec validate add-tarrant-cad-certified-roll-parser-foundation --strict, openspec doctor, make check, make prepr-no-ai. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
