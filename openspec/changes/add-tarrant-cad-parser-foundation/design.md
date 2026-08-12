## Current-state evidence

- `120cbcad362436f6c106e146`: The issue requests deterministic header-driven pipe-delimited parsing, typed Tarrant adapter-layer records, synthetic fixtures, fail-closed validation, and no unsupported value, exemption, replacement, privacy, acquisition, persistence, orchestration, or publication behavior.
- `c197b56afee6f9e9f5fb3bb3`: The maintainer decision defines parser contract version 1, ISO-8859-1 decoding, BOM rejection, pipe delimiting, quote behavior, LF and CRLF handling, exact required headers, row-width validation, metadata-only extras, and the layout fingerprint.
- `7a428c5d41ca8b7be2132ac7`: The maintainer decision defines exact synthetic rules for division, appraisal year, Account_Num, optional identifiers and text, monetary values, dates, nulls, ranges, and release-wide duplicate detection.
- `744640b7f3706d11325b9a7a`: The maintainer decision defines TarrantCertifiedSourceRecord, source-native field mappings, absent canonical semantics, and conversion through shared Issue #43 contracts.
- `acd3ec5543a2bae6735f761b`: Tarrant must not create a local vendor-neutral output, provenance, or native-value family and must consume the shared contracts from Issue #43.
- `7edd4e7de23f27539de02658`: The maintainer decision defines caller-supplied release identity, bounded provenance, the closed diagnostic vocabulary, diagnostic redaction and retention, release atomicity, privacy handling, synthetic fixtures, and the recommended adapter-local scope.
- `a8d0164e015d086c00140812`: The accepted bootstrap design establishes hexagonal dependency direction, county-specific source formats, source-native preservation, default-deny owner publication, and the distinction between appraisal information and authoritative tax-collection records.
- `1b6acee37fd0a4979b5390da`: The accepted Dallas proposal provides precedent for an adapter-local synthetic parser foundation with no acquisition, persistence, orchestration, deployment, owner publication, new dependency, or production-ready claim.
- `ecfb4ddfeb7b9aebac801060`: The accepted planning design limits trusted materialization to .openspec.yaml, proposal.md, design.md, tasks.md, and one capability specification beneath the proposed OpenSpec change.
- `01d3e6556908838866385201`: The accepted implementation design derives dependency-ordered task plans from accepted OpenSpec work and binds each slice to allowed paths and registered checks.
- `37b0be1db5c2ff2ef21f3eae`: The source-onboarding documentation states that Tarrant uses a distinct source contract and that county source work must verify release semantics, layout, identity, privacy, fixtures, and redistribution constraints.

## Proposed architecture

All work lands inside the existing adapter boundary. `property_tax_adapters.sources.texas.tarrant` gains four layers, each depending only on the one beneath it:

1. **Declared contracts** — parser contract version `1`, the physical descriptor (ISO-8859-1, `|`, `"` with doubled-quote escaping, LF and CRLF), the exact sixteen-name required header projection, and the closed twenty-one-code diagnostic vocabulary.
2. **Physical layer** — strict decoding, BOM rejection, quote-aware field splitting, single-physical-line records, one-based row numbering, exact-name header binding, observed-width validation, metadata-only extras, and the SHA-256 layout fingerprint.
3. **Lexical layer** — the approved division, year, account, identifier, text, monetary, and date grammars; empty-text-only nulls; release-wide account uniqueness; and release-level atomic rejection with bounded, deterministically truncated diagnostics.
4. **Record layer** — the frozen `TarrantCertifiedSourceRecord` and `TarrantSourceProvenance`.

A fifth layer, conversion into the shared vendor-neutral `AppraisalSourceRecord`, imports `property_tax_adapters.sources.contracts` and is therefore blocked on Issue #43. It is a separate task so that layers 1 through 4 ship without it, and no county-local substitute is written while it waits.

Supporting files are `libs/property-tax-adapters/tests/fixtures/tarrant_synthetic.py` for independently authored synthetic members and literal expected results, `libs/property-tax-adapters/tests/test_tarrant_parser.py` for contract, failure, privacy, atomicity, and architecture coverage, and `docs/sources/tarrant-parser-foundation.md` for the bounded source documentation.

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- **D1** (resolved_for_draft, requires human merge): Use parser contract version 1 with strict ISO-8859-1 decoding, UTF BOM rejection, pipe-delimited single-line records, defined double-quote handling, LF or CRLF endings, exact-name header binding, a required 16-header projection, observed-width row validation, metadata-only extra columns, and a deterministic SHA-256 layout fingerprint.
- **D2** (resolved_for_draft, requires human merge): Use deterministic synthetic lexical contracts for division, appraisal year, account and optional identifiers, source text, monetary values, dates, null handling, ranges, and release-wide Account_Num uniqueness without arithmetic or canonical semantic inference.
- **D3** (resolved_for_draft, requires human merge): Define a frozen adapter-local TarrantCertifiedSourceRecord, preserve approved fields as Tarrant-native facts, and require vendor-neutral conversion to consume the shared contracts owned by Issue #43 without introducing county-local substitutes or canonical appraisal and tax semantics.
- **D4** (resolved_for_draft, requires human merge): Require caller-supplied release identity, bounded provenance, a closed redacted diagnostic vocabulary, release-level atomic rejection, deterministic diagnostic truncation, default-deny owner and address handling, discarded unknown-column values, and independently authored synthetic fixtures.

- The foundation receives one already-selected certified-core text member; archive acquisition, member selection, network access, persistence, orchestration, publication, and deployment remain outside its scope.
- The approved 16-header projection and lexical rules form a deterministic synthetic contract and do not prove compatibility with a live Tarrant release.
- No new dependency is approved; future implementation is expected to use existing project dependencies and Python standard-library facilities.
- The complete live 56-column header vector, expected live fingerprint, source licensing, replacement behavior, and complete confidentiality behavior remain unproved.
- Only collin-cad-source-contract appears in declared_capabilities, so tarrant-cad-source-contract is an added capability regardless of proposals or historical changes elsewhere in the packet.

## Cross-issue boundaries

- #43 (requires_contract_from): out of scope here and owned there: SourceNativeValue, SourceProvenance, AppraisalSourceRecord, bounded release processing, streaming and atomic-stage contracts

## Unresolved decisions

- Issue #43 has not yet supplied the accepted and implemented SourceNativeValue, SourceProvenance, AppraisalSourceRecord, bounded release-processing, and streaming contracts required for correct vendor-neutral Tarrant conversion.

## Risks and compatibility

- The synthetic 16-header projection may differ from the complete live certified-roll layout and therefore cannot establish live-release compatibility or production readiness.
- Strict synthetic lexical constraints may reject forms appearing in a future live release; relaxation requires independently reproduced evidence and a reviewed contract change.
- Discarding unknown-column values prevents accidental identity or address retention but may omit potentially useful facts until their semantics and privacy policy are reviewed.
- Official value meanings, account stability, source replacement behavior, current and exemption source classification, confidentiality behavior, and redistribution terms remain unresolved.
- Shared vendor-neutral conversion cannot be implemented correctly until Issue #43 supplies its accepted and implemented contracts.
- No data migration or backfill is required because the foundation adds no persistence, database schema, Bronze, Silver, Gold, or published release.
- The change is additive and adapter-local but does not assert compatibility with a live Tarrant release.
- Current-roll, companion exemption, replacement, canonical-value, publication, and production-reader behavior remain separate future contracts.
- Vendor-neutral conversion must conform to the contracts supplied by Issue #43 and cannot use a temporary Tarrant-local abstraction.
- Rollback consists of reverting the five planning artifacts before implementation; no stored data or published product requires repair.
- Live Tarrant source licensing and redistribution terms remain unverified, so only independently authored synthetic fixtures are authorized by this plan.

## Rollout and failure recovery

Validation commands: make check, make prepr-no-ai, openspec validate add-tarrant-cad-parser-foundation --strict. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
