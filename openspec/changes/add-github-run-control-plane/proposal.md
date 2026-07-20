## Why

The CountyForge runner now has immutable capability profiles and a secure packet-only review executor, but it has no authenticated, durable, or auditable remote control surface. GitHub Issue and pull-request comments need to become a fail-closed control plane without allowing an untrusted target revision to replace trusted tooling or execute in a provider-secret context.

This change implements GitHub Issue #5 under parent program #2.

## What Changes

- Add a strict, line-oriented `/countyforge` command parser for `plan`, `implement`, `validate`, `review`, `fix`, `status`, `cancel`, and `retry`.
- Add repository-permission authorization, an immutable GitHub trigger envelope, semantic idempotency, target-scoped leases, legal lifecycle transitions, retry/cancellation rules, and sanitized control-plane evidence.
- Add one bot-owned canonical status comment per target and one sanitized check run per executable pull-request operation.
- Add a dedicated `countyforge-github` developer-tool package and thin GitHub-hosted Actions workflows for intake, target preparation, execution, publication, and stale-run reconciliation.
- Enforce a two-root trust model: default-branch tooling and contracts remain trusted while the immutable issue or pull-request target is handled only as untrusted data.
- Extend the runner kernel narrowly so trusted `contract_root` resources remain separate from the immutable `target_root` used for repository and packet binding.
- Keep `review.packet-only.v1` as the only executable profile. Route future mode commands to their declared profiles and preserve the kernel's structured `profile_not_implemented` result.
- Add comprehensive no-cost schema, parser, policy, race, workflow, security-boundary, and compatibility tests.
- Add an ADR and operator/developer documentation for the GitHub-native control plane.

Explicit non-goals are plan-agent reasoning, OpenSpec generation, repository-writing executors, branch/commit/push/PR creation, targeted remediation, automatic merge or thread resolution, production infrastructure or credentials, external state stores, webhook services, and self-hosted runners.

## Capabilities

### New Capabilities

- `github-agent-control-plane`: Defines command parsing, authorization, immutable trigger facts, GitHub-native durable state, dispatch, two-lane concurrency, leases, status/check publication, cancellation, retry, recovery, and the trusted-tooling boundary.

### Modified Capabilities

- `agent-runner-kernel`: Adds explicit trusted contract-root and immutable target-root resolution while preserving local single-root compatibility and all existing review provenance checks.

## Impact

- Adds `tools/countyforge-github/` to the Python 3.12 uv workspace with a one-way dependency on `countyforge-runner`.
- Adds strict schemas and a version-controlled authorization policy under `.ai/`.
- Adds `countyforge-command.yml`, `countyforge-run.yml`, and `countyforge-maintenance.yml` under `.github/workflows/` with pinned actions and explicit job permissions.
- Narrows changes to the developer-platform runner integration; property-tax domain, application, adapter, ingestion, Airflow, storage, and county-source behavior are unaffected.
- Preserves the local `make prepr` path, legacy review artifacts, packet-only image posture, opt-in paid smoke tests, and existing runner request/profile contracts.
