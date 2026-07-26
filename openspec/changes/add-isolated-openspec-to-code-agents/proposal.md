## Why

Issue #7 needs the first governed code-writing profile. The existing kernel and GitHub control plane can plan and publish OpenSpec changes, but `implement.workspace-write.v1` remains unavailable and there is no trusted handoff from an accepted planning change to an isolated implementation workspace.

## What changes

- Promote `implement.workspace-write.v1` to an executable profile with an ephemeral writable workspace that is isolated from trusted tooling and GitHub publication credentials.
- Add trusted eligibility, implementation packet/context, task-plan, command-registry, workspace, result, validation, publication, and revision contracts.
- Add a governed offline command broker, strict path/change policy, task-slice evidence, and artifact checksums.
- Add a no-provider-secret validation job that reconstructs a clean worktree and a narrow trusted publication job that creates or updates a draft implementation PR.
- Extend canonical issue state with bounded implementation metadata while preserving review/planning compatibility and visible history.

## Scope and non-goals

The model may edit only an ephemeral workspace and may request only versioned repository commands. Trusted code owns eligibility, Git operations, deterministic validation, branch/PR publication, and canonical status. Network is denied to command execution by default.

This change does not implement targeted fixes, automatic merge or deployment, arbitrary shell, unrestricted internet, production integrations, self-hosted runners, cross-repository work, parallel coding agents, or automatic OpenSpec acceptance.

## Traceability

This change implements GitHub Issue #7 under parent program Issue #2. Implementation is eligible only after an authorized maintainer merges the associated planning PR into the trusted default branch and all trusted eligibility facts validate.

## Capabilities

- **ADDED** `openspec-to-code-implementation`: eligibility, isolated workspace execution, command and path policy, task reconciliation, trusted validation, draft publication, cancellation, and supersession.
- **MODIFIED** `agent-runner-kernel`: make the implementation profile executable with bound implementation inputs and strict result/provenance handling.
- **MODIFIED** `github-agent-control-plane`: add implementation eligibility, packet/validation/publication stages, implementation state metadata, and deterministic revision identity while preserving existing state lanes and permissions.
- **MODIFIED** `issue-to-openspec-planning`: expose accepted-plan provenance required by the implementation eligibility gate without changing planning approval semantics.
