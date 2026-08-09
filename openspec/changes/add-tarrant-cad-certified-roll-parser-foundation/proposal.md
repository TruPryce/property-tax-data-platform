## Why

The accepted context establishes that Tarrant publishes a county-specific, header-driven, pipe-delimited certified appraisal roll, but it does not define the exact certified-core headers, physical parsing rules, lexical forms, value mappings, provenance contract, or diagnostic behavior required for deterministic implementation. The untrusted issue intake requests those choices but cannot authorize them, so the plan must fail closed rather than infer them. [source_id:a8d0164e015d086c00140812] [source_id:120cbcad362436f6c106e146] [source_id:b38e4cc61a61f93f7ce304e3]

## Outcome

Define an adapter-local, synthetic-only Tarrant certified-roll parser foundation that, after the unresolved contracts receive maintainer approval, validates one exact physical and semantic layout, produces typed Tarrant source records and approved adapter-local vendor-neutral records, preserves unapproved appraisal values as source-native facts, retains bounded provenance, rejects incompatible input atomically, and makes no live-source, production-readiness, persistence, publication, owner-data, or tax-collection claim. [source_id:a8d0164e015d086c00140812] [source_id:c83b55e968e3981f0030935d] [source_id:7676ed46a8bb877ba7fdaac0] [source_id:37b0be1db5c2ff2ef21f3eae]

## Scope

- Originating issue: #19
- CountyForge planning run: `gh-1f0caa39075dd8b404c4a61a-a1`
- Affected capability: tarrant-cad-source-contract (ADDED)

## Constraints

- Owner and mailing-address publication remains default-deny. Fixtures, records, extras, outputs, and diagnostics must exclude owner names, mailing addresses, protected identities, complete rows, and arbitrary source values. [source_id:fc02f32a50f16c9ec430bd1b] [source_id:7676ed46a8bb877ba7fdaac0]
- Diagnostics must use a bounded approved vocabulary and location metadata rather than echoing identifiers or source rows. The exact redaction contract remains blocked by D4. [source_id:b38e4cc61a61f93f7ce304e3]
- The implementation performs no network access, source contact, credential handling, archive acquisition, or production-data processing. [source_id:120cbcad362436f6c106e146]

## Non-goals

- Live Tarrant discovery, source contact, HTTP probing, conditional requests, download, or archive acquisition. [source_id:120cbcad362436f6c106e146]
- Parsing a mutable current roll, certified-exemption source, jurisdiction-taxable source, companion file, or another Tarrant product not explicitly approved by this change. [source_id:120cbcad362436f6c106e146]
- Approving canonical value, exemption, current-versus-certified, jurisdiction-taxable, companion, or same-year replacement semantics without maintainer evidence. [source_id:120cbcad362436f6c106e146] [source_id:b38e4cc61a61f93f7ce304e3]
- Database migrations, Bronze storage, Silver loading, Gold publication, backfills, services, APIs, Airflow DAGs, infrastructure, workflows, deployment, or production configuration. [source_id:c83b55e968e3981f0030935d] [source_id:a8d0164e015d086c00140812]
- Owner or mailing-address ingestion or publication, protected-identity reconstruction, or authoritative tax-collection behavior. [source_id:fc02f32a50f16c9ec430bd1b]
- Cross-county normalization or shared source-record, provenance, source-native-value, release-processing, or streaming abstractions owned by Issue 43. [source_id:2df1f3f72c7f5225ea93ca19]
- A production-ready designation or claim of compatibility with a live full Tarrant roll. [source_id:37b0be1db5c2ff2ef21f3eae]

## Decisions

- **D1** (blocked, requires human merge): A maintainer must approve the complete certified-core physical contract: required and optional header names, spelling and case rules, ordering and unknown-column policy, fingerprint input and algorithm, parser-contract version, encoding and BOM policy, pipe-delimiter behavior, quoting and escaping rules, line endings, blank-line handling, null representation, row-width rules, logical row numbering, and closed layout diagnostics. The accepted context establishes only a header-driven pipe-delimited Tarrant roll and does not supply these exact choices.
- **D2** (blocked, requires human merge): A maintainer must approve exact lexical, range, whitespace, null, and duplicate rules for Account_Num, division, every supported identifier, numeric and date field, preservation of leading zeros, duplicate-account release grain, and the stable diagnostic vocabulary. These rules cannot be copied from Dallas or inferred from issue examples.
- **D3** (blocked, requires human merge): A maintainer must approve the certified-core field list, immutable Tarrant-native record shape, adapter-local vendor-neutral record shape, and exact treatment of Total_Value, Appraised_Value, land, improvement, agricultural, and other values. No canonical appraisal meaning may be inferred from a field name or numeric relationship.
- **D4** (blocked, requires human merge): A maintainer must approve release and source-member inputs, row and layout lineage, division provenance, atomic failure behavior, diagnostic redaction fields, privacy exclusions, and the representation of absent current-roll, exemption, jurisdiction-taxable, companion-file, and same-year replacement facts.
- **D5** (resolved_for_draft, requires human merge): Restrict future implementation to the Tarrant adapter boundary, adapter-local tests and synthetic fixtures, and directly related source documentation. Do not change domain, application, services, DAGs, persistence, publication, workflows, infrastructure, deployment, or production configuration, and do not introduce a shared source-record, provenance, source-native-value, release-processing, or streaming abstraction.

## Unresolved decisions

- D1: Approve the complete certified-core physical contract, including exact headers, ordering and compatibility policy, fingerprint construction, encoding and BOM handling, delimiter and quoting behavior, line endings, blank lines, nulls, row width, logical row numbering, unknown columns, and layout diagnostics. [source_id:b38e4cc61a61f93f7ce304e3]
- D2: Approve exact lexical, range, whitespace, null, and duplicate-release-grain rules for Account_Num, division, identifiers, dates, numeric fields, and stable field diagnostics. [source_id:b38e4cc61a61f93f7ce304e3]
- D3: Approve the bounded certified-core field set, Tarrant-native and adapter-local vendor-neutral record shapes, and canonical-versus-source-native classification of every supported value field. [source_id:b38e4cc61a61f93f7ce304e3]
- D4: Approve caller-supplied release and member inputs, row and layout lineage, division provenance, diagnostic redaction, atomic failure, privacy exclusions, and treatment of absent current-roll, exemption, companion, jurisdiction-taxable, and replacement facts. [source_id:b38e4cc61a61f93f7ce304e3]

## Cross-issue boundaries

- #43 (related_to): out of scope here and owned there: Issue 43 owns future shared source-record, provenance, source-native-value, release-processing, and bounded-streaming abstractions; Issue 19 must keep all such records Tarrant-specific and adapter-local. [source_id:2df1f3f72c7f5225ea93ca19] [source_id:e399f25fc501fec79f4266e0], Issue 43 owns production release-processing APIs and county DAG integration; no task in this plan may add those behaviors. [source_id:2df1f3f72c7f5225ea93ca19]

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
