# ADR-0007: Issue-to-OpenSpec planning agent

- **Status:** Accepted
- **Date:** 2026-07-21
- **Decision owners:** CountyForge developer-platform maintainers

## Context

The CountyForge kernel and GitHub control plane can authorize a `plan` command, but a
planning result must be bounded and reviewable before later implementation profiles can
consume it. Issue and comment text is untrusted evidence, while GitHub publication and
OpenSpec validation require trusted tooling.

## Decision

Promote `plan.read-only.v1` to an executable provider-policy-selected profile. A trusted
GitHub adapter classifies structured issues and builds a bounded planning packet and context
manifest. The model receives only those frozen inputs, a trusted prompt, and a strict output
schema in a hardened container with no repository write mount, Git credentials, GitHub token,
production secret, arbitrary tool, or ungoverned network access.

The model emits a strict planning result. Trusted code validates provenance and safe paths,
renders only an OpenSpec change under `openspec/changes/<change-name>/`, runs deterministic
OpenSpec/documentation/artifact gates, and uses GitHub's Git data API to create or update a
deterministic draft planning PR. The model never owns Git operations. The branch is
`countyforge/plan/issue-<number>-<change-name>` and starts at the captured trusted default
branch SHA.

Repeated semantic requests deduplicate. Changed issue discussion or context creates a
revision and a linked superseding draft; an exact same-run publication is reused idempotently.
Human edits are never silently overwritten. The initial approval contract is an
authorized maintainer merging the planning PR. Until then, and whenever blocking unresolved
decisions remain, implementation eligibility is false.

## Alternatives rejected

- **Let the model write a patch or run Git:** would combine untrusted reasoning with repository
  mutation and make prompt injection a publication capability.
- **Mount the repository read-write in the model job:** would weaken the review profile's
  packet-only trust boundary and expose workflow/package hooks.
- **Infer requirements from arbitrary links or labels:** would make untrusted content part of
  authorization or policy and remove deterministic provenance.
- **Create a universal privileged agent:** profile-specific immutable capabilities remain the
  security boundary; implementation and remediation belong to later issues.

## Consequences

Planning has additional packet, manifest, result, publication, and revision contracts and a
trusted materialization step. It can produce a draft PR without changing production code, but
the provider path remains opt-in and requires the plan image/provider secret. Issues #7--#10
can later add approval-aware implementation, targeted fixes, validation, and broader operations
without granting those capabilities to this profile.

## Compatibility

The review profile, legacy review artifacts, existing request/state contracts, leases, state
revision, cancellation, retry, and audit-only maintenance behavior remain compatible. Future
profiles remain fail-closed and no implementation command is made eligible by this decision.

## Related

- [Issue-to-OpenSpec planning OpenSpec change](../../openspec/changes/add-issue-to-openspec-planning/)
- [Runner kernel ADR](0005-mode-aware-runner-kernel.md)
- [GitHub control-plane ADR](0006-github-native-countyforge-control-plane.md)
