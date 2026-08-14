## Current-state evidence

- Issue #21 requires an Ellis-specific mapping that uses the shared adapter-layer PACS component and explicitly forbids copying or forking that parser into an Ellis-specific implementation.
- The accepted Ellis source contract requires compatibility to be established independently by layout and data fingerprints rather than assumed from vendor or filename, and requires a divergence from Denton to quarantine the release or select a separately versioned Ellis mapping.
- The same contract requires the appraisal layout to be identified by content and validated package structure rather than filename extension, with the approved OpenDocument representation supported and a misleading `.xlsx.ods` name parsed as ODS.
- The same contract requires the plain certified appraisal roll to be distinguished from labelled hypothetical, potential-exemption, and mineral-only releases, which must not be classified as the authoritative certified all-property roll.
- The same contract requires `prop_id` and owner sequence as physical owner-row grain with no derived account roll-up, and owner and mailing-address publication disabled.
- The Denton change adds `property_tax_adapters.sources.pacs`, which carries serialization mechanics only and names no county, so binding to it is possible without inheriting Denton policy.
- `libs/property-tax-adapters/src/property_tax_adapters/sources/texas/ellis.py` currently holds only `ELLIS_SOURCE`, which the registry imports.

## Proposed architecture

One module, `property_tax_adapters.sources.texas.ellis`, layered on the shared component:

1. **The Ellis mapping.** A versioned layout declared with the shared field and layout types. Ellis defines no slicing, no layout validation, and no fingerprint computation of its own; those are exactly the mechanics the shared component exists to hold.
2. **Fingerprint gating.** An expected Ellis fingerprint constant, compared against the declared mapping before parsing. Ellis and Denton fingerprints are independent values, and a caller supplying another county's expected value is rejected rather than accommodated.
3. **Layout-package classification.** A bounded signature check: the ZIP local-file-header signature, then a first member named `mimetype` whose stored value is the OpenDocument Spreadsheet media type. Nothing is extracted, enumerated, or decompressed, so the check is safe on caller-supplied bytes and cannot be turned into an archive reader.
4. **Scenario-label gating.** The caller supplies a release label; anything outside the approved certified set is rejected before a record is read.
5. **Records.** The physical layer, the lexical grammars, owner-row grain, the closed diagnostic vocabulary, and atomic rejection.

`validate_property_member` returns one `EllisValidationReport` — counts, diagnostics, layout provenance, and the accepted release label. No field values, no records.

The ordering matters: the scenario label and the fingerprint are checked **before** any record is read, because both answer "is this the artifact we think it is?" and reading records from a misidentified artifact is how a mineral-only scenario roll becomes certified current state.

## Dependency direction

`ellis` depends on `pacs`. It does not depend on `denton`, and it must not: the two counties are independent bindings of one component, and a dependency between them would make a Denton layout change silently alter Ellis behaviour. Neither adds vocabulary to `property_tax_domain` or `property_tax_application`; `ELLIS_SOURCE` already imports both for the registry and is preserved unchanged.

## Data and contract changes

The Ellis capability specification in this change is the governing behaviour contract. No schema, migration, or persisted artifact is added.

## Alternatives considered

- **Reusing the Denton layout directly.** Rejected by the accepted contract: compatibility must be established by Ellis's own fingerprint, not by vendor equivalence. Reuse would also couple the two counties so that a Denton measurement changed Ellis silently.
- **Classifying the layout package by extension.** Rejected: the published name ends in `.xlsx.ods`, so extension-based selection picks the wrong parser. Content classification is the contract.
- **Parsing the ODS package to read the layout.** Rejected as out of scope and as an unnecessary risk surface. Recognition establishes what the package is; reading it is separate future work.
- **Deriving Ellis lexical bounds independently.** Rejected: no Ellis measurement exists, so diverging from Denton would be inventing a difference rather than measuring one. The bounds are declared per county so a measured divergence later changes one county only.

## Decisions and assumptions

- **D1** (proposed by this change, requires human merge): an independent expected Ellis fingerprint, compared before parsing.
- **D2** (proposed by this change, requires human merge): the ODS signature check and its fail-closed behaviour.
- **D3** (proposed by this change, requires human merge): `certified-all-property` as the approved label, everything else rejected before records are read.
- **D4** (proposed by this change, requires human merge): Ellis reuses the Denton lexical bounds, declared per county.

D1 through D4 come from this change rather than from an issue comment, so they are listed explicitly and merging is what accepts them.

- The foundation receives one already-selected, caller-supplied member and caller-supplied package bytes; discovery, downloads, and extraction remain outside its scope.
- The synthetic layout and lexical rules are a deterministic foundation contract and do not prove compatibility with a live Ellis release.
- No new dependency is approved; the implementation uses the standard library.

## Unresolved decisions

- Issue #43 has not supplied the shared adapter contracts, so typed record output is deferred. No task in this change depends on it.

## Risks and compatibility

- The synthetic Ellis layout may differ from the published Ellis PACS layout, so this establishes no live compatibility.
- The real Ellis field positions, observed widths, account alphabet, and monetary scale remain unproved, as does whether Ellis and Denton layouts genuinely agree.
- The signature check recognises a well-formed ODS package; it does not validate the layout the package contains.

## Rollout and failure recovery

Validation commands: `make check`, `make prepr-no-ai`, `openspec validate add-ellis-cad-pacs-parser-binding --strict`. Failures remain blocked and authorize no implementation.

## Testing strategy

Tests for binding rather than forking, fingerprint independence from Denton and rejection of a foreign expected value, ODS recognition behind a misleading name with fail-closed behaviour on absent, truncated, and ambiguous signatures, scenario-label acceptance and rejection before any record is read, the physical and lexical layers, owner-row grain with duplicate and conflict rejection, the closed vocabulary and its four permitted fields, deterministic truncation, atomic rejection, privacy exclusion, and the architectural boundary. Fixtures are independently authored with literal expected results.
