# ADR-0005: Mode-Aware Runner Kernel and Immutable Capability Profiles

## Status

Accepted on 2026-07-19 for GitHub Issue [#4](https://github.com/TruPryce/property-tax-data-platform/issues/4) and OpenSpec change `build-mode-aware-runner-kernel`.

## Context

The packet-only reviewer from PR #1 is intentionally unable to inspect or mutate the repository. CountyForge later needs planning, implementation, targeted remediation, and deterministic validation, but giving one image a universal privileged posture would let ordinary runtime flags turn a reviewer into a code-writing or publishing agent. Provider/model choice is also expected to change independently from filesystem, tool, network, and credential policy.

## Decision

CountyForge uses a Python developer-tool kernel under `tools/countyforge-runner/`. The kernel validates versioned requests, resolves strict immutable JSON profiles and a separate provider/model catalog, enforces hard budgets and version gates, dispatches only an eligible implemented profile, and writes generic provenance.

Capability profiles are version-controlled and canonically hashed. Review, plan, implement, fix, and validate have separate profile IDs, result schemas, mounts, tools, network rules, credential names, images/configuration bundles, and budgets. Provider selection cannot expand profile capabilities.

Only `review.packet-only.v1` executes in this decision's implementation. It remains isolated behind the existing `.ai/codex/` adapter with no repository mount, model shell, browser, apps/MCP, image generation, web search, or publication capability. The adapter and its provider-specific image bundle verify provider, profile hash, and Codex version before credential lookup.

Plan, implement, fix, and validate are declarations only. Their attempted execution produces sanitized `profile_not_implemented` evidence before credential or executor access. Later epics must supply separate executors and image/configuration bundles rather than weakening the reviewer.

Provider policy lives under `.ai/providers/`; capability policy lives under `.ai/profiles/`. The review image deliberately moves to Codex CLI 0.144.6 for the cataloged OpenAI GPT-5.6 compatibility floor, with deterministic version gates and separately opt-in live-provider probes.

PR #1 artifact contract version 1 remains readable. During migration, the kernel writes provider-neutral CountyForge event, summary, request, profile, and metrics artifacts alongside the existing review event, summary, pointers, mirrors, and logs.

## Alternatives

- One universal privileged image was rejected because a review request could gain write or publication capability through configuration drift.
- Rewriting the packet reviewer as a general Python executor was rejected because it would disturb a tested secret/evidence/container boundary without adding Issue #4 value.
- Embedding provider model IDs in profiles was rejected because provider compatibility and capability policy have different change lifecycles.
- Mutable profiles stored outside Git were rejected because historical evidence could not reconstruct the exact capability boundary.
- Immediately replacing PR #1 artifacts was rejected because existing readers and operator workflows would break silently.
- Putting the kernel in domain libraries, services, or DAGs was rejected because it is repository developer tooling, not appraisal behavior or a production runtime.

## Consequences

- Every capability posture or catalog compatibility change is explicit, reviewable, hash-visible, and contract-tested.
- Later mode implementations require their own accepted issue/OpenSpec work, executor, tests, and immutable execution bundle.
- Generic and legacy review evidence coexist temporarily and require agreement tests.
- Operators must rebuild the provider-specific review image after the deliberate CLI/profile label change.
- Paid model availability remains an opt-in operational validation, not a deterministic CI dependency.

## Related

- [Architecture decisions](README.md)
- [Runner engineering guide](../engineering/countyforge-runner-kernel.md)
- [Agent-runner OpenSpec](../../openspec/changes/build-mode-aware-runner-kernel/specs/agent-runner-kernel/spec.md)
- [Review artifact contract](../engineering/review-artifact-contract.md)
- [Issue #4](https://github.com/TruPryce/property-tax-data-platform/issues/4)
- [Parent program #2](https://github.com/TruPryce/property-tax-data-platform/issues/2)
