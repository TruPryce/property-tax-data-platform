# Property Tax Domain

Infrastructure-free value objects, entities, canonical appraisal semantics, and domain errors. This package must remain importable without Airflow, HTTP, object-store, or database dependencies.

Current scaffold: stable identities for the six-county Texas cohort, and the
canonical identity and provenance vocabulary the rest of the platform maps onto.

The package root is the vocabulary — `Jurisdiction`, `ArtifactIdentity`,
`ReleaseKind`, `ReleaseIdentity`, `ArtifactReleaseBinding`, and
`DomainProvenance`, alongside the county registry. Import them from
`property_tax_domain` rather than from the module each lives in, so moving a file
is not a breaking change. Serialization is an operation on that vocabulary rather
than part of it and stays in `property_tax_domain.serialization`.

No existing layer is rewritten to use these types yet. See
[canonical identity and provenance](../../docs/engineering/canonical-identity.md)
for what maps to what, and which task performs each mapping.

## Related

- [Shared libraries](../README.md)
- [Architecture](../../docs/architecture/README.md)
- [Canonical identity and provenance](../../docs/engineering/canonical-identity.md)
- [Normalization specification](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/county-appraisal-normalization/spec.md)
