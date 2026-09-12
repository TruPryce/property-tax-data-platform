# The canonical load session

The application-side contract a PostgreSQL loader implements, and the one a use case calls. Normative
behaviour lives in the
[canonical load session capability](../../openspec/changes/add-canonical-load-session/specs/canonical-load-session/spec.md),
whose **transition table** is the authority: the fixed context `S0`, the state components `S1`–`S6`, the
three operations, and every precondition by identifier. This page does not restate that table.
Restating it is the failure the capability was separated to correct — the protocol was once
described across a spec, a design, a decision list, a task list and two handoffs, and no reader
could tell whether a rule was complete.

Where this page and the capability disagree, the capability wins. The capability is still a change
rather than a promoted spec, so the link above points into `openspec/changes/`; archiving moves it to
`openspec/specs/canonical-load-session/spec.md` and this page's link moves with it.

## What the port is

`CanonicalReleaseRepository` opens one logical release load for a `ReleaseIdentity`, a processing
run and that run's outcome, and answers which already-persisted snapshots an account and release
offer for adoption. `ReleaseLoadSession` is the load: `write(batch)`, `commit()`, `abort()`, and a
readable `max_batch_entries`. There is no fourth operation — in particular none that adopts a parent
and none that declares an account complete, both of which are carried by a batch instead.

```text
open_load(release, run, outcome)
    │   max_batch_entries        one maximum, fixed for the session
    ├── write(batch)             bounded, many times, nothing durable
    ├── write(batch)
    └── commit() ─► completion   or abort()
```

## What it owns, and what it refuses to decide

It owns the session's whole state and every transition over it, the batch and its correlation
handles, adoption of a snapshot an earlier load persisted, completion, and the retry key.

It decides **no key over observed values**. Several snapshots at one account and release grain,
several children of one parent, two entries whose canonical records are equal — all are accepted and
retained. No precondition may be read as a deduplication rule: `B1` governs an entry's shape, `B2` a
handle's uniqueness, and neither compares one canonical record with another.

It names no schema, table, cursor, connection, transaction, bulk-load mechanism, conflict clause, or
surrogate key, and `tests/architecture/test_dependency_direction.py` asserts that of every module on
the application surface rather than trusting it.

## Two names it cites but does not own

`ProcessingRunRef` and `ReleaseProcessingOutcome` belong to the `processing-run` capability, planned
in `add-application-port-boundary` and not yet implemented. `canonical.py` carries them as the narrow
structural protocols this port actually needs — a run it holds opaquely, and an outcome whose
disposition selects a completion branch — and keeps them off the package's public surface, so the
concrete types replace them without a name collision. That is the one place this implementation
runs ahead of a capability it cites, and it is deliberate and reversible.

## Handoffs

**Bootstrap 3.5** implements this port against PostgreSQL with COPY-to-staging and set-based merges,
choosing its own staging tables, merge SQL and the value of `max_batch_entries`. It owns durable
maintenance of `S4` when one continuing account's accumulated live set exceeds memory — maintaining
that set, never extending it: a released handle stays released. Those mechanics may not move inward,
and the port may not learn them.

**Bootstrap 3.6** proves the transition table against a real database: the oversized-`S4` case end to
end, every failure row leaving `S1`–`S6` and the staged rows exactly as they were, a released handle
still refused, and candidates drawn lazily.

**Bootstrap 2.4** mints correlation handles as it walks parsed records — the only layer holding both
a record and its parent — and carries adoptions inside the batches it builds rather than adopting
separately.

## Proof

`libs/property-tax-application/tests/test_canonical_load_session.py` implements the falsification
matrix, one case per table row or precondition identifier, against an in-memory session. Two
properties it exists for: every `B` refusal happens at construction with no session in sight, and
after every refusal the whole state is what it was — proven by retrying the rejected batch's own
handles and by completing to find none of its records.

One rule is proven as an **invariant** rather than a refusal. `W8` confines a delta to accounts the
batch carries, and writing the suite showed it has no reachable counterexample: `W9` confines a
retained handle to the continuing account, completion sweeps the rest, and `W7` confines a release to
what is live, so `S4` only ever holds the open account's handles. The attempt lands on `W9`. The
suite asserts the property `W8` guarantees instead of a refusal it cannot produce.
