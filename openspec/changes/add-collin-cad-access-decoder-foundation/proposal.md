## Why

Issue #18 requests a synthetic-only Collin CAD Access decoder foundation. Accepted platform design confirms that Collin is a distinct PACS Access source, one artifact can contain current and certified field families for separate logical releases, prop_id and geo_id do not yet establish approved account identity, and exploratory 17-byte NUMERIC decoding lacked reliable signed, scaled, and multiword proof. The packet does not contain a complete accepted physical decoder contract, exact structural schema, logical mapping, or identifier and diagnostic rules, while the only detailed revision comment is untrusted and truncated. [source_ids: 515a41057d446a949cae5adc, a8d0164e015d086c00140812, d46fff5d3ff6fc4a6ca3a8e7, d253d5455b500dc5f5a9bca6]

## Outcome

Materialize a blocked draft OpenSpec change that modifies the existing collin-cad-source-contract capability, records the unresolved physical, structural, logical-mapping, and identifier decisions, defines an adapter-local synthetic-only boundary, and sequences observable implementation work without authorizing code. Implementation may become eligible only after trusted OpenSpec text resolves every blocker and an authorized maintainer merges the planning pull request. [source_ids: fc02f32a50f16c9ec430bd1b, d253d5455b500dc5f5a9bca6, 2e0a24560feb74d4881dab53]

## Scope

- Originating issue: #18
- CountyForge planning run: `gh-3e718203b9bed723f09ffaea-a1`
- Affected capabilities: MODIFIED: collin-cad-source-contract — add a synthetic-only decoder-foundation delta for the eventually approved NUMERIC, structural, typed-record, dual-observation, provenance, diagnostic, and non-production contracts without generalizing Collin or PACS formats into shared domain behavior. [source_ids: fc02f32a50f16c9ec430bd1b, a8d0164e015d086c00140812, c83b55e968e3981f0030935d]

## Constraints

- No network contact, production credential, Access database, county archive, county row, owner data, mailing address, or production record belongs in this change or its fixtures. [source_ids: 515a41057d446a949cae5adc, 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f]
- Diagnostics must use the D4-approved bounded fields and stable codes and must not echo complete rows, identifiers, monetary values, owner data, mailing addresses, credentials, or arbitrary source text. [source_ids: d6f1df2be541d1dcdefcc482, b34baeeecb2d6f95937ce5a1]
- Owner and mailing-address publication remains default-deny, and this foundation must not reconstruct protected identity or create publication output. [source_ids: b34baeeecb2d6f95937ce5a1, a8d0164e015d086c00140812]

## Non-goals

- Live Collin discovery, HTTP probing, source contact, download, ZIP extraction, or Access container handling. [source_ids: 515a41057d446a949cae5adc]
- Selecting or installing a production Access runtime or adding an unapproved dependency. [source_ids: 515a41057d446a949cae5adc]
- Bronze persistence, database migration, backfill, Silver or Gold integration, release promotion, or publication. [source_ids: 515a41057d446a949cae5adc, d6f1df2be541d1dcdefcc482]
- Airflow orchestration, ingestion-service composition, workflows, infrastructure, deployment, authentication, provider, policy, or production-configuration changes. [source_ids: 515a41057d446a949cae5adc, c83b55e968e3981f0030935d]
- Approval of Collin account identity, deduplication, owner roll-up, owner publication, or mailing-address publication. [source_ids: a8d0164e015d086c00140812, b34baeeecb2d6f95937ce5a1]
- Migration to Texas Open Data or generalization of Collin, PACS, or Access layouts into a cross-county domain abstraction. [source_ids: a8d0164e015d086c00140812, c83b55e968e3981f0030935d]
- Declaring the Collin adapter or decoder foundation production-ready. [source_ids: 05e1317dff1c2a0b0cdc4827, 37b0be1db5c2ff2ef21f3eae]

## Unresolved decisions

- D1: Approve the exact adapter-local physical NUMERIC contract, including wrapper provenance and width, sign representation, magnitude byte and word ordering, precision and scale metadata, null boundary, canonical zero, supported bounds, and every malformed or unsupported representation. Trusted material reports 17-byte values and prior decoder defects but does not define the complete normative contract. [source_ids: a8d0164e015d086c00140812, d46fff5d3ff6fc4a6ca3a8e7, d253d5455b500dc5f5a9bca6]
- D2: Approve the complete privacy-minimized Collin structural contract, including required tables, exact columns, physical types, nullability, duplicate-name handling, additional-structure policy, and canonical fingerprint input. The detailed proposal appears only in an untrusted comment that is truncated before the contract is complete. [source_ids: 515a41057d446a949cae5adc, d46fff5d3ff6fc4a6ca3a8e7, d253d5455b500dc5f5a9bca6]
- D3: Approve the exact mapping of current and certified year, status, and value families into distinct adapter-layer logical observations, including required and nullable fields and handling of inconsistent year or status combinations. Accepted design establishes dual logical releases but not the complete field-level mapping. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]
- D4: Approve lexical and physical validation for prop_id, geo_id, years, status, and repeated rows together with the typed source-record shape, provenance fields, and bounded diagnostic vocabulary. Existing evidence shows duplicate identifiers and unresolved account identity but does not resolve deterministic validation behavior. [source_ids: a8d0164e015d086c00140812, 515a41057d446a949cae5adc]

This draft requires human maintainer approval before implementation.
