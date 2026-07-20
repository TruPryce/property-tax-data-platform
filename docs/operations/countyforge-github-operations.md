# CountyForge GitHub Operations

## Enablement Boundary

The `issue_comment` workflow becomes active only after `.github/workflows/countyforge-command.yml` exists on the repository default branch. Pull-request CI validates the workflows and control-plane package but cannot activate the new comment trigger from the feature branch.

Before enabling live review, confirm repository and organization Actions policy allows:

- GitHub-owned actions pinned by full SHA;
- the workflow's explicit issue, pull-request, check, and Actions token permissions;
- `workflow_dispatch` from the trusted command workflow; and
- the selected provider repository secret.

Do not enable a self-hosted runner or `pull_request_target`. CountyForge uses GitHub-hosted ephemeral runners only.

The v1 trigger and state URL contracts intentionally accept `https://github.com/` links only. Although workflows build links from `github.server_url`, GitHub Enterprise Server is outside this release and requires an explicit schema/version migration.

Rejected or refused commands intentionally return a nonzero intake CLI exit after posting bounded feedback. The failed Actions conclusion is an explicit audit signal for an attempted command, while ignored prose and bot-recursion events exit successfully.

## Provider Configuration

The versioned execution policy deliberately preserves the existing Sakana `fugu-ultra` reviewer at `xhigh` effort as the initial GitHub review default. Every authorized `/countyforge review` is therefore a paid high-effort call. Configure only the corresponding Actions secret:

```text
SAKANA_API_KEY
```

OpenAI review is available through the declared policy and separate immutable image. If the execution policy is deliberately changed to OpenAI, configure:

```text
OPENAI_API_KEY
```

The review workflow has separate OpenAI and Sakana jobs. Only the selected job runs, and only its provider key is attached to the packet-review invocation step. Packet preparation, future-mode execution, status publication, and maintenance receive no provider key. Do not configure production database, Airflow, S3, deployment, package-publish, SSH, or code-push credentials for CountyForge.

For initial rollout, repository write-level authorization plus per-target serialization and profile hard ceilings is the accepted paid-review spend policy. There is no repository-wide aggregate cost limiter in v1. Operators must monitor provider usage and may narrow the version-controlled authorization or execution policy before broadening access; aggregate budgeting remains a rollout risk.

The pure authorization function accepts externally resolved team slugs, but live intake does not request organization-membership permissions in v1. Keep `allowed_teams` empty until a reviewed typed membership port and least-privilege token decision are added; exact bot IDs are the supported named-identity path today.

## First Controlled Verification

After merge to the default branch:

1. Create or choose a synthetic, non-sensitive pull request owned by a maintainer.
2. Confirm an actor with `read` or `triage` receives one reused refusal comment and starts no `CountyForge run` workflow or check.
3. As a `write`, `maintain`, or `admin` actor, comment `/countyforge validate`; confirm the canonical comment and neutral `profile_not_implemented` check.
4. Repeat the same command on the unchanged head; confirm it deduplicates and creates no second execution.
5. Exercise `/countyforge status`, `/countyforge cancel` on an active synthetic run, and `/countyforge retry` on a failed unchanged-head run.
6. Run `/countyforge review` only on a pull request, when a paid call is intended and the selected provider secret/image path is ready.
7. Confirm the provider job contains no target checkout and the preparation job contains no provider secret in the Actions job view.

The feature-branch test suite is the acceptance path before merge; this controlled default-branch run is the operational activation check.

## Canonical Status and Evidence

CountyForge edits one bot-owned status comment per issue or pull request. The visible table contains command, profile, abbreviated target SHA, lifecycle state, attempt, update time, and sanitized evidence link. A hidden schema-valid marker contains bounded recovery state.

For pull requests, executable commands create one `CountyForge / <command>` check. The check and comment link to the GitHub Actions run, not a raw provider log or an externally shareable artifact URL.

Detailed sanitized run evidence is retained as a `countyforge-result-<run-id>` workflow artifact. Frozen packet preparation is a separate short-retention artifact. Existing local `.ai/reviews/` evidence remains ignored and is never committed.

## Status and Reconciliation

Use:

```text
/countyforge status
```

Status requires authorization and performs no model call. It verifies canonical bot ownership plus the exact workflow repository, ID, event, path, and CountyForge run display identity; reconciles the workflow/check; and edits the existing comment. The workflow `name` field is display-oriented and advisory because the workflow configures a dynamic `run-name`. The guarded publisher refuses a stale expected predecessor and updates the existing PR check whenever reconciliation reaches a terminal state. A queued run that has no workflow owner or lease after 30 minutes becomes retryable `failed` state. If no state exists, status returns a bounded no-run message.

The maintenance workflow runs twice per hour and can also be dispatched manually. It scans at most the newest 1,000 repository comments, fails closed if that documented bound is exhausted, marks expired active leases `stale`, fails abandoned no-lease queues after their preclaim deadline only when the canonical predecessor still matches, updates the matching check, and reports `dispatched: 0`. A malformed trusted-bot marker emits a bounded `invalid_state_detected` audit event and is skipped so it cannot suppress recovery for unrelated targets; same-target intake still fails closed on malformed state. The 1,000-comment bound is accepted for this repository's initial scale and must be revisited before broader/high-volume deployment. Maintenance never starts or retries agent work.

## Cancellation

Use:

```text
/countyforge cancel
```

Cancellation requires an active canonical run. The adapter verifies repository ID, target type/number, exact workflow run ID, workflow path, `workflow_dispatch` event, and CountyForge run ID in the display title before calling GitHub's cancellation API. The comment first moves to `cancel_requested`; status or maintenance later reconciles the actual terminal conclusion. Repeating cancel after `cancel_requested` or `cancelled` returns the existing state without another cancellation call.

If cancellation stops a review before it uploads result evidence, terminal publication may conservatively report `failed` with `invalid_result_evidence` rather than `cancelled`. This is a retryable fail-closed outcome; the canonical history still records the earlier cancellation request.

Do not force-cancel another workflow manually unless the ordinary GitHub cancellation endpoint is unresponsive and repository incident procedure authorizes it. The kernel's wall-clock budget remains the independent execution timeout.

## Retry

Use:

```text
/countyforge retry
```

Retry requires the latest run to be failed, cancelled, timed out, stale, or not implemented. The target head must equal the original head. A retry increments attempt, derives a new semantic key, and preserves prior evidence. If the head changed, issue a fresh execution command; do not retry stale review provenance.

Successful or active runs are not retry-eligible in the initial policy.

## Failure and Recovery

| Symptom | Safe response |
|---|---|
| Comment refused | Confirm the actor has repository `write`, `maintain`, or `admin`; do not use labels or issue authorship as authority. |
| No workflow dispatched | Inspect the sanitized command workflow conclusion and repository Actions permission policy; never paste tokens into comments. |
| Trusted SHA mismatch | Claim recovery marks the run failed after the default branch moves; use `/countyforge retry` so trusted facts are rebuilt without duplicating the original semantic command. |
| Claim failed before lease | Claim recovery marks the queued run failed; use `/countyforge retry` on the unchanged target. |
| Preparation failed | Confirm the fork/source head and resolved merge-base objects are fetchable and the bounded artifact is under 100 MB. Do not run target scripts to diagnose. |
| Provider job failed before a valid result | Publication records `invalid_result_evidence`, `runner_exit_code_missing`, or `runner_exit_nonzero`; inspect sanitized evidence and provider availability, then use retry only on the unchanged head. |
| Lease expired | Let maintenance or a new authorized command mark it stale; never edit the hidden marker manually. |
| Multiple canonical bot comments | Stop execution and reconcile manually through reviewed tooling; do not trust a user-authored marker. |
| Provider credential suspected in output | Treat as an incident, cancel the run, rotate the selected key, restrict/delete affected artifacts, and add a regression fixture before re-enabling review. |

## Paid Calls

`/countyforge review` is a paid provider call. Plan, implement, fix, and validate currently stop at `profile_not_implemented`; they do not consume provider credentials. Local provider smoke tests remain explicitly opt-in and are documented in the [runner kernel guide](../engineering/countyforge-runner-kernel.md).

## Related

- [Operations overview](README.md)
- [Control-plane engineering guide](../engineering/countyforge-github-control-plane.md)
- [GitHub-native control-plane ADR](../decisions/0006-github-native-countyforge-control-plane.md)
- [Runner kernel](../engineering/countyforge-runner-kernel.md)
- [Contribution workflow](../../CONTRIBUTING.md)
