# Review ledger — add-canonical-load-session

One file per review round (`round-N.md`): the reviewer's report verbatim, one
disposition per finding, resolving commits, and the reviewer's machine block.
The directory listing is the count of rounds; the pull-request body does not
count rounds. The ledger is evidence, never a current contract: an implementer
works from `proposal.md`, `specs/**`, `design.md`, and `tasks.md` without
reading it.

This change has **one scope**, `canonical-load`, covering every task. There is
no scope marker in [`../tasks.md`](../tasks.md) because there is nothing to
separate — which is itself part of the remedy, since a five-scope plan meant a
stateful protocol was reviewed in fragments while the fragments changed each
other.

## Where this scope has been

The `canonical-load` scope was reviewed as part of
[PR #120](https://github.com/TruPryce/property-tax-data-platform/pull/120)
(`add-application-port-boundary`), whose ledger is
[`../../add-application-port-boundary/reviews/`](../../add-application-port-boundary/reviews/).
That history is not repeated here, and it is not evidence about this change: the
model was rebuilt, not patched. What matters carries forward as three facts.

**Two P1s were settled by maintainer disposition and are settled here.**
Adoption names a snapshot by an **opaque locator** paired with the snapshot it
locates, disposition (a); and the parent bound is stated honestly with the
durable spill left to bootstrap 3.5, disposition (c) then (b). Both hold in this
change, and the second is why `S4` is unbounded by design and bounded in
practice by the caller's discipline and by account completion.

**Ten successive corrections found defects in the applications of those
dispositions, not in the dispositions.** Each was locally right, changed the
state space, and exposed the next interaction: adoption by grain, then by
provenance, then by bare locator; a candidate that could pair a valid locator
with the wrong snapshot; a full re-declaration that could not fit in a bounded
batch, twice; delta rules that named a bound nothing enforced; an ownership rule
that excluded the batch which completes an account; atomicity that covered the
live set but not the high-water mark, then not the staged records; a standalone
adoption that opened accounts outside every transition; a closing batch that had
to list an unbounded set. The pattern, not any one finding, is the reason this
change exists and the reason it leads with a transition table.

**Nothing from that scope is open.** The findings still open in PR #120 belong
to `run-and-manifest` (adapter and county write roots), `registry-and-discovery`
(the `PageEvidence` field list), and `quality-publication-clock` (source-as-of
durability across retried stages). None of them touches this capability.

## Verdict semantics

**Verdicts.** `ACCEPT` — the scope may be implemented. `REVISE` — findings must
be resolved and a further round run. A round is identified by the exact commit
it reviewed, and a finding is closed only by a later round against a later
commit, never by an author's assertion that it was fixed.

**Severities.** `P1` blocks implementation. `P2` must be resolved before the
change is archived. `P3` is recorded and may be deferred with a reason.

**What a round must find.** A review of this change is a review of the
transition table first: a finding that a rule is missing, contradictory, or
unenforceable must name the state component, operation, or precondition ID it
concerns. A finding that the prose disagrees with the table is a finding against
the prose. If the table itself is incomplete — a state component nothing
governs, an operation without a failure row, a precondition no party can check —
that is a `P1`, because it is the class of defect that produced ten rounds.

## Scope status

| Scope | Status | Last round | Commit |
| --- | --- | --- | --- |
| `canonical-load` | REVISE (round 1 ACCEPTed the plan; round 2 reviewed the first implementation at `d5e024f`. Its plan defects are fixed and merged as PR #122; its last open P1 — no substitute for the cited `processing-run` types — is closed by the second implementation, which imports them from the capability merged as PRs #123 and #125) | 3 | PRs #122, #126, #127, then this implementation |

**Change status:** ACCEPTED, corrected, and implemented against the corrected
plan. Round 2's three blockers are closed: the plan defects merged as PR #122,
the `processing-run` values this capability cites merged as PRs #123 and #125
and are imported rather than substituted, and the implementation is a commit of
its own on top of the accepted plan rather than one commit doing three jobs.

Two corrections the second implementation made beyond the review's list, both
found by mutation-testing rather than by reading: the `I1` invariant is asserted
**from outside the session**, because a subject checking its own invariant fails
together with the thing it checks and nothing notices; and completion is recorded
independently of the rows it persisted, so a rejected pairing is idempotent on
retry.

The `W8` story is worth keeping in view, because it is the failure mode this
whole separation exists to remove and it survived into an accepted plan. Round 1
recorded it as a note; round 2 was right that a note is not enough while the
table still listed the rule, two scenarios still demanded refusals for it, and
the fake still raised it. It is retired, and `I1` states as a derived invariant
what it was trying to state as a check.
