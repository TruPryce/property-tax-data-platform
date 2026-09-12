# Round 8 — quality-publication-clock scope — findings at 88a64a97 (resolved: this commit)

Codex review posted on PR #120 at 2026-09-07T14:18Z against the head that
resolved round 7. One finding, in one scope. Badge markup and reaction prompts
removed; text otherwise verbatim.

## Reviewer's report (verbatim)

**Codex Review** — reviewed commit `88a64a977`.

1. P1 **Make active-version reevaluation persistable**
   (`specs/run-bound-quality-and-publication/spec.md:35`) — When a new
   version of an already-evaluated blocking rule becomes active for a run,
   the prescribed re-evaluation cannot be recorded: `quality.evaluation` is
   unique on `(run_id, rule_id, subject)` without `rule_version`
   (`infra/postgres/migrations/0004_quality_results.sql:102-105`), and the
   ingestion role has INSERT but no UPDATE permission. The old-version
   evaluation therefore remains while the verdict stays permanently
   incomplete at the active version, so activation can never succeed. This
   change needs to include a compatible persistence change or revise the
   version-activation contract rather than naming re-evaluation as a
   reachable remedy.

## Dispositions

1. [P1] RESOLVED — `quality-publication-clock`. Confirmed: the evaluation
   key excludes the version, the loading role holds `SELECT, INSERT` only, no
   later migration changes either, and round 7 named re-evaluation as the
   remedy. The defect was introduced by round 7's fix.

   **Maintainer decision (2026-09-07, in the working session).** Keep the
   current-active-rule policy and change the remedy; do not adopt a
   timestamp cutoff. The contract now reads: at activation, read the
   currently active blocking rule versions; require an evaluation at each
   exact active version; a missing or stale-version evaluation makes the
   verdict incomplete; the remedy is a new processing run, never same-run
   re-evaluation; more than one active version of one rule is a named
   configuration error that fails closed; the migration and configuration
   owner switches versions atomically; the check is admission-time, and an
   already-current publication remains current, consistent with the
   persisted trigger judging only the row becoming current. No migration
   belongs in PR #120.

   Why not timestamps, recorded so the alternative is not re-proposed:
   `quality.rule.defined_at` cannot reconstruct the rule set active when a
   run was evaluated — rules can be defined inactive and activated later,
   no activation or deactivation history exists, several versions may be
   active at once, evaluation timestamps do not mark a completed quality
   cycle, and transaction timestamps do not prove when a rule became
   visible. A cutoff inferred from those columns would replace a known
   defect with history the database does not store.

   Follow-up outside this change: a migration issue for a partial unique
   constraint over active rule versions. If "rules at run time" semantics are
   ever truly required, that is a persisted rule-set snapshot or an
   activation-history design, not timestamp inference.

   Reaches: spec `run-bound-quality-and-publication` (verdict requirement
   with two new paragraphs; the activation paragraph; scenarios "A blocking
   rule was activated after the run was evaluated" rewritten, "A blocking
   rule's active version changed after the run was evaluated", "Two versions
   of one blocking rule are active", "A rule changes after a publication is
   current" added, "Every active blocking rule passed" and "An attempt is
   activated with an unevaluated blocking rule" tightened); D7 and D8;
   design (the quality section, two rejected alternatives, one risk); tasks
   4.1, 4.2, 7.2. Pinned by task 7.2: a stale-version evaluation is
   incomplete, two active versions is a named configuration error, a clean
   verdict at exact versions activates, and a current publication survives a
   later version change. Resolving commit: this commit.

## Out of scope

Nothing.

## Staleness sweep

Swept every authority for `re-evaluat`, `activated after`, `active version`,
`rules of its time`, and `admission` after the fix. The only remaining
"re-evaluation" wording is in this ledger's history (round 7) and in the
design's account of the alternative it rejects. The round-7 disposition that
named re-evaluation as the remedy stands as history and is superseded here.

## Reviewer's authoritative block (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "88a64a977e30a13a6916b0b3ef410b51ae128be2",
	"scope_id": "quality-publication-clock",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```
