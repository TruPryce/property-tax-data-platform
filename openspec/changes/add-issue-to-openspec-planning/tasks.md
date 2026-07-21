## 1. OpenSpec and contracts

- [x] 1.1 Add strict planning packet, context manifest, result, publication, and revision schemas.
- [x] 1.2 Extend the runner request and profile contracts for bound planning inputs and executable plan output.
- [x] 1.3 Add the `issue-to-openspec-planning` capability requirements and acceptance scenarios.

## 2. Planning adapter

- [x] 2.1 Implement deterministic issue classification and bounded context selection.
- [x] 2.2 Implement packet/manifest provenance binding and injection-safe prompt construction.
- [x] 2.3 Implement strict planning-result validation and deterministic OpenSpec materialization.

## 3. Execution and publication

- [x] 3.1 Promote `plan.read-only.v1` and add a hardened profile-specific adapter.
- [x] 3.2 Add trusted no-secret validation and publication workflow stages.
- [x] 3.3 Implement deterministic branch/PR identity, revision/supersession, and human approval metadata.
- [x] 3.4 Preserve canonical state, cancellation, retry, lease, and status behavior.

## 4. Tests and documentation

- [x] 4.1 Add packet, bounds, path, provenance, injection, and result-contract fixtures.
- [x] 4.2 Add publication, duplicate/revision, human-edit, cancellation-race, and secret-scoping tests.
- [x] 4.3 Add plan Make targets, CI policy checks, ADR, engineering guide, runbook, and contributor documentation.
- [x] 4.4 Run all deterministic repository and CountyForge gates; record the controlled post-merge smoke procedure.
