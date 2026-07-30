## Current-state evidence

- `ca0df171cabe5f246f2a4fe5`: Parse small synthetic observed-header delimited fixtures by normalized header name, never by ordinal position or documentation-only aliases.
- `a8d0164e015d086c00140812`: `ACCOUNT_NUM` is the stable source account identifier and remains a 17-character, zero-padded string. It is not a parcel identifier; `GIS_PARCEL_ID` differs or is blank for a material share of accounts. The source row join key is `(ACCOUNT_NUM, APPRAISAL_YR)`, while canonical identity remains county-qualified.
- `a8d0164e015d086c00140812`: The Dallas `TOT_VAL` field has unresolved semantics and is not approved as canonical market, appraised, assessed, or taxable value.
- `fc02f32a50f16c9ec430bd1b`: `dallas-cad-source-contract`: Evidence-backed Dallas release discovery, mutable-artifact, schema, identity, privacy, and replacement-snapshot behavior.
- `c83b55e968e3981f0030935d`: Allowed dependency direction: `dags/services -> adapters -> application -> domain`.
- `76e21fb4c68b6f87724edaac`: Adapters translate external formats and implement ports; source-specific fields stop at this boundary.
- `7676ed46a8bb877ba7fdaac0`: Stream downloads and records; do not materialize county releases as lists or whole-file dataframes.
- `7676ed46a8bb877ba7fdaac0`: Fingerprint layouts and quarantine incompatible drift instead of guessing.
- `b34baeeecb2d6f95937ce5a1`: The API will not expose owner names or mailing addresses by default and will not label appraisal facts as authoritative tax bills, balances, payments, or delinquencies.
- `05e1317dff1c2a0b0cdc4827`: Status: repository scaffold and initial OpenSpec are complete; no county adapter is production-ready yet.
- `05e1317dff1c2a0b0cdc4827`: Synthetic fixtures and generated demo datasets are released under CC0 1.0 Universal. Third-party county data retains its publisher's terms.
- `12eb90de41980a9b5226022f`: make check        # all checks
- `37b0be1db5c2ff2ef21f3eae`: Before implementation, verify: the publisher is the official appraisal district or county; bulk/API access and redistribution terms; release kinds, cadence, tax year, and as-of semantics; layouts, schema fingerprints, pagination, and authoritative counts.
- `714534bcff3cb21530465c55`: Requirements use SHALL/MUST and four-hash `#### Scenario` headings with WHEN/THEN steps.
- `d253d5455b500dc5f5a9bca6`: Trusted code renders only `.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`, and one capability `spec.md` below `openspec/changes/<change-name>/`.
- `2e0a24560feb74d4881dab53`: The initial approval contract is an authorized maintainer merging the planning PR. Until then, and whenever blocking unresolved decisions remain, implementation eligibility is false.

## Proposed architecture

Create one issue-linked OpenSpec delta for `dallas-cad-source-contract` that records the blocking decisions and, after human approval, governs adapter-local Dallas source records, deterministic header-name parsing, provenance, privacy-safe source extras, translation into an approved vendor-neutral contract, fail-closed validation, synthetic fixtures, contract tests, and documentation. The change must not imply that the Dallas adapter is production-ready or add acquisition, persistence, publication, orchestration, or deployment behavior. Sources: fc02f32a50f16c9ec430bd1b, ca0df171cabe5f246f2a4fe5, 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0.

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- The change modifies the existing `dallas-cad-source-contract` capability rather than creating a Dallas-derived cross-county abstraction. Sources: fc02f32a50f16c9ec430bd1b, a8d0164e015d086c00140812.
- Dallas headers, layout rules, and source-native vocabulary remain owned by `property_tax_adapters`; source-specific fields do not enter application or domain contracts. Sources: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812.
- Fixtures will be small, project-authored synthetic or otherwise redistribution-safe examples, will contain no protected identity, and will require no county-source contact. Sources: ca0df171cabe5f246f2a4fe5, 7676ed46a8bb877ba7fdaac0, 05e1317dff1c2a0b0cdc4827.
- No new dependency will be selected unless maintainers separately approve that material choice. Source: ca0df171cabe5f246f2a4fe5.
- The parser foundation will not add database schemas, Bronze persistence, Gold publication, an Airflow DAG, or production runtime configuration. Source: ca0df171cabe5f246f2a4fe5.

## Unresolved decisions

- D1 — Approve the exact Dallas member and delimited-layout contract: member selection, encoding and BOM behavior, delimiter, quoting and escaping, line endings, header normalization, required observed headers, permitted aliases, null representation, row-width behavior, and accepted numeric and date forms. The supplied authoritative context does not establish this complete grammar. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 37b0be1db5c2ff2ef21f3eae.
- D2 — Approve the exact typed Dallas source-record and vendor-neutral record fields, types, semantics, provenance representation, and owning packages, including whether an existing accepted neutral type is reused or a separate shared-capability change is required. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac.
- D3 — Approve whether `(ACCOUNT_NUM, APPRAISAL_YR)` uniqueness is enforced per member or per logical release and select a state strategy compatible with bounded record streaming. An unbounded key set and batch-only duplicate checking have materially different correctness and resource behavior. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0.
- D4 — Approve the classification, retention, suppression, and diagnostic-redaction policy for unknown source extras, especially owner, mailing-address, and protected-identity fields. The issue requests extras retention, while accepted privacy behavior is default-deny for owner and mailing-address publication. Sources: ca0df171cabe5f246f2a4fe5, b34baeeecb2d6f95937ce5a1, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0.

## Risks and compatibility

- Invented or stale synthetic headers could silently mis-map a later Dallas release. Mitigation: block implementation until D1 records an evidence-backed fingerprint and reject unsupported layouts. Sources: a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0.
- Numeric coercion of `ACCOUNT_NUM` or conflation with `GIS_PARCEL_ID` would corrupt source identity. Mitigation: use independently validated fields and explicit zero-padding tests. Source: a8d0164e015d086c00140812.
- Mapping `TOT_VAL` or jurisdiction-specific values to canonical appraisal concepts would fabricate semantics. Mitigation: retain them as source-native facts until a separately accepted mapping exists. Source: a8d0164e015d086c00140812.
- Unknown extras or diagnostic payloads could expose owner, mailing-address, or protected-identity data. Mitigation: resolve D4, default deny sensitive output, and test diagnostics only with synthetic nonidentity values. Sources: b34baeeecb2d6f95937ce5a1, ca0df171cabe5f246f2a4fe5.
- Release-wide duplicate detection could consume unbounded memory, while batch-only checking could miss duplicates. Mitigation: resolve D3 and contract-test the approved bounded strategy. Sources: a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0, ca0df171cabe5f246f2a4fe5.
- Synthetic-only success could be mistaken for source or adapter production readiness. Mitigation: retain the non-production designation and require later evidence-backed acquisition, full-roll, quality, privacy, and publication gates. Sources: 05e1317dff1c2a0b0cdc4827, 37b0be1db5c2ff2ef21f3eae, 7676ed46a8bb877ba7fdaac0.
- A fixture or documentation example could violate county-data licensing or artifact policy. Mitigation: use project-authored synthetic fixtures under the documented fixture-license boundary and commit no Dallas source artifact. Sources: 05e1317dff1c2a0b0cdc4827, 12eb90de41980a9b5226022f.
- Data migration: none is planned because the scoped parser foundation adds no database schema or persistence behavior. Source: ca0df171cabe5f246f2a4fe5.
- Backfill: none is planned because this change writes no Bronze, Silver, Gold, or production release. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812.
- Rollback: revert the parser, record types, fixtures, tests, and documentation while leaving persisted and published data untouched; Dallas remains non-production-ready. Sources: ca0df171cabe5f246f2a4fe5, 05e1317dff1c2a0b0cdc4827.
- Source license: project-authored synthetic fixtures may use the repository's CC0 fixture boundary; Dallas source data retains publisher terms and remains outside this change. Sources: 05e1317dff1c2a0b0cdc4827, 37b0be1db5c2ff2ef21f3eae.
- Package compatibility: Dallas names and layout behavior remain adapter-local; a shared application or domain contract changes only if D2 identifies an already accepted type or a separately approved capability change. Sources: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812.
- County and publication compatibility: Dallas must not become the template for the other five county formats, and this foundation does not alter `latest_available`, `latest_certified`, or `history` publication behavior. Sources: c83b55e968e3981f0030935d, a8d0164e015d086c00140812.

## Rollout and failure recovery

Validation commands: make check. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
