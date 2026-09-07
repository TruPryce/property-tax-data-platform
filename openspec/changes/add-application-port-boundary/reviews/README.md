# Review ledger — add-application-port-boundary

One file per review round (`round-N.md`): the reviewer's report verbatim, one
disposition per finding, resolving commits, and the reviewer's machine block.
The directory listing is the count of rounds; the pull-request body does not
count rounds. The ledger is evidence, never a current contract: an implementer
works from `proposal.md`, `specs/**`, `design.md`, and `tasks.md` without
reading it.

Rounds 1–4 reconstruct the four automated reviews GitHub posted on
[PR #120](https://github.com/TruPryce/property-tax-data-platform/pull/120)
before this ledger existed, each pinned to the commit it reviewed. Round 5 is a
read-only review of the same head. None of the five was scope-bound, so each is
a **transition record** carrying one machine block per scope it touched. Round 6
was the first round whose findings fall in one scope; round 7 spans three again,
because the bots review the whole PR; round 8 is one scope and records a
maintainer decision.

## Verdict semantics

**Scopes.** [`../tasks.md`](../tasks.md) declares review scopes with
`<!-- review-scope: <id> -->` markers; each scope is ONE contiguous region and
a marker applies until the next marker or the end of the file:

- `run-and-manifest` — group 1: the run reference and lossless outcome, the
  manifest corrections and acquisition-grain storage, the manifest index, the
  run lifecycle (specs `processing-run`, `acquisition-manifest-index`).
- `registry-and-discovery` — group 2: the source registry, discovery, its
  evidence carriers, and identity promotion (spec
  `source-registry-and-discovery`).
- `canonical-load` — group 3: the batch, correlation, adoption, the load session
  and repository (spec `canonical-load-session`).
- `quality-publication-clock` — groups 4–5 (spec
  `run-bound-quality-and-publication`).
- `surface-and-proof` — groups 6–8: the public surface, the dependency and
  contract falsification tests, documentation (spec
  `application-port-boundary`, and the proof of every other scope).

A review round addresses ONE scope; findings against another scope are
recorded under "Out of scope" and do not block this scope's verdict.

**Finding dispositions** (each finding carries exactly one):

- `RESOLVED` — fixed in the spec authorities, resolving commit named.
- `ASSIGNED` — P2/P3 only: routed to a NAMED task id and the test or fixture
  that will pin it. Terminal for the review.
- `UNRESOLVED` — blocks acceptance. Where the fix needs a maintainer decision,
  the disposition says which.

**Severity.** P1: the plan as written makes an accepted requirement
unrepresentable, or an implementation from it would fail at the database or
violate a stated invariant. P2: a gap an implementer would have to invent
around. P3: documentation or consistency. Devin's yellow marker is recorded as
P2; its red marker as P1.

**Scope acceptance.** A scope reaches `ARCHITECTURE_ACCEPTED` when a
scope-bound round records, for that scope, zero UNRESOLVED P1s AND zero
UNASSIGNED P2/P3s. Implementation of an accepted scope begins immediately;
later findings against it enter as implementation fixtures, not spec rounds —
UNLESS they invalidate a stated requirement, which reopens the scope. A
zero-finding scope inside an unscoped round is not an acceptance.

**Authorization without acceptance.** A scope may be implemented before a
clean acceptance round ONLY on an explicit, recorded decision: its status row
reads `AUTHORIZED_WITHOUT_ACCEPTANCE (<who>, <date>: <why>)`.

**Standing practice.** A correction reaches EVERY authority (proposal, design,
specs, tasks) in the same commit, and the commit is gated on the edit script's
exit status — two rounds on this change left the task file behind a spec edit
because a script aborted between the two writes. After every fix, the whole
change is swept by each finding's VALUE pattern (type names, handle rules,
component lists), not by its cited lines. The `design.md` cross-spec contract
matrix is the first thing swept.

**Machine block.** Each round file ends with the reviewer's block:

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "<40-hex>",
	"scope_id": "<scope>",
	"verdict": "ARCHITECTURE_ACCEPTED | REVISE | ARCHITECTURE_REJECTED",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 0
}
```

Counts are what the reviewer found at the reviewed commit, before
dispositions. No checker validates the block in this repository yet; the
vocabulary is the one `governed-change-v1` and `governed-spec-driven-v2` share,
so a guard can be adopted later without rewriting the ledger.
The `reviewed_commit` line is a git SHA, not a credential; `.secrets.baseline`
carries a line filter for exactly that key shape so `make secrets` does not
flag every round file, and the block stays valid JSON with no inline pragma.

**Merge gate for this planning change.** The pull request merges when every
scope's latest round is `ARCHITECTURE_ACCEPTED`, strict OpenSpec validation and
`make spec` pass, and the PR body links here instead of narrating closure.
Implementation follows per scope, from the accepted commit, and bootstrap 2.3
stays unchecked until the separate reconciliation verifies it by substance.

**Review prompt.** One prompt reviews one scope: "Review the OpenSpec change
`add-application-port-boundary` at commit `<sha>` for scope `<scope_id>` only
(the tasks between that scope's markers, the specs and design decisions they
cite, and the cross-spec contract matrix rows they own). Report P1/P2/P3
findings with file:line, then the machine block." The GitHub review bots cannot
be scoped; when a bot reviews the whole PR, paste its report verbatim into the
next round file and file each finding under its scope.

## Scope status

| Scope                       | Status                                                                                                                           | Last round | Commit                                     |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------ |
| `run-and-manifest`          | REVISE (rounds 6–7 findings resolved; round 5: adapter and county write roots have no scope-policy entry — decision needed)         | 7          | `57526347fdd6f2001a568580a37d114bf8c91f3b` |
| `registry-and-discovery`    | REVISE (round 7 P1 resolved in the same commit; round 4: `PageEvidence` fields unspecified — UNRESOLVED)                          | 7          | `57526347fdd6f2001a568580a37d114bf8c91f3b` |
| `canonical-load`            | REVISE (round 4: adoption is ambiguous at a non-unique grain; oversized parent sets have no bounded path — two P1s UNRESOLVED)    | 5          | `67107035918a9db72ee6581c35f3c3a77f3c76c9` |
| `quality-publication-clock` | REVISE (round 9 P1 and P2 resolved in the same commit; round 4: the source as-of instant is not durable across retried stages — UNRESOLVED) | 9 | `73115fa3a3fa` |
| `surface-and-proof` | REVISE (round 9 P2 resolved in the same commit; round 5: task prerequisites cite decisions that do not exist; six tasks still exceed the 2,048-character bound — 1.1, 1.3, 2.1, 2.2, 3.1, 3.2) | 9 | `73115fa3a3fa` |

**Change status:** OPEN — no scope has an accepting round; three P1s (all in
round 4) and several P2/P3s are unresolved. Do not infer overall completion
from the PR body or from any single scope.

Round 9's P1 and both P2s are resolved in the commit that records them; they do
not change that status, because the three round-4 P1s stand and no scope has an
accepting round. Round 9 also corrects the task-length count: the bound as
`planning.py:201` applies it was exceeded by **eight** tasks, not nine, and two
of those are resolved there, leaving six.

Next review: `canonical-load` with the scope-bound prompt above, after the
maintainer decides the two round-4 P1 dispositions recorded in
[`round-4.md`](round-4.md). One further decision now waits beside them, recorded
in [`round-9.md`](round-9.md): whether the six remaining oversized tasks are
shortened now or after those dispositions, since all six sit in the scopes those
dispositions will change.
