## Why

Issue [#4](https://github.com/TruPryce/property-tax-data-platform/issues/4) requires the secure packet-only reviewer from PR #1 to become one executable profile behind a reusable CountyForge runner kernel. The repository needs versioned requests, immutable capability profiles, provider compatibility, budgets, and generic evidence before later epics can safely add planning, implementation, remediation, validation, or GitHub control-plane workflows.

## What Changes

- Add a Python 3.12 developer-tool package under `tools/countyforge-runner/` with one CLI for strict request validation, profile resolution, compatibility checks, budget enforcement, execution dispatch, and generic provenance.
- Add strict versioned request, profile, provider-catalog, generic event, generic summary, and mode-result contracts.
- Define immutable `review`, `plan`, `implement`, `fix`, and `validate` profiles while making only the packet-only review profile executable in this change.
- Preserve the existing read-only review adapter and artifact contract behind the kernel, emitting generic CountyForge evidence alongside the legacy review event and summary during migration.
- Define OpenAI and Sakana provider/model compatibility independently from capability policy, deliberately upgrade the Codex CLI pin, and enforce version and credential gates.
- Add hard profile budgets, fail-closed compatibility checks, no-cost contract fixtures, Make and CI targets, operator documentation, and an accepted ADR.
- Leave `plan`, `implement`, `fix`, and `validate` execution disabled with the structured `profile_not_implemented` disposition.
- Explicitly exclude the GitHub command/control plane, planning and code-writing workflows, repository publication, production runtime integration, and any weakening of the review container.

## Capabilities

### New Capabilities

- `agent-runner-kernel`: Versioned run requests, immutable mode profiles, provider/model compatibility, budget enforcement, fail-closed dispatch, generic provenance, and compatibility with the packet-only review foundation.

### Modified Capabilities

None. The existing `delivery-governance` capability already requires Issue/OpenSpec traceability; this change follows that requirement without changing it.

## Impact

- Adds the `countyforge-runner` uv workspace package and declarative policy under `.ai/profiles/`, `.ai/providers/`, and `.ai/schemas/`.
- Adapts `make prepr` to enter through the kernel while retaining `.ai/codex/02-run-prepr-review-docker.sh` as the isolated review execution boundary.
- Adds generic ignored run evidence without making existing PR #1 artifacts unreadable or changing the canonical review result schema.
- Upgrades the pinned Codex CLI and image provenance deliberately, with deterministic compatibility gates and paid provider probes remaining opt-in.
- Adds only repository developer-platform tooling; property-tax domain, application, adapter, DAG, ingestion, data-store, and production-service behavior are unchanged.
