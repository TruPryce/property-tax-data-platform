## Why

Issue #18 requests a synthetic Collin PACS Access decoder foundation with exact NUMERIC decoding, typed adapter records, structural validation, and separate current/certified observations [source: 515a41057d446a949cae5adc]. Accepted evidence establishes dual logical releases, unresolved prop_id/geo_id identity, and unreliable exploratory handling of 17-byte NUMERIC values, but the supplied packet does not establish the exact numeric representation, structural fingerprint, complete field mapping, or lexical validation rules needed for deterministic implementation [sources: a8d0164e015d086c00140812, 37b0be1db5c2ff2ef21f3eae].

## Outcome

Create a draft OpenSpec delta for collin-cad-source-contract that records the missing decisions as blocking. Once maintainers approve those decisions and merge the planning change, the contingent implementation can add adapter-local exact-decimal decoding, typed Collin records, fail-closed schema checks, separate current and certified observations, repeated-row preservation, and identity-free synthetic tests without persistence, publication, runtime acquisition, or a production-ready designation [sources: 2e0a24560feb74d4881dab53, 84e1270fa46d7eebbcd2d3c3, a8d0164e015d086c00140812].

## Scope

- Originating issue: #18
- CountyForge planning run: `gh-c3c54e9dc64d849c63e484c3-a1`
- Affected capabilities: collin-cad-source-contract

## Constraints

- The planned foundation is offline and fixture-only; it does not contact Collin CAD, follow external links, download an archive, execute an Access runtime, or introduce a source credential [sources: 515a41057d446a949cae5adc, 12eb90de41980a9b5226022f].
- Owner and mailing-address handling remains default-deny. Fixtures are identity-free, and protected identities are never reconstructed [source: 1f68cbd53a026079a9b30f8d].
- Diagnostics must use stable codes and bounded structural metadata rather than complete rows, owner values, addresses, arbitrary source values, credentials, or secrets [sources: 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f].
- County/vendor parsing remains adapter-local, preserving the required adapters-to-application-to-domain dependency direction and keeping parsing out of services and DAGs [sources: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac].

## Non-goals

- Live Collin discovery, HTTP probing, source contact, download, ZIP extraction, or Access database extraction [sources: 515a41057d446a949cae5adc, a8d0164e015d086c00140812].
- Selecting, installing, containerizing, or benchmarking a production Access runtime [sources: 515a41057d446a949cae5adc, a8d0164e015d086c00140812].
- Approving prop_id, geo_id, or another field as canonical account identity; deduplicating owner associations; or creating an account roll-up [sources: a8d0164e015d086c00140812, 1f68cbd53a026079a9b30f8d].
- Bronze persistence, database migrations, Silver normalization, Gold publication, API exposure, backfill, or release promotion [sources: 515a41057d446a949cae5adc, fc02f32a50f16c9ec430bd1b].
- Airflow DAGs, ingestion-service composition, infrastructure, deployment, workflows, policies, providers, authentication, or production configuration [sources: c83b55e968e3981f0030935d, 515a41057d446a949cae5adc].
- Owner or mailing-address publication, protected-identity reconstruction, or owner-bearing fixtures and diagnostics [sources: 1f68cbd53a026079a9b30f8d, 515a41057d446a949cae5adc].
- Silently replacing the Access source contract with Texas Open Data or another representation [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].
- Declaring Collin or another county adapter production-ready [sources: 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0].

## Unresolved decisions

- D1 — Approve the exact Access NUMERIC physical contract, including supported buffer width, required metadata, sign representation, precision/scale interpretation, byte and word order, zero encoding, boundaries, and malformed or unsupported forms. Existing evidence identifies decoder failures but does not define these rules [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].
- D2 — Approve the exact Collin structural contract: required table names, required columns, duplicate-column behavior, physical type descriptors, widths, precision/scale metadata, nullability, ordering policy, and canonical fingerprint input. Source onboarding requires measured fingerprints rather than inference from issue prose [sources: 37b0be1db5c2ff2ef21f3eae, 7676ed46a8bb877ba7fdaac0].
- D3 — Approve the complete current/certified field mapping and observation shape, including supported value families, the roles of curr_val_yr, cert_val_yr, and property_status, classification rules, and mandatory provenance. The accepted context establishes dual releases but not the complete mapping [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].
- D4 — Approve deterministic lexical, null, and range rules for prop_id, geo_id, years, monetary values, and stable diagnostics. The issue requests fail-closed validation, but authoritative context does not define the accepted forms or bounds [sources: 515a41057d446a949cae5adc, 37b0be1db5c2ff2ef21f3eae].

This draft requires human maintainer approval before implementation.
