# Canonical appraisal records

The infrastructure-free domain vocabulary that task 3.4 consumes when mapping
canonical appraisal facts into Silver. Normative behavior remains in the
[promoted capability](../../openspec/specs/canonical-appraisal-records/spec.md);
this page records the implemented shape and its storage-facing consequences
without choosing SQL.

## Records

| record | exact fields | parent | classification | provenance |
|---|---|---|---|---|
| `AccountIdentity` | `jurisdiction`, `source_account_id` | none | `stable_identity` | none |
| `AccountSnapshot` | `identity`, `provenance`, `source_as_of`, `situs`, `legal_description` | `AccountIdentity` | `release_snapshot` | direct |
| `OwnerObservation` | `snapshot`, `owner_name`, `provenance`, `mailing_address` | `AccountSnapshot` | `child_observation` | direct |
| `OwnerAssociation` | `snapshot`, `owner`, `provenance`, `ownership_percentage`, `source_discriminator` | `AccountSnapshot` and `OwnerObservation` | `association` | direct |
| `OwnerValueAllocation` | `association`, `kind`, `amount`, `provenance` | `OwnerAssociation` | `association` | direct |
| `AppraisalValueObservation` | `snapshot`, `kind`, `amount`, `provenance` | `AccountSnapshot` | `child_observation` | direct |
| `TaxingUnitObservation` | `snapshot`, `unit_code`, `provenance`, `unit_name` | `AccountSnapshot` | `child_observation` | direct |
| `TaxableValueObservation` | `snapshot`, `taxing_unit`, `amount`, `basis`, `provenance` | `AccountSnapshot` and `TaxingUnitObservation` | `child_observation` | direct |
| `ExemptionObservation` | `snapshot`, `classification`, `scope`, `provenance`, `amount`, `association` | `AccountSnapshot`; optionally `OwnerAssociation` when owner-scoped | `child_observation` | direct |
| `LandObservation` | `snapshot`, `provenance`, `source_discriminator`, `classification`, `area`, `area_unit` | `AccountSnapshot` | `child_observation` | direct |
| `ImprovementObservation` | `snapshot`, `provenance`, `source_discriminator`, `classification`, `area`, `area_unit`, `year_built` | `AccountSnapshot` | `child_observation` | direct |
| `GeometryObservation` | `snapshot`, `encoding`, `payload`, `crs`, `provenance` | `AccountSnapshot` | `enrichment` | direct |

`SitusAddress`, `MailingAddress`, and `LegalDescription` are composed value
objects, not records. They have no independent grain or provenance and are not
present in `RECORD_CLASSIFICATIONS`.

## Grain and relationships

The parent key is `AccountIdentity`: canonical jurisdiction plus the approved
source account identifier. The snapshot grain is the read-only
`AccountSnapshot.grain` tuple `(AccountIdentity, ReleaseIdentity)`. Object
equality is intentionally stricter than grain: snapshots from different
artifacts in one logical release share a grain but retain distinct provenance
and remain unequal. `source_as_of` is observation metadata and is excluded from
equality, hashing, and grain.

Cardinality is stated over **parented records** rather than over children of a
snapshot, because not every parented record hangs from one: an
`OwnerValueAllocation` is parented by an `OwnerAssociation`. "Parented" is a
statement about relation, not about classification — `child_observation` and
`enrichment` remain distinct.

Every parented record is one-to-many, and none is constrained to at most one:

- owner observations and owner associations, parented by a snapshot;
- owner-scoped value allocations, parented by an owner association;
- appraisal-value and taxing-unit-qualified taxable-value observations;
- taxing-unit and exemption observations;
- land and improvement observations;
- geometry enrichments — one snapshot may carry several, each with its own
  lineage, and nothing requires those lineages to differ.

Every observation, association, allocation, and enrichment carries its own
`DomainProvenance`. Its release must equal the parent snapshot's release. An
owner association must reference an owner observation of the same snapshot; an
owner-scoped exemption must reference an association of that snapshot; and a
taxable value must reference a taxing-unit observation of that snapshot. The
snapshot itself enforces that its account jurisdiction equals its provenance
release jurisdiction.

Only `AccountIdentity` asserts stable cross-release business identity. All
`*Observation` records are observations only. `OwnerAssociation` and
`OwnerValueAllocation` preserve source relationships and allocations without
claiming an owner identity or manufacturing an account total. Missing land,
improvement, or owner discriminators remain absent rather than becoming row
numbers or inferred keys.

## Canonical boundaries

The domain accepts only the closed `ValueKind` values `market`, `appraised`, and
`assessed`. Mapping a source-native *value field* into one of those canonical
kinds requires an accepted county contract establishing semantic equivalence, and
the domain exposes no mapping function. Taxable values exist only at taxing-unit
grain.

Source-native descriptive *labels* that a canonical observation is defined to
carry require no such equivalence. They are preserved verbatim as source-native
values, and preserving one is not canonicalizing it.

That distinction decides what reaches storage.

**Unmapped source-native _value fields_ do not enter canonical storage**, because
no accepted contract establishes what they mean:

- Dallas `TOT_VAL` and its components while their semantics remain unresolved;
- Tarrant value fields without an accepted canonical equivalence;
- a property-wide taxable value without a taxing unit;
- account totals assembled from owner allocations;
- a canonical account for a county whose source key is unapproved;
- source table names, families, statuses, field vectors, and arbitrary extras;
- a canonical exemption vocabulary, which no accepted contract establishes.

**Source-native _labels_ that a canonical observation is defined to carry do
enter, verbatim**, and preserving them is the purpose of those fields:

- `ExemptionObservation.classification`, the county's own exemption label;
- `TaxingUnitObservation.unit_code` and `unit_name`;
- `TaxableValueObservation.basis`;
- `LandObservation.classification` and `ImprovementObservation.classification`.

Carrying a county's label is not canonicalizing it. Each of these is declared
source-native and is never mapped into a canonical vocabulary without an accepted
contract establishing equivalence.

Account-key approval is county-adapter behavior governed by the
[`county-appraisal-normalization` contract](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/county-appraisal-normalization/spec.md).
The domain validates only the identifier's lexical form because a jurisdiction
and a string cannot prove which source field supplied it.

Representing an owner name, mailing address, situs address, or legal description
grants no publication permission. Publication stays default-deny under the
reviewed field-level policy; no appraisal record carries a publication,
visibility, permission, or redaction-override field.

No table, column, surrogate key, index, or DDL is selected here. Task 3.4 maps
these records and relationships into storage without changing their grain.

## Validated state

Recorded from the default repository configuration. OpenSpec task checkboxes and
bootstrap task 2.2 remain untouched; the separate completion and archival pull
request owns those mutations.

| gate | result |
|---|---|
| `pytest` through `make check` | 1,479 passed, 146 skipped |
| `ruff format --check .` and `ruff check .` | pass, 179 files formatted |
| `mypy` | pass, 92 source files |
| documentation links | pass, 61 documents |
| `openspec validate --all --strict` | 16 passed, 0 failed |
| `openspec doctor` | pass |
| repository artifact policy | pass, 508 files |
| `make prepr-no-ai` | pass; paid provider review skipped by policy |

The six new suites are collected by the default configuration:

| module | tests collected |
|---|---:|
| `tests/unit/property_tax_domain/test_account.py` | 16 |
| `tests/unit/property_tax_domain/test_owner.py` | 10 |
| `tests/unit/property_tax_domain/test_value.py` | 11 |
| `tests/unit/property_tax_domain/test_exemption.py` | 6 |
| `tests/unit/property_tax_domain/test_children.py` | 15 |
| `tests/unit/property_tax_domain/test_appraisal_provenance.py` | 21 |

## Related

- [Engineering documentation](../README.md)
- [Property tax domain](../../libs/property-tax-domain/README.md)
- [Canonical identity and provenance](canonical-identity.md)
- [Canonical appraisal records capability](../../openspec/specs/canonical-appraisal-records/spec.md)
