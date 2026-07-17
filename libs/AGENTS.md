# Library Agent Guide

## Dependency Direction

`property_tax_adapters -> property_tax_application -> property_tax_domain`

- Domain code is deterministic and infrastructure-free.
- Application code defines Protocol ports and orchestrates domain behavior without importing implementations.
- Adapters translate external formats and implement ports; source-specific fields stop at this boundary.
- Put composition and runtime configuration in `services/`, not shared libraries.
- Add or update architecture tests when adding a package boundary.

## Validation

```bash
make lint
make typecheck
make test
```

## Related

- [Library overview](README.md)
- [Root agent guidance](../AGENTS.md)
