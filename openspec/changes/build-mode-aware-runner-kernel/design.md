## Context

PR #1 established a Dockerized Codex/Sakana pre-PR reviewer whose trust boundary is deliberately narrow: a frozen packet on stdin, a read-only schema mount, one claimed output directory, no repository mount, no model-invokable execution or browsing tools, no web search, and secret-leak gates around generated evidence. Issue [#4](https://github.com/TruPryce/property-tax-data-platform/issues/4) is the next program slice under [#2](https://github.com/TruPryce/property-tax-data-platform/issues/2): introduce a shared execution kernel and declarations for five modes without converting that reviewer into a universal privileged agent.

The kernel is repository developer-platform tooling. It does not belong in property-tax domain or application packages, county adapters, Airflow DAGs, ingestion workers, or production services. Later issues will add a GitHub control plane, issue-to-OpenSpec planning, isolated code-writing agents, and review/remediation convergence, but this change must provide the contracts those workflows can safely consume.

## Goals / Non-Goals

**Goals:**

- Validate an immutable, versioned request before any provider or execution work.
- Resolve one immutable profile and one compatible catalog model with effective budgets and a canonical capability hash.
- Execute the existing packet-only reviewer through a stable adapter without weakening its boundary.
- Define meaningful, separately versioned plan, implementation, fix, and validation result contracts while failing their execution closed.
- Produce provider-neutral, low-cardinality generic evidence while preserving PR #1 artifact compatibility.
- Make capability, provider, credential, version, and budget drift fail deterministic no-cost tests.

**Non-Goals:**

- GitHub comment parsing, actor authorization, workflow dispatch, branches, commits, pushes, PR publication, merges, or a self-hosted GitHub runner.
- Issue-to-OpenSpec planning or executable plan, implement, fix, and validate workflows.
- Production VPS, Tailscale, PostgreSQL, Airflow, S3, county source, appraisal, or production-secret integration.
- A runtime switch that grants the reviewer repository access, a shell, browser, apps/MCP, image generation, web search, or publication capability.

## Decisions

### 1. Keep the kernel in a dedicated uv developer-tool package

`tools/countyforge-runner/` is a Python 3.12 src-layout package and `tools/*` is a uv workspace member. The package owns request/schema validation, declarative catalog loading, compatibility and budget resolution, dispatch, and generic evidence. `.ai/profiles/`, `.ai/providers/`, and `.ai/schemas/` remain version-controlled data; `.ai/codex/` remains the provider/container adapter.

Putting the package under `libs/` was rejected because it would imply reusable property-tax application behavior. Putting it under `services/` was rejected because this is not a deployable appraisal runtime. Extending the shell runner into a general mode dispatcher was rejected because it would mix policy, validation, privileged execution, and the review boundary.

### 2. Validate and resolve in a fixed fail-closed order

The kernel performs: JSON parsing, request-schema validation, contract-version gate, profile lookup/version match, mode/profile match, profile-schema validation, enabled/implementation-state check, provider/model lookup, provider/profile compatibility, Codex-version gate, effort compatibility, output/artifact allowlists, budget-ceiling checks, canonical input-root enforcement, repository identity/commit verification, and packet-provenance agreement. Only an eligible implemented profile reaches an executor.

Unknown request fields are invalid. A request has no fields for arbitrary tools, mounts, network destinations, or credentials, so attempts to add them fail schema validation. No rejection path loads provider credential values. Unimplemented profiles write sanitized generic provenance and return `profile_not_implemented` before provider credential selection, mounts, Docker, or deterministic commands.

### 3. Use immutable JSON profiles with canonical hashes

Profiles are strict JSON documents validated by one schema. Their identity is `(profile_id, profile_version)` and their canonical SHA-256 is computed from sorted compact JSON bytes. The hash covers provider/model policy, output/artifact allowlists, budgets, mounts, repository and writable-path access, tools, deterministic commands, network, credential names, environment allowlist, image/config identity, and expected security posture.

A mutable database or runtime flag set was rejected because historical evidence could no longer reconstruct the capability boundary. One universal profile was rejected because a review invocation must not be transformable into a writer by changing ordinary request values.

### 4. Separate provider/model compatibility from capability policy

Profiles state which provider IDs, logical model references, and efforts they permit. A separate strict catalog maps a logical model reference to its provider, concrete configured model identifier, supported efforts, minimum Codex CLI version, structured-output behavior, expected tool capabilities, credential name, and availability/live-validation state.

This separation prevents a model upgrade from silently changing filesystem, network, or tool policy and prevents a profile from inventing remote identifiers. The initial catalog retains the existing Sakana identifiers and adds the officially documented OpenAI `gpt-5.6` identifier.

### 5. Preserve the packet-only reviewer as an adapter

`review.packet-only.v1` dispatches `.ai/codex/02-run-prepr-review-docker.sh`. That adapter continues to own the atomic claim, packet freeze, image identity, Docker mounts, tool disables, provider-key injection, output schema, secret scans, and PR #1 evidence. The kernel passes only resolved values and a deliberately scoped environment.

The profile declares no repository mount, no repository access, only the schema directory read-only and claimed output directory read-write, no writable workspace path, no model tool, provider-request-only network, and no browser/apps/MCP/image/web capability. Future executors and images are not added to this adapter.

Rewriting the adapter in Python was rejected because it would create unnecessary posture drift. Letting the adapter choose arbitrary providers/models outside the catalogs was rejected because it would bypass compatibility validation.

### 6. Declare future profiles without making them executable

The plan profile declares read-only repository/context semantics and a plan schema; implement declares a future workspace-write boundary with network disabled and no production credentials; fix declares targeted writes and requires selected finding IDs plus an expected head SHA; validate declares repository-approved deterministic commands and no model requirement. Each uses a distinct not-built image/config identity where applicable.

All four have `implementation_state: not_implemented`. Their `run` response is never successful and uses disposition `profile_not_implemented`. Runtime flags cannot change implementation state.

### 7. Keep mode-result schemas distinct

The existing `codex-prepr-review.schema.json` remains the review result. Separate strict schemas encode plan assumptions/decisions/tasks, implementation work/paths/checks/publication eligibility, targeted fix findings/SHA/staleness, and deterministic validation commands/checks/merge eligibility. A generic success envelope was rejected because it would erase mode-specific semantics and allow a review result to masquerade as implementation evidence.

### 8. Add generic evidence alongside artifact contract v1

During migration the kernel writes `countyforge-request.provenance.json`, `countyforge-profile.snapshot.json`, `countyforge-run-event.ndjson`, `countyforge-run-summary.json`, and `countyforge-run-metrics.prom`. Review runs place them beside the legacy review artifacts. Existing `codex-runner-event.ndjson`, `codex-runner-metrics.prom`, `run.summary.json`, latest pointer, and compatibility mirror remain readable and authoritative for the PR #1 contract.

The generic event uses mode, profile identity/hash, provider/model, lifecycle state, disposition, budget usage with typed unavailable values, immutable SHAs, output/prompt/profile hashes, image identity, capability posture, secret-leak status, and artifact-export status. Generic metrics use only catalog/profile-controlled low-cardinality labels. Run IDs, branches, SHAs, issue/PR numbers, hashes, paths, and error text remain only in structured evidence.

Replacing the legacy artifacts immediately was rejected because existing readers and operator habits would silently break. Bumping the v1 review artifact contract was rejected because the review artifacts themselves are not being redefined.

### 9. Resolve effective budgets by tightening defaults under ceilings

Each profile declares defaults and ceilings for wall time, attempts, output bytes, input/context bytes, reasoning effort, tokens, and cost. Untrusted requests may omit overrides or tighten an effective default; they may never choose a larger value, even when the separately declared hard ceiling is higher. Those ceilings bound later trusted policy layers and future versioned defaults. Reasoning effort is an allowlisted choice, not an ordered numeric expansion. A concrete token/cost limit may replace a default `null` as a tighter requested bound, while `null` usage still represents unavailable reporting; the kernel never fabricates provider usage.

The review adapter receives the resolved input and output byte caps and is run under the resolved wall-clock timeout. Attempt count is enforced by the kernel dispatcher. A timed-out process is terminated and cannot be reported as successful.

### 10. Scope credentials by selected provider and never serialize values

The catalog associates OpenAI with `OPENAI_API_KEY` and Sakana with `SAKANA_API_KEY`. The host compatibility adapter may use explicitly declared Bitwarden broker token names to obtain the Sakana key, preserving current local operation, but only the selected provider key enters the container. Profiles and snapshots record credential names only. Request, resolve, explain, event, summary, metrics, exception, and logs must never contain credential values or environment dumps.

### 11. Deliberately upgrade and gate Codex CLI

The review image pin moves from `0.142.2` to the published `0.144.6`, which is above Issue #4's required `0.144.0` compatibility floor for the OpenAI GPT-5.6 path. Image labels, provider catalog, provenance, tests, and documentation use the same declared version. Compatibility resolution compares semantic versions and fails before execution when the installed or image-reported version is below either the profile or model minimum.

Sakana and OpenAI live-provider smoke tests remain separately and explicitly opt-in. Neither is part of CI. The catalog records live-validation state rather than implying a paid probe ran.

### 12. Treat executable posture as an immutable bundle

For the executable review profile, contract tests compare the profile declaration, build-script configuration, runner flags, mounts, credential injection, tool-disable list, schema, and image label. A CLI/image change that adds an undeclared tool or mount fails validation. Future write-capable profiles require their own image/configuration bundle and executor in later issues.

### 13. Bind executable inputs to an approved repository and packet snapshot

Profiles declare repository-relative approved input roots and repository identity/base policies. The executable review profile accepts its packet and packet-provenance sidecar only beneath `.ai/reviews/`. The kernel resolves each path and every symlink before checking containment, requires regular files, and records only canonical file facts rather than accepting a caller-selected host path. Ordinary run requests have no override for this boundary; the direct adversarial adapter smoke remains the explicit host/operator-only nonstandard-input path.

Review packet provenance consists of a machine-readable metadata line embedded in the packet plus a strict sidecar containing the repository full name, exact merge-base SHA, exact checked-out HEAD SHA, packet byte count, packet SHA-256, and deterministic builder identity. The request includes the packet and sidecar hashes. Before an executable review becomes eligible—and again immediately before credential selection—the kernel verifies the configured origin repository, current HEAD, existence and ancestry of the base commit, approved-root containment, regular-file posture, packet/sidecar hashes, and cross-agreement among the request, embedded metadata, and sidecar. This preserves dirty-worktree pre-PR review: HEAD identifies the checkout commit while the packet hash identifies the exact frozen review bytes.

Trusting request SHA syntax alone was rejected because it allows provenance claims unrelated to the checkout. Trusting an arbitrary sidecar alone was rejected because the request would not bind the sidecar or packet bytes. Requiring a clean worktree was rejected because the repository-native pre-PR loop intentionally reviews uncommitted changes.

## Risks / Trade-offs

- [Generic and legacy evidence can drift] -> Derive generic review evidence from the resolved request/profile and legacy result, then test cross-artifact identity and outcome agreement.
- [Declarative future write profiles may be mistaken for available workflows] -> Expose `implementation_state` and `execution_eligible` in every list/resolve/explain response and return a non-zero structured disposition from `run`.
- [Catalog data can become stale as providers evolve] -> Require explicit catalog and minimum-version changes, deterministic gates, provenance hashes, and optional live validation before relying on a changed provider path.
- [Timeout termination can leave Docker cleanup work] -> Keep the adapter's `--rm` container behavior and unique name; report timeout distinctly and never claim success.
- [Credential broker compatibility broadens host environment handling] -> Keep broker resolution inside the existing adapter, declare broker token names explicitly, prohibit them from the container, and test output artifacts against sentinel values.
- [Adding generic artifacts changes the contents of a review run directory] -> Document them as additive migration artifacts and update the adversarial allowlist without changing or removing v1 filenames.
- [A request can name unrelated host bytes or repository facts] -> Resolve profile-approved inputs, bind packet and sidecar hashes in the request, verify origin/HEAD/base ancestry and provenance agreement twice before credential selection, and cover every mismatch with no-cost tests.

## Migration Plan

1. Land strict schemas, catalogs, profiles, and deterministic validators without changing review execution.
2. Add the kernel CLI and prove all future profiles fail before credential or executor access.
3. Dispatch the legacy reviewer from the kernel and emit additive generic evidence; retain the direct adapter tests and legacy files.
4. Route `make prepr` through a generated versioned request, keeping `make prepr-no-ai` packet-only and legacy artifact locations unchanged.
5. Upgrade/build the review image under the pinned CLI version and run no-cost gates; run provider smoke tests only with explicit operator opt-in.
6. Roll back by routing `make prepr` directly to the unchanged adapter and ignoring additive generic artifacts. Existing v1 evidence remains readable throughout.

## Open Questions

None block Issue #4. Provider live availability and the concrete image/executor designs for plan, implement, fix, and validate remain acceptance decisions for their owning later issues.
