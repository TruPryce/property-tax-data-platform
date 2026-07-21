# CountyForge Runner Kernel

## Purpose

CountyForge uses a Python 3.12 developer-tool kernel to validate versioned run requests, resolve immutable capability profiles, enforce provider/model and budget compatibility, dispatch an eligible executor, and write provider-neutral evidence. The accepted behavior is the [`agent-runner-kernel` OpenSpec capability](../../openspec/changes/build-mode-aware-runner-kernel/specs/agent-runner-kernel/spec.md); this guide explains the repository layout and operator workflow.

## Responsibility Map

```text
versioned request
      |
      v
tools/countyforge-github/       optional GitHub adapter; auth/state/dispatch
      |
      v
tools/countyforge-runner/       schema validation, resolution, budgets, dispatch
      |           |
      |           +---- .ai/providers/   provider/model compatibility catalog
      +---------------- .ai/profiles/    immutable capability policy
      |
      +---- review only ----> .ai/codex/ packet-only container adapter
      |
      +---- future modes ----> profile_not_implemented before credentials/executor
      |
      v
.ai/reviews/                    ignored generic and legacy run evidence
```

The property-tax domain, application, county adapters, DAGs, ingestion workers, and appraisal services do not depend on this package.

## CLI

All commands emit JSON. `explain` performs the complete non-secret resolution but does not create evidence or start a provider call.

```bash
countyforge-runner run --request <path> --json
countyforge-runner validate-request --request <path> --json
countyforge-runner resolve-profile --request <path> --json
countyforge-runner list-profiles --json
countyforge-runner explain --request <path> --json
```

Local commands may continue to use `--repo-root <path>`. GitHub execution supplies
`--contract-root <trusted-default-branch-path>` and `--target-root <immutable-target-path>`.
The compatibility root defaults both to the current repository; an explicit contract root cannot
be combined with the compatibility option.

`validate-request`, `resolve-profile`, and `explain` validate schema, profile identity/version, mode, prompt, provider/model, Codex version, reasoning effort, budgets, canonical input files, repository identity and commits, packet provenance, output schema, and requested artifacts. They never read provider credentials.

## Versioned Contracts

| Contract | File |
|---|---|
| Run request | [countyforge-run-request.schema.json](../../.ai/schemas/countyforge-run-request.schema.json) |
| Capability profile | [countyforge-profile.schema.json](../../.ai/schemas/countyforge-profile.schema.json) |
| Provider/model catalog | [countyforge-provider-catalog.schema.json](../../.ai/schemas/countyforge-provider-catalog.schema.json) |
| Review packet provenance | [countyforge-review-packet-provenance.schema.json](../../.ai/schemas/countyforge-review-packet-provenance.schema.json) |
| Generic event | [countyforge-run-event.schema.json](../../.ai/schemas/countyforge-run-event.schema.json) |
| Generic summary | [countyforge-run-summary.schema.json](../../.ai/schemas/countyforge-run-summary.schema.json) |
| Review result | [codex-prepr-review.schema.json](../../.ai/schemas/codex-prepr-review.schema.json) |
| Plan result | [countyforge-plan-result.schema.json](../../.ai/schemas/countyforge-plan-result.schema.json) |
| Implementation result | [countyforge-implementation-result.schema.json](../../.ai/schemas/countyforge-implementation-result.schema.json) |
| Fix result | [countyforge-fix-result.schema.json](../../.ai/schemas/countyforge-fix-result.schema.json) |
| Validation result | [countyforge-validation-result.schema.json](../../.ai/schemas/countyforge-validation-result.schema.json) |

Request contract version 1 separates immutable trigger/repository facts from optional display metadata. Base and head refs are full lowercase 40-character Git SHAs. Unknown properties fail. A request cannot carry tools, mounts, network destinations, credentials, writable paths, or implementation state.

Review requests bind both `.ai/reviews/review-packet.md` and `.ai/reviews/review-packet.provenance.json` by SHA-256. A machine-readable first line binds the packet itself to the repository, merge-base, HEAD, and builder version; the sidecar records the same facts plus the exact packet hash and size.

Fix requests require selected finding IDs and an expected head SHA matching the immutable repository head. Validate requests require no provider and reasoning effort `none`.

## Profiles

| Profile | Mode | Repository posture | Execution in Issue #4 |
|---|---|---|---|
| `review.packet-only.v1` | review | no repository mount or access | implemented through `.ai/codex/` |
| `plan.read-only.v1` | plan | future read-only repository/context | `profile_not_implemented` |
| `implement.workspace-write.v1` | implement | future isolated workspace write; arbitrary network disabled | `profile_not_implemented` |
| `fix.targeted-write.v1` | fix | future selected-finding write at expected SHA; arbitrary network disabled | `profile_not_implemented` |
| `validate.deterministic.v1` | validate | future repository-declared deterministic checks | `profile_not_implemented` |

Profiles are strict JSON documents under `.ai/profiles/`. Canonical compact JSON with sorted keys is SHA-256 hashed. Tools, mounts, network, credential names, writable paths, image identity, budgets, or any other posture change therefore creates a different capability hash.

Future profiles describe the capability boundary needed by Issues #6–#8; they do not grant that capability today. A runtime flag cannot change `implementation_state`.

## Provider and Model Compatibility

The version-controlled [catalog](../../.ai/providers/catalog.v1.json) separates remote model configuration from profile capability policy.

| Logical reference | Provider | Configured model ID | Efforts | Minimum Codex CLI | Live state |
|---|---|---|---|---|---|
| `openai.gpt-5.6` | OpenAI | `gpt-5.6` | low, medium, high, xhigh | 0.144.0 | opt-in probe not run in ordinary CI |
| `sakana.fugu` | Sakana | `fugu` | high, xhigh | 0.144.0 | optional provider path |
| `sakana.fugu-ultra` | Sakana | `fugu-ultra` | high, xhigh | 0.144.0 | optional provider path |

The review image deliberately pins Codex CLI `0.144.6`. The build labels the CLI version, provider, profile ID, and canonical profile hash. Before reading a provider or Bitwarden credential, the adapter verifies the selected model allowlist and the image's provider/profile/hash/version labels. A request's claimed CLI version is never treated as image proof.

OpenAI uses `OPENAI_API_KEY`; Sakana uses `SAKANA_API_KEY`. The selected provider is the only provider credential injected into the container. The existing local Sakana compatibility path may use `BITWARDEN_TOKEN` or `BWS_ACCESS_TOKEN` on the host to obtain the selected provider key; broker tokens never enter the container. Evidence contains credential names where needed for posture provenance, never values.

## Budget Resolution

Profiles declare defaults and ceilings for wall time, attempts, input bytes, output bytes, token use, and provider cost. An untrusted request can only keep or tighten the effective default; it cannot select a larger value even when a separate hard ceiling is higher. The ceiling remains a defense-in-depth bound for later trusted policy layers and future profile defaults. Reasoning effort is a closed allowlist.

The review kernel enforces one attempt, input size before dispatch, wall-clock timeout around the adapter, and model/provider output bytes before success. Output accounting covers the final review, event stream, and captured provider stdout/stderr; deterministic provenance, event, metric, and summary files do not consume the model-output budget. Token and cost usage remain `{state: "unavailable", value: null}` when the provider does not report them; the kernel never estimates or fabricates usage.

## Evidence and Compatibility

Generic-only future-mode attempts use:

```text
.ai/reviews/countyforge/<mode>/<run-id>/
```

The kernel atomically claims that directory and refuses existing evidence. A `profile_not_implemented` run writes sanitized request/profile provenance plus a failed generic event and summary before returning non-zero.

Review runs retain the version-1 directory from PR #1:

```text
.ai/reviews/codex-prepr/<safe-branch>/<run-id>/
```

The existing adapter still owns the `.claim/`, packet freeze, Docker execution, legacy summary, legacy event/metrics, pointers, mirrors, and secret scans. The kernel adds these migration artifacts beside them:

- `countyforge-request.provenance.json`;
- `countyforge-profile.snapshot.json`;
- `countyforge-run-event.ndjson`;
- `countyforge-run-summary.json`; and
- `countyforge-run-metrics.prom`.

Historical PR #1 run directories do not need generic artifacts and remain valid. Generic metric labels are limited to mode, profile, provider, catalog model reference, outcome, and disposition. Run ID, branch, SHA, issue/PR number, hashes, paths, and error text remain out of metrics.

## Review Trust Boundary

`review.packet-only.v1` retains no repository mount, no workspace mutation, no model shell or unified execution, no browser, no apps/MCP, no image generation, and no web search. Its only mounts are `.ai/schemas/` read-only and the claimed run directory read-write. Docker uses a read-only root filesystem, a non-root user, dropped capabilities, no privilege escalation, and bounded tmpfs paths. Only the selected model-provider request path is available.

Ordinary review inputs must be regular files whose canonical paths remain beneath the profile-declared `.ai/reviews/` root. The kernel resolves symlinks, rejects `..` and outside-root paths, verifies the configured GitHub origin, requires current `HEAD` to match the request, verifies that the merge-base exists and is an ancestor, and cross-checks the packet's embedded metadata, request hashes, and strict sidecar. It repeats these checks immediately before selected provider or broker values are read. The legacy direct smoke path is the only explicit operator-only nonstandard-input path and is not reachable through a run request.

The kernel preserves declared host-only Docker client, rootless-session, SSH transport, temporary-directory, and locale variables when it launches the adapter. These values support local/remote Docker connectivity but are not forwarded by `docker run`; the container receives only its fixed home variables and the one selected provider credential.

OpenAI and Sakana use separately built provider-specific configuration bundles. Runtime request fields cannot switch an image's provider label, profile hash, tools, or mounts.

For GitHub-dispatched runs, the trusted contract root and immutable target root are distinct. The
kernel loads profiles, schemas, provider catalog, prompts, adapters, and evidence policy only from
the contract root. Repository identity, exact head, base ancestry, and packet provenance are
validated against the target root, which may be a bare Git repository with no worktree. The
provider job therefore never needs a target checkout. See the
[GitHub control-plane guide](countyforge-github-control-plane.md).

## Validation and Live Probes

No-cost checks run in ordinary CI:

```bash
make countyforge-request-fixtures
make countyforge-profile-tests
make countyforge-runner-check
make runner-contract-tests
```

Paid provider probes require a double opt-in and are never CI prerequisites:

```bash
make codex-image
RUN_LIVE_PROVIDER_SMOKE=1 make codex-smoke

make codex-image-openai
RUN_LIVE_PROVIDER_SMOKE=1 make codex-smoke-openai
```

Run a live probe before relying on a rebuilt image, changed Codex/provider integration, or changed remote model identifier in another environment.

For Issue #4 acceptance on 2026-07-19, the Sakana `fugu-ultra` review path ran successfully through the new kernel at both `xhigh` and `high` effort. The dedicated paid adversarial Sakana smoke and paid OpenAI smoke were intentionally skipped; `openai.gpt-5.6` therefore remains `live_validation: not_run` in the catalog until an operator explicitly opts in.

## Integration and Deferred Work

Issue #5 adds the GitHub command, authorization, dispatch, and run-control adapter without adding
an executor to the kernel. Issues #6 and #7 own executable planning and isolated implementation
workflows. Issue #8 owns targeted fixes and review convergence. Issues #9 and #10 own expanded
durable operational evidence and specialist routing. None of those future execution capabilities
is implied by the GitHub adapter.

## Related

- [Documentation hub](../README.md)
- [Pre-PR review contract](pre-pr-review-contract.md)
- [Review artifact contract](review-artifact-contract.md)
- [Legacy review observability](codex-runner-observability.md)
- [Mode-aware runner ADR](../decisions/0005-mode-aware-runner-kernel.md)
- [GitHub control plane](countyforge-github-control-plane.md)
- [GitHub control-plane ADR](../decisions/0006-github-native-countyforge-control-plane.md)
- [CountyForge package](../../tools/countyforge-runner/README.md)
- [Issue #4](https://github.com/TruPryce/property-tax-data-platform/issues/4)
