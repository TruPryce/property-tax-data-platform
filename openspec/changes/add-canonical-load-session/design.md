# Design: Canonical Load Session

## Context

This change carries one capability out of `add-application-port-boundary`, where it was one
scope of five. It is separated because it is the only one of the five that is a **stateful
transactional protocol** rather than a set of value contracts, and because ten successive review
rounds demonstrated what happens when such a protocol is specified in prose: each correction was
locally right, changed the state space, and exposed the next interaction. Two of the last three
findings were defects introduced by the fix before them.

The diagnosis is not that the wording was poor. It is that the state machine was never closed as
one model, so no reader — reviewer or author — could tell whether a rule was complete. This
design therefore leads with **one authoritative transition table**. Everything else in this
change, including every requirement, scenario, and task, refers to that table rather than
restating it. A transition that is not in the table does not exist, and a rule stated anywhere
else that contradicts the table is a defect in the other place.

## The session state

A `ReleaseLoadSession` holds exactly six components. Nothing else about a session is state, and
no operation may add one.

```text
S1  status        OPEN | COMMITTED | ABORTED
S2  open_account  the one account still open across a batch boundary, or none
S3  staged        the canonical records of accepted batches; none of them durable
S4  mappings      each live handle -> the parent object it denotes, and the account it belongs to
S5  live          the handles that resolve: exactly the keys of S4, never tracked separately
S6  high_water    the greatest handle yet introduced in this session
```

`S5` is named because reviewers and callers talk about "the live set", but it is the key set of
`S4` and is not independent state. Two structures that can disagree about which handles resolve
is precisely the class of defect this table exists to prevent.

`S3` is the component that a purely value-level reading keeps losing. Records written before a
refusal are invisible either way, because nothing is durable before completion — which is why
their fate has to be stated rather than assumed. An implementation that stages rows as they
arrive and validates afterwards would otherwise carry a rejected batch's rows to the same commit
as the accepted ones, and the load would be wrong before any caller could look.

## The operations

Three, and only three: `write(batch)`, `commit()`, `abort()`. Candidate *discovery* — reading
which persisted snapshots an account and release offer for adoption — is a read on
`CanonicalReleaseRepository` that touches no component of `S1`–`S6` and is therefore not an
operation of this machine.

**G1.** Every operation requires `S1 = OPEN`. An operation offered when `S1` is `COMMITTED` or
`ABORTED` is refused, explicitly rather than silently, and changes nothing. A caller extending a
load it has already ended would otherwise watch its records vanish without a word.

### `write(batch)`

The batch validates its own shape when it is constructed, knowing only itself. These are the
intrinsic preconditions, and a batch that fails one cannot be built, let alone written:

| ID | Intrinsic precondition |
| --- | --- |
| B1 | Entries are well-formed, and each canonical record appears once |
| B2 | No handle is introduced twice within the batch |
| B3 | No handle is repeated within one delta |
| B4 | No handle appears in both deltas |
| B5 | No handle is both introduced (or adopted) by the batch and released by it |
| B6 | A parent named within the batch resolves within the batch |
| B7 | An in-batch parent handle denotes **the very object** the child holds, compared by identity |
| B8 | At most one account is named as continuing |
| B9 | An adoption's carried snapshot is the object any in-batch child of it holds |

The session checks what needs history, on `write`:

| ID | Session precondition |
| --- | --- |
| W1 | `S1 = OPEN` (G1) |
| W2 | Entries + adoptions + retained + released ≤ `max_batch_entries` |
| W3 | Every handle introduced or adopted exceeds `S6` and is not in `S5` |
| W4 | Every adoption's locator resolves to a snapshot of the release being loaded, and to the snapshot the candidate carries |
| W5 | Every parent not resolved in-batch is in `S5`, and `S4` says it denotes the object the child holds |
| W6 | Every retained handle is introduced or adopted by this batch, or already in `S5` |
| W7 | Every released handle is in `S5` |
| W8 | Every handle in either delta belongs to an account open in the batch: one it introduces, one it adopts into, or `S2` |
| W9 | Every retained handle belongs to the account the batch names as continuing |
| W10 | `S2`, if set, is completed by this batch or named as continuing by it |

**On success**, all of these apply together, at the batch boundary — after every record in the
batch has been validated, never between records:

```text
S3 <- S3 + the batch's records
S6 <- the greatest handle the batch introduced or adopted, if any; otherwise unchanged
S4 <- (S4 + the handles this batch retained) - the released
                                            - every handle of an account this batch completes
S2 <- the account the batch names as continuing, or none
S1 <- unchanged
```

A handle introduced or adopted and **not** retained never enters `S4` at all: it is resolvable
inside its own batch by B6, and the batch is over. That is the ordinary case of a parent whose
children arrive beside it, and it is why `S4` only ever holds handles that cross a batch
boundary.

An account is complete at the end of the batch that touches it and does not name it as
continuing. There is no separate operation declaring completion; `S2` and the batch's
`continuing` carry the fact between them, and one fact with two sources is a fact a caller has
to reconcile.

**On failure** — any B or W precondition unmet — `S1` through `S6` are **each exactly what they
were**. No record staged, no mapping added or removed, `S6` not advanced, `S2` not moved, the
session still `OPEN`. A corrected retry may reuse the very handles the rejected attempt carried.

### `commit()`

| ID | Precondition |
| --- | --- |
| C1 | `S1 = OPEN` (G1) |
| C2 | `S2` is none |

C2 is not bookkeeping. A batch naming an account as continuing promises a batch that continues
it; committing instead persists a truncated account that nothing downstream can distinguish from
a small one. The caller closes it the way it closes every account: a final batch that does not
name it as continuing, **carrying no entries and no deltas at all**, since completion releases
what is live. Closure must not ask for a release list — a delta is bounded by `max_batch_entries`
and `S4` is not, so demanding the list would be unsatisfiable for exactly the accounts the deltas
exist to serve.

**On success**, one of two outcomes, and both are terminal:

```text
already loaded by this run   ->  nothing further persisted, already_complete = True
otherwise                    ->  S3 and the processing outcome become durable together
S1 <- COMMITTED    S2, S3, S4 cleared
```

**On failure** — C1 or C2 unmet, or the durable write itself fails — zero canonical records exist
for the load, `S1` stays `OPEN`, and `S2` through `S6` are unchanged. The caller may close the
open account and commit again, or abort. A failed completion is not a terminal state; only a
successful one is.

### `abort()`

| ID | Precondition |
| --- | --- |
| A1 | `S1 = OPEN` (G1) |

An open account does not prevent an abort, because an abort persists nothing.

```text
S1 <- ABORTED    S2, S3, S4 discarded    zero canonical records for the load
```

**On failure** — A1 unmet — refused, and nothing changes.

### The whole machine

`—` means unchanged.

| Transition | S1 status | S2 open account | S3 staged | S4 mappings | S6 high water |
| --- | --- | --- | --- | --- | --- |
| `write` success | — | ← `continuing` | += records | += retained − released − completed | ← greatest introduced |
| `write` failure | — | — | — | — | — |
| `commit` success | ← COMMITTED | cleared | durable, cleared | cleared | — |
| `commit` failure | — (OPEN) | — | — | — | — |
| `abort` success | ← ABORTED | cleared | discarded | cleared | — |
| `abort` failure | — | — | — | — | — |
| any op, `S1 ≠ OPEN` | — | — | — | — | — |

Every failure row is empty across every component. That is the property the table exists to make
checkable at a glance, and it is the property nine rounds of prose could not hold.

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

## The value contracts

### `CorrelationHandle`

A frozen value over an integer of at least one that is not a boolean, unique within one session.
It exists only to let a record name a parent, never appears in a stored row, and stops resolving
once its account completes. Session-wide rather than per-account, because one value meaning
different things in two accounts is an ambiguity nothing later can recover.

### `CorrelatedRecord` and `CanonicalRecordBatch`

`CorrelatedRecord` pairs one canonical record with an optional `handle` — the value it may later
be named by — and an optional `parent`, the value naming its own parent. Correlation rides on the
batch, never on the canonical records, which hold their parents directly and gain no correlation
field.

`CanonicalRecordBatch` carries those entries, the adoptions it makes, `continuing` naming the one
account left open at its end, and two delta tuples, `retain` and `release`. Its intrinsic
validation is exactly B1–B9 and nothing more: it cannot judge `S4`, `S6`, or `max_batch_entries`,
because it knows only itself.

### `AccountSnapshotRef`, `AdoptableSnapshot`, `ReleaseLoadCompletion`

`AccountSnapshotRef` is an opaque locator on the same terms as `ProcessingRunRef`.
`AdoptableSnapshot` pairs one with the `AccountSnapshot` it locates. `ReleaseLoadCompletion`
carries the `ProcessingRunRef` and `already_complete`, and deliberately no locator per account —
a caller wanting to name a snapshot it just wrote uses the handle it already has.

### `ReleaseLoadSession` and `CanonicalReleaseRepository`

The session is a Protocol with `__enter__` and `__exit__` annotated `-> None` so a failure cannot
be suppressed, `max_batch_entries`, and the three operations. `CanonicalReleaseRepository` opens
a session for a `ReleaseIdentity`, a `ProcessingRunRef`, and a `ReleaseProcessingOutcome`, and
offers an account and release's adoptable snapshots as a lazy `Iterator[AdoptableSnapshot]`.

Neither names a schema, table, cursor, connection, transaction, bulk-load mechanism, conflict
clause, or surrogate key. Resolving a handle to a generated key is the adapter's mechanism to
choose, subject to the table.

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

- Each of B1–B9 refuses **at construction**, without a session.
- Each of W1–W10 refuses **on write**, with a session that has the history the check needs.
- After every one of those refusals, S1–S6 are byte-for-byte what they were: nothing staged,
  `S6` not advanced — proven by a corrected retry reusing the rejected batch's handles — `S2`
  unmoved, no mapping added or removed, and the session still `OPEN`.
- A refused batch contributes no records: after a refusal, a correction, and a completion, the
  load holds the accepted batches' records and nothing from the rejected attempt.
- `write` success applies the four assignments together and at the batch boundary: a handle the
  batch releases resolves for every record of that batch, including records positioned after the
  release, and is gone for the next.
- A handle introduced and not retained never enters `S4` and dies with its batch.
- `commit` with C2 unmet is refused; the account is then closed by a batch carrying no entries
  and no deltas, and the commit succeeds. An account with more live handles than
  `max_batch_entries` could carry closes the same way.
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
