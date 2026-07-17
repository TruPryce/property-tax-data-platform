# Property Tax Adapters

Outbound adapters translate official county formats and infrastructure APIs into application ports. The initial registry contains Dallas, Collin, Tarrant, Denton, Rockwall, and Ellis definitions; every source remains `production_ready = false` until its fixtures and contract tests pass.

County modules live under `src/property_tax_adapters/sources/texas/`. Shared acquisition, Bronze, PostgreSQL, and publication implementations will be added here without importing Airflow.

## Related

- [Adapter agent guidance](AGENTS.md)
- [Shared libraries](../README.md)
- [Source reference](../../docs/sources/README.md)
- [Normalization specification](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/county-appraisal-normalization/spec.md)
