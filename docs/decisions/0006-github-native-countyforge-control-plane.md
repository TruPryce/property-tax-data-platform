# ADR-0006: GitHub-Native CountyForge Control Plane

## Status

Accepted on 2026-07-19 for GitHub Issue [#5](https://github.com/TruPryce/property-tax-data-platform/issues/5), parent program [#2](https://github.com/TruPryce/property-tax-data-platform/issues/2), and OpenSpec change `add-github-run-control-plane`.

## Context

ADR-0005 established a provider-neutral runner kernel and immutable capability profiles, with only the packet-only reviewer executable. CountyForge now needs a remote command surface that authenticates maintainers, binds commands to immutable issue or pull-request facts, serializes work, and publishes durable status without creating a privileged service or allowing pull-request code to control the runner.

GitHub comment bodies, issue text, branch names, and pull-request files are untrusted inputs. GitHub explicitly documents script-injection risk from event context and warns against executing untrusted code in privileged workflows. The `issue_comment` event runs from the default branch and can be restricted to `created`, making it a suitable trusted intake boundary when target code remains separate.

## Decision

GitHub Actions on GitHub-hosted ephemeral runners is the CountyForge control plane. Three pinned-action workflows separate created-comment intake, target execution, and stale-lease maintenance. The repository does not add a production VPS runner, self-hosted GitHub runner, external webhook, or database.

The control plane uses two roots:

- the **trusted contract root** is one immutable default-branch SHA containing workflows, `countyforge-github`, `countyforge-runner`, profiles, schemas, policies, provider catalog, prompts, packet builder, and container adapters;
- the **target root** is the exact untrusted issue or pull-request revision.

Target preparation runs without provider credentials. For a fork or branch PR, GitHub resolves the source repository and immutable head while the compare API resolves the immutable ancestor merge base. The job checks out source and base data separately, uses the trusted packet builder, caps the frozen artifact, and does not run target scripts, hooks, tests, Make targets, packages, binaries, or workflows. Provider execution downloads the frozen packet and a bare target Git identity; it never checks out the target worktree. The kernel loads policy only from the contract root and independently validates base-repository origin, head, base ancestry, packet hash, and packet provenance against the target root.

`tools/countyforge-github/` owns the strict Markdown parser, repository-permission authorization, immutable trigger construction, semantic idempotency, canonical state, leases, legal transitions, cancellation/retry policy, sanitized rendering, and GitHub API ports. Workflow YAML remains orchestration-only. `countyforge-runner` remains GitHub-neutral.

Authorization uses GitHub's resolved repository permission. `admin`, `maintain`, and `write` are allowed; `triage`, `read`, and `none` are denied. Exact bot/team allowlists are version-controlled and empty initially. Bot-authored issue comments are ignored so the status bot cannot recursively trigger commands.

One bot-owned canonical comment is the GitHub-native state store. A bounded hidden marker contains strict sanitized state and is accepted only from the configured immutable bot ID. Pull-request executions also receive one `CountyForge / <command>` check. User-authored copies of the marker are ignored.

Canonical comment mutation is serialized by a shared per-target job concurrency lane, `countyforge-state-<repository-id>-<target-type>-<target-number>`, with `cancel-in-progress: false`. GitHub does not honor `If-Match`/`412` on the issue-comment update endpoint, so an atomic compare-and-swap at the API is impossible; the lane provides serialization instead. Only the short state transaction joins the lane: reread canonical state, validate target ownership and the expected monotonic revision, compute one legal transition, PATCH the comment normally, then update the check after the comment succeeds. Target preparation, image build, provider execution, and artifact upload run outside the lane so `/countyforge cancel` and `/countyforge status` stay responsive during a long review. Each state carries a monotonic revision beginning at 1 that every successful mutation advances exactly once; it is application-level stale-state detection, so a writer whose reread no longer matches its expected predecessor fails closed with `state_write_conflict` rather than overwriting a newer state. Checks are updated only after the canonical comment update succeeds.

Semantic execution identity hashes repository ID, target type/number, normalized command/arguments, exact profile version, target head SHA, optional OpenSpec change, and control-plane contract version. Delivery/comment IDs are provenance only. A changed head gets a new identity; explicit retry derives a new identity from the original attempt and requires the head to remain unchanged.

Short control operations and target execution use separate non-cancelling concurrency groups so `/countyforge status` and `/countyforge cancel` can run while work is active. The canonical lease supplies the durable single-winner fact, stage heartbeats, expiry, and stale recovery. Scheduled maintenance is repository-wide and audit-only: it discovers candidates but never writes canonical state. `/countyforge status` or a later authorized command performs stale recovery inside the per-target state lane, while maintenance never starts agent work or overwrites terminal evidence.

Job permissions are explicit. Intake has only the GitHub comment/check/Actions rights required to authorize and dispatch. Preparation has read-only repository access and artifact publication, with no provider secret. OpenAI and Sakana execute in separate jobs; each references exactly one provider secret on the runner invocation step. Publication has no provider secret. No job receives contents, packages, deployments, OIDC, or security-event write access, and no mode receives a code-push credential.

Only `/countyforge review` can execute a model workflow, through `review.packet-only.v1`. Plan, implement, fix, and validate commands reach their existing profiles and publish the kernel's neutral `profile_not_implemented` result. Status, cancel, and retry are control-plane operations. Issues #6-#8 must introduce separate accepted executors before any new capability becomes available.

## Alternatives

- A universal privileged agent workflow was rejected because a pull request or runtime flag could expand the reviewer into a code-writing or publishing agent.
- `pull_request_target` with a pull-request checkout was rejected because it can combine privileged tokens or provider credentials with attacker-controlled code.
- A self-hosted runner or Akamai VPS control service was rejected because it creates durable host state and a broader credential/execution boundary than the initial control plane requires.
- PostgreSQL, Redis, S3, or another external state store was rejected because target concurrency, one canonical comment, checks, workflow metadata, artifacts, and explicit leases are sufficient for the first release.
- Comment ID or webhook delivery ID alone was rejected for idempotency because retries and repeated identical commands would create duplicate work.
- One concurrency lane was rejected because a cancellation command could wait behind the run it must stop.
- Loading workflow helpers or capability policy from the target revision was rejected because an untrusted pull request could weaken authorization or reviewer posture.

## Consequences

- The control plane becomes operational only after its workflows exist on the default branch; pull-request CI can validate it but cannot activate an `issue_comment` workflow from the feature branch.
- Canonical comment state has GitHub API and size limits, so it retains bounded current state and compact terminal history while detailed evidence remains in immutable workflow artifacts.
- GitHub Actions availability and repository token policy are operational dependencies; stale leases and reconciliation make interrupted runs visible rather than silently successful.
- A default-branch move between intake and dispatched execution fails the exact trusted-SHA check; claim recovery makes the run terminal, and an explicit retry rebuilds trusted facts without stranding the target.
- Live review remains a paid provider call. Ordinary CI exercises all control behavior with fakes and never reads a provider secret.

## Security References

- [GitHub Actions events: `issue_comment`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issue_comment)
- [GitHub Actions script-injection guidance](https://docs.github.com/en/actions/concepts/security/script-injections)
- [GitHub Actions concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- [Repository permission API](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user)
- [Commit comparison API](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
- [Issue comment API](https://docs.github.com/en/rest/issues/comments)
- [Workflow-run cancellation API](https://docs.github.com/en/rest/actions/workflow-runs)

## Related

- [Architecture decisions](README.md)
- [Control-plane engineering guide](../engineering/countyforge-github-control-plane.md)
- [GitHub operations](../operations/countyforge-github-operations.md)
- [Mode-aware runner decision](0005-mode-aware-runner-kernel.md)
- [Control-plane OpenSpec](../../openspec/changes/add-github-run-control-plane/specs/github-agent-control-plane/spec.md)
- [Issue #5](https://github.com/TruPryce/property-tax-data-platform/issues/5)
- [Parent program #2](https://github.com/TruPryce/property-tax-data-platform/issues/2)
