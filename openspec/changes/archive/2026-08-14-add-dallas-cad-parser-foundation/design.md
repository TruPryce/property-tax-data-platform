## Context

Issue #17 is limited to a synthetic Dallas parser foundation. Existing accepted planning preserves
`ACCOUNT_NUM` as a 17-digit textual identifier, keeps `GIS_PARCEL_ID` distinct, uses
`(ACCOUNT_NUM, APPRAISAL_YR)` as the parent-row key, and refuses to assign canonical semantics to
`TOT_VAL`. This revision records the maintainer-approved decisions that replace the generated
layout, package-boundary, and lexical/provenance blockers.

The implementation remains inside `property_tax_adapters`. It does not acquire Dallas files,
persist releases, publish data, orchestrate work, or change domain/application contracts.

## Goals / Non-Goals

**Goals:**

- Parse a precisely defined UTF-8 Dallas CSV foundation from synthetic fixtures.
- Bind known fields only by normalized observed header name and preserve unknown source extras.
- Produce typed Dallas-native and vendor-neutral adapter records with complete provenance.
- Reject malformed layouts, lexical values, row widths, and duplicate parent keys deterministically.
- Keep diagnostics bounded and safe for logs and test output.

**Non-Goals:**

- Network access, Dallas source contact, county artifacts, production data, or production credentials.
- Acquisition, Bronze, database, Silver, Gold, Airflow, services, workflows, infrastructure,
  deployment, backfill, or production-ready status.
- New dependencies, owner publication, protected-identity reconstruction, or domain/application
  model changes.
- Canonical appraisal-value or tax-collection semantics for `TOT_VAL`.

## Decisions

### 1. Physical CSV contract

The parser contract version is integer `1`. Input is UTF-8; one UTF-8 BOM is accepted only at byte
offset zero and is removed before the first observed header is retained. Any decoding failure or
BOM elsewhere fails closed. The delimiter is comma, line endings may be LF or CRLF, and Python's
standard CSV double-quote behavior applies: quoted fields may contain commas and a literal quote is
represented by two consecutive quotes. Every logical data record has exactly the observed header
width. The header is logical row 1; data records are numbered from 2 independent of physical lines
inside quoted fields.

Rejected alternatives: encoding auto-detection, delimiter sniffing, permissive row padding or
truncation, and nonstandard quote escaping. Each would make identical bytes parse differently or
hide incompatible source drift.

### 2. Observed-header binding and layout identity

Each parsed observed header is retained after BOM removal and CSV unquoting. Its normalized form is
computed with `header.strip(" \\t\\r\\n\\v\\f").upper()`. Blank normalized headers fail.
Exact repeated observed headers produce `duplicate_header`; distinct observed headers that map to
the same normalized value produce `header_normalization_collision`. No aliases,
documentation-only names, or positional bindings are supported.

The required normalized header set is exactly `ACCOUNT_NUM`, `APPRAISAL_YR`, `GIS_PARCEL_ID`, and
`TOT_VAL`; order is irrelevant. Unknown normalized headers are accepted, retained in source extras,
and reported with `extra_columns_present` without shifting known bindings.

The layout fingerprint is SHA-256 over the UTF-8 encoding of compact canonical JSON with sorted
keys and separators `(',', ':')` for this document:

```json
{"headers":["<sorted normalized header>","..."],"parser_contract_version":1}
```

The fingerprint is provenance, not an allowlist. Missing required headers, blank or duplicate
headers, normalization collisions, invalid CSV syntax, and incompatible row widths are unsupported
layouts even when their fingerprint has been observed before.

Rejected alternatives: positional mapping, header aliases, fingerprints as an allowlist, and
hashing original header order. Those approaches either weaken observed-header evidence or turn
safe reordering and extra columns into false incompatibilities.

### 3. Adapter-local record and conversion boundary

All new types live under `property_tax_adapters`; `property_tax_domain` and
`property_tax_application` do not change.

`DallasAppraisalSourceRecord` is equivalent to:

- `account_num: str`
- `appraisal_year: int`
- `gis_parcel_id: str`
- `tot_val: SourceNativeDecimal`
- `extras: Mapping[str, str]`
- `provenance: DallasSourceProvenance`

`AppraisalSourceRecord` is a vendor-neutral adapter-local output equivalent to:

- `jurisdiction_code: str`, fixed to `"tx-dallas"`
- `source_account_id: str`
- `appraisal_year: int`
- `parcel_reference: str | None`
- `source_native_values: Mapping[str, SourceNativeValue]`
- `provenance: SourceProvenance`

Extras use normalized unknown-header names as keys and preserve decoded CSV field text as values.
Conversion retains those values as explicitly source-native facts. `TOT_VAL` appears only in
`source_native_values`; it does not populate or imply market, appraised, assessed, taxable,
tax-amount, payment-status, delinquency, penalty, or interest fields. No domain type is approved.

Rejected alternatives: adding Dallas records to the domain, modifying an application port,
equating account and parcel identifiers, or coercing `TOT_VAL` into a canonical value.

### 4. Lexical forms and duplicate grain

- `ACCOUNT_NUM` matches `[0-9]{17}` exactly and is stored unchanged, including leading zeros.
- `APPRAISAL_YR` matches `[0-9]{4}` exactly, is parsed to `int`, and is accepted only from 1900
  through 2100 inclusive.
- `GIS_PARCEL_ID` is required; surrounding ASCII whitespace is removed and the remaining text must
  be non-empty. Its remaining case, punctuation, and leading zeros are preserved, and it is never
  equated with `ACCOUNT_NUM`.
- `TOT_VAL` matches `-?[0-9]+(?:\\.[0-9]+)?` exactly. Currency symbols, grouping commas, exponent
  notation, leading plus, trailing decimal point, blank text, and malformed decimal text fail.
  `decimal.Decimal` provides the parsed value while `SourceNativeDecimal` retains the exact lexical
  text and a source-native classification marker.

Required blanks never become `None`. Within one parser invocation, the second occurrence of an
`(ACCOUNT_NUM, APPRAISAL_YR)` key fails with `duplicate_parent_key`; diagnostics do not include the
key values.

### 5. Provenance and diagnostics

Both Dallas-native and vendor-neutral adapter records retain caller-supplied source member name and
release identifier, original observed headers, normalized headers, layout fingerprint, one-based
logical source row number, and parser contract version. Source member and release identity are
inputs and are never inferred from row content or filenames inside a row.

The closed diagnostic vocabulary is:

- `invalid_encoding`
- `unexpected_bom`
- `blank_header`
- `missing_required_header`
- `duplicate_header`
- `header_normalization_collision`
- `malformed_csv`
- `row_width_mismatch`
- `invalid_account_num`
- `invalid_appraisal_year`
- `invalid_gis_parcel_id`
- `invalid_tot_val`
- `duplicate_parent_key`
- `unsupported_layout`
- `extra_columns_present`

A diagnostic contains only its stable code and, when applicable, a normalized field/header name,
one-based logical row number, and layout fingerprint. It never includes a complete source row,
owner name, mailing address, protected identity, credential, or arbitrary source value. Every
header/layout failure emits its specific code and the terminal `unsupported_layout` classification;
`extra_columns_present` is a non-failing schema warning.

### 6. Fixtures, approval, and package limits

Fixtures are independently authored, small, synthetic, identity-free, and redistribution-safe.
They contain no copied county rows or protected data. Implementation may change only
`libs/property-tax-adapters`, adapter-local tests/fixtures below that package, and `docs`.

Implementation eligibility remains false while this PR is open. An authorized maintainer merge is
the approval event; implementation then follows the unchecked tasks and may not expand their paths.

## Risks / Trade-offs

- Header normalization can collapse distinct names. The parser fails closed and reports the
  collision instead of selecting one.
- Accepting unknown columns improves additive compatibility but may expose unreviewed facts. They
  remain source-native extras, diagnostics identify only header names, and no semantic mapping is
  inferred.
- A fingerprint that is provenance rather than an allowlist accepts safe reorderings and extras.
  Required-header, collision, CSV, and width validation remain the actual compatibility gates.
- `Decimal` preserves numeric precision but not every lexical distinction by itself.
  `SourceNativeDecimal` therefore retains both the parsed value and original text.
- Synthetic fixtures do not prove compatibility with a production Dallas release. The adapter
  remains non-production-ready and live source onboarding stays separate.

## Migration Plan

This is additive, pre-production adapter work with no stored data, schema migration, or backfill.
Rollback is deletion or reversion of the adapter-local parser/types/tests and associated docs. No
published product or persisted release requires repair.

## Open Questions

None for this parser-foundation slice. Any future source-member expansion, domain/application
contract, canonical value semantics, persistence, publication, or production-readiness decision
requires a separate reviewed OpenSpec change.
