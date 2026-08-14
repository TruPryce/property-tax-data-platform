# Tarrant Parser Foundation

The Tarrant parser foundation is an adapter-local, deterministic boundary for small synthetic
inputs that match the approved certified-core source contract. It does not download, persist,
orchestrate, or publish appraisal data, and it is not evidence of compatibility with a live Tarrant
CAD release. The
[Tarrant OpenSpec delta](../../openspec/changes/add-tarrant-cad-parser-foundation/specs/tarrant-cad-source-contract/spec.md)
is the normative behavior contract.

## Scope

The supported source family is the **certified core**, which is separate from the mutable current
roll and from companion exemption products. This foundation parses one already-selected
certified-core text member. Archive acquisition, member selection, and network access are outside
its scope.

## Adapter Boundary

`property_tax_adapters.sources.texas.tarrant.validate_certified_member` accepts caller-supplied
bytes or text plus a release identifier, source member name, and expected source year. It returns
one `TarrantValidationReport`.

There are now two entry points over one traversal. `validate_certified_member` is the validator
described above. `materialize_certified_member` returns that same report alongside typed
`TarrantCertifiedSourceRecord` rows, and `convert_tarrant_record` converts one into the
vendor-neutral `AppraisalSourceRecord` that
[Issue #43](https://github.com/TruPryce/property-tax-data-platform/issues/43) decision D7 owns —
now implemented in
[the shared adapter source contracts](shared-adapter-source-contracts.md). The validation is
written once and reused, so the two entry points cannot disagree about what a valid Tarrant row is.

Materialization is atomic with validation. A release rejected for any blocking reason yields zero
records, never a partial set, including when other rows in the same member were valid.

No county-local substitute for a shared contract exists, and that prohibition has not lifted — only
the wait for the real thing has ended.

`TarrantValidationReport` carries the parser contract version, an acceptance flag, the layout
fingerprint, the observed headers, the accepted row count, up to 100 `TarrantDiagnostic` entries,
the preserved total diagnostic count, and a truncation flag. It carries no parsed field value and
no row, is not persisted, cached, or logged, and its lifetime ends with the caller that received it.

## Physical Layout

Contract version 1 decodes strictly as ISO-8859-1 and rejects UTF-8, UTF-16, and UTF-32 byte-order
marks. The delimiter is `|`. The quote character is `"`, a doubled `""` inside a quoted field is one
literal quote, and there is no escape character. Embedded pipes are accepted only inside a quoted
field; an embedded CR or LF inside one is rejected as `multiline_record_unsupported`, so every
accepted record has exactly one physical source-row number. A quote that opens and never closes
anywhere in the member is `malformed_delimited_record` instead: records are scanned quote-aware over
the raw text, so the two are distinguished rather than both looking malformed. LF and CRLF boundaries are both accepted, one trailing line ending is
allowed, and blank or whitespace-only records are not silently skipped.

The header is physical row 1 and data rows begin at row 2. Header names bind case-sensitively with
no trimming and no case conversion; aliases, documentation names, delimiter sniffing, and positional
binding are not supported. Required-header order is irrelevant.

The required foundation headers are exactly `RP`, `Appraisal_Year`, `Account_Num`, `PIDN`,
`GIS_Link`, `Property_Class`, `State_Use_Code`, `Exemption_Code`, `Land_Value`, `Improvement_Value`,
`Total_Value`, `Appraised_Value`, `Ag_Value`, `Deed_Date`, `Notice_Date`, and `Appraisal_Date`.
Every data row must contain exactly the observed header width. Additional headers are accepted as
metadata-only extras, record the non-fatal `extra_columns_present`, and have their values discarded.

## Layout Fingerprint

The fingerprint is the lowercase SHA-256 hexadecimal digest of one canonical JSON document with
exactly five keys: `parser_contract_version` (the integer `1`), `encoding` (`iso-8859-1`), `dialect`
(`pipe-delimited-double-quote-v1`), `column_count`, and `headers_sorted`. The document is serialized
with keys sorted by Unicode code point, the separators `,` and `:` and no other whitespace, literal
non-ASCII characters, and UTF-8 encoding.

The original ordered header vector is retained separately rather than inside the document, so two
members whose headers differ only in order share a fingerprint. The fingerprint is provenance only:
it is not an allowlist, and required-layout validation is independent of it.

## Lexical Rules

Surrounding ASCII whitespace means space, tab, CR, LF, vertical tab, and form feed. Empty text after
permitted trimming is the only null; `NULL`, `N/A`, `None`, and similar sentinels are not treated as
null.

| Field | Rule |
| --- | --- |
| `RP` | Required, untrimmed, exactly one of `R`, `C`, `M`, `P` |
| `Appraisal_Year` | Required, four ASCII digits, 1900–2100, equal to the caller's expected year |
| `Account_Num` | Trimmed, 1–64 visible ASCII characters, preserved as text and never parsed numerically |
| `PIDN`, `GIS_Link` | Optional, 1–512 non-control characters when present |
| `Property_Class`, `State_Use_Code`, `Exemption_Code` | Optional, 1–128 non-control characters when present |
| `Total_Value`, `Appraised_Value` | Required, `[0-9]+(?:\.[0-9]{1,4})?`, exact `Decimal`, 0 through `10**28 - 1` |
| `Land_Value`, `Improvement_Value`, `Ag_Value` | Optional, same monetary grammar |
| `Deed_Date`, `Notice_Date`, `Appraisal_Date` | Optional, `M/D/YYYY` with one- or two-digit month and day, calendar-valid, 1900–2100 |

Leading signs, currency symbols, grouping separators, exponent notation, trailing decimal points,
and excessive scale all fail. No field is padded, truncated, case-folded, numerically coerced,
silently rounded, or inferred from another, and a malformed non-blank value never becomes null. The
parser does not enforce `Appraised_Value <= Total_Value`, land-plus-improvement arithmetic, or
division-distribution thresholds as row-validity rules.

`Account_Num` uniqueness is enforced across the complete logical release, and the division does not
participate in the key. The second occurrence rejects the release. The same account text in
separately identified releases is not a duplicate.

## Caller Identity

One logical release is one caller-identified certified artifact, selected member, and expected
source year. All three are required and none is inferred from row data or from a filename.

`release_identifier` and `source_member_name` are each 1–128 characters from `[A-Za-z0-9._-]` and
may not begin with `.` or `-`. That alphabet contains no `/`, `\`, `:`, whitespace, or control
character, so an absolute path, a UNC path, a drive-qualified path, and a parent-directory traversal
are unrepresentable rather than merely discouraged. `expected_source_year` is an `int` from 1900
through 2100; `bool` is rejected despite subclassing `int`.

A violation raises `ValueError` before the member is read and produces no report and no diagnostic.
Caller identity is a programming contract, not source data, and the closed diagnostic vocabulary
describes the source and never the caller.

## Diagnostics and Atomicity

The closed vocabulary is `invalid_encoding`, `unexpected_bom`, `malformed_delimited_record`,
`multiline_record_unsupported`, `blank_header`, `duplicate_header`, `header_name_collision`,
`missing_required_header`, `row_width_mismatch`, `unsupported_layout`, `extra_columns_present`,
`blank_required_value`, `invalid_division`, `invalid_appraisal_year`, `appraisal_year_mismatch`,
`invalid_account_num`, `invalid_source_identifier`, `invalid_source_text`, `invalid_monetary_value`,
`invalid_source_date`, and `duplicate_account_num`.

A diagnostic carries only its stable code and, where applicable, an approved field or header name,
the one-based physical row number, and the layout fingerprint. Those four fields are the whole type,
so there is nowhere to put a complete row, an arbitrary value, an account, release or member text,
an owner name, an address, a protected identity, a credential, exception text, or a host path.
Unknown source header text is never echoed.

`unsupported_layout` covers observed-layout rejections the four named header codes do not: a header
carrying surrounding ASCII whitespace, a header containing an ASCII control character, an observed
header of zero columns, and a member whose first physical row is absent.

`extra_columns_present` is non-fatal. Every other code rejects the logical release, and a rejected
release reports `release_accepted` false with `accepted_row_count` zero. There is no row-continues
quarantine path and no partially accepted release. At most 100 diagnostics are retained, the total
count is preserved, and truncation is marked deterministically.

## Privacy

The header names `Owner_Name`, `Owner_Address`, `Owner_CityState`, `Owner_Zip`, `Owner_Zip4`,
`Owner_CRRT`, `Situs_Address`, and `LegalDescription` may participate in layout provenance. Their
values never enter a report, a diagnostic, a fixture, evidence, a log, Gold, or API output.

Unknown-column values are discarded as well, because an unknown field may carry identity or address
data and the absence of a confidentiality flag is not publication permission.

## Fixtures

All fixtures in `libs/property-tax-adapters/tests/fixtures/tarrant_synthetic.py` are small,
independently authored, synthetic, identity-free, and redistribution-safe. They contain no county
bytes, production rows, owner values, mailing or situs addresses, protected identities, credentials,
host paths, or network responses. Expected results are stated literally rather than generated by the
code under test.

## Unproved

Approval of this contract establishes only the narrow synthetic projection above. The following
remain unproved and block any production claim:

- the complete live 56-column header vector, its order, and the expected live fingerprint;
- actual live encoding, BOM, quoting, and line-ending behavior;
- whether embedded pipes, quotes, blank lines, or multiline fields occur in a live release;
- which fields are truly nullable, and which sentinel forms occur;
- the exact live date format — the `M/D/YYYY` grammar above is a synthetic-foundation choice, not
  reproduced live evidence;
- official meanings of `Total_Value`, `Appraised_Value`, the component values, and `Exemption_Code`;
- whether `Account_Num` is stable across years, and whether a certified row is a complete snapshot;
- full-snapshot versus delta and same-year replacement behavior;
- complete confidentiality and suppression behavior;
- source licensing and redistribution terms.

Live-release compatibility and production readiness are **not** established by this foundation.

## Related

- [Source onboarding](README.md)
- [Adapter overview](../../libs/property-tax-adapters/README.md)
- [Tarrant OpenSpec delta](../../openspec/changes/add-tarrant-cad-parser-foundation/specs/tarrant-cad-source-contract/spec.md)
- [Dallas parser foundation](dallas-parser-foundation.md)
- [Architecture](../architecture/README.md)
