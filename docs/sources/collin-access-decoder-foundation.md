# Collin Access Decoder Foundation

The Collin foundation is an adapter-local, synthetic-only contract for the measured pure-Python
reader representation described by the
[Collin source-contract specification](../../openspec/specs/collin-cad-source-contract/spec.md).
That specification is the normative source. This document explains the implemented boundary; it
does not approve a production Access runtime or establish live-release compatibility.

## Adapter Boundary

`property_tax_adapters.sources.texas.collin` accepts explicit schema metadata and converts one
caller-supplied decoded `AD_Public` row at a time. It performs no download, archive extraction,
Access execution, release iteration, persistence, orchestration, publication, or network access.
The one-row API deliberately avoids defining the production release-processing or bounded-streaming
contract owned by Issue #43.

All new records, native values, provenance, diagnostics, and conversion types remain explicitly
Collin-specific inside `property_tax_adapters`. The implementation does not modify or create domain
or application contracts.

## Reader-Specific NUMERIC Wrapper

Contract version 1 handles only the observed 17-byte wrapper: one canonical sign byte followed by
four little-endian 32-bit magnitude words in most-significant-word-first order. Precision and scale
come from external column metadata. The decoder reconstructs an exact `Decimal` and never converts
through binary floating point.

This representation is not raw Jet storage, Automation `DECIMAL`, OLE DB `DB_NUMERIC`, or a
universal Access wire format. A future production reader must verify its output against the
independent vectors or introduce a separately reviewed physical-contract version.

## Structural Projection

Schema validation occurs before row conversion. The foundation accepts only `AD_Public` and binds
the approved identity, status, year, current-value, and certified-value columns by exact
case-sensitive names. It validates LONG, TEXT, and NUMERIC descriptors, wrapper width, precision,
scale, and nullability.

Every observed descriptor participates in a canonical SHA-256 fingerprint. Compatible extra
metadata changes that fingerprint and produces an `extra_columns_present` warning, but extra row
values are never requested or retained. Missing, duplicated, colliding, or incompatible required
structure fails closed. The fingerprint is provenance rather than an allowlist.

## Source Values and Dual Families

The physical record preserves `prop_id`, `geo_id`, `property_status`, current and certified years,
and the exact source-native value families. Neither identifier is approved as an account key, and
repeated physical rows are not deduplicated or rolled up.

Current and certified observations are separate immutable records. Current classification comes
from the approved `property_status`; certified values retain a separate certified family and year.
Each value keeps its exact source column, `Decimal`, precision, scale, and source-native marker.
Current and certified families never overwrite, merge, suppress, or fill one another.

Market, appraised, assessed, homestead, non-homestead, land, agricultural, loss, and cap fields
retain their distinct Collin source names. This foundation does not infer broader value semantics,
currency, taxable value, a tax bill, payment status, delinquency, penalties, or interest.

## Provenance, Diagnostics, and Privacy

The caller supplies the release identifier, source member, and one-based physical row number. Each
record retains those values with the table name, parser contract version, and schema fingerprint.
Observations additionally retain family, source year, source property status, and exact populated
source columns.

Diagnostics contain only a closed stable code and optional field or table name, row number, and
schema fingerprint. They do not include a complete row, arbitrary source value, source identifier,
owner or DBA name, mailing or situs address, credential, protected identity, or host-local path.
The approved projection never requests owner, DBA, mailing, or situs columns.

## Synthetic Evidence and Resources

The fixture module contains explicit 17-byte literals with externally declared precision and scale,
reviewed exact answers, synthetic provenance, and pinned SHA-256 checksums. No encoder mirrors the
decoder. The fixtures are small, identity-free, redistribution-safe project data and contain no
county bytes, Access database, archive, production row, owner value, or address.

The foundation holds one bounded metadata tuple and one converted row at a time. It makes no memory
claim for a full Collin release and introduces no list-returning release API. Resource limits,
streaming, backpressure, and production runtime selection remain future approved work.

## Compatibility and Rollback

Passing synthetic vectors proves only the accepted reader-wrapper arithmetic and adapter contract.
It does not prove that a future Collin release, Access library, or runtime emits compatible bytes or
metadata. The Collin source remains non-production until separate acquisition and runtime evidence
is approved.

Rollback consists of reverting the Collin module, its fixture and test modules, and this document.
There is no database state, Bronze artifact, publication output, DAG, service, or deployed component
to repair.

## Issue #43 Boundary

Issue #43 owns future shared source records, provenance, source-native values, bounded release
streaming, and production release-processing APIs. It also owns any future Collin DAG integration.
This foundation intentionally creates no competing shared abstraction.

## Related

- [Source onboarding](README.md)
- [Adapter overview](../../libs/property-tax-adapters/README.md)
- [Collin source-contract specification](../../openspec/specs/collin-cad-source-contract/spec.md)
- [Bounded release parsing issue](https://github.com/TruPryce/property-tax-data-platform/issues/43)
- [Architecture](../architecture/README.md)
