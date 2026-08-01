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
- [x] 5.12 Archive immutable command/profile/target facts and render bounded newest-first recent-run history.
- [x] 5.13 Select planning comments newest-first, retain the triggering comment, and bind late discussion changes into context identity.
- [x] 5.14 Require successful terminal plan evidence before lease preflight or planning publication.
- [x] 5.15 Recompute and verify packet context fingerprints and refuse pull-request planning targets.
- [x] 5.16 Keep free planning fixtures offline-safe and cover plan terminal evidence and unsafe context exclusions.
- [x] 5.17 Exclude trusted CountyForge status/feedback comments from planning identity while retaining user-authored marker text.
- [x] 5.18 Replace unsupported comment sorting with bounded pagination aligned with the intake adapter and cover 100+ comments.
- [x] 5.19 Render the current run separately from five sanitized newest-first prior history rows and require complete immutable display facts for new history entries.

## 6. Provider generation compatibility correction

- [x] 6.1 Separate the provider-generation schema from the authoritative planning-result schema and bind both through the profile and runner.
- [x] 6.2 Preserve full trusted result/policy validation and classify the exact provider generation sentinel distinctly.
- [x] 6.3 Add deterministic schema-subset, provenance, sentinel, and fail-closed validation fixtures.
- [x] 6.4 Update planning engineering/operations documentation and run the no-cost planning, runner, workflow-policy, OpenSpec, documentation, and `prepr-no-ai` gates.

## 7. Planning payload policy correction

- [x] 7.1 Scope executable-content scanning by field purpose and stop rejecting Markdown inline code and mid-sentence `source`/`eval` prose.
- [x] 7.2 Keep substitution, chaining, interpreter, destructive-command, and command-position builtin detection in command and task fields.
- [x] 7.3 Add accepted-vocabulary and rejected-payload fixtures plus a minimized regression fixture from run 30492011066.
- [x] 7.4 Reject `eval`/`source` in command position with any argument, drop the bypassable filename-shape exception, and keep `task_slices` prose-compatible by scanning its inline-code spans.

## 8. Publication observability and recovery

- [x] 8.1 Record the last entered publication stage from a closed vocabulary and attach it to every sanitized failure.
- [x] 8.2 Capture the publisher return code without losing its JSON result, require a structured document on every exit path, and surface disposition, stage, and status in the Actions error.
- [x] 8.3 Upload the publication result and progress documents with `if: always()`.
- [x] 8.4 Inspect the deterministic planning ref before creating it; resume an equivalent generated ref and fail closed on a divergent one.
- [x] 8.5 Add fixtures for failures at blob, parent-commit, tree, commit, ref, and pull-request creation, and prove each preserves sanitized evidence and the correct stage.
- [x] 8.6 Open stage tracking before the port preflight, never persist a null stage, and replace progress snapshots atomically.
- [x] 8.7 Normalize publisher output and its return code in a typed adapter command; fail closed on missing, malformed, non-object, failing, inconsistent, or incomplete results and emit outputs only for a validated success.
- [x] 8.8 Model non-reproducible commit SHAs in the publication fixture so tree-and-parent recovery is proven rather than assumed.
- [x] 8.9 Decide deduplication only after ref equivalence and a matching draft head; fail closed as `planning_draft_conflict` on a stale, divergent, or force-pushed marker.
- [x] 8.10 Reserve stage and completed stages as validated exact-prefix fields, make persisted progress authoritative, fail closed on contradiction, and allow-list auxiliary detail.
- [x] 8.11 Open the publication evidence boundary in the adapter command before reading inputs or constructing the GitHub client.
- [x] 8.12 Convert contract-check and unexpected exceptions into sanitized stage-carrying publication failures, and read the pull-request response inside its own stage.

## 9. Live default-branch freshness

- [x] 9.1 Resolve the default branch and its head SHA through the trusted port whenever canonical state is rendered or reconciled, degrading to an explicit unavailable record.
- [x] 9.2 Render target SHA, default branch, current default-branch SHA, retry eligibility, and the checked timestamp, reporting `unknown` rather than guessing.
- [x] 9.3 Keep the resolved value out of canonical state, the marker, and semantic identity, and out of every authorization path.
- [x] 9.4 Refresh freshness only from in-lane canonical writers, comparing the rendered body so an unchanged state still renews its observation.
- [x] 9.5 Add fixtures for equal main, advanced main, a non-`main` default branch, lookup failure, a stale display that cannot authorize retry, and an in-lane refresh that preserves identity.
- [x] 9.6 Keep repository-wide maintenance out of canonical comments entirely; an out-of-lane patch cannot be serialized and could revert a newly claimed run.
- [x] 9.7 Require the observation instant from the current operation at every canonical write, so a freshly resolved SHA is never stamped with a run's finish time.
- [x] 9.8 Emit replacement guidance that can be issued as written, naming the recorded OpenSpec change for an implementation run.
