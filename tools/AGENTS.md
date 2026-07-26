# Developer Tooling Agent Guide

## Scope

`tools/` owns repository developer-platform packages. It does not own property-tax domain behavior, county adapters, Airflow orchestration, or deployable appraisal services.

## Rules

- Follow the accepted `agent-runner-kernel` OpenSpec capability for CountyForge behavior.
- Keep request validation, profile/provider resolution, budgets, dispatch, and generic evidence in `countyforge-runner`.
- Keep GitHub parsing, authorization, semantic identity, canonical state, leases, cancellation/retry policy, rendering, and API ports in `countyforge-github`.
- Preserve the dependency direction `GitHub Actions -> countyforge-github -> countyforge-runner`; the runner must not import GitHub workflow or API concepts.
- Keep immutable capability policy in `.ai/profiles/`, provider/model compatibility in `.ai/providers/`, schemas in `.ai/schemas/`, and provider/container adapters in `.ai/codex/`.
- Never turn `review.packet-only.v1` into a repository-mounted or code-writing profile.
- Reject unknown contract fields and capability, credential, artifact, provider, model, version, or budget expansion before execution.
- Never read, emit, or log credential values. Tests use sentinels only.
- `plan.read-only.v1` and `implement.workspace-write.v1` are executable only through their bounded, trusted adapters. Fix and validate remain unavailable until their owning OpenSpec change and issue add separate executor boundaries. The implementation model never receives GitHub publication credentials.

## Validation

```bash
make countyforge-runner-check
make countyforge-github-check
make countyforge-workflow-policy-tests
make countyforge-plan-check
make countyforge-plan-fixtures
make countyforge-plan-policy-tests
make countyforge-implement-check
make countyforge-implement-fixtures
make countyforge-implement-policy-tests
make runner-contract-tests
```

## Related

- [Tooling overview](README.md)
- [CountyForge package](countyforge-runner/README.md)
- [CountyForge GitHub package](countyforge-github/README.md)
- [Root agent guidance](../AGENTS.md)
- [Runner engineering guide](../docs/engineering/countyforge-runner-kernel.md)
- [Control-plane engineering guide](../docs/engineering/countyforge-github-control-plane.md)
