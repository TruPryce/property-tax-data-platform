# Developer Tooling

Repository developer-platform packages live here so they cannot be confused with appraisal-domain libraries or production services.

| Package | Purpose |
|---|---|
| [countyforge-runner](countyforge-runner/README.md) | Strict request validation, immutable profile/provider resolution, budgets, execution dispatch, and generic run evidence |
| [countyforge-github](countyforge-github/README.md) | GitHub command parsing, authorization, semantic idempotency, canonical state, leases, and runner request dispatch |
| planning adapter (in `countyforge-github`) | bounded issue context, strict planning results, trusted OpenSpec materialization, and draft-PR publication |

## Related

- [Repository overview](../README.md)
- [Contributor workflow](../CONTRIBUTING.md)
- [Tooling agent guidance](AGENTS.md)
- [Runner engineering guide](../docs/engineering/countyforge-runner-kernel.md)
- [GitHub control-plane guide](../docs/engineering/countyforge-github-control-plane.md)
- [Planning-agent guide](../docs/engineering/countyforge-planning-agent.md)
