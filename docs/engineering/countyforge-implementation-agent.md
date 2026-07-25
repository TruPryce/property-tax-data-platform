# CountyForge implementation agent

`implement.workspace-write.v1` is the first code-writing CountyForge profile. It is an
isolated implementation worker, not a GitHub bot with repository credentials.

## Eligibility

`/countyforge implement <change>` is accepted only on the originating issue. The exact
kebab-case OpenSpec change must exist and validate on the trusted default branch, identify the
issue, contain no unresolved blocking decision, and have a planning PR merged by an authorized
human GitHub `User` with `admin`, `maintain`, or `write` permission. Trusted intake runs strict
OpenSpec validation and checks structured blocking markers across the complete accepted change.
Draft PRs, labels, reactions, bot comments, and
planning-agent output are not approval evidence.

## Three roots and credentials

- `contract_root`: trusted tooling, profiles, schemas, policies, prompts, and adapters at the
  captured default-branch SHA;
- `source_root`: immutable base repository content;
- `workspace_root`: ephemeral writable copy supplied to the model.

The model receives a de-Git workspace snapshot plus the frozen implementation packet, context
manifest, task plan, result schema, command policy, prompt, and bounded source snapshot through
the profile's explicit `bounded_stdin` input contract. The Codex process has no shell, unified-exec,
or undeclared file-reading tool; it returns a strict UTF-8 `file_bundle`, which trusted tooling
materializes into the host-side workspace after path confinement. It receives only the selected
provider key during model invocation.
It receives no GitHub write token, Git credentials, production credentials, Docker socket, host
home, SSH agent, Tailscale socket, or production network.

Before provider selection, trusted tooling writes and hashes a strict workspace-binding
manifest containing the repository, issue, accepted change, run, immutable base/head, Git hook
and credential-helper settings, implementation revision, exact protected mount exclusions, and
workspace content hash. The model mount contains no `.git`, `.github/workflows`, `.ai/policies`,
or `.env`; Git metadata remains available only to trusted host tooling.

## Commands and changes

Planning-generated `tasks.md` entries carry a trusted `countyforge-task` metadata comment with
the allowed paths, required validation checks, risk, and prerequisites. Intake refuses a change
with no unchecked tasks, and refuses unchecked tasks whose metadata is absent or names a command
outside the five implementation validation gates (`artifacts.check`, `docs.links`, `repo.check`,
`repo.runner-contract`, and `repo.prepr-no-ai`). Older unannotated changes must be re-planned
before implementation; accepted task checkboxes remain immutable.

The versioned command registry under `.ai/policies/` defines exact commands, phases, time and
output limits, and offline network policy for trusted validation. Non-mutating commands are
mounted read-only and snapshotted before and after execution; `prepr-no-ai` explicitly declares
only its two expected review packet files as a bounded mutation allowlist, and any other
candidate-tree change fails validation. The model
cannot start a process or use arbitrary shell payloads. Provider HTTPS egress is mediated by a trusted proxy
sidecar restricted to the selected provider endpoint; command execution remains offline.
Registry entries must choose either full-workspace `workspace_mutating` access or a
`mutation_allowlist`; combining both modes is rejected by the broker.
The broker uses a deny-by-default filesystem plus private PID/IPC/UTS namespaces, masks host
homes, temporary directories, `/run`, `/var/run`, and host sockets, mounts non-mutating candidates
read-only, and reaps descendant processes on timeout or output-limit failure. Candidate package
`src` roots are mapped explicitly at `/workspace` so stale editable virtualenv paths cannot select
trusted checkout code. OpenSpec is installed in a trusted no-secret step and exposed
through the read-only contract mount so offline validation never performs a package fetch.
The path policy rejects workflows,
CODEOWNERS, OpenSpec contracts, policies, providers, credentials, `.git`, infrastructure, data
archives, and other sensitive roots. Trusted reconciliation compares the result's task/path claims with the
workspace manifest and computes publication eligibility itself.

## Validation and publication

The model artifact is a bounded file bundle plus strict result, task, command, workspace, and
checksum evidence. A no-provider-secret validation job reconstructs a clean candidate worktree
from the trusted base while keeping the trusted tooling checkout immutable, applies only
declared files, enforces the path policy, runs repository gates, and emits a validation report.
The report is itself schema-validated and binds the issue, accepted change, base SHA, exact
implementation-result checksum, and workspace-manifest checksum before publication.
Only then does the short per-target state-lane publisher derive
`countyforge/implement/issue-<issue>-<change>-r<revision>`, create a commit, and open/update a
draft PR. The PR always requires human review; no merge, deployment, or issue closure occurs.

The validation job may execute model-authored files while running these deterministic gates. This
is an explicit v1 residual risk accepted because the job has no provider credential, no GitHub
write permission, no ambient production credentials, and registry commands run in a no-network
sandbox. The validated result remains untrusted evidence until the publisher rechecks its live
lease and applies only the declared manifest.

## Resume and cancellation

Identical accepted-change/base requests deduplicate or resume only from validated artifacts.
Changed OpenSpec content or base SHA creates a new revision and never silently overwrites a
human-edited branch. Cancellation is checked before workspace execution, validation, and Git
mutation. If publication wins a race, status reports the created branch/PR honestly.
The v1 publisher requires every accepted task to be complete with trusted command evidence;
partial task results remain evidence only and do not create a draft PR.

## Related

- [ADR-0008](../decisions/0008-isolated-openspec-to-code-implementation.md)
- [Runner kernel guide](countyforge-runner-kernel.md)
- [GitHub control-plane guide](countyforge-github-control-plane.md)
- [Issue #7 OpenSpec design](../../openspec/changes/add-isolated-openspec-to-code-agents/design.md)
