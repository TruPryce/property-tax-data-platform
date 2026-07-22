# CountyForge implementation agent

`implement.workspace-write.v1` is the first code-writing CountyForge profile. It is an
isolated implementation worker, not a GitHub bot with repository credentials.

## Eligibility

`/countyforge implement <change>` is accepted only on the originating issue. The exact
kebab-case OpenSpec change must exist and validate on the trusted default branch, identify the
issue, contain no unresolved blocking decision, and have a planning PR merged by an authorized
`admin`, `maintain`, or `write` maintainer. Draft PRs, labels, reactions, bot comments, and
planning-agent output are not approval evidence.

## Three roots and credentials

- `contract_root`: trusted tooling, profiles, schemas, policies, prompts, and adapters at the
  captured default-branch SHA;
- `source_root`: immutable base repository content;
- `workspace_root`: ephemeral writable copy supplied to the model.

The model receives the frozen implementation packet, context manifest, task plan, and a bounded
workspace mount. The Codex process has no shell or unified-exec tool; it returns a strict UTF-8
`file_bundle`, which trusted tooling materializes into the workspace after path confinement. It
receives only the selected provider key during model invocation.
It receives no GitHub write token, Git credentials, production credentials, Docker socket, host
home, SSH agent, Tailscale socket, or production network.

## Commands and changes

The versioned command registry under `.ai/policies/` defines exact commands, phases, time and
output limits, and offline network policy for trusted validation. The model cannot start a
process or use arbitrary shell payloads. Provider HTTPS egress is mediated by a host-side
allowlist proxy restricted to the selected provider endpoint; command execution remains offline.
The path policy rejects workflows,
CODEOWNERS, policies, providers, credentials, `.git`, infrastructure, data archives, and other
sensitive roots. Trusted reconciliation compares the result's task/path claims with the
workspace manifest and computes publication eligibility itself.

## Validation and publication

The model artifact is a bounded file bundle plus strict result, task, command, workspace, and
checksum evidence. A no-provider-secret validation job reconstructs a clean worktree from the
trusted base, applies only declared files, enforces the path policy, runs repository gates, and
emits a validation report. Only then does the short per-target state-lane publisher derive
`countyforge/implement/issue-<issue>-<change>-r<revision>`, create a commit, and open/update a
draft PR. The PR always requires human review; no merge, deployment, or issue closure occurs.

## Resume and cancellation

Identical accepted-change/base requests deduplicate or resume only from validated artifacts.
Changed OpenSpec content or base SHA creates a new revision and never silently overwrites a
human-edited branch. Cancellation is checked before workspace execution, validation, and Git
mutation. If publication wins a race, status reports the created branch/PR honestly.

## Related

- [ADR-0008](../decisions/0008-isolated-openspec-to-code-implementation.md)
- [Runner kernel guide](countyforge-runner-kernel.md)
- [GitHub control-plane guide](countyforge-github-control-plane.md)
- [Issue #7 OpenSpec design](../../openspec/changes/add-isolated-openspec-to-code-agents/design.md)
