# Denton PACS Parser Foundation

The Denton parser foundation is an adapter-local, deterministic boundary for small synthetic PACS
fixed-width inputs. It does not discover, download, unpack, persist, orchestrate, or publish
appraisal data, and it is not evidence of compatibility with a live Denton CAD release. The
[Denton OpenSpec delta](../../openspec/changes/add-denton-cad-pacs-parser-foundation/specs/denton-cad-source-contract/spec.md)
is the normative behavior contract.

## Two Modules, One Boundary

Serialization mechanics and county policy are deliberately separated, because
[Issue #21](https://github.com/TruPryce/property-tax-data-platform/issues/21) requires Ellis to
*bind* to the shared component rather than fork it.

| | `property_tax_adapters.sources.pacs` | `property_tax_adapters.sources.texas.denton` |
| --- | --- | --- |
| Holds | field positions, layout validation, the layout fingerprint, record slicing | field names, lexical grammars, grain rules, thresholds, diagnostics, privacy |
| Knows about a county | no | yes |
| Reused by | every PACS county | Denton only |

The component names no county, no county field, no threshold, and no policy. A component that knew
`prop_id` could not be bound by a county that spells its account identifier differently.

## Field Positions

Positions are **1-indexed and inclusive**, so a field at 1–5 is five characters wide. That is the
convention the published PACS layouts use, and converting to half-open ranges at the boundary is
exactly where off-by-one slicing defects come from, so the inclusive form is kept end to end.

A layout declares an identifier, a version, and ordered fields. Fields must be in ascending start
order, must not overlap, must not repeat a name, and must have `end >= start`. Those are authoring
defects in trusted repository code rather than anything a source file did, so they raise `ValueError`
at construction and produce no diagnostic.

## Layout Fingerprint

The fingerprint is the lowercase SHA-256 hexadecimal digest of one canonical JSON document with
exactly five keys: `component_contract_version` (the integer `1`), `layout_id`, `layout_version`,
`field_count`, and `fields` — the ordered list of `[name, start, end, required]`. It is serialized
with keys sorted by Unicode code point, the separators `,` and `:` and no other whitespace, literal
non-ASCII characters, and UTF-8 encoding.

It is versioned **separately from any export-header version**, so a county may accept a known layout
against an unknown export version and record both.

Each county pins its expected fingerprints as **literals** rather than deriving them from its own
layout. A derived constant would move with the mapping, so the comparison could never fail and the
gate would be decorative; written down, an unreviewed mapping edit breaks it.

A published layout that states a field length as well as its positions may declare that length, and
the component cross-checks the two. Transcribing a published layout is where a digit gets dropped,
and a length that disagrees with its positions is the defect this catches.

## Partial Values and Trailing Regions

A field whose declared end exceeds the observed record width is never emitted as a truncated value.
The shared component reports a required field in that position as truncated and an optional one as
absent. A county binding gates the observed width against the declared width first, so in practice a
county never sees a truncated required field — see the note under Physical Layout.

A record wider than the layout's greatest declared end retains a structural fingerprint of the
unknown trailing region — its byte length and a SHA-256 digest of the **source bytes**, in the
member's own encoding rather than a UTF-8 re-encoding — and no field is inferred from it.
The trailing content never appears in a report or diagnostic, because an undocumented region may
carry identity or address data.

## Physical Layout

Byte input decodes strictly as ISO-8859-1 and string input must round-trip through it. UTF-8,
UTF-16, and UTF-32 byte-order marks are rejected. LF and CRLF boundaries are accepted, one trailing
line ending is allowed, and a bare CR is **not** a boundary.

A PACS member carries no header row, so physical row 1 is the first data record.

Observed width is a **member-level** property, and it must both be uniform across records and reach
the layout's declared width. PACS records carry no delimiter, so a record of a different width is not
a narrow record — it is evidence that the member is not the layout it claims to be. Uniformity alone
is not enough either: every required Denton field ends by position 75, so a member whose records were
all 75 characters would otherwise pass against a layout declaring 305. Both cases are rejected with
`record_width_mismatch` rather than parsed at a guessed width.

Because the observed width must reach the declared width, a required field can never end beyond it,
so `truncated_required_field` is deliberately absent from the county vocabulary — a code no input can
produce should not be declared. Truncation remains a shared-component concept, reported by
`slice_record` for callers that slice directly. An embedded control character is refused with `invalid_source_text` for the same reason: a
bare CR would otherwise turn two records into one over-wide record with a trailing region.

## Lexical Rules

Empty text after trimming is the only null; `NULL`, `N/A`, and `None` are not null.

| Field | Rule |
| --- | --- |
| `prop_id` | Required, trimmed, 1–32 visible ASCII characters, preserved as text and never parsed numerically |
| `owner_sequence` | Required, one to four ASCII digits |
| `tax_year` | Required, four digits, 1900–2100, equal to the caller's expected year |
| `ownership_percentage` | Required, `[0-9]{1,3}(?:\.[0-9]{1,6})?`, 0 through 100 |
| `market_value`, `appraised_value`, `assessed_value` | Required, `[0-9]+(?:\.[0-9]{1,2})?`, exact `Decimal`, 0 through `10**26 - 1` |
| `land_value`, `improvement_value`, `agricultural_value`, `ten_percent_cap` | Optional, same monetary grammar |

## Account and Owner Grain

`prop_id` is the account identifier and is compared **as text**, so `000123` and `123` are two
accounts rather than one.

`(prop_id, owner_sequence)` is the physical owner-row grain. Every owner row is preserved distinctly.
The parser does not deduplicate rows, sum owner-scoped values, or select an arbitrary row as an
account total, and **no account-level roll-up is derived** until an approved rule exists. Two records
sharing both key parts are rejected with `duplicate_owner_row`.

Records sharing a `prop_id` must agree on the declared account-level facts — tax year, market,
appraised, and assessed value — and a disagreement is rejected with `conflicting_account_facts`.
Owner sequence, ownership percentage, and owner-scoped values legitimately differ across an
allocation and are never compared.

`ten_percent_cap` is validated as a monetary amount and preserved as a **source-native cap amount**.
It is not treated as a capped value, not substituted for market, appraised, or assessed value, and no
canonical value is derived from it, because its exact product mapping is unapproved.

## Child Relationships

Relationship rules apply by table type rather than one county-wide orphan rule. A core appraisal
child — `land`, `improvement`, `mobile_home` — that does not resolve to an accepted account blocks
the release with `core_child_orphaned`. A legal child — `arb`, `lawsuit` — records the non-fatal
`legal_child_orphaned` and does not block.

## Diagnostics and Atomicity

The closed vocabulary is `invalid_encoding`, `unexpected_bom`, `record_width_mismatch`,
`unsupported_layout_fingerprint`, `undocumented_trailing_region`,
`blank_required_key`, `invalid_account_id`, `invalid_owner_sequence`, `invalid_monetary_value`,
`invalid_ownership_percentage`, `invalid_tax_year`, `tax_year_mismatch`, `invalid_source_text`,
`duplicate_owner_row`, `conflicting_account_facts`, `core_child_orphaned`, and
`legal_child_orphaned`.

A diagnostic carries only its stable code and, where applicable, an approved field name, the
one-based physical row number, and the layout fingerprint. Those four fields are the whole type, so
there is nowhere to put a record, an arbitrary value, an account value, release or member text, an
owner name, an address, a credential, exception text, or a host path.

`undocumented_trailing_region` and `legal_child_orphaned` are non-fatal. Every other code rejects the
logical release, which reports `release_accepted` false with `accepted_row_count` zero. At most 100
diagnostics are retained, the total is preserved, and truncation is marked deterministically.

## Caller Identity

`release_identifier` and `source_member_name` are each 1–128 characters from `[A-Za-z0-9._-]` and may
not begin with `.` or `-`. That alphabet contains no `/`, `\`, `:`, whitespace, or control character,
so an absolute path, a UNC path, a drive-qualified path, and a parent-directory traversal are
unrepresentable rather than merely discouraged. `expected_tax_year` is an `int` from 1900 through
2100; `bool` is rejected despite subclassing `int`.

A violation raises `ValueError` before the member is read and produces no report and no diagnostic:
caller identity is a programming contract, not source data.

## Interim Output

The public surface is a **validator, not a row producer**. Issue #20's acceptance criteria name a
typed Denton record and an approved vendor-neutral record, and both require the
`SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` contracts owned by
[Issue #43](https://github.com/TruPryce/property-tax-data-platform/issues/43), which do not exist
yet. Returning rows today would require a county-local substitute for a shared contract — the fourth
such copy in this repository after Collin and Dallas — so typed record output is deferred rather than
duplicated.

`DentonValidationReport` carries the parser contract version, an acceptance flag, the layout
fingerprint and version, the accepted row and owner-row counts, the trailing-region byte count, up to
100 diagnostics, the preserved total, and a truncation flag. It carries no field value and no record,
is not persisted, cached, or logged, and its lifetime ends with the caller.

## Privacy

`owner_name`, `owner_address`, and `situs_address` are sensitive. Their declared positions participate
in layout provenance; their values never enter a report, a diagnostic, a fixture, a log, or any
output. Publisher omissions are preserved and are never reconstructed, enriched, joined, or inferred.

## Fixtures

All fixtures in `libs/property-tax-adapters/tests/fixtures/denton_synthetic.py` are small,
independently authored, synthetic, identity-free, and redistribution-safe. They contain no county
bytes, production rows, PACS exports, archives, published layouts, owner values, addresses,
credentials, host paths, or network responses. The owner and situs columns carry invented
placeholders solely to prove those values never leave the parser, and the fixture refuses to build an
over-wide value rather than silently clipping it.

## Unproved

- The published Denton PACS layout, its true field positions, and the observed record widths — the
  layout here is a synthetic foundation contract, not a reproduction.
- `ten_percent_cap` semantics and its exact product mapping.
- The real account and owner-sequence alphabets, monetary scale, and orphan rates.
- Undivided-interest account roll-up behavior.
- Preliminary, certified, and roll-correction precedence and same-year replacement.
- Confidentiality and field-level publication policy.
- Source licensing and redistribution terms.

## Outside This Change

Discovery, conditional observation, download, archive and member resolution, ZIP or XLSX container
parsing, the nightly extract, roll precedence, the record-free evidence manifest, account roll-up,
and the production-readiness gate all remain outside this foundation. Live-release compatibility and
production readiness are **not** established by it.

## Related

- [Source onboarding](README.md)
- [Adapter overview](../../libs/property-tax-adapters/README.md)
- [Denton OpenSpec delta](../../openspec/changes/add-denton-cad-pacs-parser-foundation/specs/denton-cad-source-contract/spec.md)
- [Tarrant parser foundation](tarrant-parser-foundation.md)
- [Architecture](../architecture/README.md)
