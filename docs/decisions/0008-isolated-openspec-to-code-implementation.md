# ADR-0008: Isolated OpenSpec-to-code implementation

- Status: Accepted
- Date: 2026-07-22
- Issue: #7
- OpenSpec: `add-isolated-openspec-to-code-agents`

## Context

CountyForge planning produces human-reviewable OpenSpec changes. The next step needs to
implement an accepted change without turning the model into a GitHub, deployment, or
production operator. A universal privileged agent would make issue text, model output, and
repository credentials share one unsafe boundary.

## Decision

`implement.workspace-write.v1` runs only after the exact planning change is present on the
trusted default branch and its planning PR was merged by an authorized human maintainer.
The model receives a frozen packet and an ephemeral workspace copied from the immutable base;
it never receives a GitHub write token, Git credentials, production credentials, Docker socket,
or production network. The model has no process-execution tools and emits a bounded file bundle;
trusted tooling materializes it only after policy checks. Versioned command and path policies
constrain trusted validation, with command network denied by default. Provider HTTPS traffic is
restricted to a trusted allowlist proxy sidecar for the selected model endpoint.

Trusted code owns eligibility, task reconciliation, artifact validation, deterministic gates,
Git data API publication, draft PR creation, and canonical state. The model's result is
evidence, not authority to publish. Only the dedicated publication job receives code-write
permissions, and it creates a draft branch/PR rather than writing `main` or merging.

The no-provider-secret validation job may execute model-authored files through the repository's
deterministic gates. This is an explicit v1 residual risk, bounded by no GitHub write permission,
no provider or production credentials, and registry commands enforced in a no-network sandbox;
the separate publisher still revalidates the artifact and live lease before any Git mutation.

The implementation package remains under `tools/`; the runner stays GitHub-neutral. Review
and planning profiles retain their existing boundaries, while fix and validate remain
fail-closed until their own issues define executors.

## Alternatives considered

- A universal privileged agent was rejected because it couples read-only review, planning,
  implementation, and publication credentials.
- Letting the model commit or push was rejected because model output and issue evidence are
  untrusted and cannot own branch identity or protected-ref policy.
- A persistent workspace or external state database was rejected for v1; validated artifacts
  and GitHub-native state are sufficient for bounded resume and supersession.

## Consequences

Implementation is slower because each run reconstructs a workspace and trusted validation
worktree. It is auditable: packet, task, command, workspace, validation, and publication
manifests bind to one run and base SHA. A failed or cancelled run cannot publish unless the
trusted validation report and live lease both succeed. Later Issues #8–#10 can add targeted
fixes, richer approval, and operational integrations without weakening this profile.

## Related

- [Issue-to-OpenSpec planning ADR](0007-issue-to-openspec-planning.md)
- [CountyForge runner kernel](../engineering/countyforge-runner-kernel.md)
- [CountyForge GitHub control plane](../engineering/countyforge-github-control-plane.md)
- [Issue #7 OpenSpec design](../../openspec/changes/add-isolated-openspec-to-code-agents/design.md)
