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

The publication job starts from the immutable trusted default-branch SHA, validates the deterministic branch `countyforge/plan/issue-<number>-<change-name>`, runs trusted gates, and creates or updates a draft PR. No raw model patch is applied. A per-target publication preflight rereads canonical state and requires the live workflow lease immediately before Git data API writes.

## Context selection and provenance

Selection is stable and bounded: approved repository roots only, normalized paths, symlink confinement, regular files, deterministic ordering, per-file and aggregate byte/file ceilings, explicit truncation metadata, and SHA-256 hashes. GitHub comments are retrieved through the same bounded ten-page pagination contract used by the intake adapter, then deduplicated and selected in a deterministic newest-first window of 16 entries. Trusted bot-owned CountyForge status and feedback comments are removed using the immutable configured bot ID and canonical markers; user-authored marker text is retained as untrusted evidence. The triggering command comment is retained when it would otherwise fall outside that window. The packet records issue facts as untrusted source material, never as instructions. A manifest records every included source and every excluded candidate with a bounded category and reason code; packet and manifest hashes are required in the runner request.

## Result and publication

The planning result is strict JSON. It contains classification, problem/outcome, assumptions, unresolved decisions, affected capabilities, safe OpenSpec paths, task slices, acceptance criteria, risks, security/compatibility notes, validation commands, non-goals, implementation eligibility, blocked reasons, and packet citations. Provider invocation uses a separate generation schema limited to the structured-output keywords already exercised by the known-working provider contract. That schema preserves the complete required field and object shape but deliberately omits bounds, patterns, constants, and uniqueness constraints that remain enforced by the authoritative planning-result schema and trusted planning policy after generation. Both schema files are profile-owned and hash-bound; the generation schema can never authorize materialization. Trusted code validates the full result and renders templates, preserving the invariant that tasks are unmarked and production paths cannot be emitted. Executable-content scanning is tiered by field purpose. `validation_commands` names commands and carries every rule, including `eval`/`source` in command position with any argument. `task_slices` describes work in prose that quotes its commands, so the builtin tier applies to its Markdown inline-code spans rather than to the surrounding sentence, while substitution, chaining, separators, interpreters, and destructive commands still apply to the whole slice. The remaining planning fields are architecture prose and are checked only for command/parameter substitution and interpreter piping. Markdown inline code is unwrapped rather than rejected, because a county source-onboarding plan necessarily writes `` `ACCOUNT_NUM` `` and "source record". Builtin detection deliberately makes no judgement about whether an argument resembles a filename: `source script.sh` is as executable as `source ./script.sh`, and a shape heuristic would only be bypassable. Prose stays bounded by the authoritative schema, path policy, citations, output budgets, and trusted materialization rather than by shell regexes. Model-provided text is redacted for high-confidence credential literals before packet export and normalized before Markdown headings are rendered.

Canonical status remains one trusted bot comment. The current run is rendered in the primary status table; when a terminal run is replaced or retried, its complete immutable display facts are archived in bounded history and up to five prior terminal runs are rendered newest-first in `Recent runs`. Historical rows use sanitized evidence links or a bounded disposition when evidence is unavailable, so a new command never visually erases the prior result.

The initial human approval rule is an authorized maintainer merging the planning PR. Unresolved blocking decisions make implementation ineligible. A repeated semantic request deduplicates; changed context creates a revision. To avoid overwriting human edits, a changed context creates a new linked superseding draft; only an exact same-run publication is idempotently reused. Human edits are never silently overwritten.

## Publication observability and recovery

GitHub's Git data API is a multi-step sequence, so an exit code alone cannot distinguish a failure before the branch exists from one after it is visible. The publisher enters a closed stage vocabulary — `validate_result`, `validate_provenance`, `resolve_predecessor`, `create_blobs`, `load_parent_commit`, `create_tree`, `create_commit`, `create_ref`, `create_pull_request`, `complete` — records each transition to an optional progress file, and attaches the current stage and the completed prefix to every sanitized failure. The trusted workflow captures the publisher's return code instead of aborting on it, guarantees a structured document on every exit path, surfaces the sanitized disposition, stage, and status in the Actions error, and uploads both documents with `if: always()` so the evidence outlives the runner workspace.

Because a retry cannot reproduce a commit SHA but a tree is content-addressed, publication inspects the deterministic ref before creating it. An absent ref is created; a ref whose commit carries this plan's tree and the trusted parent is a prior attempt of the same plan and is resumed, reusing the draft it may already have created; any other ref is human-owned or divergent and fails closed as `planning_branch_conflict` rather than being moved.

## Failure recovery and security

Validation, binding, cancellation, provider-generation, or publication failures create no new commit/PR, preserve sanitized evidence, and transition canonical state through the existing per-target state lane. An exact provider generation sentinel is reported as `provider_generation_failed`; arbitrary malformed or policy-invalid JSON remains `validation_failed`. Cancellation before publication creates no branch or PR; a publication race is stopped by a live lease preflight and reports any already-created branch/PR honestly. Provider credentials are available only to the selected plan execution step. Publication receives no provider secret. The trusted `plan-publish` job is the only v1 workflow with contents write, narrowly authorized for deterministic planning refs and draft PRs; materialization and deterministic validation occur first in a read-only job outside the state lane. A bounded fingerprint of the redacted issue discussion participates in plan semantic identity before dispatch deduplication, so unchanged discussion deduplicates while changed discussion creates a new revision. Packet preparation recomputes that fingerprint from its exact bounded comment window and fails closed on drift; pull-request targets are refused because this executor is issue-oriented.

## Compatibility

The review profile and legacy review artifacts are unchanged. Future profiles remain fail-closed. The optional profile `generation_schema` field defaults to the authoritative `output_schema`, so existing profiles remain valid and only planning opts into a distinct provider schema. Existing request/state contracts and artifact paths remain readable.
