## ADDED Requirements

<!-- Owns: `CanonicalReleaseRepository`, `ReleaseLoadSession`, the session state
     machine, `CanonicalRecordBatch`, `CorrelatedRecord`, `CorrelationHandle`,
     batch-scoped adoption of a persisted snapshot, `ReleaseLoadCompletion`,
     the retry key, and the no-natural-key rule.
     Cites: `processing-run` for `ProcessingRunRef` and
     `ReleaseProcessingOutcome`; `source-registry-and-discovery` for the
     promoted `ReleaseIdentity`; `application-port-boundary` for the
     opaque-locator rule; the accepted `canonical-appraisal-records` spec for
     the record types; the accepted `canonical-silver-persistence` spec for the
     snapshot grain, one-to-many children, cross-load lineage, and
     release-scoped retry.
     The transition table in `design.md` is the authority for every state
     component, precondition, and transition named below. -->

### Requirement: The canonical load session is a closed state machine

The canonical persistence boundary SHALL expose one logical release load as a session whose
entire state is the six components `S1`–`S6` of the transition table in
[`design.md`](../../design.md), and whose entire behaviour is the transitions that table
defines for `write(batch)`, `commit()`, and `abort()`.

The session SHALL hold no state beyond those six components, and SHALL offer no operation
beyond those three. Reading which persisted snapshots an account and release offer for adoption
SHALL be a repository read that changes no component, and SHALL NOT be an operation of the
session.

Every operation SHALL require `S1 = OPEN` (`G1`). An operation offered after a session has
committed or aborted SHALL be refused explicitly rather than ignored, because a caller adding to
a load it has already ended would otherwise lose those records silently.

**Every failure transition SHALL leave the complete state unchanged.** For any refused
operation, each of `S1`–`S6` SHALL be exactly what it was before the operation: no record
staged, no mapping added or removed, `S6` not advanced, `S2` not moved, and `S1` still `OPEN`.
This SHALL hold for every refusal reason the table names, and an implementation that stages,
mints, or opens anything before its checks complete SHALL discard it.

A refused batch SHALL contribute nothing to the completed load. Records are invisible before
completion either way, which is why this is stated rather than assumed: an implementation
staging rows as they arrive and validating afterwards would otherwise carry a rejected batch's
rows to the same completion as the accepted ones, and no caller could tell until the load was
already wrong.

A session SHALL NOT make any batch durable before completion, and SHALL NOT require a complete
release to be held in memory. A session that aborts, or whose completion fails, SHALL leave zero
canonical records for that load.

#### Scenario: The session's state and operations are enumerated
- **WHEN** the session contract is examined
- **THEN** its state is exactly `S1`–`S6` of the transition table, its operations exactly `write`, `commit`, and `abort`, and candidate discovery is a repository read that changes no component

#### Scenario: A release is loaded in batches
- **WHEN** a caller writes several bounded batches and then completes the session
- **THEN** the records become durable together at completion and not before

#### Scenario: A whole release is not materialised
- **WHEN** the session contract is examined
- **THEN** no operation requires a complete release as a single in-memory collection

#### Scenario: Any refused operation leaves the whole state alone
- **WHEN** an operation is refused for any reason the transition table names
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
- **THEN** zero canonical records exist for that load

#### Scenario: An abort leaves an open account behind
- **WHEN** a caller aborts while `S2` names an account
- **THEN** it is permitted by `A1` and zero canonical records exist for that load

### Requirement: A batch is validated by whichever party can see the answer

Validation authority SHALL be split by what each party can know, and the split SHALL be exactly
`B1`–`B9` for the batch and `W1`–`W10` for the session, as the transition table lists them.

A batch SHALL be an immutable value that knows only itself, and SHALL therefore reject exactly
its intrinsic defects. It SHALL NOT judge handles opened by earlier batches, accounts already
completed, or its own size against `max_batch_entries`, knowing none of them.

The session SHALL reject everything requiring history, on `write`. Atomicity SHALL be the
session's, because only the session holds the state a refusal must leave unmoved.

#### Scenario: A batch is validated on its own
- **WHEN** a batch is constructed
- **THEN** it rejects exactly `B1`–`B9` and judges neither handles from earlier batches nor its own size against a maximum it never sees

#### Scenario: The session judges what needs history
- **WHEN** a batch is written whose defect is a duplicate live handle, a handle not exceeding `S6`, a parent never introduced, a parent whose account has completed, or a parent handle denoting a record other than the one the child holds
- **THEN** the session refuses it by the matching `W` precondition, proving the split rather than assuming it

#### Scenario: A batch names a parent from an earlier batch
- **WHEN** a batch names a parent it does not itself contain
- **THEN** the batch accepts it as well-formed under `B6`, and the session decides under `W5` whether that parent is live

### Requirement: Parent linkage is resolved by bounded, account-scoped correlation

The boundary SHALL allow one account's records to span more than one bounded batch, and SHALL
provide a correlation mechanism by which a record names a parent written in an earlier batch.

Correlation SHALL be carried by the batch rather than by the canonical records, which hold their
parents directly and SHALL NOT gain a correlation field. A parent SHALL be named the same way
whether it appears in the same batch or an earlier one.

Each batch SHALL carry **bounded deltas** to `S4`: the handles it newly requires to survive
beyond it, and those it no longer requires. `S4` SHALL be the accumulation of those deltas as the
`write` success row defines it, and a batch SHALL NOT be required to re-declare it in full. A
complete re-declaration is what this replaces, and the reason is arithmetic: a full declaration
must itself fit inside a bounded batch, so it would cap `S4` at one batch's worth and an account
whose parents exceed that could never finish.

Releasing SHALL be explicit, and completing an account SHALL release every handle of that account
still live, as the same row states. An account SHALL be complete at the end of the batch that
touches it and does not name it as continuing, and completion SHALL be determined that way alone:
there SHALL be no separate operation declaring it.

The session SHALL state `max_batch_entries`, one maximum for what a batch may carry, enforced by
`W2`. It SHALL be an integer of at least one that is not a boolean — a boolean is an integer in
Python, and `True` would otherwise pass as a maximum of one — it SHALL count a batch's entries
plus its adoptions plus the values in each delta, it SHALL NOT change while the session is open,
and the caller SHALL be able to read it, so it sizes what it builds rather than discovering the
bound by refusal.

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
- **THEN** the batch is well-formed and the handle never enters `S4`, being resolvable inside its own batch by `B6` and gone after it

#### Scenario: Deltas take effect at the batch boundary
- **WHEN** a batch releases a live handle and records positioned both before and after the release name it as a parent
- **THEN** every record in that batch resolves it and the batch after does not, because the `write` success row applies at the boundary rather than between records

#### Scenario: A released handle is named afterwards
- **WHEN** a batch releases a handle and a record in a later batch names it
- **THEN** it is refused by `W5`, because release is explicit and a released handle is gone whatever an implementation still holds

#### Scenario: An account completes without any separate declaration
- **WHEN** a batch touches an account and does not name it as continuing
- **THEN** that account is complete at the end of the batch and every handle of it still live leaves `S4`, with no second operation able to disagree

#### Scenario: A completion is attempted with an account still open
- **WHEN** a caller commits while `S2` names an account
- **THEN** it is refused by `C2`, because that batch promised a batch continuing the account and nothing downstream could tell the truncation from a small account

#### Scenario: An account is closed by a batch carrying nothing
- **WHEN** a caller closes the last continuing account with a batch carrying no entries, no adoptions, and no deltas, naming no account as continuing
- **THEN** it is accepted and completion releases what was live, so closing requires neither inventing a record nor enumerating a live set the maximum could not hold

#### Scenario: A closing batch would have to list an unbounded live set
- **WHEN** the account being closed has more live handles than `max_batch_entries` could carry
- **THEN** it still closes, because closure releases nothing by name

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

#### Scenario: A batch drops the account continuing into it
- **WHEN** a batch neither completes `S2` nor names it as continuing again
- **THEN** it is refused by `W10`, because an account cannot be left open with no batch carrying it

#### Scenario: A batch edits another account's handles
- **WHEN** a batch retains or releases a handle belonging to an account it neither introduces, adopts into, nor inherits as `S2`
- **THEN** it is refused by `W8`, because correlation is account-scoped and one account editing another's live set is retargeting by another route

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

Adoption SHALL be carried by the batch and SHALL NOT be a session operation. The handles it binds
SHALL be introduced by that batch and SHALL follow exactly the rules any introduced handle
follows, so a refused batch adopts nothing and adoption adds no transition to the table. A
standalone adoption would mint a handle and open an account outside every transition, which is
an unbounded way around the one-open-account bound.

Adoption SHALL name the snapshot by an **opaque locator** paired with the `AccountSnapshot` it
locates, never by its grain and never by its provenance alone: the accepted persistence contract
makes the grain deliberately non-unique and retains two snapshots sharing a load, release, and
provenance that differ only in a composed situs or legal value, so each of those names more than
one snapshot.

The pair SHALL be verified, by `W4`, because a candidate is an ordinary value a caller can
assemble: a valid locator carrying a snapshot it does not locate SHALL be refused with a named
error distinct from the one raised for a locator resolving to no snapshot of the release being
loaded. `B9` SHALL refuse a candidate whose carried snapshot is not the object an in-batch child
of it holds, which is the identity check an in-batch parent already gets.

The number of candidates for one account and release SHALL NOT be assumed bounded, and the
boundary SHALL offer them as a lazy iterator that an implementation SHALL NOT fully draw before
the caller consumes the first.

Adoption SHALL create no observation and SHALL leave the existing snapshot unchanged, and the
child SHALL retain its own load and artifact lineage rather than being attached to its parent's.
A parent that is not an account snapshot SHALL NOT be adoptable, because the canonical model
gives those observations no identity to name them by and inventing one would be the natural key
this boundary forbids; a child of such a parent SHALL be written in the same session as it.

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
- **WHEN** a batch adopts a candidate whose locator resolves to no snapshot persisted for the release being loaded, including one belonging to another release
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
- **THEN** there is none, because such an operation would mint a handle and open an account outside every transition in the table

#### Scenario: An account has more candidates than a caller wishes to hold
- **WHEN** the snapshots persisted for one account and release outnumber what a caller wants in memory
- **THEN** candidates are obtained lazily through the iterator, and neither the boundary nor the caller is required to hold all of them

#### Scenario: A deeper parent is offered for adoption
- **WHEN** adoption is attempted for an observation that is not an account snapshot
- **THEN** it is refused, because that observation has no declared identity to name it by

### Requirement: The processing outcome and the canonical load complete as one unit of work

The session SHALL own the relationship between the processing run, its accepted or rejected
outcome with bounded diagnostics and notices, and the canonical load, such that the outcome and
the load become durable together at the one completion point the `commit` success row defines.

The boundary SHALL NOT require an implementation to make the accepted outcome durable in one unit
of work and the canonical load in another.

#### Scenario: An accepted release is completed
- **WHEN** a session carrying an accepted outcome is completed
- **THEN** the outcome and the canonical load become durable together

#### Scenario: A rejected release is completed
- **WHEN** a run's outcome is rejected
- **THEN** the outcome is recorded and zero canonical records are committed for that release

#### Scenario: A completion fails
- **WHEN** the durable write of a completion fails
- **THEN** zero canonical records exist for the load, `S1` is still `OPEN`, and `S2`–`S6` are unchanged, so the caller may commit again or abort

#### Scenario: The contract is examined for independent commits
- **WHEN** the boundary is examined
- **THEN** no arrangement of its operations requires the outcome and the load to be committed separately

### Requirement: Retry is scoped to one release and one processing run

The retry key SHALL be the pairing of a canonical release with the processing run that loaded it.
Completing a load for a pairing that has already completed SHALL persist nothing further and
SHALL return a bounded, machine-readable result stating that the load had already happened,
rather than raising an error the caller must interpret.

Two distinct processing runs loading one canonical release SHALL be two loads, and the second
SHALL NOT be treated as a retry of the first.

#### Scenario: A completed load is retried
- **WHEN** a load is completed again for the same release and the same run
- **THEN** the result reports that the load was already complete and nothing further is persisted

#### Scenario: A release is reprocessed by a second run
- **WHEN** a second processing run loads a release a first run already loaded
- **THEN** the result reports a new load rather than an already-complete one, and both loads are retained

#### Scenario: The retry key is inspected
- **WHEN** the retry key is examined
- **THEN** it is composed of a release and a run and of no observed value

### Requirement: The boundary defines no key over observed values

The canonical persistence boundary SHALL NOT define a natural key, a uniqueness rule, or a
deduplication rule over observed canonical values. Submitting records that the canonical model
admits SHALL NOT cause the boundary to discard, merge, or reject them on the basis of their
values.

#### Scenario: Divergent evidence is submitted at one grain
- **WHEN** several account snapshots are submitted at one account and release grain, differing in provenance or in situs or legal description
- **THEN** all are accepted and retained, and none is treated as a duplicate of another

#### Scenario: Several children of one parent are submitted
- **WHEN** several children of an accepted one-to-many type, or several geometries, are submitted for one parent
- **THEN** all are accepted and none is collapsed

#### Scenario: Children arrive from another load of the same release
- **WHEN** children are submitted by a second load of the same logical release
- **THEN** they are retained alongside the first load's records
