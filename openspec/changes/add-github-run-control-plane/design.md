## Context

PR #11 established a provider-neutral CountyForge kernel with immutable capability profiles and one executable packet-only reviewer. The kernel currently assumes one repository root for both trusted contracts and the checked-out revision. GitHub Issue #5 makes GitHub comments the remote control surface, which introduces untrusted Markdown, authorization decisions, webhook replay, concurrent commands, durable status, cancellation, retries, and fork pull-request code.

The control plane is privileged even though the reviewer is read-only: it can read repository metadata, update comments/checks, dispatch/cancel Actions, and selectively expose a provider credential. The reviewed target MUST therefore never replace or execute the workflow, parser, kernel, profiles, schemas, provider catalog, prompts, packet builder, or container adapter that enforce policy.

PR #11 and Issue #4 were merged before this branch was created. The earlier `build-mode-aware-runner-kernel` OpenSpec remains an active, strictly valid historical change in this repository rather than being rewritten here. This change layers only its narrow `contract_root`/`target_root` integration delta, and strict validation covers both changes together. After this PR merges, the archive order is the earlier runner-kernel change first and this control-plane change second.

## Goals / Non-Goals

**Goals:**

- Parse and authorize one explicit `/countyforge` command from a newly created issue or pull-request comment.
- Resolve immutable issue/PR and actor facts, construct strict trigger and runner requests, and dispatch only the exact selected profile.
- Keep trusted default-branch tools separate from the immutable untrusted target revision through packet preparation and provider execution.
- Serialize target state, deduplicate semantic commands, model explicit leases and lifecycle transitions, and recover expired work without overwriting terminal evidence.
- Maintain one sanitized bot-owned status comment and, for pull-request executions, one sanitized check run.
- Support authorized status, cancellation, and retry without external state services.
- Preserve the kernel's fail-closed future profiles and all PR #11 review boundaries.

**Non-Goals:**

- Implementing plan, implement, fix, or validate executors; generating OpenSpec artifacts; or modifying repository contents.
- Creating branches, commits, pushes, pull requests, merges, or review-thread resolutions.
- Running target tests, scripts, package hooks, workflow files, Make targets, or binaries in any secret-bearing job.
- Adding external databases, queues, object stores, webhook services, production infrastructure, self-hosted runners, or production credentials.

## Decisions

### 1. Use a dedicated GitHub adapter with ports around API access

`tools/countyforge-github/` owns pure command parsing, authorization policy, trigger construction, semantic identifiers, state/lease transitions, request construction, rendering, sanitization, and reconciliation. A small `GitHubPort` protocol isolates REST operations so unit and race tests use in-memory fakes. Workflow YAML supplies immutable event facts and orchestrates jobs; it does not implement policy.

The package depends on `countyforge-runner`; the kernel never imports GitHub concepts. This keeps repository developer-platform behavior out of property-tax domain/runtime packages.

Rejected alternatives:

- Shell/`jq` policy in workflow YAML is difficult to type, fuzz, and keep consistent across intake, maintenance, and retry.
- Adding GitHub APIs to the kernel would couple provider-neutral execution to one control plane.

### 2. Treat trusted contracts and target content as different roots

The kernel gains `contract_root` and `target_root`. Profiles, schemas, provider catalog, prompts, adapters, and evidence paths resolve only from `contract_root`; repository identity, `HEAD`, base ancestry, and packet provenance bind to `target_root`. Local developer commands default both to the current repository, preserving `make prepr`.

Every Actions phase checks out trusted tooling at one immutable default-branch SHA. Packet preparation uses that trusted packet builder against a separate target worktree in a job with no provider credential. It executes only fixed commands from the trusted script, with system/global Git configuration disabled and command-scope configuration disabling target hooks, fsmonitor commands, credential helpers, SSH, and ext transports. It also creates a minimal bare target identity repository containing the immutable base/head objects. The provider job downloads the frozen packet, provenance, and bare identity artifact; it never checks out a target worktree or runs target-controlled code.

Rejected alternatives:

- `pull_request_target` plus a PR checkout combines secrets with attacker-controlled code.
- Loading profiles or workflow helpers from the target lets a PR weaken the reviewer.
- Trusting only a packet manifest would weaken PR #11's repository/commit binding; the bare repository retains independent Git object validation without a worktree.

### 3. Use a strict Markdown command grammar

The parser scans a bounded comment line by line while tracking fenced code and HTML comments. It removes inline-code spans before matching exact ASCII `/countyforge <command>` lines. Blockquotes, generated status regions, bot comments, edited/deleted events, Unicode lookalikes, prose flags, unknown arguments, multiple commands, and oversized input are ignored or rejected with stable reason codes. Exactly one execution or control operation is produced.

The canonical command has a closed command enum and a closed argument object. OpenSpec change is the only initial optional execution argument and MUST match a conservative identifier grammar; commands without declared arguments reject extra tokens.

### 4. Authorize repository permission before material work

The adapter resolves the actor's effective repository permission through GitHub. `admin`, `maintain`, and `write` are allowed; `triage`, `read`, and `none` are denied. GitHub's legacy `permission` value and `role_name` are normalized without granting custom roles more access than their base permission.

An immutable version-controlled policy can additionally allow exact bot identity IDs or exact organization/team slugs. The initial allowlists are empty. Issue authorship, labels, comment text, and forged status markers never grant authority. Every post-authorization intake result includes bounded immutable actor facts, resolved permission, policy version, outcome, and reason code as structured evidence while metrics retain only low-cardinality authorization outcome. Denial creates only a concise sanitized audit/refusal and cannot create a runner request, target-preparation job, provider-secret job, check run, dispatch, or cancellation.

### 5. Separate semantic identity from delivery provenance

Execution idempotency is SHA-256 over canonical JSON containing contract version, repository ID, target type/number, normalized command/arguments, profile ID/version, immutable head SHA, and optional OpenSpec change. Comment ID and delivery ID remain trigger provenance but do not alter semantic identity. A repeated command on the same head deduplicates; a new head produces a new eligible identity. Fork targets record their immutable source-repository identity separately from the base repository, and GitHub's compare result supplies the ancestor merge base used by packet and kernel provenance.

Retry is not a repeated execution command. A strict retry envelope carries the original semantic key/run ID and incremented attempt; the effective dispatch identity derives from those facts, preserves the original execution command provenance, and requires the current target head to equal the original head.

### 6. Keep GitHub-native state in one bot-owned canonical comment

The adapter searches comments for a bounded hidden marker, accepts it only when the comment's immutable author ID/type matches the trusted bot identity supplied by the workflow, requires exactly one well-formed marker, base64url-decodes canonical JSON, validates the strict state schema, and binds repository ID plus target type/number to the current event. Malformed, duplicated, oversized, schema-invalid, or target-mismatched bot state fails closed. A matching marker in a user comment is untrusted text.

State stores repository/target identity, current run and idempotency key, command/profile/head, attempt, monotonic revision, workflow/check IDs, lifecycle state, lease, timestamps, disposition, and sanitized GitHub links. Rendering updates the existing comment rather than creating status spam. Every intake, execution, and maintenance writer reads the exact bot-owned comment ETag, validates its schema/revision against the expected predecessor, and sends a conditional `If-Match` update. A `412` causes one bounded reread/rebase or a fail-closed conflict; the same publication mirrors the resulting lifecycle into an existing PR check only after the canonical CAS succeeds. Terminal run data is immutable; display-only reconciliation may refresh links or timestamps without rewriting prior artifacts.

An external database was rejected for this release because target concurrency, a canonical comment, checks, workflow metadata, and artifacts provide enough recoverable GitHub-native state for the initial single-repository control plane.

### 7. Use two serialized lanes plus an explicit lease

Short control operations use `countyforge-control-<repo-id>-<target-type>-<number>` with `cancel-in-progress: false`. Dispatched execution uses `countyforge-run-<repo-id>-<target-type>-<number>`, also without automatic cancellation. Keeping lanes separate allows `/countyforge status` and `/countyforge cancel` to run while a model job is active.

The canonical lease records owner workflow run/attempt, semantic key, command, target SHA, acquired/heartbeat/expiry timestamps, and a nonce. GitHub comment ETag plus monotonic revision forms the canonical optimistic-concurrency contract; each transition requires the expected revision and produces the next revision, while transport `412` conflicts are bounded to one reread/rebase. The control lane and target execution lane remain independent, so cancellation/status do not wait behind a provider job. A stale status, cancellation, claim, terminal publication, or maintenance write preserves a newer state or fails with `state_write_conflict` instead of replacing it. Stage transitions update heartbeats. Check creation and check-ID publication failures convert an already-published queue to a retryable terminal failure. A queued run with no workflow owner or lease has a 30-minute preclaim deadline that status, a later command, or maintenance converts to `workflow_claim_timeout`. An authorized new command or maintenance run can reclaim an expired leased run by transitioning the old run to `stale`; completed evidence is never replaced. Maintenance only reconciles terminal recovery and never starts model work.

GitHub concurrency is defense in depth rather than the state store. Ordinary duplicate commands never use `cancel-in-progress: true`.

### 8. Define an explicit lifecycle and operation semantics

Legal execution states are `received`, `authorized`, `deduplicated`, `queued`, `preparing`, `running`, `succeeded`, `failed`, `cancel_requested`, `cancelled`, `timed_out`, `stale`, and `not_implemented`. `unauthorized` is an audited terminal control-plane disposition rather than a runner state. The transition module rejects every edge not in its versioned table and prevents terminal-state mutation.

`status` reconciles canonical state with workflow/check facts and makes no model call. Workflow ownership uses exact repository/run ID, workflow-dispatch event, workflow path, and CountyForge run ID in the display title; the display-oriented `name` field is advisory because `run-name` is dynamic. Because GitHub may expose a terminal workflow conclusion before a polling writer observes every intermediate stage, a queued or preparing state may reconcile directly to a terminal state; backward transitions remain illegal. `cancel` verifies repository, target, active state, and the same stable workflow identity before requesting the Actions cancellation endpoint; repeated cancellation is idempotent. `retry` accepts only retry-eligible terminal runs, rejects active/successful/stale-head runs, increments attempt, preserves old evidence, and dispatches a new run.

For pull requests, executable commands receive `CountyForge / <command>` check runs. Queued/running map to `in_progress`; succeeded to `success`; failed to `failure`; cancelled to `cancelled`; timed out to `timed_out`; and not implemented to `neutral`. For this issue, that check represents trusted executor health, while the packet review verdict remains in sanitized evidence; making review verdicts a required merge gate is a later repository-policy decision. Terminal review success additionally requires valid result JSON and a present zero captured runner exit code. Unauthorized commands create no check. Check `external_id` uses the semantic key, and links point only to sanitized GitHub evidence.

### 9. Dispatch future modes through the kernel without granting capabilities

`review` maps to `review.packet-only.v1`. `plan`, `implement`, `fix`, and `validate` map to their existing exact profiles. The control plane builds a strict request and invokes the kernel; it does not preempt or emulate execution. The kernel returns `profile_not_implemented` before credential loading or mounts, and publication records a neutral `not_implemented` outcome. `status`, `cancel`, and `retry` never map to runner modes.

### 10. Scope permissions and provider secrets per phase

All workflows declare top-level read-only defaults and narrow job permissions. Intake/control receives read contents plus write comments/checks and the Actions write permission required for dispatch/cancel. Packet preparation receives read contents and artifact access but no provider secret. Provider execution receives read-only contents/actions and exactly one selected provider key on the invocation step. Publication receives comment/check write access and no provider key.

No job receives contents/package/deployment/OIDC/security-event write access. No mode receives a code-push credential. Trigger, state, request, logs, comments, checks, events, metrics, profile snapshots, and exceptions record credential names only.

### 11. Pin workflow dependencies and validate posture deterministically

Every third-party action reference uses a full commit SHA. Workflow policy tests parse YAML and reject forbidden triggers, unpinned actions, target-derived `run` expressions, broad permissions, secrets in preparation/publication, target checkout in provider jobs, target script/package execution, and simultaneous OpenAI/Sakana credential exposure.

Parser fixtures cover malicious Markdown, authorization fixtures cover all permission classes, and fake-port orchestration covers duplicates, canonical comment ownership, cancellation ownership, retry head binding, lease races/recovery, status reconciliation, check mapping, secret sanitization, and no-overwrite guarantees. Paid provider calls remain opt-in.

## Risks / Trade-offs

- **GitHub comment state is not a transactional database** -> Keep independent workflow lanes, validate marker ownership/schema, use ETag/revision conditional updates with bounded reconciliation, and use leases plus idempotent recovery.
- **GitHub Actions concurrency ordinarily keeps only one pending run** -> Refuse a second execution while an unexpired lease exists and keep cancellation/status in a separate control lane; no valid work relies on an unbounded pending queue.
- **A dispatched workflow may start before its workflow ID is written to state** -> The run claims state with its semantic key and actual `${{ github.run_id }}` before preparation; cancellation/status tolerate a short queued state with no owner ID, then fail it closed after the bounded preclaim deadline.
- **A bare target repository artifact contains untrusted Git objects** -> Never check it out, install it, import it, or execute hooks; use it only with fixed read-only Git object queries in the trusted kernel.
- **The repository `GITHUB_TOKEN` is a GitHub App installation token with broad contextual reach** -> Set explicit permissions per job, never persist credentials into target Git configuration, and keep target code out of jobs that can mutate GitHub state or access provider credentials.
- **Provider review remains a paid external call** -> Preserve explicit profile/provider selection, hard budgets, credential minimization, and opt-in live smoke tests; ordinary CI uses only fakes and contract tests.

## Migration Plan

1. Merge strict schemas, policy, adapter package, kernel two-root compatibility, workflows, tests, ADR, and documentation with only the review profile executable.
2. Keep `make prepr` on the single-root compatibility default and preserve all legacy/generic review artifacts.
3. Enable the default-branch `issue_comment: created` workflow after merge; run a controlled authorized review and unauthorized fixture before treating the command surface as operational.
4. If rollback is required, disable the three CountyForge workflows. Existing local runner commands and evidence remain usable because the kernel root defaults are backward compatible and GitHub state is additive.

## Open Questions

None for this change. Later epics must make new security decisions before enabling plan reasoning, repository writes, remediation, publication, or specialist routing; the profiles remain `not_implemented` until those changes are accepted.
