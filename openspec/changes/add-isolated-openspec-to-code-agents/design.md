## Context

The runner kernel and GitHub control plane are trusted developer tooling. Issue text, planning output, target files, and model claims are untrusted evidence. Implementation therefore uses three roots: a trusted contract root, an immutable source root at the captured default-branch SHA, and an ephemeral writable workspace. The model never owns GitHub publication.

## Architecture

`countyforge-github` resolves eligibility and builds an implementation packet and manifest. `countyforge-runner` resolves `implement.workspace-write.v1` and invokes a profile-specific adapter. The adapter mounts only the isolated workspace and claimed output, provides the selected provider credential at invocation time, and exposes no model process-execution tool; the model returns a bounded file bundle. Trusted tooling materializes that bundle and uses the versioned command broker for validation rather than arbitrary host shell. A no-provider-secret validation job reconstructs the artifact from the trusted base and runs trusted gates. A short per-target publication transaction creates or updates a deterministic draft branch and PR, then updates canonical state.

## Eligibility and identity

Eligibility requires a real originating issue, the exact kebab-case change on the trusted default branch, valid OpenSpec proposal/design/tasks/specs, issue traceability, no unresolved blocking decisions, an authorized command actor, an immutable trusted base SHA, and no active implementation lease. The planning PR must have been merged by an authorized maintainer; reactions, labels, draft PRs, bot output, and issue prose are not approval evidence. Semantic identity includes repository ID, issue, command, change hash, base SHA, profile/version, policy version, and implementation revision.

## Packet and context

Trusted selection includes the accepted change, applicable capabilities and ADRs, root/scoped guidance, ownership and dependency rules, relevant files/tests, validation definitions, prior validated evidence when resuming, and bounded issue evidence. Every source has a stable ID, repository-relative path, hash, byte count, category, trust class, selection reason, and truncation state. Paths are canonicalized and confined; symlinks, non-regular files, prohibited roots, oversized files, and external content are excluded with reason codes. Packet and context-manifest hashes are cross-checked before provider execution.

## Workspace, commands, and change policy

The workspace is created from the trusted base with hooks, credential helpers, fsmonitor, SSH, Docker, Tailscale, host-home mounts, and production credentials disabled. A trusted workspace-binding manifest records the repository, issue, accepted change, run, immutable base/head, disabled Git settings, and a content hash before provider credentials are selected. The model mount masks `.git`; Git metadata remains available only to trusted host tooling. A versioned command registry permits only exact repository-declared commands with bounded time/output, offline network by default, and phase/path policy. The command broker uses a deny-by-default bubblewrap filesystem that exposes only the candidate workspace and read-only contract runtime; host homes, temporary directories, `/run`, `/var/run`, Docker/SSH/Tailscale sockets, and other host roots are unavailable. A separate path policy rejects writes outside the workspace and disallows OpenSpec contracts, workflows, CODEOWNERS, policies, providers, credentials, infrastructure, data archives, `.env`, `.git`, and other sensitive roots unless an accepted higher-risk flag explicitly permits them. No model output can expand either policy.

## Task slices and artifacts

Trusted code derives a task plan from accepted OpenSpec checkboxes. Each slice records prerequisites, allowed paths, required checks, risk, workspace revision, and bounded command evidence. After every slice, the trusted broker computes the diff and enforces file/byte/symlink/binary limits. The model's result is evidence only; trusted reconciliation determines task completion and publication eligibility. Handoff artifacts are a declared file bundle, strict JSON result, task/command evidence, workspace manifest, checksums, and sanitized provenance; `.git`, credentials, caches, production data, and unbounded logs are excluded.

## Validation and publication

Validation downloads and checksums the artifact, verifies run/issue/change/base/profile/packet bindings, strictly validates every downloaded result/manifest/task/event/report contract, reconstructs a clean worktree, applies only declared files, enforces path and secret policy, runs the full deterministic CountyForge and repository gates plus change-selected tests, and emits a trusted validation report bound to the exact implementation-result checksum. OpenSpec is installed in a trusted no-secret step before the command sandbox and is exposed through the read-only contract mount; sandboxed gates never fetch packages. Generic runner evidence is uploaded independently of workspace-bundle freezing so adapter/schema/policy failures remain diagnosable. Only a successful report and live lease permit publication. The publisher derives `countyforge/implement/issue-<issue>-<change>-r<revision>`, never writes `main`, creates a commit from the validated manifest, and opens or updates a draft PR with no provider credential. Human review remains required.

Validation can execute model-authored files as part of those deterministic gates. This bounded v1
residual risk is accepted only in the no-provider-secret, no-write validation job: registry
commands run in an enforced no-network sandbox, and the publisher treats all model claims as
untrusted until it rechecks the live lease and validates the declared manifest again.

## Resume, cancellation, and compatibility

An unchanged semantic request deduplicates or resumes only from validated artifacts. A changed accepted hash or base SHA creates a superseding revision and never overwrites a human-edited branch/PR. Cancellation is checked at intake, execution, validation, and immediately before Git mutation; a cancellation/publication race reports any already-created ref honestly. Existing review/planning commands, state markers, history, leases, and artifacts remain readable; implementation metadata is optional for legacy states.
