## Why

Issue #43 required decision 7 directs: "Move vendor-neutral adapter types such as `AppraisalSourceRecord`, `SourceProvenance`, and `SourceNativeValue` to a county-neutral `property_tax_adapters` module before Collin or a DAG depends on them."

Those types exist today, in merged and accepted Dallas code, with concrete fields. A literal move would relocate that exact shape. This change proposes to **revise** the shape while moving it, and says so plainly below, because a straight move does not serve the four counties that came after Dallas.

The cost of not having it is now measurable. Eight tasks are unchecked across three accepted changes — Tarrant 6.1–6.2, Denton 6.1–6.3, Ellis 6.1–6.3 — because each of those contracts forbids building a county-local substitute until this lands. Meanwhile Collin wrote its own parallel set, which disagrees with Dallas's on nearly every field.

## Outcome

Add `property_tax_adapters.sources.contracts` holding the vendor-neutral `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord`, designed against five counties rather than one, and migrate Dallas and Collin onto it.

## Scope

- Originating issue: #43, required decision 7 only
- Affected capability: adapter-source-contracts (ADDED)

## This is a revision of required decision 7, not only a move

Required decision 7 names the types but states no field list of its own. The field list it points at is the merged Dallas definition. Here is exactly what this change proposes to alter, so the departure is reviewable rather than buried:

| type | merged Dallas today | proposed |
| --- | --- | --- |
| `SourceNativeValue` | `lexical_text: str`, `value: str \| Decimal` | adds `source_field: str`; `lexical_text` becomes `str \| None`; `value` widens to `str \| int \| Decimal \| None` |
| `SourceProvenance` | `observed_headers`, `normalized_headers`, plus five shared fields | header vectors move out to the already-existing `DallasSourceProvenance`; adds `jurisdiction_code` and `source_contract_version` |
| `AppraisalSourceRecord` | `source_account_id: str`, `jurisdiction_code: Literal["tx-dallas"]` | `source_account_id` becomes `str \| None`; adds `source_family: str \| None`, `source_status: str \| None`, `source_native_identifiers`; `jurisdiction_code` stops being a Dallas literal |

Every one of these is forced by a county other than Dallas, and each is justified under its decision below. None of it is accepted until a maintainer merges this change.

## Explicitly not in this change

Issue #43 carries eight required decisions. This change takes **7** only. Decisions 1–6 and 8 — the bounded production input contract, validation ordering, the release-rejection boundary, bounded cross-row checks, `LocalExecutor` resource limits, the disposition of the Dallas `bytes | str -> tuple` helper, and the progress-event contract — remain open in #43, along with every acceptance criterion that depends on them.

The measured memory problem is real and stays open: 663 MiB retained on 200,000 Dallas rows against a 4 GiB scheduler with `PARALLELISM=4`. It is a property of the release-processing API, not of the record types, and making per-record containers lighter would not change a design that materializes every row. Splitting also fixes a practical problem: planning the whole of #43 spent 2,727 seconds against a 2,700-second budget, and overrides may only tighten, so the 3,600-second ceiling was unreachable.

## Constraints

- The shared module carries no county vocabulary, no county field name, and no county policy, exactly as the shared PACS component does.
- No canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement semantics are introduced.
- `property_tax_domain` and `property_tax_application` are unchanged and gain no adapter vocabulary.
- No new dependency; the standard library only.
- Migration preserves each county's observable behaviour exactly. A migration that changes what a parser accepts or rejects is out of scope.
- Dependency direction, layout fingerprinting, release-level atomicity, bounded diagnostics, provenance, and exact-decimal handling are not weakened.

## Non-goals

- Bounded release processing, streaming, the atomic stage, progress events, and the benchmark — all still #43.
- Persistence, Bronze, Silver, Gold, DAGs, services, migrations, and orchestration.
- Unblocking Tarrant, Denton, or Ellis, which happens in their own accepted changes once these contracts exist.
- Amending any accepted county contract.

## Decisions

- **D1** (proposed by this change, requires human merge): `SourceNativeValue` carries `source_field: str`, `lexical_text: str | None`, `value: str | int | Decimal | None`, and `classification: Literal["source-native"]`. `source_field` is added because three accepted county specifications require the exact source field to travel with the value, and Dallas's type cannot name where a value came from. `lexical_text` is **nullable** because Collin has no source text to supply: `decode_collin_numeric` reads a 17-byte binary wrapper, so there is no original lexical form to preserve exactly. It SHALL be present whenever the source is textual. Collin's `precision` and `scale` are not promoted; they describe an Access NUMERIC decode. This does not weaken Collin's accepted requirement to preserve "declared precision, declared scale, exact source column" — precision and scale stay in a Collin-local type composing the shared value, and the exact source column becomes `source_field`.
- **D2** (proposed by this change, requires human merge): `SourceProvenance` carries `jurisdiction_code`, `release_identifier`, `source_member_name`, `source_row_number`, `parser_contract_version`, `layout_fingerprint`, and `source_contract_version`. That is the intersection all five counties already agree on, plus the contract version that identifies which shared contract produced a record. County-specific provenance composes the shared type rather than subclassing it. `DallasSourceProvenance` already exists on `main` and already holds the header vectors; this change makes it hold a shared `SourceProvenance` too.
- **D3** (proposed by this change, requires human merge): `AppraisalSourceRecord` carries `jurisdiction_code`, `source_account_id: str | None`, `appraisal_year`, `source_family: str | None`, `source_status: str | None`, `parcel_reference: str | None`, `source_native_identifiers`, `source_native_values`, and a required `provenance`. When present, `source_account_id` is **text**, because Denton's accepted contract requires `000123` and `123` to compare as distinct and an integer type erases that silently. It is **nullable** because Collin's accepted contract forbids declaring either candidate an account key (see D5), and `source_family`/`source_status` are nullable because Dallas classifies neither today. A blank string is rejected; absence is expressed as `None`, never as `""`.
- **D4** (proposed by this change, requires human merge): `jurisdiction_code` is a lowercase state prefix plus county slug and is no longer a Dallas literal. `source_family` and `source_status` are county-supplied strings rather than a shared enumeration, because the observed families are county products and an enum would need editing whenever a county finds a new one.
- **D5** (proposed by this change, requires human merge): Collin sets `source_account_id` to `None`. Its accepted contract states that `prop_id` "MUST NOT be declared a unique or canonical account key" and that `geo_id` "MUST NOT be equated with `prop_id`", so neither may be promoted. Both are preserved in `source_native_identifiers` under their exact source names, as distinct entries with no equivalence asserted between them. `CollinAppraisalSourceRecord`, `CollinObservationProvenance`, and `CollinAppraisalObservation` remain county-local. Collin emits one shared record per current or certified observation, with no deduplication and no merging, which upholds its requirement that the adapter "MUST NOT ... fill a missing current or certified value from the other family."
- **D6** (proposed by this change, requires human merge): the shared types guarantee that they define **no named identity field and no untyped payload attribute**. They do **not** guarantee that no identity value can reach a record, and this change does not claim otherwise. `source_native_values` is a mapping of county-chosen source fields, and Dallas's accepted contract requires retaining unknown extras — `convert_dallas_appraisal_record` already places every unknown CSV column into the vendor-neutral values map. A shared allowlist would therefore contradict an accepted county contract. Keeping identity out of records stays a county-contract obligation, enforced where the county knows its columns.

**Provenance.** Issue #43 required decision 7 and the five accepted county contracts are the authoritative input. D1 through D6 are proposed by this change, each departing from the merged Dallas shape only where a named accepted contract makes that shape unusable. No prior maintainer selection is claimed for any of them, and merging this change is what accepts them.

## Unresolved decisions

- None. Issue #43 decisions 1–6 and 8 are out of scope here rather than unresolved; they keep their issue.

## Risks and open tension worth a maintainer's attention

Dallas's accepted contract requires retaining unknown extras, and those extras flow into the vendor-neutral record today. That is accepted behaviour and this change preserves it, but it means a Dallas release that adds an owner-name column would carry it into a shared record. Closing that belongs in the Dallas contract, not here; D6 states the limit honestly rather than promising a guarantee the type system cannot keep.

## Cross-issue boundaries

- #19, #20, #21 (related_to): Tarrant, Denton, and Ellis each hold blocked tasks that these contracts unblock. Those tasks are completed in their own changes, not here.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
