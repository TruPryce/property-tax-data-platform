## Why

The repository needs a deterministic, adapter-local foundation for parsing Denton CAD PACS fixed-width records from synthetic evidence, and a reusable fixed-width serialization component that Ellis and later PACS counties bind to rather than fork. Without the shared component each PACS county reimplements position slicing; without the county boundary, PACS vocabulary leaks into the canonical domain.

## Outcome

Add `property_tax_adapters.sources.pacs`, a reusable fixed-width serialization component containing mechanics only, and implement the Denton binding on top of it in the existing Denton adapter module, with independently authored synthetic fixtures, a Denton test module, and bounded source documentation.

The interim public surface is a validator rather than a row producer. `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` are owned by Issue #43 and do not exist yet, and this change adds no county-local substitute for any of them, so typed record output is deferred rather than duplicated.

## Scope

- Originating issue: #20
- Affected capability: denton-cad-source-contract (ADDED)
- Governing input: the accepted Denton source contract in `bootstrap-six-county-appraisal-platform`

## Constraints

- Owner names, mailing addresses, situs addresses, complete records, arbitrary values, account values, credentials, and host paths remain default-deny for fixtures, reports, diagnostics, logs, and outputs.
- Values sliced from an undocumented trailing region are discarded, because an unknown region may carry identity or address data.
- Diagnostics use a closed vocabulary, four permitted metadata fields, a 100-entry retention cap, a preserved total count, and deterministic truncation.
- The foundation performs no network access and uses no county artifacts, production rows, archives, or layouts.
- The shared component contains serialization mechanics only and carries no county field name, threshold, or policy.

## Non-goals

- Live Denton discovery, conditional observation, redirect handling, download, or archive acquisition.
- ZIP or XLSX container parsing, and member resolution across an archive.
- Nightly CSV, text, geodatabase, or GIS extract support.
- Preliminary, certified, and roll-correction precedence, and same-year replacement semantics.
- Account-level owner-allocation roll-up.
- The record-free evidence manifest and the production-readiness gate.
- Database migrations, persistence, Bronze, Silver, Gold, backfill, Airflow, services, APIs, workflows, infrastructure, deployment, or production configuration.
- Owner or mailing-address publication.
- Domain or application changes, and any county-local substitute for a contract Issue #43 owns.

## Decisions

- **D1** (proposed by this change, requires human merge): The shared component declares fields as 1-indexed inclusive `start` and `end` with a required flag, and validates ascending order, non-overlap, and length agreement at construction. Those are authoring defects in trusted repository code, so they raise `ValueError` rather than emitting a diagnostic: a trusted-code defect is not source data.
- **D2** (proposed by this change, requires human merge): Each county pins its expected fingerprints as literals rather than deriving them from the layout, so an unreviewed mapping edit breaks the gate instead of moving both sides of it. The layout fingerprint is the lowercase SHA-256 of a canonical JSON document with exactly `component_contract_version`, `layout_id`, `layout_version`, `field_count`, and `fields`, serialized with keys sorted by code point, the separators `,` and `:` and no other whitespace, literal non-ASCII, and UTF-8 bytes. It is versioned separately from any export-header version.
- **D3** (proposed by this change, requires human merge): Denton lexical bounds are `prop_id` 1 through 32 visible ASCII characters, `owner_sequence` one to four ASCII digits, monetary `[0-9]+(?:\.[0-9]{1,2})?` bounded 0 through `10**26 - 1`, `ownership_percentage` `[0-9]{1,3}(?:\.[0-9]{1,6})?` bounded 0 through 100, and a four-digit tax year bounded 1900 through 2100 that equals the caller-supplied expected year.
- **D4** (proposed by this change, requires human merge): A core appraisal child orphan blocks the release; a legal child orphan warns without blocking. An undocumented trailing region is likewise non-fatal, and its content is discarded.

**Provenance.** The Denton source contract in `bootstrap-six-county-appraisal-platform` and Issue #20 are the authoritative input. D1 through D4 are proposed by this change to close gaps that input leaves open — it fixes the obligations but states no positions grammar, fingerprint serialization, lexical bounds, or orphan disposition — and no prior maintainer selection is claimed for any of them. Merging this change is what accepts them.

## Unresolved decisions

- Issue #43 has not supplied the accepted and implemented `SourceNativeValue`, `SourceProvenance`, `AppraisalSourceRecord`, bounded release-processing, and streaming contracts. Typed Denton and vendor-neutral record output is therefore deferred to tasks 6.1 and 6.2, which are recorded unchecked rather than omitted: Issue #20 is not complete until they land. This change adds no county-local substitute while waiting, and tasks 1.1 through 5.1 are runnable without it.

## Cross-issue boundaries

- #43 (requires_contract_from): out of scope here and owned there: SourceNativeValue, SourceProvenance, AppraisalSourceRecord, bounded release processing, streaming and atomic-stage contracts. Denton physical parsing, lexical validation, grain preservation, and diagnostics carry no dependency on that boundary.
- #21 (related_to): Ellis binds to the shared PACS component this change adds and must not fork it.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
