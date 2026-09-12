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
| `canonical-load` | REVISE (no round yet against this change; the model was rebuilt as one transition table with batch-scoped adoption, and has never been reviewed in that form) | — | — |

**Change status:** OPEN — no accepting round. Implementation of tasks 1.1
through 3.1 waits for one.

Next review: the whole change, against the commit that creates it, with the
transition table as the object of review.
