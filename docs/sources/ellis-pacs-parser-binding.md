# Ellis PACS Parser Binding

The Ellis parser binding is an adapter-local, deterministic boundary for small synthetic PACS
fixed-width inputs. It does not discover, render, download, unpack, persist, orchestrate, or publish
appraisal data, and it is not evidence of compatibility with a live Ellis CAD release. The
[Ellis OpenSpec delta](../../openspec/changes/add-ellis-cad-pacs-parser-binding/specs/ellis-cad-source-contract/spec.md)
is the normative behavior contract.

## Binding, Not Forking

Ellis uses the shared component documented in the
[Denton PACS parser foundation](denton-pacs-parser-foundation.md). It declares its layout with the
shared field and layout types and defines **no** position slicing, **no** layout validation, and
**no** fingerprint computation of its own. A test parses the module's AST and asserts none of those
appear.

Ellis also imports nothing from the Denton module. The two counties are independent bindings of one
component; a dependency between them would let a Denton layout change silently alter Ellis behavior.

## Compatibility Is Ellis's Own Fingerprint

Sharing a vendor with Denton is **not** evidence that the schemas agree. Ellis carries its own
expected layout fingerprint — written as a **literal**, not derived from the layout, so an unreviewed
mapping edit breaks the gate instead of moving both sides of it — and compares the declared mapping
against it before parsing. A caller
supplying another county's expected value is rejected with `unsupported_layout_fingerprint`.

The Ellis and Denton fingerprints are independent values, asserted to differ, and neither is derived
from the other. Whether the two published layouts genuinely agree is unproved, and this foundation
measures neither.

## Gate Order

Two gates run **before any record is read**:

1. the release label, and
2. the layout fingerprint.

Both answer "is this the artifact we think it is?" Reading records from a misidentified artifact is
exactly how a mineral-only scenario roll becomes certified current state, so a misidentified artifact
never reaches record parsing. Tests assert this by feeding a member with a width defect through each
gate and confirming only the gate's own code is reported.

## Layout Package Classification

The published Ellis layout is named `.xlsx.ods`, so selecting a parser by extension picks the wrong
one. `classify_layout_package` reads a bounded window of caller-supplied bytes and **parses** the
ZIP local file header — signature, compression method, file-name length, extra-field length — then
requires `mimetype` as the first member, stored uncompressed, carrying the media type
`application/vnd.oasis.opendocument.spreadsheet`.

Parsing the header rather than searching for the marker matters: an archive that merely contains
those bytes somewhere after a ZIP signature is not an ODS package, and a deflated `mimetype` is not
one either, because ODS stores it uncompressed precisely so the media type is readable without
decompressing anything.

It takes only bytes — there is no filename argument, so a name cannot mislead it. It extracts
nothing, enumerates nothing, and decompresses nothing, and it adds no archive library, so a hostile
package cannot turn recognition into extraction. An absent, truncated, or ambiguous signature is
classified `unrecognised` and fails closed.

Recognition establishes what the package *is*. Reading the layout it contains is separate future
work.

## Scenario Labels

The only label parsed as certified current state is `certified-all-property`. A potential-exemption
scenario such as `RC2 Potential`, a mineral-only release, an ambiguous value, and an empty label are
all rejected with `unsupported_scenario_label` before any record is read.

## Physical and Lexical Rules

Byte input decodes strictly as ISO-8859-1 with byte-order marks rejected. LF and CRLF boundaries are
accepted with one trailing ending allowed; a bare CR is not a boundary, and an embedded control
character is refused with `invalid_source_text` so two records cannot be read as one over-wide
record. A PACS member has no header row, so physical row 1 is the first data record. Observed width
must be uniform across records **and** reach the layout's declared width; a uniformly short member is
not the declared layout however consistent it is, and both cases are rejected with
`record_width_mismatch`.

`truncated_required_field` is deliberately absent from the vocabulary for the reason the Denton
document gives: with width gated against the declared width, a required field can never end beyond
it.

## Child Records

Child members are validated against a caller-supplied set of accepted `prop_id` values, behind the
same label, fingerprint, control-character, and width gates. A core appraisal child — `land`,
`improvement`, `mobile_home` — that does not resolve blocks the release with `core_child_orphaned`;
a legal child — `arb`, `lawsuit` — records the non-fatal `legal_child_orphaned`. A child member from
a scenario roll is no more parseable than a property member from one.

| Field | Rule |
| --- | --- |
| `prop_id` | Required, trimmed, 1–32 visible ASCII characters, preserved as text |
| `owner_sequence` | Required, one to four ASCII digits |
| `tax_year` | Required, four digits, 1900–2100, equal to the caller's expected year |
| `ownership_percentage` | Required, `[0-9]{1,3}(?:\.[0-9]{1,6})?`, 0 through 100 |
| `market_value`, `appraised_value`, `assessed_value` | Required, `[0-9]+(?:\.[0-9]{1,2})?`, 0 through `10**26 - 1` |
| `land_value`, `improvement_value`, `agricultural_value` | Optional, same monetary grammar |

These bounds match Denton's, because no Ellis measurement exists and diverging without evidence would
be inventing a difference rather than measuring one. They are **declared per county**, so a later
measurement changes one county without touching the other.

## Account and Owner Grain

`prop_id` is compared as text, so `000123` and `123` are two accounts. `(prop_id, owner_sequence)` is
the physical owner-row grain; every owner row is preserved distinctly, and the parser does not
deduplicate, sum owner-scoped values, or select an arbitrary row as an account total. No
account-level roll-up is derived. Two records sharing both key parts are rejected with
`duplicate_owner_row`, and records sharing a `prop_id` that disagree on tax year, market, appraised,
or assessed value are rejected with `conflicting_account_facts`.

## Diagnostics and Atomicity

The closed vocabulary is `invalid_encoding`, `unexpected_bom`, `record_width_mismatch`,
`unsupported_layout_fingerprint`, `undocumented_trailing_region`, `unsupported_scenario_label`,
`blank_required_key`, `invalid_account_id`, `invalid_owner_sequence`,
`invalid_monetary_value`, `invalid_ownership_percentage`, `invalid_tax_year`, `tax_year_mismatch`,
`invalid_source_text`, `duplicate_owner_row`, `conflicting_account_facts`, `core_child_orphaned`, and
`legal_child_orphaned`. Every code in it is reachable, proved by driving inputs through the public entry points rather than by comparing the vocabulary with itself.

There is no `unrecognised_layout_package` code: `classify_layout_package` returns a `LayoutPackageKind`, which is the reportable outcome, so a code for it would promise a report no entry point produces.

A diagnostic carries only its stable code and, where applicable, an approved field name, the
one-based physical row number, and the layout fingerprint — the whole type, so there is nowhere to
put a record, an account value, an owner name, an address, a credential, or a host path.

`legal_child_orphaned` is the only non-fatal code. Every other code rejects the logical release,
which reports `release_accepted` false with `accepted_row_count` zero, including
`undocumented_trailing_region` — the governing issue requires unknown trailing bytes to fail closed,
as the Denton document explains. At most 100 diagnostics are retained,
the total is preserved, and truncation is marked deterministically.

## Interim Output

The public surface is a **validator, not a row producer**, matching Denton. Issue #21's acceptance
criteria name a typed Ellis record and a vendor-neutral record, and both require the contracts owned
by [Issue #43](https://github.com/TruPryce/property-tax-data-platform/issues/43), which do not exist
yet. Typed record output is deferred rather than duplicated into a county-local substitute.

`EllisValidationReport` carries the parser contract version, an acceptance flag, the layout
fingerprint and version, the accepted release label, the accepted row and owner-row counts, the
trailing-region byte count, up to 100 diagnostics, the preserved total, and a truncation flag. It
carries no field value and no record.

## Privacy

`owner_name`, `owner_address`, and `situs_address` are sensitive. Their declared positions participate
in layout provenance; their values never enter a report, a diagnostic, a fixture, a log, or any
output. Values from an undocumented trailing region are likewise discarded.

## Fixtures

All fixtures in `libs/property-tax-adapters/tests/fixtures/ellis_synthetic.py` are small,
independently authored, synthetic, identity-free, and redistribution-safe. The package fixtures are
hand-assembled byte prefixes, not real spreadsheet files, and no published ODS or XLSX layout is
committed. The owner and situs columns carry invented placeholders solely to prove those values never
leave the parser, and the fixture refuses to build an over-wide value rather than silently clipping.

## Unproved

- The published Ellis PACS layout, its true field positions, and the observed record widths.
- Whether the Ellis and Denton layouts genuinely agree — this foundation asserts only that
  compatibility must be established independently, never assumed.
- The real account alphabet, monetary scale, and owner-allocation shapes.
- Undivided-interest account roll-up behavior.
- Confidentiality and field-level publication policy.
- Source licensing and redistribution terms.

## Outside This Change

Live rendered-page discovery, redirect handling, download, archive extraction, complete ODS layout
extraction, historical certified release modelling across tax years, preliminary and correction-roll
behavior, the record-free evidence manifest, account roll-up, and the production-readiness gate all
remain outside this binding. Live-release compatibility and production readiness are **not**
established by it.

## Related

- [Source onboarding](README.md)
- [Denton PACS parser foundation](denton-pacs-parser-foundation.md)
- [Adapter overview](../../libs/property-tax-adapters/README.md)
- [Ellis OpenSpec delta](../../openspec/changes/add-ellis-cad-pacs-parser-binding/specs/ellis-cad-source-contract/spec.md)
- [Architecture](../architecture/README.md)
