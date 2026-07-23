# CountyForge GitHub Control Plane

## Purpose

GitHub Issue and pull-request comments provide the authenticated remote control surface for the CountyForge runner kernel. The accepted behavior is the [`github-agent-control-plane` OpenSpec capability](../../openspec/changes/add-github-run-control-plane/specs/github-agent-control-plane/spec.md). This guide explains the implementation and trust boundaries; [GitHub operations](../operations/countyforge-github-operations.md) owns enablement and recovery procedures.

`review.packet-only.v1`, `plan.read-only.v1`, and `implement.workspace-write.v1` execute through separate profile boundaries. Implementation requires an accepted merged planning change and publishes only a trusted draft PR; fix and validate remain fail-closed with the kernel's `profile_not_implemented` outcome.

## Command Grammar

One human-authored, newly created comment may contain exactly one top-level command line:

```text
/countyforge plan
/countyforge implement
/countyforge validate
/countyforge review
/countyforge fix
/countyforge status
/countyforge cancel
/countyforge retry
```

Execution commands may optionally declare one accepted OpenSpec change:

```text
/countyforge review --openspec-change add-github-run-control-plane
```

The parser ignores fenced and inline code, blockquotes, HTML comments, quoted prior comments, generated status content, and all bot-authored comments. Edited and deleted comment events are not subscribed. Multiple commands, Unicode lookalikes, unknown commands/arguments, prose flags, lines over 512 characters, and comment bodies over 64 KiB fail closed.

## Authorization

Authorization uses the repository permission returned by GitHub, not issue authorship, labels, team claims, comment text, or hidden markers.

| Resolved permission | Initial policy |
|---|---|
| `admin` | Allow |
| `maintain` | Allow |
| `write` | Allow |
| `triage` | Deny |
| `read` | Deny |
| `none` | Deny |

The strict [authorization policy](../../.ai/policies/countyforge-github-authorization.v1.json) supports exact bot IDs and accepts externally resolved team slugs; both allowlists are empty initially. Live v1 intake deliberately does not request organization-membership permissions, so `allowed_teams` is reserved and must remain empty until a typed membership port is accepted. Every allowed or denied intake result carries a bounded authorization object with actor login/immutable ID/type, resolved permission, policy version, outcome, and reason code. Those high-cardinality audit facts never become metric labels. Unauthorized commands create no runner request, check run, target-preparation job, dispatch, cancellation, or provider-secret job. The refusal does not reveal broader permission topology or any token.

## Two-Root Trust Model

```text
issue_comment created
        |
        v
trusted default-branch SHA       profiles / schemas / policies / packages
        |
        +---- no-secret preparation ----> untrusted base + source worktrees
        |                                      |
        |                                      +-- fixed Git reads only
        |                                      +-- trusted packet builder
        |                                      +-- no target execution
        |
        +---- frozen packet + provenance + bare target Git identity
                                               |
                                               v
                                    packet-only provider job
                                    (no target worktree checkout)
```

The kernel exposes `contract_root` and `target_root`. Profiles, schemas, provider catalog, prompts, adapters, policies, images, and evidence resolve from the trusted contract root. Origin, exact `HEAD`, base existence/ancestry, packet metadata, packet hash, and provenance resolve against the target root. A local `make prepr` invocation defaults both roots to the current repository for backward compatibility.

For pull requests, intake resolves the immutable head repository separately from the base repository and uses GitHub's compare result as the ancestor review base. Preparation checks out the source head and merge-base data separately, then combines only their Git objects before the trusted packet builder runs. This supports forks without treating the fork as the repository identity.

The provider job receives a bounded bare target repository so it can validate immutable Git objects without a worktree. The complete preparation artifact is capped at 100 MB before upload. Target-directed Git reads inherit trusted command-scope configuration that disables target hooks, fsmonitor programs, credential helpers, SSH, and ext transports, while system/global Git configuration is suppressed. Target `.github/`, `scripts/`, `Makefile`, package hooks, profiles, prompts, and schemas are never loaded or executed. The packet-preparation job has no provider secret.

## Workflow Phases

| Workflow/job | Trusted responsibility | Provider secret |
|---|---|---|
| `countyforge-command.yml` intake | Parse, resolve permission/target/tool SHA, deduplicate, create state/check, dispatch | None |
| `countyforge-run.yml` claim | Validate semantic identity, claim lease, bind actual workflow run | None |
| `countyforge-run.yml` claim recovery | Mark a pre-lease claim failure terminal so retry remains possible | None |
| `countyforge-run.yml` prepare | Fetch target data, build packet/provenance, build bare target identity, upload frozen artifact | None |
| `countyforge-run.yml` plan-packet | Fetch bounded issue context and build planning packet/manifest from the trusted root; no target checkout or package hooks | None |
| `countyforge-run.yml` mark-running | Heartbeat and publish running state | None |
| `review-sakana` | Build trusted Sakana image and invoke packet reviewer | `SAKANA_API_KEY` only on invocation |
| `review-openai` | Build trusted OpenAI image and invoke packet reviewer | `OPENAI_API_KEY` only on invocation |
| `plan-sakana` / `plan-openai` | Invoke the bounded read-only planning profile | Selected provider key only on invocation |
| `future-mode` | Invoke kernel for fix/validate and require `profile_not_implemented` | None |
| `plan-validation` | Materialize and validate the bounded planning draft outside the state lane | None |
| `plan-publish` | Verify the live planning lease, publish deterministic planning refs/draft PRs, and release terminal lease | None |
| `implementation-packet` | Verify merged-plan eligibility and build bounded packet/context/task artifacts | None |
| `implementation-openai` | Run the implementation model in an ephemeral workspace with no publication permission | `OPENAI_API_KEY` only on invocation |
| `implementation-validation` | Reconstruct a clean trusted worktree, enforce artifact/path policy, and run deterministic gates | None |
| `implementation-publish` | Verify validation and live lease, create/update a deterministic draft implementation PR, and finalize state | None |
| `publish` | Map sanitized non-planning result to canonical comment/check and release terminal lease | None |
| `countyforge-maintenance.yml` | Read-only discovery of expired leases; never mutate or dispatch | None |

All external actions are pinned to full commit SHAs. Jobs run on GitHub-hosted ephemeral runners. No workflow uses `pull_request_target`, a self-hosted runner, target-controlled shell expressions, or a repository-write credential in model/preparation jobs. Result uploads explicitly include only the declared hidden `.ai/reviews` evidence paths plus bounded non-hidden result files; workflow-policy tests lock that behavior. Only the trusted planning `plan-publish` job may use `contents: write`, and it receives no provider secret. Planning materialization and validation run in the separate read-only `plan-validation` job outside the state lane; the write-capable lane performs only the live lease check, deterministic Git data API mutation, and canonical finalization.

The read-only `plan-validation` job runs the pinned OpenSpec package from the trusted checkout. The `implementation-validation` job installs that exact package before entering the no-network command sandbox, then runs it from a clean candidate worktree; no provider secret is present. Candidate files are never overlaid onto the immutable trusted tooling checkout. The write-capable publication jobs perform only live-lease checks, deterministic Git data API mutation, and canonical finalization. Any future validator upgrade must retain the pre-provisioned, no-secret, trusted-tooling boundary.

## Trigger and State Contracts

| Contract | File |
|---|---|
| Parsed command | [countyforge-github-command.schema.json](../../.ai/schemas/countyforge-github-command.schema.json) |
| Immutable trigger | [countyforge-github-trigger.schema.json](../../.ai/schemas/countyforge-github-trigger.schema.json) |
| Authorization policy | [countyforge-github-authorization-policy.schema.json](../../.ai/schemas/countyforge-github-authorization-policy.schema.json) |
| Execution selection | [countyforge-github-execution-policy.schema.json](../../.ai/schemas/countyforge-github-execution-policy.schema.json) |
| Canonical state | [countyforge-github-state.schema.json](../../.ai/schemas/countyforge-github-state.schema.json) |
| Target lease | [countyforge-github-lease.schema.json](../../.ai/schemas/countyforge-github-lease.schema.json) |
| State transition | [countyforge-github-transition.schema.json](../../.ai/schemas/countyforge-github-transition.schema.json) |
| Control event | [countyforge-github-event.schema.json](../../.ai/schemas/countyforge-github-event.schema.json) |

Unknown properties fail. Trigger facts include immutable base-repository identity, target source-repository identity, ancestor merge-base/head SHAs, comment, actor, permission, command, trusted tool SHA, workflow, and timestamp fields. Explicit retries add the original semantic key/run ID and incremented attempt without replacing the original command facts. Triggers exclude token values, provider keys, environment dumps, complete issue/comment bodies, and target file contents. Display title and URL are separate bounded metadata.

The versioned [execution policy](../../.ai/policies/countyforge-github-execution.v1.json) owns exact command-to-profile/provider/model/effort selection. A workflow input cannot substitute another profile or expand capability.

## Idempotency and Canonical State

The execution key is SHA-256 over canonical JSON containing:

```text
contract version
repository ID
target type and number
normalized command and arguments
profile ID and version
target head SHA
OpenSpec change, when declared
```

Comment ID and delivery ID remain provenance only. Repeated semantic commands on the same head deduplicate even after completion. A changed head creates a distinct eligible key. Retry carries an explicit schema-bound envelope and derives a new key from the original key and incremented attempt; workflow claim revalidates that effective key and run ID.

One bot-authored comment contains the human status table, the current run as its primary record, up to five sanitized newest-first prior terminal runs in a `Recent runs` table, and a hidden `countyforge-status:v1` marker. The marker is decoded only when the immutable author ID equals the configured GitHub Actions bot ID, exactly one well-formed marker exists, the strict state schema passes, and its repository ID plus target type/number match the current event. Malformed, duplicated, oversized, schema-invalid, or target-mismatched trusted state fails closed; user-authored copies are ignored. Updates edit that comment; they do not create status spam. Each newly archived run preserves its run ID, command, profile/version, target SHA, idempotency key, attempt, revision, lifecycle, completion time, and evidence link; legacy history entries remain readable with bounded fallback display. Historical rows never display `Pending`: missing evidence is represented by a bounded disposition, while only the current run may be pending.

## Lifecycle, Concurrency, and Leases

```text
received -> authorized -> queued -> preparing -> running
                                                   |
                 +---------------------------------+--------------------+
                 v                 v               v                    v
             succeeded          failed        timed_out          not_implemented

queued/preparing/running -> cancel_requested -> cancelled | failed | succeeded
active + expired lease -----------------------------------------------> stale
```

Every edge is versioned and validated; terminal runs cannot return to an active state. GitHub may report a workflow conclusion before a polling writer observes every intermediate phase, so queued or preparing runs may reconcile directly to a terminal result. Short control commands use a `countyforge-control-...` concurrency group. Execution uses a separate `countyforge-run-...` group. Both disable ordinary automatic cancellation, allowing status/cancel to operate while execution is active.

All state-writing paths—intake/control, execution publication, and status reconciliation—use the same guarded publisher. Scheduled maintenance is deliberately read-only and only reports candidates; it cannot write from its repository-wide scan. The publisher re-reads the trusted bot comment immediately before updating and requires its complete validated state to equal the expected predecessor; a competing transition produces `state_write_conflict`. After the comment update, the publisher mirrors that lifecycle into the existing PR check, so status reconciliation and stale recovery cannot leave an old check in progress. Interleaving tests cover status versus claim, status versus terminal publication, cancellation versus terminal publication, and maintenance discovery versus a late heartbeat.

GitHub does not support conditional writes (`If-Match`/`412`) on the issue-comment update endpoint, so canonical-state mutations are serialized by a shared per-target job concurrency lane rather than an atomic API compare-and-swap. Every state-mutating job across the command and run surfaces joins the byte-identical group `countyforge-state-<repository-id>-<target-type>-<target-number>` with `cancel-in-progress: false`, so at most one state transaction runs for a target at a time; scheduled maintenance stays outside this lane because it is audit-only. That transaction is small and fixed: reread the canonical comment, require its complete validated state (lifecycle and monotonic `revision` included) to equal the expected predecessor, compute one legal transition, PATCH the comment normally, then update the PR check only after the comment update succeeds. Target preparation, image build, provider execution, and artifact upload run outside the lane so `/countyforge cancel` and `/countyforge status` are never blocked behind a 20–45 minute review. New state starts at revision 1 and every successful mutation advances it exactly once; the revision is application-level stale-state detection, so a serialized loser whose reread no longer matches its expected predecessor fails closed with `state_write_conflict` and never overwrites a newer terminal, retry, cancellation, or heartbeat state. The revision appears in the hidden marker/history.

The lease records workflow run/attempt, semantic key, command, target SHA, acquisition/heartbeat/expiry timestamps, and a nonce. Its initial four-hour TTL exceeds the bounded execution workflow, and stage changes renew it. Claim, heartbeat, and publication require exact ownership **and a live lease**: any publish, including a terminal one, fails closed once the lease has expired. Scheduled maintenance is repository-wide but audit-only, so it never participates in canonical writes. Recovery of an expired run is therefore performed by the `stale` reclamation path inside the per-target state lane (a new authorized command or `/countyforge status`); an owner whose lease lapsed does not race that reclaim, so a state reclaimed as `stale` — or any completed evidence — is never overwritten. A queued state with no workflow owner or lease has a separate 30-minute preclaim deadline. Check creation/publication failures fail that queue immediately; status or a later command converts an abandoned queue to retryable `failed` state with `workflow_claim_timeout`.

## Status, Cancellation, Retry, and Checks

- `status` loads only target-bound bot-owned state, preserves `cancel_requested` while GitHub still reports the workflow in progress, verifies run ID, repository, workflow event/path/display identity, reconciles matching terminal workflow/check facts, recovers an expired no-lease queue, updates the canonical comment, and starts no model call. The display-oriented workflow `name` field is advisory because GitHub also supports a dynamic `run-name`; it is not an ownership key. Status and cancel branch before mutable PR head/compare resolution, so a deleted fork branch cannot prevent recovery of an already-owned workflow.
- `cancel` verifies repository, target, workflow path/event, exact run ID, and CountyForge run ID in the display identity before calling the Actions cancellation API. Repeated cancellation after `cancel_requested` or `cancelled` is idempotent; if cancellation races with a future mode's neutral unavailable result, the operator's cancellation wins and publishes `cancelled`.
- `retry` accepts failed, cancelled, timed-out, stale, or not-implemented runs; rejects active/successful work; requires an unchanged head; increments attempt; and preserves prior evidence.
- pull-request execution checks use `CountyForge / <command>` and the semantic key as `external_id`. Success/failure/cancel/timeout map directly; not implemented and stale map to neutral. In this release the check reports trusted executor health, not the semantic `block`/`pass` review verdict; the verdict remains in sanitized evidence. Unauthorized commands create no execution check.

Publication interprets runner artifacts through tested Python policy rather than shell-only JSON selection. A review reaches `succeeded` only when its result is valid JSON with `disposition: completed` and its separately captured process exit code is present and zero. The synthetic two-root workflow test serializes the actual successful `Runner.run()` document and feeds that exact artifact plus its captured exit code through the publication resolver, preventing unnoticed seam drift. Missing, malformed, or inconsistent evidence publishes a stable sanitized failure disposition.

Comments and checks contain no raw model output, provider response, target text, token, internal path, or free-form exception.

## Post-merge GitHub smoke

The repository-native `make prepr` gate does not activate an `issue_comment` workflow from a feature branch. After these workflows are present on the default branch, enable the command workflow in a controlled setting and post `/countyforge validate` on a same-repository controlled PR. Verify authorization, one canonical comment, dispatch, lease acquisition/release, no-secret preparation, `profile_not_implemented`, neutral check, sanitized artifacts, deduplication, status, and maintenance audit discovery. Then configure only the intended provider secret and post `/countyforge review`; verify that only the selected provider job receives it, target code is never executed in that job, packet/provenance binding passes, evidence is sanitized, and the check reaches the expected conclusion.

Expected authorized refusals—no run, active work, stale or ineligible retry, an unclaimed cancellation window, insufficient planning intake, and issue-scoped review—update one bounded bot-owned feedback comment with a safe next action. They retain a nonzero machine disposition but do not require maintainers to inspect Actions logs. `/countyforge review` is PR-only because its executable profile is diff-oriented; `/countyforge plan` is issue-oriented and requires sufficient structured intake.

## CLI

All commands emit JSON and stable non-zero exits for rejected input:

```bash
countyforge-github parse-command --event event.json
countyforge-github authorize --event event.json --permission permission.json
countyforge-github build-trigger --event event.json --command command.json \
  --authorization authorization.json --target target.json \
  --trusted-tool-sha <sha> --workflow-run-id <id> --workflow-run-attempt <attempt>
countyforge-github idempotency-key --trigger trigger.json
countyforge-github transition --state state.json --transition transition.json
countyforge-github render-status --state state.json
countyforge-github build-run-request --trigger trigger.json --target-root <path>
countyforge-github reconcile --state state.json --workflow workflow.json --at <timestamp>
countyforge-github resolve-terminal-result --command review \
  --result result.json --exit-code runner-exit-code
countyforge-github check
```

Workflow-only commands `intake`, `claim-run`, `advance-run`, and `maintain` require a scoped `GITHUB_TOKEN` at the API mutation boundary. `resolve-terminal-result` is a pure artifact-policy command and loads no credential. Provider values are never accepted by this CLI.

## Validation

```bash
make countyforge-github-check
make countyforge-command-fixtures
make countyforge-workflow-policy-tests
make runner-contract-tests
```

The suites use fake GitHub ports and synthetic target data. They cover malicious Markdown, all permission classes, bot recursion, duplicate and changed-head identity, fork source identity, merge-base binding, forged markers, canonical comment reuse, lease races/expiry, no-lease dispatch timeout, check-initialization recovery, cancellation ownership, retry dispatch identity, future-mode failure, malformed/nonzero runner result evidence, two-root policy isolation, workflow permissions, action pins, shell-expression isolation, hostile target hooks/fsmonitor configuration, provider-secret scoping, bounded preparation, structured events, and low-cardinality metrics. Ordinary CI makes no GitHub mutation or paid provider call.

## Deferred Work

Issue #6 owns issue-to-OpenSpec planning agents. Issue #7 owns isolated implementation agents. Issue #8 owns review/remediation convergence. Issue #9 owns expanded durable evidence and operator observability. Issue #10 owns specialist routing. None may weaken or reuse the packet-only reviewer as a write-capable profile.

## Related

- [Documentation hub](../README.md)
- [GitHub operations](../operations/countyforge-github-operations.md)
- [Runner kernel](countyforge-runner-kernel.md)
- [Pre-PR review contract](pre-pr-review-contract.md)
- [GitHub-native control-plane ADR](../decisions/0006-github-native-countyforge-control-plane.md)
- [CountyForge GitHub package](../../tools/countyforge-github/README.md)
- [Issue #5](https://github.com/TruPryce/property-tax-data-platform/issues/5)
