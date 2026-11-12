# Library Agent Guide

## Dependency Direction

`property_tax_adapters -> property_tax_application -> property_tax_domain`

- Domain code is deterministic and infrastructure-free.
- Application code defines Protocol ports and orchestrates domain behavior without importing implementations.
- Adapters translate external formats and implement ports; source-specific fields stop at this boundary.
- Put composition and runtime configuration in `services/`, not shared libraries.
- Add or update architecture tests when adding a package boundary.

## Application Boundary

- Keep the package-level port surface explicit in `property_tax_application.__all__`.
- Keep `BronzeStore` and `ManifestIndex` separate: one returns immutable storage evidence, the other
  the queryable reference a run binds to.
- Compose application ports, not adapter types, in bootstrap 2.4; that handoff also owns replacing the
  S3 adapter's time helper with injected `Clock`.
- Keep publication limited to attempts, lineage, admission, failure, and supersession. Bootstrap 6.2
  owns Gold construction and promotion mechanics.
- Follow the promoted [`canonical-load-session`](../openspec/specs/canonical-load-session/spec.md)
  capability instead of restating its transition table.

## Validation

```bash
make lint
make typecheck
make test
```

## Related

- [Library overview](README.md)
- [Application boundary](property-tax-application/README.md)
- [Root agent guidance](../AGENTS.md)
