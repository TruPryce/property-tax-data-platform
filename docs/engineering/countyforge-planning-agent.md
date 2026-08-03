# CountyForge planning agent

The planning agent turns an authorized structured GitHub Issue into a draft OpenSpec change.
Planning is not implementation: the model proposes bounded intent, while trusted workflow code
owns materialization, validation, Git operations, and draft-PR publication.

## Trust boundary

Issue titles, bodies, comments, labels, links, and target revisions are untrusted evidence.
The packet builder labels them explicitly and never treats them as system instructions,
commands, paths, provider settings, or authorization facts. Context is selected from approved
repository documentation and contract roots with symlink confinement, regular-file checks,
stable ordering, per-file/aggregate limits, hashes, and truncation metadata. External URLs are
references only.

The planning model receives a frozen planning packet, context manifest, trusted prompt, and a
provider-compatible generation schema. Trusted runner code then validates the generated document
against the stricter authoritative result schema and planning policy before materialization. The
model has no writable repository, GitHub token, Git credential, production credential, arbitrary
tool, or ungoverned network. Only the selected provider key is attached to the model invocation.
The review profile remains packet-only and is not broadened.

## Contracts

| Contract | Purpose |
|---|---|
| `countyforge-planning-packet.schema.json` | bounded issue/context evidence |
| `countyforge-planning-context-manifest.schema.json` | source hashes and selection provenance |
| `countyforge-plan-generation.schema.json` | provider-compatible generation shape |
| `countyforge-plan-result.schema.json` | strict model output and eligibility gate |
| `countyforge-planning-publication-manifest.schema.json` | rendered OpenSpec files and validation |
| `countyforge-planning-revision.schema.json` | deduplication/supersession lineage |

The runner request binds packet and manifest hashes to one issue, repository, immutable target
SHA, and run ID. The plan profile binds both schema names and hashes. Its generation schema does
not replace or weaken authoritative post-generation validation. The profile is read-only and
writes only run evidence.

Both the runner and the GitHub adapter then apply the same executable-content policy, scoped by
what a field is for.

| Field | Scanned for |
|---|---|
| `validation_commands` | everything, including `eval`/`source` in command position with any argument |
| `task_slices` | substitution, chaining, separators, interpreter `-c`, destructive commands; the builtin rule applies to its inline-code spans |
| all other planning fields | command/parameter substitution and interpreter piping only |

Markdown inline code is unwrapped before scanning instead of being treated as command
substitution, so a plan may write `` `ACCOUNT_NUM` ``, `` `dallas-cad-source-contract` ``, or "the
Dallas source record" without failing closed. Builtin detection makes no judgement about whether
an argument resembles a filename — `source script.sh` is rejected exactly like
`source ./script.sh` — because a shape heuristic would only be bypassable. Prose stays bounded by
the authoritative schema, path policy, citations, output budgets, and trusted materialization.

## Materialization and publication

Trusted code renders only `.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`, and one
capability `spec.md` below `openspec/changes/<change-name>/`. It rejects absolute/traversal
paths, workflow/policy/provider/secret paths, and production source paths. Tasks are unmarked.
Validation runs before branch or PR mutation:

```text
openspec validate --all --strict --no-interactive
openspec doctor
python scripts/check_doc_links.py
python scripts/check_repository_artifacts.py
```

The deterministic branch is `countyforge/plan/issue-<issue>-<change-name>` from trusted
default-branch SHA. The draft PR links the originating issue and run, lists assumptions and
unresolved decisions, states that no production code is included, and requires maintainer
approval. A merged planning PR is the initial approval evidence; reactions and labels do not
approve a plan.

## Publication stages and evidence

Publication is a multi-step sequence against GitHub's Git data API, so a bare exit code cannot
say which mutation failed. The publisher enters a closed stage vocabulary and attaches the
current stage plus the completed prefix to every sanitized failure:

```text
validate_result  validate_provenance  resolve_predecessor  create_blobs  load_parent_commit
create_tree  create_commit  create_ref  create_pull_request  complete
```

Tracking opens inside `validate_result` before the first fallible preflight — before the result
artifact is read and before the GitHub client is constructed — so an unreadable input or a missing
token is attributed like any other publication failure, and no snapshot ever names a stage outside
that list. `--publication-progress <path>` replaces each transition atomically, so a hard kill
still leaves evidence.

Nothing leaves publication unsanitized. A trusted contract check keeps its stable code; an
unexpected exception — an `OSError` reading a rendered file, an `AttributeError` from an untrusted
GitHub response — becomes `publication_internal_error` carrying the stage and only the exception
class name, never a value.

The workflow captures the publisher's return code rather than aborting on it, then reduces stdout
and that code to one document with `normalize-publication-result`:

| Publisher output at exit | Normalized disposition | Effective exit |
|---|---|---|
| complete, well-typed, `ok: true`, exit 0 | `planning_publication_completed` | 0 |
| absent or empty | `publication_result_missing` | captured code, or 5 |
| unparseable or not a single JSON object | `publication_result_malformed` | captured code, or 5 |
| `ok: false` | its own sanitized disposition | captured code, or 5 |
| `ok: true` with a nonzero exit | `publication_result_inconsistent` | captured code |
| `ok: true` missing or mistyped publication facts | `publication_result_incomplete` | 5 |

A closed-vocabulary stage surviving in the progress file is carried into the fallback, so a hard
kill still reports where it died. Step outputs are read only from the normalizer's validated
`.outputs`. `countyforge-publication.json`, `countyforge-publication-progress.json`, and
`countyforge-publication-normalized.json` all upload with `if: always()`.

Before creating the ref, publication inspects it. A retry cannot reproduce a commit SHA, but a
tree is content-addressed:

| Deterministic ref | Behavior |
|---|---|
| absent | create it |
| commit carries this plan's tree and trusted parent | resume, reusing an already-created draft |
| anything else | fail closed as `planning_branch_conflict`; the ref is never moved |

A draft's `<!-- countyforge-plan:v1 run=… context=… -->` marker only nominates a candidate.
Markers are mutable and outlive their branch, so a deduplicated success is reported only after the
ref passes that check **and** the draft's head is the verified ref — and the reported commit is
the verified SHA, not the draft's claim. A marker whose branch is absent, divergent, or
force-pushed away fails closed as `planning_draft_conflict`.

Stage evidence is validated the same way. Stages advance only to the next in the vocabulary, so
`completed` is always the exact ordered prefix; anything reordered, duplicated, truncated, or
invented is discarded. Persisted progress outranks the reported document, two valid records that
disagree fail closed as `publication_evidence_inconsistent`, and only an integer HTTP `status`
crosses into the normalized document — the rest stays in the raw artifact.

## Revisions and recovery

Identical semantic planning identity deduplicates. Changed context creates a revision. The
publisher conservatively preserves every predecessor and creates a linked superseding draft;
an exact same-run publication is idempotently reused. Cancellation before publication creates no branch or PR. A
publication race rereads canonical state and reports any already-created branch/PR honestly.
Canonical issue status is serialized through the existing per-target state lane and records
planning revision/change/PR metadata while implementation eligibility remains false.

## Local checks

Use `make countyforge-plan-check`, `make countyforge-plan-fixtures`, and
`make countyforge-plan-policy-tests`. These are deterministic and do not call a provider. Plan
image construction and paid calls remain explicitly opt-in.

## Supplying maintainer decisions

A planning run reads issue text as untrusted evidence. When a decision package is
too large for one comment, split it across several comments carrying this exact
marker as the first line:

```markdown
<!-- countyforge-plan-input:v1 issue=18 input=collin-decoder-decisions-1 part=1/4 -->

## D1 — Access NUMERIC physical contract
...
```

Then post the command on its own, in a separate comment:

```
/countyforge plan
```

Do not put the command inside a decision part: a comment containing a
`/countyforge` line is excluded from decision content.

### What the marker does and does not do

It changes **selection**, not trust. A marked comment is still untrusted
evidence; nothing in it becomes policy, and the planner cannot accept its own
decisions. What the marker buys is that parts are assembled whole rather than
clipped.

### Rules

| Rule | Behaviour when violated |
|---|---|
| The marker must match exactly, including `:v1` | The comment is ordinary evidence, not a decision part |
| The marker must **open the comment** (leading blank lines are fine) | The comment is ordinary evidence: quoting the marker in prose or inside a fenced example never selects it |
| `issue=` must match the issue being planned | Excluded, `issue_number_mismatch` |
| The author must be the actor who triggered the run | Excluded, `author_not_authorized` |
| Parts must be contiguous `1/N … N/N` with one declared total | Refused, `missing_part` / `conflicting_total` |
| No duplicate part numbers | Refused, `duplicate_part` |
| At most 12 parts, 24,000 bytes per part, 160,000 bytes total | Oversized part excluded, `comment_too_large`; total over budget refused |
| Parts must exist before the triggering command | Excluded, `posted_after_trigger` |

Nothing is ever silently truncated. Every exclusion is recorded in the context
manifest with its reason, alongside each included part's comment ID, author,
content digest, and `updated_at`.

### Supersession

Posting a second complete package with a different `input=` identifier replaces
the first: the newest package wins and the older one is recorded as
`superseded_decision_input`. Packages are never merged, so two rounds of
decisions cannot be spliced into one.

### Editing a decision after triggering a run

Don't. The packet binds each part's digest and timestamp, and publication
re-reads the comments and compares both before creating any Git object. An edit
— **including editing a comment and restoring its original text**, which leaves
the digest identical but the timestamp newer — fails the run with
`part_edited_after_trigger`. Deleting a bound part fails it too.

If you need to change a decision, let the run finish or fail, then post a new
package with a new `input=` identifier and trigger again.

## Trusted planning scope

`.ai/policies/countyforge-planning-scope.v1.json` declares, per issue and per
capability, the maximum write roots a generated plan may claim and the
cross-issue boundaries it must state. A plan may narrow that ceiling; nothing it
emits can widen it.

An issue absent from the policy collapses to the change's own OpenSpec directory.
That is deliberate: a forgotten entry produces a refusal rather than a wide
grant. Add the issue to the policy before planning work that touches a package.

## Related

- [Runner kernel](countyforge-runner-kernel.md)
- [GitHub control plane](countyforge-github-control-plane.md)
- [GitHub operations](../operations/countyforge-github-operations.md)
- [ADR-0007](../decisions/0007-issue-to-openspec-planning.md)
- [ADR-0009](../decisions/0009-maintainer-decision-input-and-planning-semantics.md)
