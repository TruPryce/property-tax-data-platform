## 1. Contracts and policy

- [x] 1.1 Add strict eligibility, implementation packet/context, task-plan, command-registry/event, workspace, result, validation, publication, and revision schemas.
- [x] 1.2 Promote the implementation profile and add the governed command/path/network policies without weakening review or planning profiles.
- [x] 1.3 Add capability deltas preserving the complete accepted runner, control-plane, and planning guarantees.

## 2. Eligibility and packet

- [x] 2.1 Implement accepted-plan eligibility from trusted default-branch and merged planning-PR evidence.
- [x] 2.2 Implement bounded implementation context selection, packet/manifest binding, and redaction.
- [x] 2.3 Implement task-plan derivation and strict implementation-result validation.

## 3. Isolated execution

- [x] 3.1 Add the profile-specific implementation adapter and ephemeral workspace lifecycle.
- [x] 3.2 Add the exact command broker with bounded evidence and default-deny network policy.
- [x] 3.3 Add path/change, higher-risk, disk/output, and artifact handoff enforcement.

## 4. Validation and publication

- [x] 4.1 Add trusted reconstruction and deterministic validation workflow stages.
- [x] 4.2 Add deterministic branch/commit/draft-PR publication and canonical implementation state.
- [x] 4.3 Add resume, supersession, cancellation, lease, and visible-history behavior.

## 5. Tests and documentation

- [x] 5.1 Add eligibility, injection, isolation, command, path, artifact, and policy fixtures.
- [x] 5.2 Add validation/publication, cancellation race, resume/supersession, and workflow permission tests.
- [x] 5.3 Add implement Make targets, CI policy checks, ADR, engineering guide, operations/runbook, and contributor updates.
- [x] 5.4 Run all deterministic gates and document the controlled post-merge implementation smoke; do not run paid provider calls automatically.

## 6. Retry provenance correction

- [x] 6.1 Define the bounded implementation-approval fingerprint, fresh eligibility revalidation, stable refusal dispositions, and legacy-state behavior.
- [x] 6.2 Persist implementation approval provenance and attach the freshly resolved approval envelope to eligible retries.
- [x] 6.3 Add current and legacy plan/implementation retry fixtures, packet-precondition coverage, and sanitized workflow claim diagnostics.
- [x] 6.4 Run the deterministic CountyForge, workflow-policy, OpenSpec, documentation, repository, and `prepr-no-ai` gates.

## 7. Planning retry context correction

- [x] 7.1 Bind original intake and retry provenance to the plan-command ID and define the immutable planning discussion cutoff.
- [x] 7.2 Reconstruct planning packets at that cutoff while rejecting edits or deletion within the selected original context.
- [x] 7.3 Add end-to-end retry packet fixtures and run the deterministic CountyForge, workflow-policy, OpenSpec, documentation, and `prepr-no-ai` gates.
- [x] 7.4 Reconcile the 16-comment selection contract and cover selected, older unselected, and post-cutoff mutations.

## 9. Provider-routed implementation execution

- [x] 9.1 Declare both implementation providers, their pinned images, and their credentials in `implement.workspace-write.v1`.
- [x] 9.2 Build both implementation images from a public pinned base with the pinned Codex CLI, replacing the uncredentialed-pull failure of `ghcr.io/openai/codex`.
- [x] 9.3 Add a dedicated `implementation-sakana` lane alongside `implementation-openai`, mutually exclusive on the resolved provider.
- [x] 9.4 Resolve the provider credential and endpoint in the adapter before either is exposed, and refuse an unsupported provider.
- [x] 9.5 Publish provider-qualified lane artifacts and consume only the selected provider's in trusted validation, failing closed when it is absent.
- [x] 9.6 Classify a lane that published no result as a provider infrastructure failure rather than a model failure, with a fixture from run 30691544362.

## 10. Implementation provider routing correction

- [x] 10.1 Pin `implement` to Sakana in the trusted execution policy, matching the repository's configured credential and the plan/review defaults.
- [x] 10.2 Require the selected provider credential before any provider network activity or model invocation, reading only that credential and never printing its value.
- [x] 10.3 Deliver the bounded prompt to the model container, reproduced against the real invocation shape before changing any Docker posture.
- [x] 10.4 Classify lane outcome from host-observed execution facts so a deliberately green wrapper job can never mean completed.
- [x] 10.5 Emit bounded host-observed lane evidence from both provider jobs and preserve the classified disposition in terminal state.
