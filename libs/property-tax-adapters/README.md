# Property Tax Adapters

Outbound adapters translate official county formats and infrastructure APIs into application ports. The initial registry contains Dallas, Collin, Tarrant, Denton, Rockwall, and Ellis definitions; every source remains `production_ready = false` until its fixtures and contract tests pass.

County modules live under `src/property_tax_adapters/sources/texas/`. Shared acquisition, Bronze, PostgreSQL, and publication implementations will be added here without importing Airflow.

The [Dallas parser foundation](../../docs/sources/dallas-parser-foundation.md) adds an adapter-local,
synthetic-only source contract parser. It retains source-native values and provenance without adding
acquisition, persistence, canonical value semantics, or a production-ready designation.

## Related

- [Adapter agent guidance](AGENTS.md)
- [Shared libraries](../README.md)
- [Source reference](../../docs/sources/README.md)
- [Dallas parser foundation](../../docs/sources/dallas-parser-foundation.md)
- [Normalization specification](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/county-appraisal-normalization/spec.md)
