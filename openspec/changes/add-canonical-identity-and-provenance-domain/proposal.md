# Establish canonical identity and provenance in the domain

## Why

The same three facts — which jurisdiction, which logical release, which bytes —
are now represented independently in five places, and none of them is the
source of truth.

- `bronze.release_partition` keys `(manifest_id, jurisdiction_code, tax_year, release_kind)`.
- `bronze.artifact` keys content by SHA-256.
- `silver.source_record` inlines `release_identifier`, `source_member_name`, and
  `source_row_number` as bare strings and integers.
- `S3ArtifactSink` composes `releases/{jurisdiction_code}/{tax_year}/{release_kind}/`
  and `artifacts/{sha256}`.
- `SourceProvenance` carries `jurisdiction_code` and `release_identifier` as
  validated but unrelated strings.

Each was correct for the layer that built it. Together they are five encodings
of one concept, agreeing today because one author held all five in mind at once.
Defects live where two representations must agree, and this change exists to
remove four of the five.

PR #99 is what made the gap visible. It landed durable lineage — manifests,
runs, quality results, publication metadata — and every foreign key in it points
at a string whose meaning is documented in prose rather than enforced by a type.
Bootstrap task 3.4 stayed unchecked for that reason: the columns exist, and the
vocabulary they encode does not.

## What changes

`property_tax_domain` gains the identity and provenance value objects the rest
of the platform will map onto: `Jurisdiction`, `ArtifactIdentity`,
`ReleaseIdentity`, `ReleaseKind`, `ArtifactReleaseBinding`, and
`DomainProvenance`. Construction is validated, equality is structural, and
serialization is a named-field JSON contract that round-trips.

Nothing else is rewritten. Acquisition, Bronze, bounded release processing,
county adapters, and the migrations keep their current representations, and this
change documents how each maps to the new types rather than moving any of them.
The one normative correction is to the still-unimplemented canonical account
contract, whose account identity becomes `(Jurisdiction, source_account_id)`
rather than `(county_fips, source_account_id)`, so that a county is identified
one way rather than by slug in the layers that key on it and by FIPS in the
sentence that defines account identity.

FIPS keeps its accepted role. It appears in fourteen files outside this change,
including all six county source contracts, each of which assigns it from
version-controlled configuration — none of which keys, joins, or compares on it
except the one sentence amended here. What changes is FIPS as an *identifier*;
what remains is FIPS as validated registry metadata.

Every decision below is proposed and takes effect on merge of this planning pull
request, which is the repository's approval event. Issue #100 carries no
comments, so nothing here is settled yet.

## What this change does not do

Task 2.2 canonical records — account, owner, value, exemption,
jurisdiction-value, land, improvement, geometry — are out of scope beyond that
single identity correction. No PostgreSQL migration, S3 key, Airflow behavior,
API surface, or publication policy changes. No runtime dependency is added:
these types must be usable without boto3, psycopg, Airflow, or any county
adapter import, and an architecture test proves it.

## Blocked, deliberately

Two points are recorded as blockers rather than resolved by inference, and
neither blocks the rest of the change.

**Tarrant release discrimination.** The accepted Tarrant contract requires every
artifact to be preserved as a separate release, and supplies no discriminator
that separates two mutable same-year snapshots. Its own scenario already says a
newer artifact under a mutable locator is stored in Bronze and blocked until
classified. Canonical `ReleaseIdentity` construction for that case stays blocked
on the same evidence, rather than inventing a release kind or letting the
checksum become an implicit discriminator.

**Two Denton label mappings.** `preliminary` and `roll-correction` are not
canonicalized as `proposed` and `supplemental`. The words resemble the canonical
vocabulary; no accepted contract establishes that they mean the same thing, and
Denton's own contract leaves preliminary-to-certified semantics unclassified.
They remain source-native until a separate decision establishes equivalence.
