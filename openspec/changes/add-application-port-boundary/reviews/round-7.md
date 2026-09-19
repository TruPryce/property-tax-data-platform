# Round 7 — three scopes (transition record) — findings at 57526347 (resolved: this commit)

Codex review requested on PR #120 at 2026-09-06T15:02Z and posted at 15:07Z
against the head that resolved round 6. Three findings in three scopes, so
this file carries three review-time blocks. Badge markup and reaction prompts
removed; text otherwise verbatim.

## Reviewer's report (verbatim)

**Codex Review** — reviewed commit `57526347f`.

1. P1 **Require complete quality evaluation before activation**
   (`specs/run-bound-quality-and-publication/spec.md:15`) — When an active
   blocking rule is never evaluated—for example, because a worker skips or
   crashes during one rule—the proposed repository records only the
   evaluations it receives and exposes no run-level completion seal.
   `PublicationAttempt.activate()` can consequently make the attempt current
   because the existing publication gate checks for recorded blocking
   failures, and an absent evaluation looks like success; this violates the
   accepted requirement that all blocking rules pass before publication. Add
   a completeness/verdict operation or require activation to verify coverage
   of the active rule set.
2. P1 **Attach source freshness to each logical release**
   (`specs/source-registry-and-discovery/spec.md:44`) — When one candidate
   yields multiple logical releases with different freshness—for example,
   current and certified partitions backed by one artifact—this shape
   provides only candidate-level source-as-of evidence, while
   `LogicalReleaseEvidence` in task 2.2 carries no such value. The later
   publication boundary therefore cannot select the correct instant for each
   release even in the same process and may publish both with one timestamp;
   carry source-as-of on each logical-release evidence value rather than only
   on the shared candidate.
3. P2 **Pin the boundary contract version in the outcome** (`tasks.md:32`) —
   When a caller constructs `ReleaseProcessingOutcome` with
   `boundary_contract_version=2`, none of the enumerated validations rejects
   it, but `ingestion.release_outcome` requires the value to equal 1, so an
   otherwise valid canonical completion aborts at persistence. Require the
   application value to equal the accepted boundary constant and add a
   falsification case for a different integer, just as the task already does
   for the evidence-seal constraints.

## Dispositions

1. [P1] RESOLVED — `quality-publication-clock`. Confirmed against migration
   `0005`: `publication.assert_current_is_validated` refuses a current
   publication only when the outcome is not accepted or
   `quality.blocking_failure` holds a row for the run, and that view is
   derived from recorded evaluations that failed, so an unevaluated blocking
   rule is invisible to it; `quality.evaluation`'s comment names the blind
   spot. The accepted `validated-data-publication` scenario requires all
   blocking rules to pass. Fix: `QualityRepository` computes a run-level
   `QualityVerdict` when asked — active blocking rules with no recorded
   evaluation at their active version, recorded blocking failures, warning
   failures; complete when nothing is unevaluated, clean when complete with
   no blocking failure — stored nowhere, so it cannot go stale when a rule is
   activated. `activate()` refuses by name and leaves the prior publication
   current unless the verdict is clean at that moment; a rule activated after
   the run was evaluated makes it incomplete, and re-evaluation is the remedy.
   This also closes the design's open question, which had left the verdict to
   the use case — a use case cannot compute coverage after a crash, because
   the boundary offered no read of what a dead worker recorded. Reaches:
   spec `run-bound-quality-and-publication` (both requirements; five new
   scenarios); D7 and D8; design (the quality section, the transactions
   diagram, the matrix, a rejected alternative, the open question removed);
   tasks 4.1, 4.2, 7.2. Pinned by task 7.2: an unevaluated active blocking
   rule makes the verdict incomplete and activation refuse; a clean verdict
   activates. Resolving commit: this commit.
2. [P1] RESOLVED — `registry-and-discovery`. Confirmed: `LogicalReleaseEvidence`
   carried identity facts only, and the as-of instant lived on the candidate,
   which promotion does not consume. Fix: each evidence carries the source
   as-of instant established for its release — a page instant for the export
   applies to every release drawn from it, a content-established instant for
   one release takes precedence, absence is recorded and the acquisition
   instant never substituted — and the publication attempt receives the
   release's own instant. The candidate keeps the source as-of evidence the
   accepted discovery requirement makes it preserve. Reaches: spec
   `source-registry-and-discovery` (requirement text; three new scenarios);
   spec `run-bound-quality-and-publication` (freshness requirement and
   scenarios); D2d and D2m; design (promotion section, matrix, a rejected
   alternative); tasks 2.2, 4.2, 7.2. Pinned by task 7.2: two evidences from
   one artifact carry their own instants and each attempt receives its own.
   Resolving commit: this commit. Round 4 finding 3, where the instant lives
   durably across independently retried stages, stays UNRESOLVED; this fix
   narrows it, because the instant is now a release-level fact carried by the
   evidence promotion consumes, so its durable home is wherever that evidence
   is retained.
3. [P2] RESOLVED — `run-and-manifest`. Confirmed: `ingestion.release_outcome`
   carries `CHECK (boundary_contract_version = 1)` and the adapters pin
   `BOUNDARY_CONTRACT_VERSION = 1` in `property_tax_adapters.release.outcome`,
   which the application may not import. Fix: the application holds its own
   `BOUNDARY_CONTRACT_VERSION` of `1`, the outcome refuses any other integer
   at construction, and task 7.1 — whose suite may import both packages —
   asserts the two constants equal so the mirror cannot drift. Reaches: spec
   `processing-run` (lossless outcome requirement; one new scenario); D10;
   design (the outcome section, the matrix); tasks 1.1, 7.1, 7.2. Pinned by
   task 7.2: an outcome carrying another version is refused. Resolving
   commit: this commit.

## Out of scope

Nothing.

## Staleness sweep

Swept every authority for the value patterns `source as-of`, `as_of`,
`verdict`, `blocking`, `activate`, and `boundary_contract_version` after the
fixes. The design's transactions diagram and the proposal's capability table
were updated with the rest; the ledger README's scope rows moved. The open
question about a computed verdict was removed from the design rather than
left beside the decision that answers it.

## Reviewer's authoritative blocks (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "57526347fdd6f2001a568580a37d114bf8c91f3b",
	"scope_id": "quality-publication-clock",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "57526347fdd6f2001a568580a37d114bf8c91f3b",
	"scope_id": "registry-and-discovery",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "57526347fdd6f2001a568580a37d114bf8c91f3b",
	"scope_id": "run-and-manifest",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 1
}
```
