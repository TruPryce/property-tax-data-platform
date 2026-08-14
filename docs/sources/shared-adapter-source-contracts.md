# Shared adapter source contracts

`property_tax_adapters.sources.contracts` holds the three vendor-neutral types every county
adapter can reuse without importing a county module: `SourceNativeValue`, `SourceProvenance`,
and `AppraisalSourceRecord`.

They are source-native containers. They record what a county observed and where it came from,
and nothing about what any of it means. No market, appraised, assessed, taxable, tax-amount,
exemption-entitlement, or replacement semantics live here; a value keeps its county's meaning
until a later canonical layer assigns one.

This implements [issue #43](https://github.com/TruPryce/property-tax-data-platform/issues/43)
decision **D7 — Shared adapter-neutral records**, and nothing else from that issue.

## The types

### `SourceNativeValue`

| field | type | notes |
| --- | --- | --- |
| `source_field` | `str` | the exact field or column the value was read from; blank or whitespace-only is rejected |
| `value` | `str \| int \| Decimal` | no `None` member |
| `lexical_text` | `str \| None` | the original text, where the source has one |
| `precision` | `int \| None` | supplied together with `scale` or not at all |
| `scale` | `int \| None` | |
| `classification` | `Literal["source-native"]` | fixed, not caller-supplied |

### `SourceProvenance`

| field | type | notes |
| --- | --- | --- |
| `jurisdiction_code` | `str` | lowercase state prefix, hyphen, county slug |
| `release_identifier` | `str` | caller-supplied |
| `source_member_name` | `str` | caller-supplied |
| `source_row_number` | `int` | one-based physical row |
| `parser_contract_version` | `int` | |
| `layout_fingerprint` | `str` | |
| `table_name` | `str \| None` | optional, per D7 |
| `source_family` | `str \| None` | optional, per D7 |
| `source_year` | `int \| None` | optional, per D7 |
| `source_status` | `str \| None` | optional, per D7 |
| `observed_fields` | `tuple[str, ...] \| None` | optional, per D7 |
| `normalized_fields` | `tuple[str, ...] \| None` | optional, per D7 |

Twelve fields, and no thirteenth. A county whose native provenance names a fingerprint
differently maps it onto `layout_fingerprint` rather than adding a second one — Collin's
`schema_fingerprint` is the same digest under a county name.

### `AppraisalSourceRecord`

| field | type | notes |
| --- | --- | --- |
| `jurisdiction_code` | `str` | must equal the provenance jurisdiction |
| `appraisal_year` | `int` | |
| `provenance` | `SourceProvenance` | required; no default |
| `source_account_id` | `str \| None` | text where present, so leading zeroes survive |
| `source_family` | `str \| None` | |
| `source_status` | `str \| None` | |
| `parcel_reference` | `str \| None` | |
| `source_native_identifiers` | `Mapping[str, str]` | read-only view over a defensive copy |
| `source_native_values` | `Mapping[str, SourceNativeValue]` | each key equals its value's `source_field` |

## Why three fields are nullable

Each nullable field is forced by a named accepted county contract, not by preference.

- **`source_account_id`** — Collin's contract states `prop_id` "MUST NOT be declared a unique or
  canonical account key" and `geo_id` "MUST NOT be equated with `prop_id`". Neither may be
  promoted, so Collin sets `None` and preserves both under their exact source names in
  `source_native_identifiers`, as distinct entries asserting no equivalence.
- **`lexical_text`** — Collin decodes values from an approved 17-byte binary NUMERIC wrapper.
  There is no original text to preserve. `None` means "this source carries no text"; an observed
  empty text stays `""`, which Dallas emits today for an empty extra column. The two are
  different facts and are not conflated.
- **`source_family`** — Dallas classifies no source family. D7 requires this field on the record;
  this is the single field the accepted change proposed as optional against that approved list,
  because a required field with no approved Dallas value would force either inventing one or
  abandoning the case-for-case Dallas migration D7 also requires.

Where a county did specify concrete values, it still supplies them.

## Composition, not subclassing

County-native input records and county diagnostics stay in county modules. A county that keeps
its own provenance type holds a shared `SourceProvenance` rather than subclassing it, so one
county's mechanism never becomes another's obligation:

- `DallasSourceProvenance` keeps its observed and normalized header vectors — a CSV concept a
  fixed-width county has no use for — and exposes a shared view.
- `CollinObservationProvenance` keeps its observation lineage: `source_family`, `source_year`,
  `property_status`, and `value_source_columns`, with their Collin enum types.

`DallasAppraisalSourceRecord`, `CollinAppraisalSourceRecord`, and `CollinAppraisalObservation`
all remain county-local. What is prohibited is a second definition of a shared shape, not a
county-prefixed name.

## Privacy boundary

The guarantee is narrow, and stated narrowly on purpose:

> The shared types define no field naming an owner, a mailing address, or a situs address, and
> expose no untyped or free-form payload attribute.

That is the whole of it. These types **do not** guarantee that identity data cannot reach a
record. `source_native_values` is keyed by county-chosen source fields, and Dallas's accepted
contract requires retaining unknown source columns — its converter places every unknown CSV
column into the vendor-neutral value mapping. A shared allowlist would contradict an accepted
county contract, so bounding columns remains a county-contract obligation, enforced where the
county knows its columns.

**Open tension.** A Dallas release adding an owner-name column would carry it into a shared
record. That is accepted behaviour today and unchanged by this work, and it matters only once a
real release is parsed.
[Issue #78](https://github.com/TruPryce/property-tax-data-platform/issues/78) tracks the
decision, and [issue #60](https://github.com/TruPryce/property-tax-data-platform/issues/60) is
blocked on it for live-source work.

## What is not here

Issue #43 carries eight decisions. This implements D7 alone. Still open in that issue:

| decision | subject |
| --- | --- |
| D1 | bounded production input contract |
| D2 | when layout validation completes relative to decoding and staging |
| D3 | where release rejection is detected, and zero visible accepted records |
| D4 | bounded duplicate-key and cross-row checks |
| D5 | deterministic resource limits for the `LocalExecutor` runtime |
| D6 | disposition of the small-input `bytes \| str` fixture helper |
| D8 | the `ReleaseProgressEvent` progress contract |

The measured memory problem — 663 MiB retained on 200,000 Dallas rows — belongs to the
release-processing API rather than to these per-record containers, and stays open with them.

## Unblocked, but completed elsewhere

The conversion tasks blocked in the accepted Tarrant, Denton, and Ellis changes are unblocked by
these contracts and are completed in those changes, not here:

- [Tarrant](tarrant-parser-foundation.md) tasks 6.1 and 6.2
- [Denton](denton-pacs-parser-foundation.md) tasks 6.1, 6.2, and 6.3
- [Ellis](ellis-pacs-parser-binding.md) tasks 6.1, 6.2, and 6.3
