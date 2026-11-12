# Round 9 — whole-PR review — findings at 73115fa3 (P1 and both P2s resolved: this commit)

Maintainer review posted against the head that resolved round 8. The review was
not scope-bound, so each finding is filed under its scope below, per the process
in [`README.md`](README.md). Text otherwise verbatim.

## Reviewer's report (verbatim)

Reviewed exact head 73115fa3a3fa.

Findings

- P1 — activation can race a rule-version switch. The verdict is computed through
  QualityRepository, then activation occurs through a separate port. A clean v1
  verdict can be read, v2 activated, and publication admitted using the stale
  verdict. Require verdict evaluation and activation to share one consistent
  snapshot/atomic boundary, with an adversarial test. openspec/changes/add-
  application-port-boundary/specs/run-bound-quality-and-publication/spec.md:19,
  openspec/changes/add-application-port-boundary/tasks.md:81

- P2 — ambiguity scope is inconsistent. The maintainer decision, D7, and task 4.1
  reject multiple active versions of any rule, but the normative requirement limits
  this to a "blocking rule." Apply the rule to every rule_id, regardless of version
  severity. openspec/changes/add-application-port-boundary/specs/run-bound-quality-
  and-publication/spec.md:23

- P2 — new-run recovery is not directly falsified. Task 7.2 should prove v1 becomes
  stale, a new run evaluates v2, and that new run becomes clean. openspec/changes/
  add-application-port-boundary/tasks.md:101

The original same-run re-evaluation P1 is correctly fixed. However, PR #120 remains
blocked by the three prior P1s recorded in openspec/changes/add-application-port-
boundary/reviews/README.md:116, and nine task lines now exceed the 2,048-character
materializer limit. Verdict: REQUEST CHANGES.

## Filed by scope

| Finding | Scope | Disposition |
| --- | --- | --- |
| P1 activation races a rule-version switch | `quality-publication-clock` | **Resolved in this commit** |
| P2 ambiguity limited to a blocking rule | `quality-publication-clock` | **Resolved in this commit** |
| P2 new-run recovery not falsified | `surface-and-proof` | **Resolved in this commit** |
| Task lines over the 2,048-character bound | `surface-and-proof` | **Partly resolved** — see the count correction below |
| Three prior P1s from round 4 | `registry-and-discovery`, `canonical-load` ×2 | Unchanged; awaiting the maintainer dispositions round 4 records |

## Resolutions

**P1 — the admitting verdict is derived inside the activation.** The requirement
said the verdict must be clean "at the moment of activation" and left who computes
it unstated, which reads as a guarantee and was not one. It now states that the
verdict admitting an activation is derived within the same atomic boundary as the
state change, against the rule set active inside that boundary; that a verdict
obtained earlier through the quality port is advisory only, never the admission
decision; and that activation refuses where the store cannot serialize the two
rather than proceeding on a verdict it cannot vouch for. Two scenarios were added —
a rule version becoming active between a caller's clean read and its `activate()`
call, and a store that cannot serialize the pair. `design.md` records why, and the
falsification matrix carries the adversarial case with a fake that flips the active
set between the read and the call.

**P2 — the ambiguity is about the rule identifier, not the severity.** The
requirement now applies to more than one active version of *one rule*, whatever the
severity of the versions involved, matching D7, `design.md`, and task 4.1. The
narrowing was a loophole rather than a tightening: severity is a property of a
version, so two active versions disagreeing about whether the rule blocks is exactly
the case where "is this a blocking rule?" has no answer, and the verdict would have
had to pick one to decide whether to care. Its scenario now covers that disagreement
explicitly and requires the verdict to reach the error without reading either
severity.

**P2 — new-run recovery is falsified directly.** The matrix now requires proving the
whole remedy, not half of it: a run holding an evaluation at v1 becomes stale when v2
becomes active and its activation refuses; a new run evaluated against v2 is complete
and clean; and that new run activates. Proving the refusal without the recovery left
the remedy asserted rather than demonstrated.

## Correction: the task-length count

The report says nine task lines exceed 2,048 characters. Measured against the bound
as `planning.py:201` applies it — the rendered `- [ ] X.Y Title — description` line,
truncated at 2,048 — the count at `73115fa3` was **eight**, not nine. Task 4.1 is the
near miss at 1,935. The eight were 1.1 (3,616), 1.3 (2,343), 2.1 (2,083), 2.2
(3,541), 3.1 (4,521), 3.2 (3,159), 4.2 (2,499), and 7.2 (6,787). The round-5 entry
recording "seven" was correct when written; the count grew as tasks were revised.

Two are resolved here, because this round required editing both: 7.2 is now 1,234
characters and 4.2 is 1,616. The forty-odd falsification cases 7.2 enumerated were
not deleted — they moved to the falsification matrix in `design.md`, grouped by
review scope, which is both the authoritative list and, being scope-grouped,
reviewable the way this change is reviewed.

**Six remain over the bound: 1.1, 1.3, 2.1, 2.2, 3.1, 3.2.** They are not touched
here, and that is a decision the maintainer should confirm rather than one to take
silently. All six sit in `run-and-manifest`, `registry-and-discovery`, and
`canonical-load` — the three scopes holding the unresolved round-4 P1s. Shortening
them now means rewriting task text that those dispositions may change again. The
remedy is the same one applied to 7.2: the enumerated invariant lists move into
`design.md` as named contracts the task cites, which relocates the prose without
losing a single normative instruction. Say the word and it happens in this branch;
otherwise it follows the round-4 dispositions.
