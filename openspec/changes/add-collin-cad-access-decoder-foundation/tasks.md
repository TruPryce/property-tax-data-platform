## 1. Approved Contracts and Independent Fixtures

<!-- countyforge-task: 1.1 paths=libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py,libs/property-tax-adapters/tests/fixtures/collin_synthetic.py checks=repo.check risk=normal prerequisites=D1,D2,D3,D4 -->
- [x] 1.1 Add the approved Collin physical contracts and independent fixtures — Extend the existing `collin.py` module with Collin-specific physical descriptor and closed diagnostic declarations required by D1, D2, and D4. Add `collin_synthetic.py` with independently authored literal NUMERIC vectors and small identity-free schema and row fixtures covering D1 through D4, documented checksums, and no mirrored encoder, county artifact, production row, owner value, address, or runtime-generated expectation. Preserve `COLLIN_SOURCE` and the existing registry import surface; typed source records and observations remain task 3.1 work. [source_ids: 3321aaed641cd22210fac979, be2861af666dfc3b02456915, c3dd5eb82533bab379d6af62, 8230e8434d4ed3576ea75416, 7676ed46a8bb877ba7fdaac0]

## 2. Exact Decoder and Structural Validation

<!-- countyforge-task: 2.1 paths=libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D4,1.1 -->
- [x] 2.1 Implement exact NUMERIC decoding and the bounded `AD_Public` schema contract — Implement the approved 17-byte exact-`Decimal` decoder, required table and column descriptors, case-sensitive binding, canonical schema fingerprint, metadata-only extra-column warning, stable structural diagnostics, and fail-closed compatibility validation in the existing Collin adapter module. Use task 1.1 literals as independent evidence and add no Access runtime, network behavior, or dependency. [source_ids: 3321aaed641cd22210fac979, be2861af666dfc3b02456915, 76e21fb4c68b6f87724edaac]

## 3. Typed Rows and Dual Observations

<!-- countyforge-task: 3.1 paths=libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py checks=repo.check risk=higher_risk prerequisites=D2,D3,D4,2.1 -->
- [x] 3.1 Implement typed Collin rows and separate current and certified observations — Add exact identifier, status, year, null-family, and monetary validation; Collin-specific source-native values; mandatory provenance; physical-row preservation; and immutable current/certified observation conversion on top of task 2.1. Preserve source column semantics and repeated rows without introducing a shared abstraction, account key, deduplication, family merging, production release-processing API, or any boundary owned by Issue #43. [source_ids: be2861af666dfc3b02456915, c3dd5eb82533bab379d6af62, 8230e8434d4ed3576ea75416, c83b55e968e3981f0030935d]

## 4. Contract, Failure, Privacy, and Architecture Tests

<!-- countyforge-task: 4.1 paths=libs/property-tax-adapters/tests/test_collin_decoder.py,libs/property-tax-adapters/tests/fixtures/collin_synthetic.py checks=repo.check risk=normal prerequisites=D1,D2,D3,D4,1.1,2.1,3.1 -->
- [x] 4.1 Add Collin decoder and source-contract tests — Cover canonical zero, signed, scaled, multiword, precision-boundary, year, and monetary decoding; malformed buffers and metadata; schema order, drift, collisions, descriptors, fingerprints, and extras; lexical and null-family failures; separate dual-family provenance; repeated-row preservation; the closed diagnostic vocabulary and redaction; owner-data exclusion; existing registry compatibility; package boundaries; and absence of production runtime, network, dependency, or source artifacts. Ensure `make test` collects this exact test module. [source_ids: 515a41057d446a949cae5adc, 3321aaed641cd22210fac979, be2861af666dfc3b02456915, c3dd5eb82533bab379d6af62, 8230e8434d4ed3576ea75416]

## 5. Bounded Source Documentation

<!-- countyforge-task: 5.1 paths=docs/sources/collin-access-decoder-foundation.md checks=docs.links risk=normal prerequisites=D1,D2,D3,D4,4.1 -->
- [x] 5.1 Document the Collin adapter foundation contract — Add `collin-access-decoder-foundation.md` describing the implemented reader-specific wrapper, exact structural projection, source-value and dual-family semantics, unresolved account identity, provenance, diagnostics, independent synthetic fixture authorship, resource assumptions, privacy boundary, rollback posture, Issue #43 ownership, and non-production compatibility limits. Link to this OpenSpec change rather than duplicating it as a competing normative source. [source_ids: 3ff4dd1258ffbf8403ca8eec, 8230e8434d4ed3576ea75416, 37b0be1db5c2ff2ef21f3eae]

## 6. Deterministic Validation

<!-- countyforge-task: 6.1 paths=libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py,libs/property-tax-adapters/tests/test_collin_decoder.py,libs/property-tax-adapters/tests/fixtures/collin_synthetic.py,docs/sources/collin-access-decoder-foundation.md checks=repo.check,repo.prepr-no-ai risk=normal prerequisites=1.1,2.1,3.1,4.1,5.1 -->
- [x] 6.1 Run the complete no-cost acceptance gates — Run `openspec validate add-collin-cad-access-decoder-foundation --strict`, `openspec doctor`, `make check`, and `make prepr-no-ai`. Confirm Ruff, mypy, collected pytest coverage, documentation links, strict OpenSpec validation, artifact policy, and secret scanning pass and that no county artifact, production data, owner value, credential, network behavior, new dependency, domain/application change, production API, persistence, orchestration, deployment, or production-ready claim was introduced.
