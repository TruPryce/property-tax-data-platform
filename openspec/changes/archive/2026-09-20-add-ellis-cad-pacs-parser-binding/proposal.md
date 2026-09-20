## Why

Ellis publishes a PACS fixed-width export like Denton, and the tempting shortcut is to assume the two are the same because the vendor is. The accepted Ellis contract forbids that: compatibility must be established by Ellis's own fingerprint rather than by vendor, filename, or Denton equivalence. Ellis also publishes its layout as an OpenDocument package behind a misleading `.xlsx.ods` name, and classifying it by extension would select the wrong parser.

## Outcome

Bind Ellis to the shared PACS serialization component added for Denton, with an Ellis-specific versioned mapping, an independent expected fingerprint, content-based layout-package classification, scenario-label exclusion, and the Ellis lexical, grain, diagnostic, and privacy rules, plus independently authored synthetic fixtures, an Ellis test module, and bounded source documentation.

The interim public surface is a validator rather than a row producer, matching Denton. `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` are owned by Issue #43 and do not exist yet, and this change adds no county-local substitute.

## Scope

- Originating issue: #21
- Affected capability: ellis-cad-source-contract (ADDED)
- Governing input: the accepted Ellis source contract in `bootstrap-six-county-appraisal-platform`

## Constraints

- The shared PACS component is bound, never copied or forked. Ellis defines no position-slicing, layout-validation, or fingerprint logic of its own.
- Owner names, mailing addresses, situs addresses, complete records, arbitrary values, account values, credentials, and host paths remain default-deny for fixtures, reports, diagnostics, logs, and outputs.
- Layout-package recognition is a bounded signature check on caller-supplied bytes. No package is extracted, enumerated, or decompressed.
- Diagnostics use a closed vocabulary, four permitted metadata fields, a 100-entry retention cap, a preserved total count, and deterministic truncation.
- The foundation performs no network access and uses no county artifacts, production rows, archives, or published layouts.

## Non-goals

- Live Ellis rendered-page discovery, redirect handling, or download.
- ZIP or archive extraction, and complete ODS layout extraction.
- Preliminary or correction-roll behaviour, and historical release modelling across tax years.
- Account-level owner-allocation roll-up.
- The record-free evidence manifest and the production-readiness gate.
- Database migrations, persistence, Bronze, Silver, Gold, backfill, Airflow, services, APIs, workflows, infrastructure, deployment, or production configuration.
- Owner or mailing-address publication.
- Cross-county policy generalisation, and any county-local substitute for a contract Issue #43 owns.

## Decisions

- **D1** (proposed by this change, requires human merge): Ellis carries its own expected layout fingerprint, written as a literal rather than derived from the layout, and compares the declared mapping against it before parsing. A derived constant would move with the mapping and the comparison could never fail. Sharing a vendor with Denton is not evidence of compatibility, and the two fingerprints are independent values that are never assumed equal.
- **D2** (proposed by this change, requires human merge): An OpenDocument Spreadsheet package is recognised by a ZIP local-file-header signature followed by a first member named `mimetype` whose stored value is `application/vnd.oasis.opendocument.spreadsheet`. Recognition is a bounded signature check on caller-supplied bytes; nothing is extracted, enumerated, or decompressed. An absent, truncated, or ambiguous signature fails closed.
- **D3** (proposed by this change, requires human merge): The approved certified release label is `certified-all-property`. Any other caller-supplied label — a potential-exemption scenario, a mineral-only release, or an ambiguous value — is rejected with `unsupported_scenario_label` before any record is read.
- **D5** (proposed by this change, requires human merge): Ellis child lexical bounds mirror Denton's: `child_sequence` one to four ASCII digits and required, `child_value` the property monetary grammar bounded 0 through `10**26 - 1` and optional, with empty text after trimming as the only null. Decided here so task 6.3 applies them rather than an implementer choosing them.
- **D4** (proposed by this change, requires human merge): Ellis reuses the Denton lexical bounds, because both are PACS exports and diverging without evidence would be inventing a difference rather than measuring one. The bounds remain declared per county so a measured divergence changes one county without touching the other.

**Provenance.** The Ellis source contract in `bootstrap-six-county-appraisal-platform` and Issue #21 are the authoritative input. D1 through D5 are proposed by this change to close gaps that input leaves open — it fixes the obligations but states no fingerprint comparison mechanism, package signature, approved label value, or property and child lexical bounds — and no prior maintainer selection is claimed for any of them. Merging this change is what accepts them.

## Unresolved decisions

- Issue #43 has not supplied the accepted and implemented `SourceNativeValue`, `SourceProvenance`, `AppraisalSourceRecord`, bounded release-processing, and streaming contracts. Typed Ellis and vendor-neutral record output, and typed child records, are therefore deferred to tasks 6.1, 6.2, and 6.3, which are recorded unchecked rather than omitted: Issue #21 is not complete until all three land. This change adds no county-local substitute while waiting, and tasks 1.1 through 5.1 are runnable without it.

## Cross-issue boundaries

- #20 (requires_contract_from): the shared PACS serialization component is added there and bound here. This change adds no position-slicing, layout-validation, or fingerprint logic of its own.
- #43 (requires_contract_from): out of scope here and owned there: SourceNativeValue, SourceProvenance, AppraisalSourceRecord, bounded release processing, streaming and atomic-stage contracts.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
