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

## 5. Review contract corrections

- [x] 5.1 Add MODIFIED deltas for the runner kernel and GitHub control-plane capabilities and document the narrow trusted publication permission.
- [x] 5.2 Preserve legacy canonical-state readability with optional planning metadata and bounded rendering defaults.
- [x] 5.3 Separate trusted planning-packet construction from target preparation and keep it secret-free.
- [x] 5.4 Add live lease publication preflight and unconditional sanitized terminal finalization.
- [x] 5.5 Resolve the Git tree base from the target commit and test commit/tree identity separately.
- [x] 5.6 Bind resolved planning model and reasoning effort to image labels and runtime configuration.
- [x] 5.7 Render valid OpenSpec delta sections, X.Y tasks, readable citations, and validate generated drafts in a temporary fixture.
- [x] 5.8 Record bounded excluded-candidate provenance and select the repository’s numbered ADR files.
- [x] 5.9 Split planning validation from the write-capable publication lane and scope contents write to `plan-publish` only.
- [x] 5.10 Redact credential-looking issue/comment literals and bind the redacted planning-context fingerprint into semantic identity before deduplication.
- [x] 5.11 Preserve complete accepted kernel/control-plane guarantees in delta specs and keep legacy canonical planning fields optional.
