## Context

The runner kernel and GitHub control plane are trusted developer tooling. Issue text, comments, linked content, and target revisions are untrusted evidence. Planning therefore has two boundaries: a trusted contract/tool root and a bounded planning packet containing quoted evidence. The model produces structured intent; it does not own filesystem or Git operations.

## Architecture

`countyforge-github` classifies the issue and constructs a planning request. A trusted planning adapter selects approved files, emits a packet and context manifest, and invokes `countyforge-runner` with `plan.read-only.v1`. The plan adapter uses a profile-specific hardened container with only packet, manifest, prompt, schema, and claimed output mounts. A no-secret materialization job validates the result and renders only:

```
openspec/changes/<change-name>/
  .openspec.yaml
  proposal.md
  design.md
  tasks.md
  specs/<capability>/spec.md
```

The publication job starts from the immutable trusted default-branch SHA, validates the deterministic branch `countyforge/plan/issue-<number>-<change-name>`, runs trusted gates, and creates or updates a draft PR. No raw model patch is applied.

## Context selection and provenance

Selection is stable and bounded: approved repository roots only, normalized paths, symlink confinement, regular files, deterministic ordering, per-file and aggregate byte/file ceilings, explicit truncation metadata, and SHA-256 hashes. The packet records issue facts as untrusted source material, never as instructions. A manifest records every included and excluded candidate with category, reason, hash, bytes, and source provenance; packet and manifest hashes are required in the runner request.

## Result and publication

The planning result is strict JSON. It contains classification, problem/outcome, assumptions, unresolved decisions, affected capabilities, safe OpenSpec paths, task slices, acceptance criteria, risks, security/compatibility notes, validation commands, non-goals, implementation eligibility, blocked reasons, and packet citations. Trusted code validates those fields and renders templates, preserving the invariant that tasks are unmarked and production paths cannot be emitted.

The initial human approval rule is an authorized maintainer merging the planning PR. Unresolved blocking decisions make implementation ineligible. A repeated semantic request deduplicates; changed context creates a revision. To avoid overwriting human edits, a changed context creates a new linked superseding draft; only an exact same-run publication is idempotently reused. Human edits are never silently overwritten.

## Failure recovery and security

Validation, binding, cancellation, or publication failures create no new commit/PR, preserve sanitized evidence, and transition canonical state through the existing per-target state lane. Cancellation before publication creates no branch or PR; a publication race rereads canonical state and reports any already-created branch/PR honestly. Provider credentials are available only to the selected plan execution step. Publication receives no provider secret.

## Compatibility

The review profile and legacy review artifacts are unchanged. Future profiles remain fail-closed. Existing request/state contracts are extended only with optional, strictly validated planning metadata; existing commands and artifact paths remain readable.
