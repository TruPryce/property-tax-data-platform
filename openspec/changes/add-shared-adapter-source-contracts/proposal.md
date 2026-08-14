## Why

Five counties now have parsers, and they disagree about the three types that were supposed to be shared.

Collin and Dallas each wrote their own. Dallas's `SourceNativeValue` carries `lexical_text` and a `str | Decimal` value; Collin's carries `precision`, `scale`, and `source_column` but no lexical text. Dallas's provenance carries observed and normalized headers; Collin's carries a table name and a schema fingerprint. Dallas's record is one row with a parcel reference; Collin's is one account with separate current and certified value maps.

Tarrant, Denton, and Ellis have the same types **excised** rather than duplicated, on the grounds that Issue #43 owns them. That leaves eight tasks unchecked across three accepted changes — Tarrant 6.1–6.2, Denton 6.1–6.3, Ellis 6.1–6.3 — and none of those three issues can be called complete.

So the cost of the missing contract is now measurable: eight blocked tasks, two divergent implementations, and three specifications that describe a type nothing provides.

## Outcome

Add `property_tax_adapters.sources.contracts`: the vendor-neutral `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` that every county adapter can reuse without importing a county module, designed against five counties rather than one.

Migrate Collin and Dallas onto it, deleting their local copies. Unblocking the three deferred counties is separate work in their own changes; this change makes it possible.

## Scope

- Originating issue: #43, narrowed
- Affected capability: adapter-source-contracts (ADDED)

## Explicitly not in this change

Issue #43 bundles four things. This change takes the first only:

| | |
| --- | --- |
| shared vendor-neutral contracts | **this change** |
| bounded release processing | separate |
| streaming and memory bounds | separate |
| the atomic stage contract | separate |

The measured memory problem — 663 MiB retained on 200,000 Dallas rows against a 4 GiB scheduler — is real and remains open. It is a property of the *release-processing API*, not of the record types, and the three deferred counties are blocked on the types alone. Separating them lets eight tasks unblock without waiting for a streaming design, and keeps a change small enough to plan and review. It also fixes a practical problem: planning the whole of #43 exhausted the provider's wall clock at 2,727 seconds against a 2,700-second budget.

## Constraints

- The contracts carry no county vocabulary, no county field name, and no county policy, exactly as the shared PACS component does.
- No canonical market, appraised, assessed, taxable, tax-amount, exemption-entitlement, or replacement semantics are introduced. These are source-native containers.
- Owner names, mailing addresses, and situs addresses remain default-deny and MUST NOT be representable in a shared record.
- `property_tax_domain` and `property_tax_application` are unchanged and gain no adapter vocabulary.
- No new dependency; the standard library only.
- Migration preserves each county's observable behaviour. A migration that changes what a parser accepts or rejects is out of scope and would be a separate change.

## Non-goals

- Bounded release processing, streaming, and the atomic stage.
- Persistence, Bronze, Silver, Gold, DAGs, services, migrations, and orchestration.
- Discovery, acquisition, and archive handling for any county.
- Unblocking Tarrant, Denton, or Ellis, which happens in their own accepted changes once these contracts exist.
- Collapsing Collin's dual current/certified observation model into the shared record.

## Decisions

- **D1** (proposed by this change, requires human merge): `SourceNativeValue` carries `source_field: str`, `lexical_text: str`, `value: str | int | Decimal | None`, and `classification: Literal["source-native"]`. The exact source field name and the original lexical text travel with every value, because three accepted county specifications require them and a value without its source field cannot be traced back. Collin's `precision` and `scale` are **not** promoted: they describe how an Access NUMERIC was decoded, which is Collin's mechanism, and a shared type that carried them would be modelling one county's storage format for everyone. This does not weaken Collin's accepted requirement that the adapter "SHALL preserve each exact `Decimal`, declared precision, declared scale, exact source column" — precision and scale move to a Collin-local type composing the shared value, and the exact source column becomes the shared `source_field`, so both remain preserved.
- **D2** (proposed by this change, requires human merge): `SourceProvenance` carries `jurisdiction_code`, `release_identifier`, `source_member_name`, `source_row_number`, `parser_contract_version`, and `layout_fingerprint`. That is the intersection the five counties already agree on. County-specific provenance — Dallas's header vectors, Collin's table name, Denton's and Ellis's layout version, Tarrant's collision metadata — stays in a county provenance type that **composes** the shared one rather than extending it, so a county may record more without every county carrying its fields.
- **D3** (proposed by this change, requires human merge): `AppraisalSourceRecord` carries `jurisdiction_code`, `source_account_id: str`, `appraisal_year: int`, `source_family: str`, `source_status: str`, `parcel_reference: str | None`, `source_native_identifiers: Mapping[str, str]`, `source_native_values: Mapping[str, SourceNativeValue]`, and `provenance: SourceProvenance`. Account identifiers are `str` in the shared type even where a county stores an integer, because leading zeroes and punctuation are meaning in three of the five counties and a numeric type destroys them.
- **D4** (proposed by this change, requires human merge): `jurisdiction_code` is `tx-` plus the county slug; `source_family` and `source_status` are free strings the county supplies rather than a shared enum, because the families observed so far — `certified-core`, `current`, `exemption` — are county products and a shared enum would have to change every time a county discovers one.
- **D5** (proposed by this change, requires human merge): Collin keeps its dual current/certified observation model as a county concept layered over shared records. Its `CollinAppraisalObservation` is not migrated. One Collin account produces one shared record per observed family, which preserves the accepted Collin contract's requirement that the adapter "MUST NOT ... fill a missing current or certified value from the other family." A single shared record holding both families would make that leak easy and undetectable.

**Provenance.** Issue #43 and the five accepted county contracts are the authoritative input. D1 through D5 are proposed by this change to close gaps that input leaves open — it requires vendor-neutral records "where every county adapter can reuse them" but states no field list, no identifier type, and no disposition for Collin's observation model — and no prior maintainer selection is claimed for any of them. Merging this change is what accepts them.

## Unresolved decisions

- None. The memory and streaming work that Issue #43 also describes is out of scope here rather than unresolved; it keeps its own issue.

## Cross-issue boundaries

- #19, #20, #21 (related_to): Tarrant, Denton, and Ellis each hold blocked tasks that these contracts unblock. Those tasks are completed in their own changes, not here.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
