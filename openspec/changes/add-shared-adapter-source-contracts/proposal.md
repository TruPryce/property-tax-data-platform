## Why

Issue #43 decision **D7 — Shared adapter-neutral records** is authoritative maintainer input and it specifies these contracts field by field. This change implements it.

Eight tasks are unchecked across three accepted changes — Tarrant 6.1–6.2, Denton 6.1–6.3, Ellis 6.1–6.3 — because each of those contracts forbids building a county-local substitute until D7 lands. Collin and Dallas meanwhile carry duplicate, mutually inconsistent copies, which D7 directs be moved into one shared module.

## Outcome

Add `property_tax_adapters.sources.contracts` holding `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` as D7 specifies, and migrate Dallas and Collin onto it case-for-case.

## Scope

- Originating issue: #43, decision D7 only
- Affected capabilities: adapter-source-contracts (ADDED), dallas-cad-source-contract (MODIFIED)

## Conformance with the approved D7 field list

D7's approved fields, and what this change does with each. Everything is adopted as approved except one field, marked and justified below.

**`SourceNativeValue`**

| D7 approved | this change |
| --- | --- |
| exact `str \| int \| Decimal` value | adopted, unchanged — `None` is **not** a value |
| optional original lexical text | adopted; absent as `None`, and `""` when an empty text was genuinely observed |
| exact source field | adopted |
| optional precision/scale | adopted |
| fixed `source-native` classification | adopted |

**`SourceProvenance`**

| D7 approved | this change |
| --- | --- |
| jurisdiction | adopted |
| caller-supplied release/member identity | adopted |
| one-based physical row | adopted |
| parser contract version | adopted |
| layout fingerprint | adopted |
| optional table, source family, source year, status, observed fields, normalized fields | adopted, all six |

**`AppraisalSourceRecord`**

| D7 approved | this change |
| --- | --- |
| jurisdiction | adopted |
| optional approved source-account ID | adopted |
| source-native identifier mapping | adopted |
| appraisal year | adopted |
| source family | **superseded — proposed optional** (D3) |
| optional source status | adopted |
| optional parcel reference | adopted |
| source-native value mapping | adopted |
| shared provenance | adopted |

D7's rules are adopted verbatim: the account ID is optional so Collin's `prop_id` or `geo_id` is not silently promoted; Dallas populates its approved account ID and parcel reference; Collin preserves both identifiers as source identifiers and emits distinct current and certified records without family collapse; county-native input records and county diagnostics remain in county modules; existing Dallas and Collin behaviour and tests remain case-for-case.

## The one supersession

`source_family` is required on the record in D7. This change proposes it be `str | None`.

Dallas classifies no source family today — `dallas.py` has no such concept — and D7's own rules assign Dallas only "its approved account ID and parcel reference", naming no family value for it. A required field with no approved Dallas value would force this change either to invent one or to abandon the case-for-case Dallas migration that D7 also requires. Making it optional keeps both. D7 already places source family on provenance as optional, so optionality is not foreign to the decision.

This supersedes approved input and is not accepted until a maintainer merges this change.

## Explicitly not in this change

Issue #43 also carries D1 through D6 and D8 — the bounded production input contract, validation ordering, the release-rejection boundary, bounded cross-row checks, `LocalExecutor` resource limits, the disposition of the `bytes | str` fixture helper, and the `ReleaseProgressEvent` progress contract. None are touched here.

The measured memory problem stays open: 663 MiB retained on 200,000 Dallas rows against a 4 GiB scheduler. It is a property of the release-processing API, not of per-record containers. Splitting also fixes a practical problem: planning the whole of #43 spent 2,727 seconds against a 2,700-second budget, and overrides may only tighten, so the 3,600-second ceiling was unreachable.

## Constraints

- `property_tax_domain` and `property_tax_application` are not modified, as D7 directs.
- The shared module carries no county vocabulary, no county field name, and no county policy.
- No canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement semantics are introduced.
- No new dependency; the standard library only.
- Migration preserves observable behaviour exactly. Every existing Dallas and Collin case is preserved or migrated case-for-case, and none disappears.
- Dependency direction, layout fingerprinting, release-level atomicity, bounded diagnostics, provenance, and exact-decimal handling are not weakened.

## Non-goals

- Bounded release processing, streaming, the atomic stage, progress events, and the benchmark.
- Persistence, Bronze, Silver, Gold, DAGs, services, migrations, and orchestration.
- Unblocking Tarrant, Denton, or Ellis, which happens in their own accepted changes.
- Amending any accepted county contract.

## Decisions

- **D1** (conforms to issue #43 D7; gap-fills proposed by this change): `SourceNativeValue` carries `source_field: str`, `lexical_text: str | None`, `value: str | int | Decimal`, `precision: int | None`, `scale: int | None`, and `classification: Literal["source-native"]`. Gap-fills D7 leaves open: a blank or whitespace-only `source_field` is rejected; `lexical_text` is `None` only where the source has no text — Collin's `decode_collin_numeric` reads a 17-byte binary wrapper — and is `""` where an empty text was observed, which Dallas produces today for an empty extra column; `precision` and `scale` are supplied together or not at all.
- **D2** (conforms to issue #43 D7): `SourceProvenance` carries `jurisdiction_code: str`, `release_identifier: str`, `source_member_name: str`, `source_row_number: int`, `parser_contract_version: int`, `layout_fingerprint: str`, and D7's six optional fields typed `table_name: str | None`, `source_family: str | None`, `source_year: int | None`, `source_status: str | None`, `observed_fields: tuple[str, ...] | None`, and `normalized_fields: tuple[str, ...] | None`. `None` on a field vector means the county records no such vector; an empty tuple means it recorded an empty one. No field is added beyond D7's list. A nonpositive row number is rejected. County-native provenance types stay in county modules and hold a shared `SourceProvenance` as a field rather than subclassing it.
- **D3** (supersedes issue #43 D7 in one field; otherwise conforms): `AppraisalSourceRecord` carries `jurisdiction_code: str`, `source_account_id: str | None`, `source_native_identifiers: Mapping[str, str]`, `appraisal_year: int`, `source_family: str | None`, `source_status: str | None`, `parcel_reference: str | None`, `source_native_values: Mapping[str, SourceNativeValue]`, and a required `provenance: SourceProvenance`. Both mappings are exposed as read-only views over defensive copies. `source_family` optional is the supersession justified above. Where present, an account identifier is text, so Denton's requirement that `000123` and `123` compare as distinct survives. Gap-fills: every nullable metadata field — `source_account_id`, `source_family`, `source_status`, `parcel_reference` on the record and `table_name`, `source_family`, `source_status` on provenance — rejects a blank **or whitespace-only** string, so absence is `None` and never a string that merely looks empty; `lexical_text` is exempt, because an observed text is preserved exactly, whitespace included. Each `source_native_values` key equals its value's `source_field`; the record's jurisdiction equals its provenance's.
- **D4** (proposed by this change; D7 states jurisdiction without a shape): `jurisdiction_code` is a lowercase two-letter state prefix, a hyphen, and a county slug, and is not pinned to one county by type.
- **D5** (conforms to issue #43 D7's Collin rules and to maintainer direction): Collin sets `source_account_id` to `None`, because its accepted contract states `prop_id` "MUST NOT be declared a unique or canonical account key" and `geo_id` "MUST NOT be equated with `prop_id`". Both are preserved in `source_native_identifiers` under their exact source names as distinct entries with no equivalence asserted. `CollinAppraisalSourceRecord`, `CollinObservationProvenance`, and `CollinAppraisalObservation` remain county-local. Collin emits one shared record per current or certified observation, with no deduplication and no family collapse.
- **D6** (proposed by this change; D7 is silent on the privacy limit): the shared types guarantee no named identity field and no untyped payload attribute. They do **not** guarantee that identity data cannot reach a record. `source_native_values` is keyed by county-chosen source fields, and Dallas's accepted contract requires retaining unknown extras — `convert_dallas_appraisal_record` already places every unknown CSV column there. A shared allowlist would contradict an accepted county contract, so keeping identity out of records remains a county-contract obligation.

**Provenance.** Issue #43 D7 and the five accepted county contracts are the authoritative input. D1, D2, and D5 conform to D7. D3 supersedes exactly one approved field and says so. D4 and D6 fill gaps D7 leaves open. No prior maintainer selection is claimed for the supersession or the gap-fills, and merging this change is what accepts them.

## Unresolved decisions

- None.

## Open tension worth a maintainer's attention

Dallas's accepted contract requires retaining unknown extras, and those extras reach vendor-neutral records today. This change preserves that, so a Dallas release adding an owner-name column would carry it into a shared record. Closing this belongs in the Dallas contract and is worth its own issue before live release work.

## Cross-issue boundaries

- #19, #20, #21 (consumers of this contract; **not** a blocking dependency of this change): Tarrant, Denton, and Ellis hold blocked tasks these contracts unblock. Those tasks are completed in their own changes.

Review asked that these three be relabelled `requires_contract_from`. That relationship is directional and inbound: `_BLOCKING_RELATIONSHIPS` in `planning_semantics.py` treats `blocked_by` and `requires_contract_from` as obligations *this* plan cannot satisfy, and `_validate_dependency_obligations` fails a plan that declares one without `status: blocked`. Declaring it here would assert that #43 is blocked by #19, #20, and #21, which inverts the real dependency and would make this plan ineligible.

The relationship already exists in the correct direction, in the consumers' own accepted artifacts: Tarrant declares `#43 (requires_contract_from, blocking tasks 6.1 and 6.2)`, and Denton and Ellis each declare `#43 (requires_contract_from)`. Nothing is missing; adding the inverse would break the semantic gate rather than strengthen it.

## Delta to an accepted capability

The shared `source_account_id` is `str | None`, but Dallas's accepted contract guarantees `source_account_id: str` and a jurisdiction fixed to `tx-dallas`. Adopting a nullable shared field would silently weaken that guarantee, so this change carries a MODIFIED delta to `dallas-cad-source-contract` restating it against the shared types: the Dallas converter always emits `tx-dallas`, always emits a non-null account identifier and parcel reference, and keys `source_native_values` by the normalized header. Task 3.1 carries the regression tests.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
