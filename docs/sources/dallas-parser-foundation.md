# Dallas Parser Foundation

The Dallas parser foundation is an adapter-local, deterministic boundary for small inputs that
match the approved synthetic source contract. It does not download, persist, orchestrate, or
publish appraisal data, and it is not evidence of compatibility with a live Dallas CAD release.
The [Dallas OpenSpec delta](../../openspec/specs/dallas-cad-source-contract/spec.md)
is the normative behavior contract.

## Adapter Boundary

`property_tax_adapters.sources.texas.dallas.parse_dallas_appraisal_csv` accepts caller-supplied
bytes or text plus a source member name and release identifier. A successful call atomically
returns Dallas-native records, vendor-neutral adapter records, and bounded non-fatal layout
warnings. A failed call raises bounded diagnostics and returns no partial accepted records.

All records and conversion types remain in `property_tax_adapters`. The parser creates no domain or
application object. The vendor-neutral record uses jurisdiction `tx-dallas`, preserves the Dallas
account and distinct parcel reference, and carries source-native values without assigning canonical
tax semantics.

## Physical Layout

Contract version 1 handles UTF-8 comma-delimited input, an optional leading UTF-8 BOM, LF or CRLF
line endings, and standard CSV double-quote escaping. Header names bind after surrounding ASCII
whitespace is removed and the result is uppercased. Column order is not significant; aliases and
positional binding are not supported.

The required foundation headers are `ACCOUNT_NUM`, `APPRAISAL_YR`, `GIS_PARCEL_ID`, and `TOT_VAL`.
Unambiguous extra columns remain source-native and produce deterministic schema warnings. The parser
computes a SHA-256 layout fingerprint from the contract version and normalized header set for
provenance; the fingerprint is not an allowlist.

## Values and Provenance

The parser validates the accepted lexical forms before creating records. It retains leading zeros
in account identifiers, keeps the parcel reference distinct, and preserves the exact `TOT_VAL` text
alongside its parsed `Decimal`. `TOT_VAL` does not populate or imply market, appraised, assessed,
taxable, bill, payment, delinquency, penalty, or interest semantics.

Each native and converted record carries the caller-supplied member and release identities,
observed and normalized headers, layout fingerprint, logical source row number, and parser contract
version. Those identities are never inferred from row data.

## Diagnostics and Privacy

Diagnostics expose only a stable closed code and optional normalized field name, logical row number,
and layout fingerprint. They do not retain complete rows or arbitrary source values. Invalid
encoding, malformed layouts, invalid lexical values, incompatible row widths, and duplicate parent
keys fail closed.

Tests use only the independently authored byte strings documented in the
[fixture manifest](../../libs/property-tax-adapters/tests/fixtures/README.md). They are small,
synthetic, identity-free, redistribution-safe, and checksum-pinned. No county release, owner record,
mailing address, credential, production byte, or network response is included.

## Compatibility Limits

This slice establishes a parser contract, not a production ingestion adapter. Live acquisition,
county artifact handling, Bronze or database persistence, cross-county normalization, Airflow,
publication, owner-data handling, and deployment remain outside this foundation. A future live
adapter requires separately approved source evidence and compatibility work.

## Related

- [Source onboarding](README.md)
- [Adapter overview](../../libs/property-tax-adapters/README.md)
- [Dallas OpenSpec delta](../../openspec/specs/dallas-cad-source-contract/spec.md)
- [Architecture](../architecture/README.md)
