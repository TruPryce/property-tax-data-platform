# Service Agent Guide

- Treat each service as a composition root and inbound adapter.
- Configuration names are typed and non-secret; secret values come from the runtime environment or secrets backend.
- Keep reusable rules in domain/application packages and external translations in adapters.
- CLI/task commands return nonzero on failure and emit structured, secret-safe diagnostics.
- Service tests use fake ports or local containers; they do not contact official county systems by default.

## Related

- [Services overview](README.md)
- [Root agent guidance](../AGENTS.md)
