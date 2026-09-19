# Review ledger — add-processing-run-values

One file per review round (`round-N.md`): the reviewer's report verbatim, one
disposition per finding, resolving commits, and the reviewer's machine block.
The directory listing is the count of rounds; the pull-request body does not
count rounds. The ledger is evidence, never a current contract: an implementer
works from `proposal.md`, `specs/**`, `design.md`, and `tasks.md` without
reading it.

This change has **one scope**, `processing-run-values`, covering every task.

## Where this vocabulary has been

These contracts were reviewed as the value half of the `processing-run`
capability inside
[PR #120](https://github.com/TruPryce/property-tax-data-platform/pull/120),
whose ledger is
[`../../add-application-port-boundary/reviews/`](../../add-application-port-boundary/reviews/).
Nothing in that history is an open finding against these values: the
`run-and-manifest` scope's unresolved item is the adapter and county write-root
decision, which belongs to the manifest and lifecycle work staying there.

What brought them out is [PR #121](https://github.com/TruPryce/property-tax-data-platform/pull/121).
The canonical load session carries a run reference and an outcome in its
signatures, could not import types that did not exist, and its first
implementation substituted local structural protocols. The review measured the
cost: an empty runtime-checkable protocol returns `True` for
`isinstance(None, …)`, `isinstance(7, …)` and `isinstance("raw-run-id", …)`, so
the substitute accepted exactly the raw persistence value the reference type
exists to exclude. These values therefore land on their own, before anything
that cites them.

## Verdict semantics

**Verdicts.** `ACCEPT` — the scope may be implemented. `REVISE` — findings must
be resolved and a further round run. A round is identified by the exact commit
it reviewed, and a finding is closed only by a later round against a later
commit, never by an author's assertion that it was fixed.

**Severities.** `P1` blocks implementation. `P2` must be resolved before the
change is archived. `P3` is recorded and may be deferred with a reason.

**What a round should look for here.** These are values, so the review is of
what they refuse. A rule that cannot be falsified is the defect class the
sibling changes have spent ten rounds removing: if a stated rule has no
reachable counterexample, say so and have it stated as a derived property
instead. The seal and the two code vocabularies are where that matters most,
because each is enforced twice — once here and once by a database constraint —
and the two must not disagree.

## Scope status

| Scope | Status | Last round | Commit |
| --- | --- | --- | --- |
| `processing-run-values` | IMPLEMENTED under recorded authorization (the plan merged as PR #123; the maintainer directed implementation of the complete value slice rather than three names, and the review of PR #121 is why it exists at all) | — | plan merged at `39bcdce` |

**Change status:** OPEN, implemented. The plan merged as PR #123 and the
maintainer directed implementation immediately, which is the recorded
authorization this scope had in place of an accepting round — noted here because
the process otherwise reads implementation without a round as an error.

Next review: the implementation, against the commit that adds it. The two places
to press hardest are the ones enforced twice, here and by a database constraint:
the evidence seal, and the two code vocabularies. If either disagrees with what
`ingestion.release_diagnostic` and `ingestion.release_notice` accept, a value
this boundary blesses will fail at the write.
