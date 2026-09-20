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
- `canonical-load` — **moved out.** This scope became the sibling change
  `add-canonical-load-session`, with its own ledger. The rounds recorded here
  that touched it stay here as history; nothing in them is a current finding
  against either change.
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
| `run-and-manifest` | REVISE (rounds 6–7 findings resolved; round 5's write-root decision **settled** — issue 119 added to the planning scope policy with the application package, the objectstore module and tests, the six Texas county definitions, `libs/AGENTS.md`, the architecture tests and `docs/engineering/`, every one of them a path a task already declares. Round 4's source-as-of P1 **resolved** here: the instant is recorded on the acquisition's partition) | 7 | `57526347fdd6f2001a568580a37d114bf8c91f3b` |
| `registry-and-discovery` | REVISE (round 7 P1 resolved in the same commit; round 4's `PageEvidence` P2 **resolved** — the carrier has a named bounded field per fact the counties need and nowhere to put a page body, and both of this scope's oversized tasks are now under the bound) | 7 | `57526347fdd6f2001a568580a37d114bf8c91f3b` |
| `canonical-load` | MOVED OUT to `add-canonical-load-session`, where the model was rebuilt as one transition table with batch-scoped adoption. Its two round-4 P1s were settled by maintainer disposition and are settled there; ten successive corrections to the applications of those dispositions are why it is now its own change | 9 | `d147bdb` |
| `quality-publication-clock` | REVISE (round 9 P1 and P2 resolved in the same commit; round 4's source-as-of P1 **resolved** by maintainer disposition — recorded on the partition, retrieved through the run's manifest reference, no migration) | 9 | `73115fa3` |
| `surface-and-proof` | REVISE (round 9 P2 resolved; round 5: task prerequisites cite decisions that do not exist; four tasks still exceed the 2,048-character bound — 1.1, 1.3, 2.1, 2.2, all awaiting their scopes' own dispositions) | 9 | `e6a3a24+1` |

**Change status:** OPEN — no scope has an accepting round, and nothing here
should be read as one. What changed is that the three findings that were
blocking every scope are now settled, two of them by maintainer disposition:

- **Source as-of durability** (round 4 P1, `quality-publication-clock`) — the
  instant is recorded on the acquisition's **partition**, one partition being
  one logical release. It rides in the object-store manifest whose shape D18
  already versions, so no migration and no relational column. A publication
  resuming in a later process reads it through the manifest reference the run
  was started from, never by rediscovering a mutable page.
- **`PageEvidence` fields** (round 4 P2, `registry-and-discovery`) — a named
  bounded field per fact the counties need, and deliberately nowhere to put a
  page body, an HTML fragment, a script, or a credential.
- **Write roots** (round 5, `run-and-manifest`) — issue 119 now has a planning
  scope policy entry. Every path any task declares is authorized by it, and
  nothing wider: the adapter roots are three narrow ones rather than a blanket
  `libs/property-tax-adapters/`.

With every disposition landed, **no task exceeds the 2,048-character bound**.
Two of the four that did are simply gone: task 1.1's subject — the run
reference and the lossless outcome — shipped as the promoted
`processing-run-values` capability, so the task, the requirement it built, and
the three decisions behind it left this change rather than being shortened.
That edit was promised by PR #123 and deferred to this branch; until now this
change's `processing-run` delta would have re-added a requirement already
promoted, word for word.

Round 9's P1 and both P2s are resolved in the commit that records them. Round 9
also corrects the task-length count: the bound as `planning.py:201` applies it
was exceeded by **eight** tasks, not nine.

**`canonical-load` has left this change.** Everything below about it is history.
Since then the maintainer settled both `canonical-load` P1s from round 4 —
adoption by opaque locator (a), and the parent bound stated honestly with the
durable spill left to task 3.5 (c then b) — and both are applied. Ten review
rounds have since found defects in the applications themselves rather than in the
dispositions; each is recorded as a numbered correction under round 4's finding 1.
The seventh took the delta rules from four to six; the eighth made three of the six
enforceable and closed the adoption hole in rollback; the ninth bounded the
adoption the eighth had introduced and wrote the session lifecycle down; the tenth
took the unbounded list back out of the ninth's closing batch and separated a refused
batch's records from its state. That leaves
**one P1 open**, round 4's source-as-of durability in
`quality-publication-clock`, plus round 4's `PageEvidence` P2 in
`registry-and-discovery` and round 5's write-root decision in
`run-and-manifest`. Four tasks remain over the character bound: 1.1 and 1.3 in
`run-and-manifest`, 2.1 and 2.2 in `registry-and-discovery`. They are held
deliberately until those two scopes' dispositions land, which is the sequence the
round-9 reviewer recommended — shorten a task once its final contract is known.

An automated round at `eeaf972` found three defects in the dispositions
themselves, all accepted and fixed: the as-of instant had a durable location
and no boundary able to read it back; the page-evidence fields required a
stated maximum and stated none; and the discovery port's invocation shape was
still an open question a task was expected to implement. `ManifestIndex` gains
a partition lookup, the limits are numbers, and discovery observes one
jurisdiction per call.

Next review: `quality-publication-clock` for round 4's source-as-of durability,
which is now the last open P1 in this change. `canonical-load` is reviewed in its
own change and its own ledger, and this change resumes only after that capability
is accepted.
