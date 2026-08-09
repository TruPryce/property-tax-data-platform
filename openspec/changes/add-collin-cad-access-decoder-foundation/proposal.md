## Why

The repository has an evidence-backed Collin CAD source contract but lacks an adapter-local, independently testable foundation for exact decoding of the observed 17-byte NUMERIC wrapper, validation of the privacy-minimized AD_Public structure, and preservation of separate current and certified observations. This foundation must not approve account identity, add a production Access runtime, or cross into acquisition, persistence, orchestration, publication, domain, or application behavior. [source_id:515a41057d446a949cae5adc] [source_id:a8d0164e015d086c00140812] [source_id:3321aaed641cd22210fac979]

## Outcome

Produce an accepted OpenSpec change defining a synthetic-only Collin adapter foundation that decodes exact Decimal values without floating-point conversion, validates the bounded Access schema and lexical contracts, creates typed adapter-local records, emits immutable current and certified observations with exact provenance, preserves physical rows and source identifiers without approving an account key, and fails closed with privacy-safe diagnostics. [source_id:3321aaed641cd22210fac979] [source_id:be2861af666dfc3b02456915] [source_id:c3dd5eb82533bab379d6af62] [source_id:8230e8434d4ed3576ea75416]

## Scope

- Originating issue: #18
- CountyForge planning run: `gh-1162c41aab31da12e3206bc9-a1`
- Affected capability: collin-cad-source-contract (ADDED)
- Permitted implementation files: `libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py`, `libs/property-tax-adapters/tests/test_collin_decoder.py`, `libs/property-tax-adapters/tests/fixtures/collin_synthetic.py`, and `docs/sources/collin-access-decoder-foundation.md`.

## Constraints

- The adapter reads only the approved privacy-minimized projection and never reads owner, DBA, mailing, or situs values into typed records, fixtures, diagnostics, or extras. [source_id:be2861af666dfc3b02456915]
- Diagnostics are limited to a stable code, field or table name, one-based row number, and schema fingerprint; complete rows, arbitrary values, identities, addresses, credentials, and host-local paths are prohibited. [source_id:8230e8434d4ed3576ea75416]
- The implementation performs no network access, receives no production credential, and commits no county archive, Access database, source row, owner record, address, or production appraisal record. [source_id:515a41057d446a949cae5adc] [source_id:7676ed46a8bb877ba7fdaac0]
- The implementation extends the existing `collin.py` registry module and does not create a competing sibling `collin/` package or alter the established `COLLIN_SOURCE` import surface.

## Non-goals

- Live Collin CAD discovery, download, range probing, source contact, archive extraction, or Access container execution. [source_id:515a41057d446a949cae5adc]
- Selection or installation of a production Access runtime or introduction of a new dependency. [source_id:515a41057d446a949cae5adc] [source_id:3321aaed641cd22210fac979]
- Migration to Texas Open Data or treatment of another Collin source as a transparent substitute for the measured Access contract. [source_id:515a41057d446a949cae5adc] [source_id:a8d0164e015d086c00140812]
- Approval of prop_id, geo_id, or any combination as a canonical account key, and any owner-row deduplication or account roll-up. [source_id:c3dd5eb82533bab379d6af62] [source_id:8230e8434d4ed3576ea75416]
- Bronze acquisition, database persistence, migrations, Silver normalization, Gold publication, Airflow orchestration, services, APIs, infrastructure, deployment, or production configuration. [source_id:515a41057d446a949cae5adc]
- Owner or mailing-address ingestion or publication, protected-identity reconstruction, or authoritative tax-bill, payment, delinquency, penalty, or interest behavior. [source_id:515a41057d446a949cae5adc] [source_id:fc02f32a50f16c9ec430bd1b]
- A production-ready designation for the Collin adapter or any claim of live full-roll compatibility. [source_id:05e1317dff1c2a0b0cdc4827] [source_id:8230e8434d4ed3576ea75416]

## Decisions

- **D1** (resolved_for_draft, requires human merge): Define the decoder as the observed 17-byte wrapper: byte zero is the canonical sign; four little-endian 32-bit magnitude words follow in most-significant-word-first order; and external precision and scale metadata control exact Decimal construction. Accept precision 1 through 28 and scale 0 through precision. Reject unsupported signs, widths, metadata, overflow, and negative zero. Require independently authored literal fixtures covering zero, signed, scaled, multiword, boundary, year, and monetary values without a mirrored encoder.
- **D2** (resolved_for_draft, requires human merge): Validate exactly the AD_Public table and the approved privacy-minimized identity, status, year, current-value, and certified-value columns. Bind exact case-sensitive names rather than positions or aliases, validate physical descriptors and nullability, reject incompatible required structure and table drift, ignore values of additional metadata columns, and compute the documented canonical SHA-256 schema fingerprint.
- **D3** (resolved_for_draft, requires human merge): Create separate immutable adapter-local current and certified observations. The current observation uses curr_val_yr and property_status; a certified observation uses cert_val_yr and the certified value family when consistently populated. Each retains exact source-column lineage, source family, source year, status, release and member identity, table, physical row, parser contract version, and schema fingerprint. Neither family may merge with, overwrite, suppress, or fill values for the other.
- **D4** (resolved_for_draft, requires human merge): Apply the approved prop_id, geo_id, property_status, year, monetary, null-family, exact-normalization, diagnostic, and privacy rules. Restrict implementation to the Collin adapter, adapter-local tests and synthetic fixtures, and directly related source documentation. Do not modify domain or application packages, define a production release-processing API, introduce shared vendor-neutral abstractions, add Collin DAG integration, or enter boundaries owned by Issue 43.

## Unresolved decisions

- None.

## Cross-issue boundaries

- #43 (related_to): out of scope here and owned there: Issue 43 owns production release-processing APIs and future shared source-record, provenance, native-value, and bounded-streaming abstractions; this change must remain a synthetic Collin adapter-local foundation. [source_id:8230e8434d4ed3576ea75416], Issue 43 owns future Collin DAG integration and shared record or streaming boundaries; no task in this plan may modify those areas. [source_id:8230e8434d4ed3576ea75416]

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
