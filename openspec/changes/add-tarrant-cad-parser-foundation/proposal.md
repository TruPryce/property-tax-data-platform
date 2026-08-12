## Why

The repository needs a deterministic, adapter-local foundation contract for parsing Tarrant CAD certified-core pipe-delimited records from synthetic evidence. The contract must preserve Tarrant-native values and provenance, fail closed on malformed releases, protect sensitive values, and avoid unsupported canonical appraisal, exemption, replacement, or tax-collection semantics.

## Outcome

Implement the synthetic Tarrant certified-core parser in the existing Tarrant adapter module, with independently authored synthetic fixtures, a Tarrant test module, and bounded source documentation. The parser decodes one already-selected member, binds the sixteen required headers by exact name, computes the exact layout fingerprint, validates the approved lexical grammars, enforces release-wide account uniqueness, rejects a logical release atomically through a closed diagnostic vocabulary, and excludes sensitive and unknown-column values.

Parsing, validation, diagnostics, fixtures, tests, and documentation are implementable now and produce validated values rather than a record type. Both typed-record slices — the frozen `TarrantCertifiedSourceRecord` and the shared conversion — wait on Issue #43, because the approved native record holds shared `SourceNativeValue` entries and no county-local substitute may be written in the meantime.

## Scope

- Originating issue: #19
- CountyForge planning run: `gh-8909f91cd2ad7733ad833633-a1`
- Affected capability: tarrant-cad-source-contract (ADDED)

## Constraints

- Owner, mailing-address, situs-address, legal-description, protected-identity, credential, host-path, complete-row, arbitrary-value, and account-value content remains default-deny for fixtures, records, diagnostics, logs, and outputs.
- Unknown-column values are discarded because absence of a confidentiality marker is not publication permission.
- Diagnostics use a closed vocabulary, bounded permitted metadata, a 100-entry retention cap, a preserved total count, and deterministic truncation.
- The parser foundation performs no network access and uses no county artifacts, production rows, or network responses.

## Non-goals

- Live Tarrant discovery, source contact, HTTP probing, download, archive acquisition, or member selection.
- Parsing mutable current-roll or companion exemption products.
- Approving complete live headers, fingerprints, encoding behavior, field nullability, official value semantics, account stability, or same-year replacement behavior.
- Database migrations, persistence, Bronze, Silver, Gold, backfill, Airflow, services, APIs, workflows, infrastructure, deployment, or production configuration.
- Owner or mailing-address publication, protected-identity reconstruction, or retention of unknown-column values.
- Domain or application changes, cross-county normalization, a shared county base parser, or a Tarrant-derived vendor-neutral abstraction.
- A production-ready designation for the Tarrant adapter.

## Decisions

- **D1** (resolved_for_draft, requires human merge): Use parser contract version 1 with strict ISO-8859-1 decoding, UTF BOM rejection, pipe-delimited single-line records, defined double-quote handling, LF or CRLF endings, exact-name header binding, a required 16-header projection, observed-width row validation, metadata-only extra columns, and a deterministic SHA-256 layout fingerprint.
- **D2** (resolved_for_draft, requires human merge): Use deterministic synthetic lexical contracts for division, appraisal year, account and optional identifiers, source text, monetary values, dates, null handling, ranges, and release-wide Account_Num uniqueness without arithmetic or canonical semantic inference.
- **D3** (resolved_for_draft, requires human merge): Define a frozen adapter-local TarrantCertifiedSourceRecord, preserve approved fields as Tarrant-native facts, and require vendor-neutral conversion to consume the shared contracts owned by Issue #43 without introducing county-local substitutes or canonical appraisal and tax semantics.
- **D4** (resolved_for_draft, requires human merge): Require caller-supplied release identity, bounded provenance, a closed redacted diagnostic vocabulary, release-level atomic rejection, deterministic diagnostic truncation, default-deny owner and address handling, discarded unknown-column values, and independently authored synthetic fixtures.

## Unresolved decisions

- Issue #43 has not yet supplied the accepted and implemented SourceNativeValue, SourceProvenance, AppraisalSourceRecord, bounded release-processing, and streaming contracts. This blocks tasks 6.1 and 6.2 — the frozen Tarrant-native record and the shared conversion — because the approved record holds shared `SourceNativeValue` entries. Tasks 1.1 through 5.1 — contracts and fixtures, physical and header parsing with the layout fingerprint, lexical validation with uniqueness and atomic rejection, the test module, and the source documentation — are runnable without it, and the change adds no county-local substitute while waiting.
- Date grammar validation is **deferred out of this change**, and no task depends on an undecided input. D2 fixes the date components, calendar validity, and the 1900–2100 range but states no separator, so `3/14/2025`, `03-14-2025`, and `2025-03-14` are equally consistent with the approved input. Rather than ask a maintainer to approve a decision that selects nothing, this change carries `Deed_Date`, `Notice_Date`, and `Appraisal_Date` as opaque source-native text and leaves `invalid_source_date` reserved and unemitted. Nothing here interprets a date, so no other behavior depends on the deferral. A follow-on change adds the grammar once a maintainer supplies the exact lexical pattern.

## Cross-issue boundaries

- #43 (requires_contract_from, blocking tasks 6.1 and 6.2): out of scope here and owned there: SourceNativeValue, SourceProvenance, AppraisalSourceRecord, bounded release processing, streaming and atomic-stage contracts. Tarrant-native physical parsing, lexical validation, and county diagnostics carry no dependency on that boundary and are implemented independently of it.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
