## ADDED Requirements

<!-- Owns: `CanonicalReleaseRepository`, `ReleaseLoadSession`, the session state
     machine and its transition table, `CanonicalRecordBatch`,
     `CorrelatedRecord`, `CorrelationHandle`, `AdoptedParent`, batch-scoped
     adoption of a persisted snapshot, `ReleaseLoadCompletion`, the retry key,
     and the no-natural-key rule.
     Cites: `processing-run` for `ProcessingRunRef` and
     `ReleaseProcessingOutcome`; `source-registry-and-discovery` for the
     promoted `ReleaseIdentity`; `application-port-boundary` for the
     opaque-locator rule; the accepted `canonical-appraisal-records` spec for
     the record types; the accepted `canonical-silver-persistence` spec for the
     snapshot grain, one-to-many children, cross-load lineage, and
     release-scoped retry.
     The transition table below is the authority for this capability. It lives
     in the spec, not in the change's design, because the spec is what survives
     promotion and the design is archived with the change. -->

### Requirement: The canonical load session is a closed state machine

The canonical persistence boundary SHALL expose one logical release load as a session whose
entire state is the components below and whose entire behaviour is the transitions this
requirement defines. The session SHALL hold no state beyond them and SHALL offer no operation
beyond the three named here. **This table is the authority for this capability**: a transition it
does not define does not exist, and any text elsewhere that disagrees with it is a defect in that
text.

**The context**, fixed when the session opens and mutated by no transition:

```text
S0  context   the ReleaseIdentity being loaded, the ProcessingRunRef, the
              ReleaseProcessingOutcome, and max_batch_entries
```

**The state**, six components and no others:

```text
S1  status        OPEN | COMMITTED | ABORTED
S2  open_account  the one account still open across a batch boundary, or none
S3  staged        the canonical records of accepted batches; none of them durable
S4  mappings      each live handle -> the parent object it denotes, and the account it belongs to
S5  live          the handles that resolve: exactly the keys of S4, never tracked separately
S6  high_water    the greatest handle yet introduced in this session
```

`S5` SHALL be the key set of `S4` and SHALL NOT be tracked as a second structure, because two
structures that can disagree about which handles resolve is the defect this table exists to
prevent.

**The initial state.** When a session opens, `S1` SHALL be `OPEN`, `S2` SHALL be none, `S3` and
`S4` SHALL be empty, and `S6` SHALL be *no handle yet introduced*, so the first handle a session
sees need only satisfy the handle rules themselves. `S0` SHALL be complete at that moment: a
session SHALL NOT be opened without the release, the run, the outcome, and the maximum it will be
judged against.

**Opening.** A session SHALL be obtained from `CanonicalReleaseRepository` for a `ReleaseIdentity`,
a `ProcessingRunRef`, and a `ReleaseProcessingOutcome`, and SHALL be refused rather than opened
when `S0` cannot be completed — a maximum that is not a usable count included. A refused open SHALL
produce no session and no state, so there is nothing to abort and nothing staged. The boundary
SHALL NOT serialize sessions: two sessions open for one release and run are two attempts, and the
retry key decides between them at completion, not at open.

**Resolution.** Resolving an `AccountSnapshotRef` — what `W4` requires — SHALL be the
repository's, SHALL be scoped to the release `S0` names, and SHALL be a read that changes no
component. No other party SHALL be required to resolve a locator, and the boundary SHALL NOT
expose resolution as an operation a caller invokes for its own purposes, because a resolved
snapshot outside a batch is the standalone adoption this specification removed.

**The operations** SHALL be exactly `write(batch)`, `commit()`, and `abort()`, and the surface
SHALL be stated precisely enough that two implementations cannot differ on it:

```text
CanonicalReleaseRepository
  open_load(release: ReleaseIdentity,
            run: ProcessingRunRef,
            outcome: ReleaseProcessingOutcome) -> ReleaseLoadSession
  adoptable_snapshots(account: AccountIdentity,
                      release: ReleaseIdentity) -> Iterator[AdoptableSnapshot]

ReleaseLoadSession
  max_batch_entries: int                      read-only, fixed for the session
  write(batch: CanonicalRecordBatch) -> None  refusal is an exception, never a return value
  commit() -> ReleaseLoadCompletion           carries already_complete
  abort() -> None
  __enter__() -> ReleaseLoadSession
  __exit__(exc_type, exc, tb) -> None         annotated -> None so a failure cannot be suppressed
```

`write` SHALL return nothing: a refusal is raised, so a caller cannot ignore one by discarding a
result, and every failure row of this table is reached the same way. `commit` SHALL return the
completion rather than raise on an already-complete pairing, because a retry is the ordinary path
and not an error. `__exit__` SHALL be annotated `-> None` rather than `-> bool`, so an
implementation cannot silently swallow the exception that should have aborted the load. Reading which
persisted snapshots an account and release offer for adoption SHALL be a repository read that
changes no component, and SHALL NOT be an operation of this machine.

**G1.** Every operation SHALL require `S1 = OPEN`. An operation offered when `S1` is `COMMITTED`
or `ABORTED` SHALL be refused explicitly rather than ignored, because a caller extending a load it
has already ended would otherwise lose those records silently.

#### `write(batch)` — intrinsic preconditions

A batch SHALL validate these when it is constructed, knowing only itself:

| ID | Intrinsic precondition |
| --- | --- |
| B1 | Every entry is well-formed: one canonical record, an optional handle, an optional parent |
| B2 | No handle is introduced twice, counting entry handles and adoption handles together |
| B3 | No handle is repeated within one delta |
| B4 | No handle appears in both deltas |
| B5 | No handle is both introduced by the batch and released by it |
| B6 | No entry names its own handle as its parent |
| B7 | An in-batch parent handle denotes **the very object** the child holds, compared by identity |
| B8 | At most one account is named as continuing |
| B9 | A child naming an adoption's handle within the batch holds the very snapshot that adoption carries |
| B10 | The batch does not name one account as both continuing and closing |

A batch SHALL NOT refuse a parent handle it does not introduce. It cannot know whether such a
handle is live, whose account it belongs to, or what it denotes, so it SHALL accept the entry as
well-formed and `W5` SHALL decide. Where the parent handle **is** one this batch introduces, `B7`
SHALL apply and the batch SHALL settle it without the session. Naming a parent from an earlier
batch is therefore ordinary, and no intrinsic precondition may be read as forbidding it.

`B1` SHALL NOT include any rule about records being distinct. Two entries carrying equal canonical
records are two records and SHALL both be accepted, because a rule refusing the second would be a
deduplication rule over observed values, which this boundary forbids.

Three terms are used below and SHALL mean exactly this.

A batch **carries** an account when it holds at least one entry or adoption belonging to it. This
SHALL be settled by the batch's records alone and SHALL NOT consult either delta.

An account is **open in a batch** when the batch carries it, or when it is `S2`. This SHALL be
settled without consulting either delta, because a rule permitting a delta is not permitted to
take the delta as its evidence: a batch naming another account's handle in `release` would
otherwise make that account open by the act of naming it, and the account-scoping rule would
permit exactly what it exists to refuse.

A batch **touches** an account when it carries it or names one of its handles in either delta.
This term SHALL be used only where a delta is legitimate evidence that a batch is dealing with an
account, never as the source of permission to name it.

A batch SHALL carry two account declarations, each optional: `continuing`, naming the one account
left open at its end, and `closing`, naming the account it deliberately completes without
necessarily carrying anything of it. `closing` exists because an account cannot always be closed
by touching it: its live handles may outnumber `max_batch_entries`, so a closing batch may have
nothing it is able to carry. Without an explicit declaration the boundary would have to read
silence as either "close it" or "an accident", and it cannot tell those apart.

#### `write(batch)` — session preconditions

The session SHALL check these on `write`:

| ID | Session precondition |
| --- | --- |
| W1 | `S1 = OPEN` (G1) |
| W2 | Entries + adoptions + retained + released ≤ `max_batch_entries` |
| W3 | Every handle introduced exceeds `S6` and is not in `S5` |
| W4 | Every adoption's locator resolves to a snapshot of the release `S0` names, and to the snapshot its `AdoptedParent` carries |
| W5 | Every parent not resolved in-batch is in `S5`, and `S4` says it denotes the object the child holds |
| W6 | Every retained handle is introduced by this batch or already in `S5` |
| W7 | Every released handle is in `S5` |
| W8 | Every handle in either delta belongs to an account **open in the batch**: one it carries, or `S2` |
| W9 | Every retained handle belongs to the account the batch names as continuing |
| W10 | `S2`, if set, is named by this batch as continuing, or as closing, or is touched by it |
| W11 | The account named as continuing, if any, is **open in the batch** |
| W12 | The account named as closing, if any, is `S2` |

`W10` SHALL be checkable by inspecting the batch against `S2` alone, and its violation SHALL be a
batch that says nothing about the account the previous batch left open and carries nothing of it.
That batch is refused rather than allowed to close the account by silence: the previous batch
promised more of it, and closing by omission is indistinguishable from forgetting. Any of three
things satisfies `W10` — carrying some of the account, carrying it onward, or declaring it closed
— and the third SHALL be available with an otherwise empty batch, since an account whose live
handles outnumber `max_batch_entries` cannot be closed by carrying anything at all.

`W12` SHALL hold because `closing` exists only to end the one account left open. An account a
batch introduces and does not carry onward is already complete by the success transition below,
and needs no declaration.

`W8` SHALL be checked against accounts open in the batch and never against touched ones, so a
handle a batch has no other business with cannot be released by being released. Its violation is a
batch naming, in either delta, a handle of an account it neither carries nor inherits as `S2`.

`W11` SHALL be the session's and not the batch's, because carrying `S2` onward without carrying it
is legitimate — a batch may complete other work and still promise more of the open account — and a
batch that knows only itself cannot tell `S2` from an account it has never seen. Naming as
continuing an account that is neither touched here nor already open SHALL be refused, because such
a batch promises more of an account nothing has begun.

#### `write(batch)` — transitions

**On success**, all of these SHALL apply together, at the batch boundary — after every record in
the batch has been validated, never between records:

```text
S3 <- S3 + the batch's records
S6 <- the greatest handle the batch introduced, if any; otherwise unchanged
S4 <- (S4 + the handles this batch retained) - the released
                                            - every handle of an account this batch completes
S2 <- the account the batch names as continuing, or none
S1 <- unchanged
```

An account SHALL be **complete** at the end of a batch that names it as closing, or that touches
it and does not name it as continuing. Completion SHALL be determined that way and by no other means: there SHALL be no
operation declaring it, because `S2` and the batch's `continuing` already carry the fact between
them and one fact with two sources is a fact a caller must reconcile.

A handle introduced and **not** retained SHALL never enter `S4`: it resolves inside its own batch
under `B7`, and the batch is over. That is the ordinary case of a parent whose children arrive beside
it, and it is why `S4` holds only handles that cross a batch boundary.

**On failure** — any `B` or `W` precondition unmet — each of `S1` through `S6` SHALL be exactly
what it was. No record staged, no mapping added or removed, `S6` not advanced, `S2` not moved, and
`S1` still `OPEN`. An implementation that stages, mints, or opens anything before its checks
complete SHALL discard it, and a corrected retry SHALL be free to reuse the very handles the
rejected attempt carried.

#### `commit()`

| ID | Precondition |
| --- | --- |
| C1 | `S1 = OPEN` (G1) |
| C2 | `S2` is none |

**On success**, one of three outcomes, all terminal:

```text
branches are tried in this order, and exactly one applies

1. already loaded by S0's release and run  ->  nothing persisted at all, not even the outcome,
                                               already_complete = True, S3 discarded and
                                               never merged into the earlier load
2. S0's outcome is rejected                ->  the outcome recorded, S3 discarded,
                                               zero canonical records for the load
3. otherwise                               ->  S3 and the outcome become durable together
S1 <- COMMITTED    S2, S3, S4 cleared
```

The order SHALL be normative. A retried pairing whose outcome is rejected satisfies both of the
first two conditions, and "persist nothing further" and "record the outcome" cannot both hold: the
first branch wins, because the earlier completion already recorded an outcome for that pairing and
a retry that overwrote it would make the retry key a lie.

The rejected branch SHALL exist because the outcome is fixed in `S0` and a caller MAY have staged
records before the run was rejected. Committing them because the accepted branch is the only one
written would persist the records of a release the outcome says was not accepted, which no
constraint downstream would catch. Writing batches under a rejected outcome SHALL NOT be refused —
`S0` is fixed at open and the disposition is not the session's to police — and those records SHALL
simply not become durable.

**On failure** — `C1` or `C2` unmet, or the durable write itself failing — zero canonical records
SHALL exist for the load, `S1` SHALL stay `OPEN`, and `S2` through `S6` SHALL be unchanged. A
failed completion SHALL NOT be terminal: the caller may close the open account and commit again,
or abort.

#### `abort()`

| ID | Precondition |
| --- | --- |
| A1 | `S1 = OPEN` (G1) |

An open account SHALL NOT prevent an abort, because an abort persists nothing.

Aborting SHALL affect only this session. Records an earlier session made durable for the same
release, including a load this session would have found already complete, SHALL be untouched: an
abort removes nothing that was already committed, and there SHALL be no operation on this boundary
that does. The same SHALL hold for a completion that fails and for a session that is abandoned
without either operation.

```text
S1 <- ABORTED    S2, S3, S4 discarded    zero canonical records for the load
```

**On failure** — `A1` unmet — refused, and nothing changes.

#### The whole machine

`—` means unchanged.

| Transition | S1 status | S2 open account | S3 staged | S4 mappings | S6 high water |
| --- | --- | --- | --- | --- | --- |
| `write` success | — | ← `continuing` | += records | += retained − released − completed | ← greatest introduced |
| `write` failure | — | — | — | — | — |
| `commit` success, outcome accepted | ← COMMITTED | cleared | durable, cleared | cleared | — |
| `commit` success, outcome rejected | ← COMMITTED | cleared | discarded, cleared | cleared | — |
| `commit` success, already complete | ← COMMITTED | cleared | discarded, cleared | cleared | — |
| `commit` failure | — (OPEN) | — | — | — | — |
| `abort` success | ← ABORTED | cleared | discarded | cleared | — |
| `abort` failure | — | — | — | — | — |
| any op, `S1 ≠ OPEN` | — | — | — | — | — |

**Every failure row SHALL be empty across every component.** That is one rule a reader checks by
looking, rather than several a reader must assemble, and it SHALL hold for every refusal reason
named above.

Throughout this specification, "zero canonical records" SHALL mean zero **from the session being
described**. Records an earlier session made durable for the same release are not this session's
to remove, and no operation on this boundary removes them.

A refused batch SHALL contribute nothing to the completed load. Records are invisible before
completion either way, which is why this is stated rather than assumed: an implementation staging
rows as they arrive and validating afterwards would otherwise carry a rejected batch's rows to the
same completion as the accepted ones, and no caller could tell until the load was already wrong.

A session SHALL NOT make any batch durable before completion, and SHALL NOT require a complete
release to be held in memory.

#### Scenario: A session cannot be opened without its context
- **WHEN** a session is requested without a release, a run, or an outcome, or with a maximum that is not a usable count
- **THEN** it is refused and no session exists, so there is nothing staged and nothing to abort

#### Scenario: Two sessions are opened for one release and run
- **WHEN** two sessions are opened for the same release and run
- **THEN** both open, and the retry key decides between them at completion rather than at open

#### Scenario: A locator is resolved
- **WHEN** an adoption's locator is resolved for `W4`
- **THEN** the repository resolves it against the release `S0` names, as a read that changes no component, and no operation exposes resolution for a caller's own use

#### Scenario: A session opens in the initial state
- **WHEN** a session is opened for a release, a run, and an outcome
- **THEN** `S1` is `OPEN`, `S2` is none, `S3` and `S4` are empty, `S6` is no handle yet introduced, and `S0` already carries the release, the run, the outcome, and `max_batch_entries`

#### Scenario: The surface is examined for its signatures
- **WHEN** the ports are examined
- **THEN** `write` returns nothing and raises on refusal, `commit` returns a `ReleaseLoadCompletion` rather than raising on an already-complete pairing, `abort` returns nothing, `max_batch_entries` is read-only, and `__exit__` is annotated `-> None` so no implementation can suppress a failure

#### Scenario: The session's state and operations are enumerated
- **WHEN** the session contract is examined
- **THEN** its state is exactly `S1`–`S6` over the fixed context `S0`, its operations exactly `write`, `commit`, and `abort`, and candidate discovery is a repository read that changes no component

#### Scenario: A release is loaded in batches
- **WHEN** a caller writes several bounded batches and then completes the session
- **THEN** the records become durable together at completion and not before

#### Scenario: A whole release is not materialised
- **WHEN** the session contract is examined
- **THEN** no operation requires a complete release as a single in-memory collection

#### Scenario: Any refused operation leaves the whole state alone
- **WHEN** an operation is refused for any reason this requirement names
- **THEN** every one of `S1`–`S6` is what it was before it, matching that operation's failure row

#### Scenario: A refused batch is followed by a completion
- **WHEN** a batch is refused, the caller corrects it, writes it again, and completes the session
- **THEN** the load holds the records of the accepted batches and none from the refused attempt, whatever an implementation staged before refusing it

#### Scenario: A corrected batch reuses the handles its rejected attempt introduced
- **WHEN** a refused batch had introduced handles above `S6`, and the caller retries a corrected batch carrying those same handles
- **THEN** they are accepted, because the failure row advanced `S6` no more than it staged records

#### Scenario: A session is used after it ends
- **WHEN** a caller writes, commits, or aborts a session that has already committed or aborted
- **THEN** the operation is refused by `G1`, rather than silently ignored or applied to a load that has ended

#### Scenario: A load is abandoned partway
- **WHEN** a caller aborts after writing several batches
- **THEN** zero canonical records from that session exist, and any earlier session's durable records for the release are untouched

#### Scenario: An abort leaves an open account behind
- **WHEN** a caller aborts while `S2` names an account
- **THEN** it is permitted by `A1` and zero canonical records exist for that load

#### Scenario: A completion is attempted with an account still open
- **WHEN** a caller commits while `S2` names an account
- **THEN** it is refused by `C2`, because that batch promised a batch continuing the account and nothing downstream could tell the truncation from a small account

#### Scenario: A completion fails
- **WHEN** the durable write of a completion fails
- **THEN** zero canonical records exist for the load, `S1` is still `OPEN`, `S2`–`S6` are unchanged, and the caller may commit again or abort

#### Scenario: A batch abandons the account left open
- **WHEN** `S2` names an account and a batch neither touches that account nor names it as continuing
- **THEN** it is refused by `W10`, because the previous batch promised more of that account and this batch neither delivers any of it nor closes it by touching it

#### Scenario: A batch closes the open account by touching it
- **WHEN** `S2` names an account and a batch carries one entry of it, or one delta value of it, and does not name it as continuing
- **THEN** it is accepted and that account is complete at the end of the batch, which is the difference `W10` measures

#### Scenario: A batch promises an account nothing has begun
- **WHEN** a batch names as continuing an account it does not carry and which is not `S2`
- **THEN** it is refused by `W11`, because a batch cannot promise more of an account nothing has begun

#### Scenario: A batch carries the open account onward without carrying any of it
- **WHEN** a batch completes other work and names `S2` as continuing without carrying any record of it
- **THEN** it is accepted by `W11`, because promising more of the account already open is legitimate, and `W10` is satisfied by naming it as continuing

### Requirement: A batch is validated by whichever party can see the answer

Validation authority SHALL be split by what each party can know, and the split SHALL be exactly
`B1`–`B10` for the batch and `W1`–`W12` for the session.

A batch SHALL be an immutable value that knows only itself, and SHALL therefore reject exactly its
intrinsic defects. It SHALL NOT judge handles opened by earlier batches, accounts already
completed, or its own size against `max_batch_entries`, knowing none of them. The session SHALL
reject everything requiring history, on `write`. Atomicity SHALL be the session's, because only
the session holds the state a refusal must leave unmoved.

#### Scenario: A batch is validated on its own
- **WHEN** a batch is constructed
- **THEN** it rejects exactly `B1`–`B10` and judges neither handles from earlier batches nor its own size against a maximum it never sees, nor whether the account it names as continuing is the one already open

#### Scenario: The session judges what needs history
- **WHEN** a batch is written whose defect is a duplicate live handle, a handle not exceeding `S6`, a parent never introduced, a parent whose account has completed, or a parent handle denoting a record other than the one the child holds
- **THEN** the session refuses it by the matching `W` precondition, proving the split rather than assuming it

#### Scenario: A batch names a parent from an earlier batch
- **WHEN** a batch names a parent it does not itself contain
- **THEN** the batch accepts it as well-formed, because no intrinsic precondition judges a handle it does not introduce, and the session decides under `W5` whether that parent is live

### Requirement: Parent linkage is resolved by bounded, account-scoped correlation

The boundary SHALL allow one account's records to span more than one bounded batch, and SHALL
provide a correlation mechanism by which a record names a parent written in an earlier batch.

Correlation SHALL be carried by the batch rather than by the canonical records, which hold their
parents directly and SHALL NOT gain a correlation field. A parent SHALL be named the same way
whether it appears in the same batch or an earlier one.

Each batch SHALL carry **bounded deltas** to `S4`: the handles it newly requires to survive beyond
it, and those it no longer requires. `S4` SHALL be the accumulation of those deltas as the `write`
success transition defines it, and a batch SHALL NOT be required to re-declare it in full. A
complete re-declaration is what this replaces, and the reason is arithmetic: a full declaration
must itself fit inside a bounded batch, so it would cap `S4` at one batch's worth and an account
whose parents exceed that could never finish. The same arithmetic SHALL forbid requiring a closing
batch to release what remains: closing an account SHALL carry nothing at all, and completion SHALL
release what is live.

The session SHALL state `max_batch_entries`, enforced by `W2`. It SHALL be an integer of at least
one that is not a boolean — a boolean is an integer in Python, and `True` would otherwise pass as
a maximum of one — it SHALL count a batch's entries plus its adoptions plus the values in each
delta, it SHALL NOT change while the session is open, and the caller SHALL be able to read it, so
it sizes what it builds rather than discovering the bound by refusal.

A `CorrelationHandle` SHALL be an integer of at least one that is not a boolean, for the same
reason. It SHALL be unique within one session, SHALL increase strictly, and SHALL NOT be reused
once its account is complete; `S6` retains the greatest yet introduced, which is one integer, so
the bound is untouched. It SHALL be neither domain nor persistence identity, SHALL carry no
meaning outside the session, and SHALL NOT appear in any persisted record as a business value.

An implementation MAY hold `S4` durably rather than in memory, which is what allows a large
accumulated set to stay resolvable; the boundary SHALL NOT name that mechanism and SHALL NOT
require the set to fit in memory.

#### Scenario: A record is paired with its correlation
- **WHEN** a batch entry is examined
- **THEN** it pairs the canonical record with the handle it may be named by and the handle naming its parent, and the canonical record itself carries no correlation field

#### Scenario: One account spans several batches
- **WHEN** an account's owners are written in one batch and its allocations in a later batch of the same account
- **THEN** the later records name their parents by the handles the earlier batch introduced, which stayed in `S4` without being re-declared

#### Scenario: An account carries more parents than one batch could enumerate
- **WHEN** one account's live parents outnumber what a single bounded batch could have listed
- **THEN** the account still completes, because each batch contributed bounded deltas rather than a full declaration, and the boundary names no mechanism for holding the accumulation

#### Scenario: A handle introduced and not retained
- **WHEN** a batch introduces a handle, names it as a parent within that same batch, and does not retain it
- **THEN** the batch is well-formed and the handle never enters `S4`, being resolvable inside its own batch under `B7` and gone after it

#### Scenario: Deltas take effect at the batch boundary
- **WHEN** a batch releases a live handle and records positioned both before and after the release name it as a parent
- **THEN** every record in that batch resolves it and the batch after does not, because the success transition applies at the boundary rather than between records

#### Scenario: A released handle is named afterwards
- **WHEN** a batch releases a handle and a record in a later batch names it
- **THEN** it is refused by `W5`, because release is explicit and a released handle is gone whatever an implementation still holds

#### Scenario: An account completes without any separate declaration
- **WHEN** a batch touches an account and does not name it as continuing
- **THEN** that account is complete at the end of the batch and every handle of it still live leaves `S4`, with no second operation able to disagree

#### Scenario: An account is closed by a batch carrying nothing
- **WHEN** a caller closes an account whose live handles outnumber `max_batch_entries`, with a batch carrying no entries, no adoptions, and no deltas, naming it as closing
- **THEN** it is accepted and completion sweeps `S4` for that account, so closing requires neither inventing a record nor enumerating a live set the maximum could not hold

#### Scenario: A batch declares an account both continuing and closing
- **WHEN** a batch names one account in both declarations
- **THEN** it is refused by `B10`, the batch seeing the contradiction without any history

#### Scenario: A batch closes an account that is not the open one
- **WHEN** a batch names as closing an account that is not `S2`
- **THEN** it is refused by `W12`, because the declaration exists only to end the one account left open, and an account the batch introduces and does not carry onward is already complete

#### Scenario: An account is closed by being touched
- **WHEN** a batch carries one entry of `S2`'s account and names it neither as continuing nor as closing
- **THEN** it is accepted and that account is complete at the end of the batch, which is the second of `W10`'s three satisfiers

#### Scenario: A caller sizes its batches before building them
- **WHEN** a caller reads `max_batch_entries`
- **THEN** it is one integer of at least one, fixed for the session, counting entries plus adoptions plus each delta's values, and the caller does not have to find the bound by being refused

#### Scenario: A maximum that is not a usable count
- **WHEN** a session states a maximum that is zero, negative, not an integer, or a boolean
- **THEN** it is refused as a session no caller can use, the boolean named because it is an integer in Python and `True` would otherwise pass as a maximum of one

#### Scenario: The maximum changes while the session is open
- **WHEN** a session states one maximum and later states a different one
- **THEN** it breaks the contract, because a caller sized the batch it is building against the first answer

#### Scenario: A correlation handle is a boolean
- **WHEN** a batch introduces a handle that is a boolean
- **THEN** it is refused, because a boolean is an integer in Python and `True` would otherwise be a handle equal to one

#### Scenario: A completed handle is minted again
- **WHEN** a later batch introduces a handle already used by an account that has completed
- **THEN** it is refused by `W3`, because handles must exceed `S6`, so a released handle cannot be silently retargeted

#### Scenario: A correlation handle denotes a parent the record does not hold
- **WHEN** a record embedding one parent is paired with a handle denoting a different parent of the same kind
- **THEN** the write is refused by `B7` in the same batch or `W5` across batches, even though the handle resolves

#### Scenario: A batch leaves two accounts incomplete
- **WHEN** a batch would leave more than one account continuing into the next
- **THEN** it is refused by `B8`, so at most one account is ever open across a batch boundary

#### Scenario: A batch edits another account's handles
- **WHEN** a batch retains or releases a handle belonging to an account it neither carries nor inherits as `S2`
- **THEN** it is refused by `W8`, because an account is open in a batch by what the batch carries and never by what its deltas name, so naming another account's handle does not make that account the batch's business

#### Scenario: A batch tries to make an account its own by naming it in a delta
- **WHEN** a batch carries no entry and no adoption of an account, does not inherit it as `S2`, and names one of its handles in `release`
- **THEN** it is refused by `W8`, the delta being the thing under judgement and never the evidence for it

#### Scenario: A batch retains a handle of an account it completes
- **WHEN** a batch retains a handle belonging to an account it does not name as continuing
- **THEN** it is refused by `W9`, because the retain asks the handle to outlive the batch and completion releases it at that batch's end

#### Scenario: A batch releases some of a completing account's handles
- **WHEN** a batch releases some of a completing account's handles by name and leaves the rest
- **THEN** it is accepted and completion releases the rest, so an exhaustive release is a caller's option and never its obligation

#### Scenario: A caller never releases within an account
- **WHEN** a caller retains every handle it introduces and releases none until the account completes
- **THEN** `S4` is bounded by that one account and empties at completion, rather than growing with the release

#### Scenario: Correlation state is examined for growth
- **WHEN** the boundary is examined
- **THEN** correlation state grows with neither the release nor the number of accounts in it: only one continuing account's handles outlive a batch, and the boundary permits an implementation to hold them durably

### Requirement: A child may name a parent persisted by an earlier load, through its batch

A child written in this load SHALL be able to name, as its parent, an `AccountSnapshot` that an
earlier load already persisted for the release being loaded, without resubmitting that snapshot
and without being forced onto its parent's load.

Adoption SHALL be carried by the batch and SHALL NOT be a session operation. A standalone adoption
would mint a handle and open an account outside every transition, which is an unbounded way around
the one-open-account bound.

The batch SHALL carry its adoptions as values that state the binding exactly. An `AdoptedParent`
SHALL pair one `AdoptableSnapshot` with the one `CorrelationHandle` the batch binds to it, so
which handle denotes which snapshot is carried by the value rather than inferred from position or
order. A handle bound by an `AdoptedParent` SHALL be **introduced by that batch** for every
purpose this specification names — `B2`, `W3`, retention, release, account ownership, and the
`write` success transition — so adoption adds no lifetime, no ownership rule, and no transition of
its own.

Adoption SHALL name the snapshot by an **opaque locator** paired with the `AccountSnapshot` it
locates, never by its grain and never by its provenance alone: the accepted persistence contract
makes the grain deliberately non-unique and retains two snapshots sharing a load, release, and
provenance that differ only in a composed situs or legal value, so each of those names more than
one snapshot.

The pair SHALL be verified by `W4`, because a candidate is an ordinary value a caller can
assemble: a valid locator carrying a snapshot it does not locate SHALL be refused with a named
error distinct from the one raised for a locator resolving to no snapshot of the release being
loaded. `B9` SHALL refuse a batch whose child names an adoption's handle while holding a snapshot
other than the one that adoption carries, which is the identity check an in-batch parent gets.

The number of candidates for one account and release SHALL NOT be assumed bounded, and the
boundary SHALL offer them as a lazy iterator that an implementation SHALL NOT fully draw before
the caller consumes the first.

Adoption SHALL create no observation and SHALL leave the existing snapshot unchanged, and the
child SHALL retain its own load and artifact lineage rather than being attached to its parent's. A
parent that is not an account snapshot SHALL NOT be adoptable, because the canonical model gives
those observations no identity to name them by and inventing one would be the natural key this
boundary forbids; a child of such a parent SHALL be written in the same session as it.

#### Scenario: An adoption states its binding
- **WHEN** a batch's adoptions are examined
- **THEN** each is an `AdoptedParent` pairing one candidate with the one handle bound to it, and no binding is inferred from the order of the adoptions or of the entries

#### Scenario: An adopted handle is an introduced handle
- **WHEN** a batch adopts a parent and retains, releases, or leaves unretained the handle it binds
- **THEN** the handle follows `B2`, `W3`, and the success transition exactly as a handle introduced by an entry does, and adoption adds no rule of its own

#### Scenario: A geometry enrichment arrives from a second artifact
- **WHEN** a child carrying provenance from a second load and artifact names an account snapshot already persisted for the same release
- **THEN** it is retained with its own artifact lineage, its parent is the existing snapshot, and no second snapshot is created

#### Scenario: An account has two snapshots at one grain and one is enriched
- **WHEN** an account has two persisted snapshots for one release differing in provenance, and a child from a third artifact must name one of them
- **THEN** the candidates are offered as locator-and-snapshot pairs, the batch adopts one, and the child attaches to exactly that observation rather than to whichever the grain would have matched

#### Scenario: Two candidates share a provenance and differ only in a composed value
- **WHEN** an account has two persisted snapshots sharing one load, release, and provenance that differ only in a situs address or a legal description
- **THEN** both are offered as distinct candidates carrying their own snapshot values, and adopting one attaches the child to that observation and not the other

#### Scenario: An adopted parent does not exist
- **WHEN** a batch adopts a candidate whose locator resolves to no snapshot persisted for the release `S0` names, including one belonging to another release
- **THEN** the write is refused by `W4` with a named error, and no snapshot is created

#### Scenario: A candidate pairs a valid locator with a snapshot it does not locate
- **WHEN** a batch adopts a candidate assembled by the caller whose locator resolves to a snapshot other than the one it carries
- **THEN** the write is refused by `W4` with a named error distinct from the one for an unknown snapshot, because a handle bound to an object the locator never named is the ambiguity this requirement removes

#### Scenario: An adopted parent is named by a child holding an equal but different snapshot
- **WHEN** a child names an adopted handle while holding a snapshot equal in value to the adopted one but not the same object
- **THEN** it is refused by `B9`, exactly as it would be for a parent introduced in the batch

#### Scenario: A batch carrying adoptions is refused
- **WHEN** a batch that adopts a parent is refused for any reason
- **THEN** nothing is adopted and `S1`–`S6` are unchanged, which is the whole reason adoption is carried by the batch

#### Scenario: Adoption is offered a grain instead of a candidate
- **WHEN** adoption is attempted by account identity and release rather than by a candidate
- **THEN** no such operation exists, because the grain does not identify one snapshot

#### Scenario: Adoption is attempted as a session operation
- **WHEN** the session contract is examined for an operation that adopts a parent outside a batch
- **THEN** there is none, because such an operation would mint a handle and open an account outside every transition

#### Scenario: An account has more candidates than a caller wishes to hold
- **WHEN** the snapshots persisted for one account and release outnumber what a caller wants in memory
- **THEN** candidates are obtained lazily through the iterator, and neither the boundary nor the caller is required to hold all of them

#### Scenario: A deeper parent is offered for adoption
- **WHEN** adoption is attempted for an observation that is not an account snapshot
- **THEN** it is refused, because that observation has no declared identity to name it by

### Requirement: The processing outcome and the canonical load complete as one unit of work

The session SHALL own the relationship between the processing run, its accepted or rejected
outcome with bounded diagnostics and notices, and the canonical load, such that the outcome and
the load become durable together at the one completion point the `commit` success transition
defines.

The boundary SHALL NOT require an implementation to make the accepted outcome durable in one unit
of work and the canonical load in another.

#### Scenario: An accepted release is completed
- **WHEN** a session carrying an accepted outcome is completed
- **THEN** the outcome and the canonical load become durable together

#### Scenario: A rejected release is completed
- **WHEN** a run's outcome is rejected
- **THEN** the outcome is recorded and zero canonical records are committed for that release

#### Scenario: Records were staged before a rejected outcome is completed
- **WHEN** a session whose `S0` outcome is rejected has accepted several batches and is then completed
- **THEN** those staged records are discarded, the outcome is recorded, and zero canonical records exist for the load, because the accepted branch of the completion is not the only one

#### Scenario: The contract is examined for independent commits
- **WHEN** the boundary is examined
- **THEN** no arrangement of its operations requires the outcome and the load to be committed separately

### Requirement: Retry is scoped to one release and one processing run

The retry key SHALL be the pairing of a canonical release with the processing run that loaded it,
both carried by `S0`. Completing a load for a pairing that has already completed SHALL persist
nothing further and SHALL return a bounded, machine-readable result stating that the load had
already happened, rather than raising an error the caller must interpret.

Two distinct processing runs loading one canonical release SHALL be two loads, and the second
SHALL NOT be treated as a retry of the first.

Deciding that a pairing has already completed and making this session's records durable SHALL be
one atomic step. Two sessions open for one pairing MAY complete concurrently, and exactly one
SHALL persist a load while the other reports `already_complete`; the boundary SHALL NOT permit an
interleaving in which both observe an incomplete pairing and both persist. The check is worthless
if a caller can pass it and then lose the race, and a retry key that admits two loads for one
pairing is not a retry key.

#### Scenario: A completed load is retried
- **WHEN** a load is completed again for the same release and the same run
- **THEN** the result reports that the load was already complete, nothing is persisted — not even the outcome — and the staged records of this session are discarded rather than merged into the earlier load

#### Scenario: A retried pairing has a rejected outcome
- **WHEN** a session whose outcome is rejected completes a pairing that has already completed
- **THEN** the already-complete branch applies and nothing is persisted, because the earlier completion already recorded an outcome for that pairing and overwriting it would make the retry key a lie

#### Scenario: A retrying session is aborted instead of completed
- **WHEN** a session opened for a release and run that already completed is aborted
- **THEN** zero records are added and the earlier load is untouched, because an abort affects only its own session

#### Scenario: A release is reprocessed by a second run
- **WHEN** a second processing run loads a release a first run already loaded
- **THEN** the result reports a new load rather than an already-complete one, and both loads are retained

#### Scenario: Two sessions for one pairing complete concurrently
- **WHEN** two sessions open for the same release and run both complete
- **THEN** exactly one persists a load and the other reports that the load was already complete, because the decision and the durable write are one atomic step

#### Scenario: The retry key is inspected
- **WHEN** the retry key is examined
- **THEN** it is composed of a release and a run and of no observed value

### Requirement: The boundary defines no key over observed values

The canonical persistence boundary SHALL NOT define a natural key, a uniqueness rule, or a
deduplication rule over observed canonical values. Submitting records that the canonical model
admits SHALL NOT cause the boundary to discard, merge, or reject them on the basis of their
values. No precondition of the transition table SHALL be read as such a rule: `B1` governs the
shape of an entry and `B2` the uniqueness of a handle, and neither compares one canonical record
with another.

#### Scenario: Two entries carry equal canonical records
- **WHEN** one batch carries two entries whose canonical records are equal in value
- **THEN** both are accepted and both persist, because refusing the second would be a deduplication rule over observed values

#### Scenario: Divergent evidence is submitted at one grain
- **WHEN** several account snapshots are submitted at one account and release grain, differing in provenance or in situs or legal description
- **THEN** all are accepted and retained, and none is treated as a duplicate of another

#### Scenario: Several children of one parent are submitted
- **WHEN** several children of an accepted one-to-many type, or several geometries, are submitted for one parent
- **THEN** all are accepted and none is collapsed

#### Scenario: Children arrive from another load of the same release
- **WHEN** children are submitted by a second load of the same logical release
- **THEN** they are retained alongside the first load's records
