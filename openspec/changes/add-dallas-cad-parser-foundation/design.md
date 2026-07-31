## Current-state evidence

- `ca0df171cabe5f246f2a4fe5`: Issue 17 requests synthetic observed-header Dallas parsing, typed source and vendor-neutral records, deterministic failures, source extras, tests, documentation, and strict scope exclusions.
- `a8d0164e015d086c00140812`: ACCOUNT_NUM remains a 17-character zero-padded account identifier, GIS_PARCEL_ID is distinct, the source key includes APPRAISAL_YR, and TOT_VAL has unresolved semantics.
- `c83b55e968e3981f0030935d`: Accepted behavior lives in OpenSpec, and the allowed dependency direction is dags and services to adapters to application to domain.
- `76e21fb4c68b6f87724edaac`: Adapters translate external formats and implement ports, while source-specific fields stop at the adapter boundary.
- `7676ed46a8bb877ba7fdaac0`: County adapters fingerprint layouts and quarantine incompatible drift, use only small synthetic or redistribution-safe fixtures, and require verified OpenSpec tasks before production readiness.
- `12eb90de41980a9b5226022f`: The repository provides make check as the aggregate gate and requires delivery work to call out schema changes, backfill needs, migration order, and rollback behavior.
- `05e1317dff1c2a0b0cdc4827`: No county adapter is production-ready yet. Synthetic fixtures are CC0, while third-party county data retains its publisher's terms.
- `37b0be1db5c2ff2ef21f3eae`: County source onboarding must establish source authority, release semantics, format and schema behavior, identity and grain, privacy handling, quality gates, and publication blockers.
- `714534bcff3cb21530465c55`: OpenSpec uses one spec directory per capability, normative requirements with scenarios, design decisions and risks, dependency-ordered tasks, validation, and doctor checks.
- `d253d5455b500dc5f5a9bca6`: Trusted planning code renders only the five bounded OpenSpec artifacts, validates before publication, and keeps implementation eligibility false pending human approval and resolved decisions.
- `2e0a24560feb74d4881dab53`: The initial approval contract is an authorized maintainer merging the planning PR, and blocking unresolved decisions keep implementation eligibility false.
- `1f68cbd53a026079a9b30f8d`: Repository review policy blocks source artifacts, protected-owner publication, dependency violations, fabricated canonical value semantics, and premature production-ready claims.
- `3ff4dd1258ffbf8403ca8eec`: Engineering documentation must link to normative OpenSpec requirements rather than duplicate them.
- `fc02f32a50f16c9ec430bd1b`: The bootstrap proposal defines dallas-cad-source-contract as the distinct Dallas capability for release, schema, identity, privacy, and replacement-snapshot behavior.

## Proposed architecture

Create a draft OpenSpec delta for dallas-cad-source-contract that records the blocking decisions and, once maintainers resolve them, specifies typed Dallas adapter records, deterministic header-name binding, fail-closed layout and row validation, source extras and provenance preservation, approved vendor-neutral conversion, synthetic-fixture coverage, and boundary documentation. The delta must not make the adapter production-ready or add acquisition, persistence, publication, orchestration, infrastructure, or deployment behavior. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0, 05e1317dff1c2a0b0cdc4827]

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- Dallas format names and source-native fields remain in property_tax_adapters, while property_tax_application and property_tax_domain remain vendor-neutral and preserve the adapters-to-application-to-domain dependency direction. [source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812]
- The proposal modifies the existing dallas-cad-source-contract capability rather than creating a PACS or cross-county abstraction. [source_ids: fc02f32a50f16c9ec430bd1b, 37b0be1db5c2ff2ef21f3eae, a8d0164e015d086c00140812]
- All examples and fixtures are small synthetic or redistribution-safe data with documented provenance and no full county release, owner, mailing-address, or protected-identity content. [source_ids: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0, 05e1317dff1c2a0b0cdc4827]
- No network access, database migration, Bronze persistence, Gold publication, Airflow DAG, production configuration, or new dependency is planned. Any newly required dependency remains a blocking human decision. [source_id: ca0df171cabe5f246f2a4fe5]
- Engineering documentation will link to the normative OpenSpec delta rather than duplicate its requirements. [source_id: 3ff4dd1258ffbf8403ca8eec]

## Unresolved decisions

- BLOCKING: Maintainers must approve the authoritative required observed headers, delimiter and encoding, header-normalization and collision rules, supported layout fingerprints, quoting behavior, and accepted row-width forms. The issue requests these behaviors but the accepted Dallas evidence supplied here does not define their complete contract. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 37b0be1db5c2ff2ef21f3eae]
- BLOCKING: Maintainers must identify the exact approved vendor-neutral target record and field types, including whether an existing domain type is sufficient and which Dallas facts must remain adapter-only. [source_ids: ca0df171cabe5f246f2a4fe5, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812]
- BLOCKING: Maintainers must approve lexical and typed representations for Dallas numeric and date fields, the retained representation of unresolved values such as TOT_VAL, and the exact source-member, header, release, extras, and diagnostic provenance carried by parser output. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0]

## Risks and compatibility

- Authority risk: implementing directly from Issue 17 could promote untrusted requirements evidence into policy or choose behavior inconsistent with the complete accepted Dallas contract. Mitigation: keep implementation blocked until the missing choices are approved in OpenSpec. [source_ids: d253d5455b500dc5f5a9bca6, c83b55e968e3981f0030935d, ca0df171cabe5f246f2a4fe5]
- Layout-drift risk: header normalization can collapse distinct source names or silently remap an incompatible release. Mitigation: approve normalization and collision rules, fingerprint compatible layouts, and quarantine incompatible drift rather than guessing. [source_ids: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0]
- Semantic risk: numeric conversion could fabricate canonical meaning for TOT_VAL or lose source evidence such as leading zeros and original lexical forms. Mitigation: preserve ACCOUNT_NUM as text, retain unresolved values as source-native facts, and map only approved semantics. [source_ids: a8d0164e015d086c00140812, 1f68cbd53a026079a9b30f8d]
- Architecture risk: Dallas or PACS vocabulary could leak into reusable domain or application contracts. Mitigation: keep external-format records and mappings in property_tax_adapters and require separate approval for any vendor-neutral domain type. [source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812]
- Privacy risk: unknown fields or malformed-row diagnostics could expose owner or mailing information. Mitigation: use identity-free synthetic fixtures, retain owner publication as default-deny, and require diagnostics that do not emit protected values. [source_ids: ca0df171cabe5f246f2a4fe5, 1f68cbd53a026079a9b30f8d, 7676ed46a8bb877ba7fdaac0]
- Fixture-governance risk: synthetic examples could be mistaken for measured source evidence or could reproduce restricted source bytes. Mitigation: document fixture provenance and checksum, keep fixtures CC0 or otherwise redistribution-safe, and retain accepted source evidence as the authority. [source_ids: 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0, 37b0be1db5c2ff2ef21f3eae]
- Data migration: no database schema migration is planned because the issue scope excludes database loading, Bronze persistence, and Gold publication. [source_id: ca0df171cabe5f246f2a4fe5]
- Backfill: no production backfill is planned because this change is limited to a parser foundation and synthetic fixtures rather than processing county releases. [source_id: ca0df171cabe5f246f2a4fe5]
- Rollback: the planned implementation is additive parser, fixture, test, and documentation work that can be reverted before production use. Because persistence and publication are excluded, no persisted-data rollback is planned. [source_ids: ca0df171cabe5f246f2a4fe5, 12eb90de41980a9b5226022f]
- Package compatibility: preserve the adapters-to-application-to-domain dependency direction and keep Dallas-specific formats out of application and domain contracts. [source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac]
- County compatibility: Dallas remains a distinct delimited-source contract and must not become a PACS or cross-county layout abstraction. [source_ids: a8d0164e015d086c00140812, fc02f32a50f16c9ec430bd1b]
- Readiness compatibility: existing release and publication behavior remains unchanged, and the Dallas adapter remains non-production-ready until its accepted OpenSpec tasks and required checks pass. [source_ids: 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f]

## Rollout and failure recovery

Validation commands: openspec validate add-dallas-cad-parser-foundation, make check. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
