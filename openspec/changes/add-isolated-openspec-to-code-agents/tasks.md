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

## 11. Bounded implementation model input

- [x] 11.1 Declare a provider-safe `maximum_model_input_chars` in the trusted implementation profile and schema, keeping byte ceilings as defence in depth.
- [x] 11.2 Extract prompt assembly into a tested module that reserves mandatory contracts, measures characters, and adds only whole source files.
- [x] 11.3 Prioritize source context by the trusted task plan's approved paths, deterministically and with recorded included/omitted evidence.
- [x] 11.4 Fail closed before any provider activity when the budget cannot be met, without echoing prompt or source content.
- [x] 11.5 Record bounded prompt provenance and classify a budget failure as input preparation rather than a model outcome.
- [x] 11.6 Define the gated character unit as the larger of code points and UTF-16 code units.
- [x] 11.7 Refuse rather than elide any file under the task plan's approved paths.
- [x] 11.8 Disclose elided source context to the model in the prompt and report budget utilisation as evidence.
- [x] 11.9 Classify a provider rejection that the configured ceiling accepted as ceiling drift.
- [x] 11.10 Report the specific assembly failure from the Python boundary instead of inferring one from a nonzero shell exit.
- [x] 11.11 Materialize the model workspace from the same bounded set as the prompt and enforce the declared snapshot byte bound.
- [x] 11.12 Carry the adapter disposition through lane evidence into canonical terminal state.
- [x] 11.13 Capture the model command status so ceiling drift stays reachable on a nonzero provider exit, and sanitize evidence on every path.

## 12. Finishable single-shot implementation requests

- [x] 12.1 Discover the model event stream independently of the implementation result so a run that produced no result still retains evidence.
- [x] 12.2 Upload a bounded model-event summary on every outcome and record absence explicitly rather than by omission.
- [x] 12.3 Classify a corroborated `timed_out` runner result as `implementation_model_timed_out` without overriding any more specific cause.
- [x] 12.8 Require the full corroborated timeout shape, and fail closed through the existing failure paths when the envelope, mode, exit code, or summary disagree.
- [x] 12.4 Declare an operational source-selection target below the hard ceiling and record both bounds in prompt provenance.
- [x] 12.5 Order source selection so the approved package, its siblings, and its build config precede unrelated services, tools, and documentation.
- [x] 12.6 Allow approved-path material to exceed the operational target up to the hard ceiling, recording the pressure and still failing closed at the ceiling.
- [x] 12.7 Resolve implementation reasoning effort to `high` in the trusted policy and profile, with no retry at another effort and no provider fallback.
- [x] 12.9 Derive every image capability-identity dimension from the resolved request so the image producer and the runtime consumer share one source of truth.
- [x] 12.10 Refuse to build an implementation image when provider, model reference, reasoning effort, Codex version, or profile digest is absent.
