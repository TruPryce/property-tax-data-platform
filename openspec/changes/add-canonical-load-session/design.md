# Design: Canonical Load Session

## Context

This change carries one capability out of `add-application-port-boundary`, where it was one
scope of five. It is separated because it is the only one of the five that is a **stateful
transactional protocol** rather than a set of value contracts, and because ten successive review
rounds demonstrated what happens when such a protocol is specified in prose: each correction was
locally right, changed the state space, and exposed the next interaction. Two of the last three
findings were defects introduced by the fix before them.

The diagnosis is not that the wording was poor. It is that the state machine was never closed as
one model, so no reader — reviewer or author — could tell whether a rule was complete.

**The transition table therefore lives in the capability spec, not here.** The spec is what
survives promotion into `openspec/specs/canonical-load-session/`; this design is archived with the
change. A table that is authoritative but archived would leave the promoted contract pointing at
a document the reader no longer has, and a relative link that no longer resolves — so the spec
carries the state components `S0`–`S6`, opening and resolution, the operations, the precondition
IDs `B1`–`B10`, `W1`–`W12`, `C1`–`C2`, `A1`, `G1`, and the transitions of each operation.

What follows is the reasoning behind that table: why each shape was chosen, what was tried and
rejected, and what the falsification suite must prove. It restates no transition, and where it
appears to disagree with the spec, the spec is right and this document is the defect.

## Why adoption is batch-scoped

A child can legitimately name a parent that an *earlier* load persisted: the accepted
`canonical-silver-persistence` contract permits a child from a second artifact of the same
release and forbids forcing it onto its parent's load. Resubmitting the parent would manufacture
a second snapshot, so the boundary has to offer some way to name an existing one.

An earlier draft made adoption a **session operation** — `adopt(candidate)` returning a handle.
That single choice was responsible for most of the lifecycle's complexity, and for three review
findings in a row:

- it minted a handle outside any batch, so `S6` moved outside a transition and nothing said
  whether a later refused write moved it back;
- it opened an account outside any batch, which is an unbounded way around the one-open-account
  rule the whole correlation model rests on — a caller could adopt into a hundred accounts before
  writing anything;
- it needed its own atomicity story for failure, its own lifetime rule for the handle, and its
  own entry in the ownership rule's enumeration of open accounts.

Adoption is therefore carried **by the batch**. A batch declares the adoptions it makes; the
handles they bind are introduced by that batch, live and die by exactly the rules any introduced
handle follows, and the whole thing takes effect or does not with the batch. `W4` is the only
precondition adoption adds, `B9` the only intrinsic one, and the machine has three operations
instead of four. Nothing else in the table mentions adoption, which is the point.

The binding has to be carried, not inferred. A batch declaring "these adoptions and these
handles" as two parallel sequences would make the pairing depend on order, and a reader of one
batch could not say which handle denotes which snapshot without counting. `AdoptedParent` pairs
one candidate with the one handle bound to it, so the binding is a value. That handle is then
**introduced by the batch** for every rule in the table — `B2`, `W3`, retention, release,
ownership, and the success transition — which is what keeps adoption from acquiring a second
lifetime.

The candidate itself is unchanged from the accepted argument: an **opaque locator** paired with
the `AccountSnapshot` it locates. Never the grain — the accepted contract makes it deliberately
non-unique — and never provenance alone, which two snapshots of one account and release can
share while differing in a composed situs or legal value. The pair is verified because a caller
can build one by hand: `W4` refuses a valid locator carrying a snapshot it does not locate,
which would otherwise bind a handle to an object the locator never named. Candidates are offered
lazily, as an iterator, because no accepted contract bounds how many an account and release have.

Deeper observations remain unadoptable. The canonical model gives them no identity to name them
by, and inventing one would be the natural key this boundary forbids; children of such a parent
are written in the same session as the parent.

## Why correlation is a delta and not a declaration

A record whose parent was written in an earlier batch names it by a session-local handle. The
handle is neither domain nor persistence identity, appears in no stored row, and stops resolving
when its account completes.

The bound is the whole point, and two shapes fail it:

- **No declaration at all.** One continuing account bounds nothing by itself: an account with an
  unbounded number of owner associations whose allocations arrive in later batches keeps every
  association's mapping live until the account completes.
- **A complete re-declaration each batch.** The declaration must itself fit inside a bounded
  batch, so it caps `S4` at one batch's worth, and an account with more parents than that could
  never finish. This is the arithmetic that caught three separate drafts, including a "closing
  batch listing what remains" — a bounded carrier cannot hold an unbounded list, whatever it is
  called.

So a batch carries **bounded deltas**: the handles it newly requires to outlive it, and those it
no longer requires. `S4` accumulates them. Every declaration is bounded because `W2` bounds it;
`S4` is bounded by the caller's own retain-and-release discipline and by account completion,
which releases everything that account still holds. Where one continuing account's `S4` exceeds
memory, an implementation may hold it durably — bootstrap 3.5's obligation, and the port names no
mechanism.

`max_batch_entries` is what makes "bounded" a property rather than an adjective. It is an integer
of at least one and not a boolean — `True` is an `int` in Python, and the guard this repository
already writes as `isinstance(value, bool) or not isinstance(value, int)` exists for exactly this
— it counts entries plus adoptions plus each delta's values, it does not change while the session
is open, and a caller reads it to size what it builds rather than discovering the bound by
refusal.

Handles increase **strictly**, and `S6` retains the greatest yet introduced: one integer, so the
bound is untouched. Without it, session-wide uniqueness would be unenforceable, because
completing an account releases its mappings and a later account could mint the same value,
silently retargeting a late record.

## Completion, and why it is one unit of work

The session owns the relationship between the processing run, its accepted or rejected outcome,
and the canonical load, so that the outcome and the load become durable together. No arrangement
of the operations may require an implementation to commit them separately, because a run whose
outcome is durable and whose records are not is a run nothing can interpret afterwards.

Retry is keyed by the pairing of a canonical release with the processing run that loaded it.
Completing a pairing that already completed persists nothing further and returns a bounded,
machine-readable result saying so, rather than an error a caller must interpret. Two distinct
runs loading one release are two loads, and the second is not a retry of the first.

## What the boundary refuses to decide

No natural key, uniqueness rule, or deduplication rule over observed canonical values. Records
the canonical model admits are not discarded, merged, or rejected on the basis of their values —
several snapshots at one account and release grain, several children of one parent, children
arriving from another load of the same release, all retained.

## The falsification matrix

This is the authoritative list of what the falsification suite proves. Every case is a row of the
transition table or a precondition ID, and a case that cannot be named in those terms is a case
this change does not have.

**The state machine.**

- A session opens in the initial state: `S1` open, `S2` none, `S3` and `S4` empty, `S6` with no
  handle yet introduced, and `S0` already carrying the release, run, outcome, and maximum. The
  first handle a session ever sees is accepted on its own merits.
- Each of B1–B10 refuses **at construction**, without a session. `B6` is falsified by an entry
  naming its own handle as its parent, and the batch accepting a parent handle it does not
  introduce is proven alongside it, since a rule that refused those would forbid naming a parent
  from an earlier batch at all.
- Each of W1–W12 refuses **on write**, with a session that has the history the check needs.
- `W8` is falsified by a batch that carries no entry and no adoption of an account, does not
  inherit it as `S2`, and names one of its handles in `release`: refused, because an account is
  open in a batch by what the batch **carries** and never by what its deltas name. A rule that
  took the delta as evidence for the delta would permit exactly the retargeting it forbids.
- `W10` has three satisfiers and each is exercised: a batch that touches `S2`'s account, one that
  names it as continuing, and one that names it as closing while carrying nothing at all. Its
  violation is a batch that does none of the three, which is refused rather than allowed to close
  the account by silence. `B10` refuses a batch naming one account as both; `W12` refuses a
  closing declaration for an account that is not `S2`.
- An account whose live handles outnumber `max_batch_entries` is closed by an **empty** batch that
  declares it closing — the case that has to work, since such an account can be closed by carrying
  nothing else.
- `W11` is falsified by a batch naming as continuing an account it neither **carries** nor
  inherits, and satisfied by one that carries `S2` onward while carrying none of it — decided
  against accounts open in the batch, never touched ones, for the same reason `W8` is, and the
  session's because a batch that knows only itself cannot tell `S2` from an account nothing has
  begun.
- After every one of those refusals, S1–S6 are byte-for-byte what they were: nothing staged,
  `S6` not advanced — proven by a corrected retry reusing the rejected batch's handles — `S2`
  unmoved, no mapping added or removed, and the session still `OPEN`.
- A refused batch contributes no records: after a refusal, a correction, and a completion, the
  load holds the accepted batches' records and nothing from the rejected attempt.
- `write` success applies the four assignments together and at the batch boundary: a handle the
  batch releases resolves for every record of that batch, including records positioned after the
  release, and is gone for the next.
- A handle introduced and not retained never enters `S4` and dies with its batch.
- `commit` with C2 unmet is refused; the account is then closed by an empty batch declaring it
  closing, and the commit succeeds.
- `commit` takes the first branch that applies, in the order the table states: **already
  complete** persists nothing at all, not even the outcome, and is proven with a retried pairing
  whose outcome is *rejected* — both conditions hold and only the first may apply, since
  overwriting the earlier outcome would make the retry key a lie; **rejected** records the outcome
  and discards the records, proven by staging batches under a rejected outcome and finding zero
  canonical records; **accepted** makes records and outcome durable together.
- Two sessions completing one pairing concurrently yield exactly one load, the other reporting
  `already_complete` — the decision and the durable write being one atomic step, which a fake that
  interleaves them must fail.
- The signatures hold: `write` returns `None` and raises on refusal, `commit` returns a completion
  rather than raising on an already-complete pairing, `abort` returns `None`, `max_batch_entries`
  is read-only, `__enter__` returns the session, and `__exit__` is annotated `-> None`.
- Suppression is falsified at **runtime**, not by reading the annotation: an exception raised
  inside the block reaches the caller and leaves zero records of that session, and a fake that
  returns truthy from `__exit__` is caught because the exception never arrives.
- `W10` is exercised through each of its three satisfiers and its violation, including the case
  satisfied only by a delta — which is why it is decided against `S4` as well as `S2`, since only
  `S4` says which account a released handle belongs to.
- An abort, a failed completion, and an abandoned session each leave an earlier session's durable
  records untouched — including the load a retrying session would have found already complete.
- Opening is refused when `S0` cannot be completed, and a refused open leaves no session to abort.
  Two sessions for one release and run both open, and the retry key decides at completion.
  Resolving a locator is the repository's, scoped to `S0`'s release, and is exposed as no
  operation of its own.
- A failed `commit` leaves `S1 = OPEN` and everything else unchanged, and a subsequent `abort`
  still leaves zero records.
- `abort` succeeds with an account open. Every operation offered after a terminal one is refused.

**Correlation.**

- `max_batch_entries` is rejected when zero, negative, non-integer, or **a boolean**; it is
  readable before a batch is built; a session reporting a different value later breaks the
  contract. A `CorrelationHandle` that is a boolean is refused for the same reason.
- A handle duplicating one already live, one not exceeding `S6`, a parent never introduced, a
  parent whose account has completed, and a parent handle denoting a record other than the one
  the child actually holds are each refused by the **session** — proving the B/W split rather
  than assuming it.
- A batch naming a parent it does not itself contain is well-formed on its own.
- An account spanning several batches keeps its parents resolvable without re-declaring them,
  and one whose live handles outnumber what a single batch could have listed still completes.

**Adoption.**

- An `AdoptedParent` states its binding: the pairing survives reordering the batch's adoptions and
  its entries, and nothing infers a handle from position.
- An adopted handle behaves as an introduced one under `B2`, `W3`, retention, release, and the
  success transition — proven by exercising each of those rules on an adopted handle, not by
  asserting the sentence.
- Adoption by candidate yields a usable parent handle and creates no observation; the child keeps
  its own load and artifact lineage.
- W4 refuses a locator resolving to no snapshot of the release being loaded, one belonging to
  another release, and a candidate whose locator resolves to a snapshot other than the one it
  carries. B9 refuses a candidate whose carried snapshot is not the object an in-batch child
  holds.
- Two snapshots of one account and release sharing a provenance and differing only in a composed
  situs or legal value are offered as distinct candidates, and adopting one attaches the child to
  that observation and not the other.
- A refused batch carrying adoptions adopts nothing: the same empty failure row as any other
  refusal, which is the whole reason adoption is batch-scoped.
- Candidates are drawn lazily; an account with more candidates than a caller wants in memory is
  consumed one at a time.
- A parent that is not an account snapshot is not adoptable.

**Completion and the no-key rule.**

- The outcome and the load become durable together; a rejected outcome commits zero records.
- Completing an already-completed release-and-run pairing persists nothing and reports
  `already_complete`; a second distinct run reports a new load and both loads are retained.
- Several snapshots at one grain, several children of one parent, and children from another load
  of the same release are all retained and none collapsed.
- **Two entries of one batch carrying equal canonical records both persist.** No precondition may
  be read as a deduplication rule: `B1` governs an entry's shape and `B2` a handle's uniqueness,
  and neither compares one canonical record with another.

## Alternatives rejected

- **`adopt()` as a session operation.** Rejected above: it moved `S6` and `S2` outside any
  transition and cost three review findings.
- **A separate operation declaring an account complete.** One fact with two sources. `continuing`
  already carries it.
- **A full per-batch declaration of what must stay resolvable.** Bounded by the batch, so it caps
  `S4` at one batch's worth.
- **A closing batch that releases what remains.** The same arithmetic, arriving through the door
  marked "closing".
- **Tracking `live` separately from `mappings`.** Two structures that can disagree about which
  handles resolve.
- **A batch rule requiring its canonical records to be distinct.** It reads as tidiness and is a
  deduplication rule over observed values, which the accepted persistence contract forbids and
  which this boundary exists not to impose.
- **Keeping the transition table in this design.** It would be authoritative and archived, leaving
  the promoted spec citing a document the reader no longer has, through a relative link that no
  longer resolves.
- **Letting a batch close the open account by saying nothing about it.** Silence cannot be told
  from forgetting, and the alternative — inferring the close from a touch — leaves an account with
  more live handles than a batch can carry impossible to close at all. The `closing` declaration
  costs one optional field and makes both cases explicit.
- **One completion transition for every disposition.** It would persist the staged records of a
  run whose outcome was rejected, which nothing downstream would catch.
- **Defining "the accounts a batch may edit" in terms of what the batch touches.** Touching
  includes naming a handle in a delta, so the rule would take the delta as the evidence for the
  delta: any account could be made the batch's business by releasing one of its handles. Accounts
  open in a batch are settled by what it *carries*, records alone.
- **Letting `write` return a refusal instead of raising.** A caller that discards the result would
  march past every failure row in the table.
- **Treating the `-> None` annotation on `__exit__` as the whole rule.** An implementation that
  returns truthy suppresses the exception whatever the annotation says, so the contract states the
  behaviour and the suite observes it.

## Risks

- **One continuing account's `S4` can exceed memory.** Every declaration is bounded, but their
  accumulation is bounded only by the caller's discipline and by account completion. Bootstrap
  3.5 owns durable maintenance of it. A released handle stays released; the durable store
  maintains `S4`, it does not extend it.
- **The session can be implemented as a lie.** Nothing in a Protocol forces an implementation to
  honour the failure rows; a `write` that stages eagerly conforms structurally. The falsification
  suite proves the contract's shape with in-memory fakes, and bootstrap 3.6's containerised tests
  are where the transitions are proven against a real database.
- **`AccountSnapshotRef` invites misuse.** It is an opaque locator that will be a `bigint` in
  practice, and someone will sort by it. The contract names it and a test asserts it carries no
  ordering guarantee.

## Handoffs

**To bootstrap 3.5.** PostgreSQL implements `CanonicalReleaseRepository` and `ReleaseLoadSession`
using COPY-to-staging and set-based operations, choosing its own staging tables, batch sizing,
merge SQL, and the value of `max_batch_entries`. It owns durable maintenance of `S4` when one
continuing account's live set exceeds memory, and that store obeys the same failure rows: a
refused write leaves it, and `S6`, exactly as they were, and stages no row that reaches a
completed load.

**To bootstrap 3.6.** The containerised integration tests prove the transition table against a
real database: the oversized-parent case end to end, a refused write leaving the durable `S4`,
`S6`, and staged rows unmoved, and a released handle staying refused.

**To bootstrap 2.4.** The use cases mint correlation handles as they walk parsed records, since
that layer is the only one holding both a record and its parent, and they carry adoptions in the
batches they build rather than adopting separately.
