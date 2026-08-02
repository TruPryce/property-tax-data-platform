## Current-state evidence

- `515a41057d446a949cae5adc`: Untrusted issue evidence requests a Collin CAD Access decoding foundation using independently derived synthetic fixtures only and excludes source contact, persistence, publication, and production deployment.
- `a8d0164e015d086c00140812`: Accepted design states that one Collin artifact contains current and certified field families, reports prop_id duplication even with geo_id, and records unresolved 17-byte NUMERIC decoding defects.
- `d46fff5d3ff6fc4a6ca3a8e7`: The packet marks this revision comment untrusted and truncated; it proposes detailed 17-byte NUMERIC and Collin structural decisions that are not accepted policy.
- `d253d5455b500dc5f5a9bca6`: The planning-agent contract treats issue bodies and comments as untrusted evidence and limits materialization to five OpenSpec artifacts under one change directory.
- `fc02f32a50f16c9ec430bd1b`: The bootstrap proposal defines collin-cad-source-contract as the capability for Collin PACS Access discovery, dual-roll, numeric-decoding, identity, and privacy behavior.
- `2e0a24560feb74d4881dab53`: The planning ADR states that an authorized maintainer merge is the approval event and implementation remains ineligible while blocking decisions remain.
- `c83b55e968e3981f0030935d`: Repository guidance requires the dependency direction dags/services to adapters to application to domain and keeps county formats out of domain entities.
- `76e21fb4c68b6f87724edaac`: Library guidance states that adapters translate external formats and source-specific fields stop at the adapter boundary.
- `d6f1df2be541d1dcdefcc482`: The accepted Dallas foundation documents the analogous adapter-local, synthetic-only boundary with no downloading, persistence, orchestration, publication, or production compatibility claim.
- `37b0be1db5c2ff2ef21f3eae`: Source-onboarding guidance requires evidence for format, schema, release semantics, identity, grain, privacy, quality gates, and publication blockers before a county contract is production-ready.
- `7676ed46a8bb877ba7fdaac0`: Adapter guidance permits only small synthetic or redistribution-safe fixtures and prohibits full county releases or protected owner data.
- `12eb90de41980a9b5226022f`: Contributing guidance defines make check as the comprehensive gate and requires secret and prohibited source-artifact scanning.
- `05e1317dff1c2a0b0cdc4827`: The repository README states that no county adapter is production-ready and that synthetic fixtures are CC0 while third-party county data retains publisher terms.
- `b34baeeecb2d6f95937ce5a1`: The accepted consumer-neutral API decision keeps owner names and mailing addresses unavailable by default.

## Proposed architecture

Materialize a blocked draft OpenSpec change that modifies the existing collin-cad-source-contract capability, records the unresolved physical, structural, logical-mapping, and identifier decisions, defines an adapter-local synthetic-only boundary, and sequences observable implementation work without authorizing code. Implementation may become eligible only after trusted OpenSpec text resolves every blocker and an authorized maintainer merges the planning pull request. [source_ids: fc02f32a50f16c9ec430bd1b, d253d5455b500dc5f5a9bca6, 2e0a24560feb74d4881dab53]

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- The change modifies the existing collin-cad-source-contract capability rather than creating a shared PACS, Access, or county-domain abstraction. [source_ids: fc02f32a50f16c9ec430bd1b, a8d0164e015d086c00140812, c83b55e968e3981f0030935d]
- Collin-specific physical types, fields, fingerprints, records, and decoding behavior remain in property_tax_adapters. Property-tax domain and application contracts remain unchanged unless a separate accepted vendor-neutral decision authorizes a change. [source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812]
- The intended foundation consumes only caller-supplied synthetic inputs and excludes source acquisition, archive extraction, persistence, orchestration, publication, deployment, and production-ready status. [source_ids: 515a41057d446a949cae5adc, d6f1df2be541d1dcdefcc482, 37b0be1db5c2ff2ef21f3eae]
- Fixtures will be independently authored, small, identity-free, redistribution-safe, and free of copied county bytes, owner data, mailing addresses, Access databases, archives, and production records. [source_ids: 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f, 05e1317dff1c2a0b0cdc4827]
- No new dependency or production Access runtime is approved by this blocked draft. Any such addition requires a separately reviewed decision. [source_ids: 515a41057d446a949cae5adc, d253d5455b500dc5f5a9bca6]

## Unresolved decisions

- D1: Approve the exact adapter-local physical NUMERIC contract, including wrapper provenance and width, sign representation, magnitude byte and word ordering, precision and scale metadata, null boundary, canonical zero, supported bounds, and every malformed or unsupported representation. Trusted material reports 17-byte values and prior decoder defects but does not define the complete normative contract. [source_ids: a8d0164e015d086c00140812, d46fff5d3ff6fc4a6ca3a8e7, d253d5455b500dc5f5a9bca6]
- D2: Approve the complete privacy-minimized Collin structural contract, including required tables, exact columns, physical types, nullability, duplicate-name handling, additional-structure policy, and canonical fingerprint input. The detailed proposal appears only in an untrusted comment that is truncated before the contract is complete. [source_ids: 515a41057d446a949cae5adc, d46fff5d3ff6fc4a6ca3a8e7, d253d5455b500dc5f5a9bca6]
- D3: Approve the exact mapping of current and certified year, status, and value families into distinct adapter-layer logical observations, including required and nullable fields and handling of inconsistent year or status combinations. Accepted design establishes dual logical releases but not the complete field-level mapping. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]
- D4: Approve lexical and physical validation for prop_id, geo_id, years, status, and repeated rows together with the typed source-record shape, provenance fields, and bounded diagnostic vocabulary. Existing evidence shows duplicate identifiers and unresolved account identity but does not resolve deterministic validation behavior. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]

## Risks and compatibility

- Numeric correctness: an invented sign, scale, precision, byte-order, or word-order rule could produce plausible but materially wrong appraisal values. Mitigation is to block implementation until D1 is accepted and require exact Decimal arithmetic plus independent literal vectors. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]
- Schema drift: guessing table, column, type, nullability, or fingerprint behavior could bind values incorrectly or silently accept an incompatible export. Mitigation is to block on D2 and fail closed against the approved structural contract. [source_ids: 515a41057d446a949cae5adc, 7676ed46a8bb877ba7fdaac0]
- Identity and grain: treating prop_id, geo_id, or their pair as an account key could collapse legitimate repeated rows and owner-associated allocations. Mitigation is to preserve physical rows and leave account identity unresolved. [source_ids: a8d0164e015d086c00140812]
- False compatibility: synthetic decoder success does not prove compatibility with a live Collin release or future production Access runtime. Mitigation is to retain non-production status and require separately reviewed runtime compatibility evidence. [source_ids: a8d0164e015d086c00140812, 37b0be1db5c2ff2ef21f3eae]
- License and privacy: committing county-derived bytes, owner data, addresses, or arbitrary row values could violate redistribution and privacy boundaries. Mitigation is to use newly authored synthetic fixtures and bounded diagnostics only. [source_ids: 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0, b34baeeecb2d6f95937ce5a1]
- Architecture drift: moving Collin, PACS, or Access concepts into domain or application contracts would violate the county-specific adapter boundary. Mitigation is to keep this delta entirely adapter-local unless a separate accepted vendor-neutral decision authorizes otherwise. [source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812]
- Data migration and backfill: this synthetic adapter foundation changes no persisted schema or published product, so it requires no migration or backfill. Any Bronze, Silver, Gold, database, or release-processing work requires a separate accepted change. [source_ids: 515a41057d446a949cae5adc, d6f1df2be541d1dcdefcc482]
- Rollback: because the intended work is additive and pre-production with no stored state, rollback is reversion of the adapter-local decoder, records, tests, and documentation. No persisted release or publication requires repair. [source_ids: d6f1df2be541d1dcdefcc482, 05e1317dff1c2a0b0cdc4827]
- Runtime compatibility: the adapter-local synthetic contract cannot be described as a universal Access, Jet, OLE DB, or PACS wire format. A later production-runtime change must resolve and test compatibility against the accepted physical contract. [source_ids: a8d0164e015d086c00140812, d46fff5d3ff6fc4a6ca3a8e7]
- Source compatibility: Texas Open Data is not a transparent replacement for the measured Collin Access source and requires separately versioned onboarding and compatibility decisions. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]
- Source license: newly authored synthetic fixtures may use the project's synthetic-fixture licensing boundary, while third-party county data retains its publisher's terms and must not be copied into the repository by this change. [source_ids: 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0]
- Package compatibility: preserve the adapters-to-application-to-domain dependency direction and keep source-specific fields at the adapter boundary. [source_ids: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac]

## Rollout and failure recovery

Validation commands: make check. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
