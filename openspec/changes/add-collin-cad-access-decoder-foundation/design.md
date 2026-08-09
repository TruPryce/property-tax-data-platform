## Current-state evidence

- `515a41057d446a949cae5adc`: Issue 18 supplies the requested Collin decoder outcome, implementation constraints, acceptance evidence, and non-goals.
- `3321aaed641cd22210fac979`: D1 defines the exact 17-byte wrapper, precision and scale limits, canonical encoding, failures, and independent fixtures.
- `be2861af666dfc3b02456915`: D2 defines AD_Public, required privacy-minimized columns, physical descriptors, fingerprinting, extras, and schema-drift behavior.
- `c3dd5eb82533bab379d6af62`: D3 defines current and certified mapping, provenance, family separation, and preservation of identifiers and repeated rows.
- `8230e8434d4ed3576ea75416`: D4 defines lexical validation, null handling, diagnostics, privacy, implementation scope, and the Issue 43 boundary.
- `a8d0164e015d086c00140812`: The accepted bootstrap design establishes the Collin Access and dual-roll context and county-specific architecture boundary.
- `fc02f32a50f16c9ec430bd1b`: The bootstrap proposal identifies collin-cad-source-contract as the capability governing Collin source behavior.
- `c83b55e968e3981f0030935d`: Repository guidance establishes OpenSpec authority, dependency direction, and the prohibition on generalizing county layouts into domain behavior.
- `76e21fb4c68b6f87724edaac`: Library guidance supplies supported lint, typecheck, and test commands and confines source-specific fields to adapters.
- `7676ed46a8bb877ba7fdaac0`: Adapter guidance requires layout fingerprinting, fail-closed drift, safe synthetic fixtures, and exclusion of protected owner data.
- `714534bcff3cb21530465c55`: OpenSpec guidance supplies strict validation commands and requires normative requirements with observable scenarios.
- `3ff4dd1258ffbf8403ca8eec`: Documentation guidance requires bounded source documentation to link to normative OpenSpec and run maintained documentation checks.
- `37b0be1db5c2ff2ef21f3eae`: Source documentation states that adapter foundations remain non-production until separate live-source evidence and compatibility work are approved.
- `05e1317dff1c2a0b0cdc4827`: The repository overview states that no county adapter is production-ready and defines synthetic-fixture and third-party-data licensing boundaries.

## Proposed architecture

Produce an accepted OpenSpec change defining a synthetic-only Collin adapter foundation that decodes exact Decimal values without floating-point conversion, validates the bounded Access schema and lexical contracts, creates typed adapter-local records, emits immutable current and certified observations with exact provenance, preserves physical rows and source identifiers without approving an account key, and fails closed with privacy-safe diagnostics. [source_id:3321aaed641cd22210fac979] [source_id:be2861af666dfc3b02456915] [source_id:c3dd5eb82533bab379d6af62] [source_id:8230e8434d4ed3576ea75416]

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

- Extend the existing `libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py` module. Do not create a sibling `collin/` package or replace the existing `COLLIN_SOURCE` registry surface.
- Keep every new physical descriptor, exact numeric wrapper, source record, observation, provenance value, and diagnostic explicitly Collin-specific and adapter-local. Shared vendor-neutral records and bounded release streaming remain owned by Issue 43.
- Use immutable records for the typed physical row and separate current/certified observations. Retain exact `Decimal`, declared precision and scale, source family, source year, exact source columns, and caller-supplied provenance.
- Keep implementation evidence in `libs/property-tax-adapters/tests/fixtures/collin_synthetic.py` and `libs/property-tax-adapters/tests/test_collin_decoder.py`, and keep the directly related operator-facing explanation in `docs/sources/collin-access-decoder-foundation.md`.

## Alternatives considered

- **Create a new `collin/` package:** rejected because `collin.py` already exists and is imported by the Texas source registry; a sibling package would create an ambiguous module boundary and the approved task ceiling would not authorize modifying or removing the existing file.
- **Introduce shared source-native or provenance types now:** rejected because Issue 43 owns future vendor-neutral records, provenance, native-value, release-processing, and bounded-streaming contracts.
- **Select an Access runtime in this slice:** rejected because the approved evidence covers only the observed 17-byte reader wrapper and synthetic vectors, not a production acquisition/runtime decision.

## Decisions and assumptions

- **D1** (resolved_for_draft, requires human merge): Define the decoder as the observed 17-byte wrapper: byte zero is the canonical sign; four little-endian 32-bit magnitude words follow in most-significant-word-first order; and external precision and scale metadata control exact Decimal construction. Accept precision 1 through 28 and scale 0 through precision. Reject unsupported signs, widths, metadata, overflow, and negative zero. Require independently authored literal fixtures covering zero, signed, scaled, multiword, boundary, year, and monetary values without a mirrored encoder.
- **D2** (resolved_for_draft, requires human merge): Validate exactly the AD_Public table and the approved privacy-minimized identity, status, year, current-value, and certified-value columns. Bind exact case-sensitive names rather than positions or aliases, validate physical descriptors and nullability, reject incompatible required structure and table drift, ignore values of additional metadata columns, and compute the documented canonical SHA-256 schema fingerprint.
- **D3** (resolved_for_draft, requires human merge): Create separate immutable adapter-local current and certified observations. The current observation uses curr_val_yr and property_status; a certified observation uses cert_val_yr and the certified value family when consistently populated. Each retains exact source-column lineage, source family, source year, status, release and member identity, table, physical row, parser contract version, and schema fingerprint. Neither family may merge with, overwrite, suppress, or fill values for the other.
- **D4** (resolved_for_draft, requires human merge): Apply the approved prop_id, geo_id, property_status, year, monetary, null-family, exact-normalization, diagnostic, and privacy rules. Restrict implementation to the Collin adapter, adapter-local tests and synthetic fixtures, and directly related source documentation. Do not modify domain or application packages, define a production release-processing API, introduce shared vendor-neutral abstractions, add Collin DAG integration, or enter boundaries owned by Issue 43.

- Python standard-library Decimal, hashing, and JSON facilities and existing repository test tooling are sufficient; discovering a required new dependency would require a separate maintainer decision rather than expanding this plan. [source_id:515a41057d446a949cae5adc] [source_id:3321aaed641cd22210fac979]
- The decoder is limited to the observed pure-Python reader's 17-byte wrapper and does not claim compatibility with raw Jet storage, Automation DECIMAL, OLE DB DB_NUMERIC, or an unselected production Access runtime. [source_id:3321aaed641cd22210fac979]
- Synthetic fixtures can represent the approved physical, structural, dual-family, invalid-value, and privacy cases without incorporating county records, owner information, addresses, archives, databases, or network responses. [source_id:515a41057d446a949cae5adc] [source_id:7676ed46a8bb877ba7fdaac0]

## Cross-issue boundaries

- #43 (related_to): out of scope here and owned there: Issue 43 owns production release-processing APIs and future shared source-record, provenance, native-value, and bounded-streaming abstractions; this change must remain a synthetic Collin adapter-local foundation. [source_id:8230e8434d4ed3576ea75416], Issue 43 owns future Collin DAG integration and shared record or streaming boundaries; no task in this plan may modify those areas. [source_id:8230e8434d4ed3576ea75416]

## Unresolved decisions

- None.

## Risks and compatibility

- Synthetic vectors and metadata prove the approved adapter contract but do not prove that an unselected production Access runtime emits the same wrapper or that a future live Collin release remains compatible. Mitigation: retain the non-production designation and require a later runtime change to verify these vectors or version a different physical contract. [source_id:3321aaed641cd22210fac979] [source_id:8230e8434d4ed3576ea75416]
- The privacy-minimized structural projection deliberately does not claim complete compatibility with every observed live column. Mitigation: validate required structure independently, include all observed descriptors in provenance fingerprints, ignore extra values, and fail closed on incompatible required drift. [source_id:be2861af666dfc3b02456915]
- Current and certified fields on one row could be accidentally merged or used to fill one another. Mitigation: model them as separate immutable adapter-local observations whose identity and provenance include source family and year. [source_id:c3dd5eb82533bab379d6af62]
- Repeated prop_id and geo_id values could be mistaken for approved account identity. Mitigation: preserve physical rows and identifiers only as source fields and prohibit account roll-up or deduplication in this change. [source_id:c3dd5eb82533bab379d6af62] [source_id:8230e8434d4ed3576ea75416]
- No data or schema migration and no backfill are authorized because this is additive adapter-local code with no persistence, Bronze, Silver, Gold, service, or database change. [source_id:515a41057d446a949cae5adc] [source_id:8230e8434d4ed3576ea75416]
- Rollback consists of reverting the Collin adapter module, adapter-local tests and fixtures, and directly related source documentation; there is no persisted or published data to repair. [source_id:8230e8434d4ed3576ea75416]
- Only independently authored synthetic or otherwise redistribution-safe fixtures are permitted; no county bytes or rows may be copied into the repository. Repository-generated synthetic fixtures fall within the stated CC0 fixture boundary, while third-party county data retains publisher terms. [source_id:515a41057d446a949cae5adc] [source_id:7676ed46a8bb877ba7fdaac0] [source_id:05e1317dff1c2a0b0cdc4827]
- The 17-byte decoder is a versioned contract for the observed pure-Python reader representation, not a universal Access, Jet, Automation DECIMAL, or OLE DB format. A future production runtime must verify its representation against the independent vectors or introduce a separately reviewed contract version. [source_id:3321aaed641cd22210fac979]
- No domain or application contract, service interface, DAG, persistence format, release-processing API, publication contract, dependency, or production-ready claim is introduced. Shared record, provenance, native-value, and streaming designs remain owned by Issue 43. [source_id:c83b55e968e3981f0030935d] [source_id:515a41057d446a949cae5adc] [source_id:8230e8434d4ed3576ea75416]

## Rollout and failure recovery

Validation commands: `openspec validate add-collin-cad-access-decoder-foundation --strict`, `openspec doctor`, `make check`, and `make prepr-no-ai`. Failures remain blocked and do not authorize implementation. Rollback reverts only the existing Collin adapter module, its one synthetic fixture module, its one test module, and its directly related source document; no persisted or published data requires repair.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
