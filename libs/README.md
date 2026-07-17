# Shared Libraries

Reusable workspace packages implement the hexagonal core.

| Package | Responsibility | Allowed internal dependencies |
|---|---|---|
| [`property-tax-domain`](property-tax-domain/README.md) | Domain identity and canonical semantics | None |
| [`property-tax-application`](property-tax-application/README.md) | Ports and use cases | Domain |
| [`property-tax-adapters`](property-tax-adapters/README.md) | County and infrastructure adapters | Application, domain |

## Related

- [Library agent guidance](AGENTS.md)
- [Architecture](../docs/architecture/README.md)
- [Services](../services/README.md)
