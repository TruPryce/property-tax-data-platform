# Property Tax Domain

Infrastructure-free value objects, entities, canonical appraisal semantics, and domain errors. This package must remain importable without Airflow, HTTP, object-store, or database dependencies.

Current scaffold: stable identities for the six-county Texas cohort, canonical
identity and provenance, and release-scoped canonical appraisal records at their
accepted grain.

The package root is the vocabulary — identities, provenance, canonical appraisal
records, composed address values, and their closed classifications, alongside
the county registry. Import them from `property_tax_domain` rather than from the
module each lives in, so moving a file is not a breaking change. Serialization is
an operation on identity vocabulary rather than part of it and stays in
`property_tax_domain.serialization`.

No storage schema is chosen by these types. See [canonical identity and
provenance](../../docs/engineering/canonical-identity.md) for release lineage and
[canonical appraisal records](../../docs/engineering/canonical-appraisal-records.md)
for the exact Silver-facing record and relationship model.

## Related

- [Shared libraries](../README.md)
- [Architecture](../../docs/architecture/README.md)
- [Canonical identity and provenance](../../docs/engineering/canonical-identity.md)
- [Canonical appraisal records](../../docs/engineering/canonical-appraisal-records.md)
- [Normalization specification](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/county-appraisal-normalization/spec.md)
