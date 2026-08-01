## 1. Adapter Records and Parser

<!-- countyforge-task: 1.1 paths=libs/property-tax-adapters checks=repo.check risk=normal prerequisites=- -->
- [ ] 1.1 Add adapter-local `SourceNativeDecimal`, `SourceNativeValue`, `DallasSourceProvenance`, `SourceProvenance`, `DallasAppraisalSourceRecord`, `AppraisalSourceRecord`, and the closed Dallas diagnostic vocabulary without changing domain or application packages.

<!-- countyforge-task: 1.2 paths=libs/property-tax-adapters checks=repo.check risk=normal prerequisites=1.1 -->
- [ ] 1.2 Implement UTF-8/BOM handling, strict comma-delimited CSV parsing, observed-header normalization, required-header and collision checks, canonical layout fingerprinting, exact row-width enforcement, unknown extras, and deterministic unsupported-layout diagnostics.

<!-- countyforge-task: 1.3 paths=libs/property-tax-adapters checks=repo.check risk=normal prerequisites=1.1,1.2 -->
- [ ] 1.3 Implement exact lexical validation and conversion for account number, appraisal year, parcel identifier, and source-native decimal values, including required-blank and duplicate account-year rejection.

<!-- countyforge-task: 1.4 paths=libs/property-tax-adapters checks=repo.check risk=normal prerequisites=1.1,1.2,1.3 -->
- [ ] 1.4 Implement adapter-local vendor-neutral conversion with jurisdiction `tx-dallas`, complete provenance retention, source-native extras, and no canonical semantics for `TOT_VAL`.

## 2. Adapter Tests and Synthetic Fixtures

<!-- countyforge-task: 2.1 paths=libs/property-tax-adapters checks=repo.check risk=normal prerequisites=1.2,1.3,1.4 -->
- [ ] 2.1 Add small independently authored synthetic fixtures and deterministic tests for valid rows, reordered columns, optional BOM, LF and CRLF, quoting, missing/duplicate/colliding headers, unknown extras, short/long rows, lexical failures, and duplicate account-year keys.

<!-- countyforge-task: 2.2 paths=libs/property-tax-adapters checks=repo.check risk=normal prerequisites=2.1 -->
- [ ] 2.2 Add deterministic tests for layout fingerprints, complete provenance and source-native marker retention, closed diagnostic codes, diagnostic redaction, `TOT_VAL` remaining source-native, and the domain/application package boundary.

## 3. Documentation and Validation

<!-- countyforge-task: 3.1 paths=docs checks=repo.check risk=normal prerequisites=1.4,2.2 -->
- [ ] 3.1 Document the Dallas parser source boundary, physical layout, lexical rules, provenance, diagnostics, synthetic fixture authorship, compatibility limits, privacy defaults, and non-production-ready status while linking to this normative OpenSpec contract.

<!-- countyforge-task: 3.2 paths=libs/property-tax-adapters,docs checks=repo.check risk=normal prerequisites=2.1,2.2,3.1 -->
- [ ] 3.2 Run `openspec validate add-dallas-cad-parser-foundation --strict`, `openspec doctor`, `make check`, and `make prepr-no-ai`; confirm no county artifact, production data, secret, network behavior, new dependency, domain/application change, persistence, publication, orchestration, deployment, owner publication, or production-ready claim was introduced.
