# Source Onboarding

The code registry at [`property_tax_adapters.sources.texas.registry`](../../libs/property-tax-adapters/src/property_tax_adapters/sources/texas/registry.py) is the maintained list of initial county source definitions. The [normalization specification](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/county-appraisal-normalization/spec.md) defines shared adapter behavior. Evidence-backed county differences belong in the thin [Dallas](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/dallas-cad-source-contract/spec.md), [Collin](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/collin-cad-source-contract/spec.md), [Denton](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/denton-cad-source-contract/spec.md), [Ellis](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/ellis-cad-source-contract/spec.md), and [Rockwall](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/rockwall-cad-source-contract/spec.md) source contracts.

Source work begins with the GitHub source-onboarding Issue form. Before implementation, verify:

- the publisher is the official appraisal district or county;
- bulk/API access and redistribution terms;
- release kinds, cadence, tax year, and as-of semantics;
- layouts, schema fingerprints, pagination, and authoritative counts;
- fixture redistribution and data-sensitivity constraints;
- stable identifiers and one-to-many relationships.

Denton and Ellis have measured full PACS fixed-width exports but remain non-production until their evidence, grain, release, and privacy gates are resolved. Rockwall's public shapefiles are partial GIS enrichment only; the complete Rockwall appraisal adapter remains blocked pending an official full-roll source. Tarrant is the remaining unspiked initial county.

Add a county source-contract capability only after its spike establishes source authority, release semantics, format and schema behavior, identity and grain, privacy handling, quality gates, and publication blockers. Do not duplicate shared acquisition or canonical requirements in each county contract.

## Related

- [Documentation hub](../README.md)
- [Adapter overview](../../libs/property-tax-adapters/README.md)
- [Architecture](../architecture/README.md)
