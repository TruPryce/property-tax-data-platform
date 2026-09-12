## Why

Bootstrap 3.5 implements the canonical load against PostgreSQL and needs an application contract
to implement rather than one to invent while designing SQL.

That contract was one scope of five in `add-application-port-boundary` (issue #119, PR #120), and
ten review rounds there showed why it cannot stay: the canonical load is a stateful transactional
protocol, the other four scopes are value contracts, and a protocol written as prose across a
spec, a design, a decision list, a task list, and two handoffs cannot be checked for completeness.
Every correction was locally right, changed the state space, and exposed the next interaction; two
of the last three findings were defects introduced by the fix before them. The full account is in
`design.md`.

Separating the capability is half the remedy. The other half is the artefact: one authoritative
transition table in the spec, with every requirement, scenario, and task referring to it.

## What Changes

- **ADDED** capability `canonical-load-session`: the session state machine and its transition
  table, `CanonicalReleaseRepository`, `ReleaseLoadSession`, `CanonicalRecordBatch`,
  `CorrelatedRecord`, `CorrelationHandle`, `AccountSnapshotRef`, `AdoptableSnapshot`,
  `AdoptedParent`, `ReleaseLoadCompletion`, the retry key, and the no-natural-key rule.
- **MODIFIED** the sibling change `add-application-port-boundary`: it loses this capability, its
  spec delta, its two canonical tasks, ten decisions, six design sections, its canonical
  falsification block, and the `canonical-load` review scope, and cites this change instead.
- **MODIFIED** bootstrap tasks 3.5 and 3.6: they reference the transition table by ID rather than
  paraphrasing its rules.
- No code, no migration, no adapter, and no orchestration change. Implementation of the tasks in
  this change waits for an accepting review round.

## Outcome

Add the `canonical-load-session` capability as its own change: the session state machine, the
batch and its correlation, batch-scoped adoption of a persisted snapshot, completion, and the
retry key. `add-application-port-boundary` keeps the remaining four scopes and cites this
capability rather than defining it.

## Scope

- Originating issue: #119 (bootstrap task 2.3), carried out of PR #120
- Affected capabilities: one, ADDED — `canonical-load-session`
- Affected changes: `add-application-port-boundary` loses this capability, its two canonical
  tasks, and its canonical decisions, and cites this change instead
- Affected decisions: none outside this change. Hexagonal ownership is settled in the root
  `AGENTS.md`; this change works inside it.

### Capabilities

| Capability | Owns | Cites |
| --- | --- | --- |
| `canonical-load-session` | the session state machine `S1`–`S6` and its three operations, `CanonicalReleaseRepository`, `ReleaseLoadSession`, `CanonicalRecordBatch`, `CorrelatedRecord`, `CorrelationHandle`, batch-scoped adoption, `ReleaseLoadCompletion`, the retry key, the no-natural-key rule | `processing-run` for `ProcessingRunRef` and `ReleaseProcessingOutcome`; `source-registry-and-discovery` for `ReleaseIdentity`; `application-port-boundary` for the opaque-locator rule; the accepted `canonical-appraisal-records` and `canonical-silver-persistence` specs |

## Decisions

- **D1 — The state machine is the authority, and it lives in one table, in the spec.** The
  capability spec defines the fixed context `S0`, six state components, three operations, every
  precondition with an ID, and the transitions of each operation. It is in the **spec** and not in
  `design.md` because the spec is what promotion keeps: a table that is authoritative and archived
  would leave the promoted contract citing a document the reader no longer has. The spec's other
  requirements, its scenarios, `design.md`, and the tasks all reference the IDs; nothing restates
  them. A transition absent from the table does not exist, and
  any text elsewhere that disagrees with the table is a defect in that text. This is a direct
  response to ten rounds in which the same protocol was described in five places and no reader
  could tell whether a rule was complete.

- **D2 — Every failure transition leaves the complete state unchanged.** Not "leaves the live set
  alone", which was the first version, nor "leaves the live set, the high-water mark and the
  continuing account alone", which was the second and still omitted the staged records. Each
  failure row of the table is empty across every one of `S1`–`S6`, which is one rule a reader can
  check by looking rather than five a reader has to assemble.

- **D3 — Adoption is carried by the batch, not by the session.** A standalone `adopt()` minted a
  handle and opened an account outside every transition, and cost three consecutive review
  findings: a high-water mark moved outside the machine, an unbounded way around the
  one-open-account rule, and a failure case with no atomicity story. Carried by the batch, an
  adopted handle is an introduced handle, a refused batch adopts nothing, and adoption adds one
  session precondition (`W4`), one intrinsic precondition (`B9`), and no transition at all.

- **D4 — Adoption names a snapshot by an opaque locator paired with the snapshot it locates.**
  Never the grain, which the accepted persistence contract makes deliberately non-unique, and
  never provenance alone, since two snapshots of one account and release can share a provenance
  and differ only in a composed situs or legal value. The pair is verified because a caller can
  assemble one by hand, and binding a handle to an object the locator never named is the exact
  ambiguity the locator exists to remove.

- **D5 — Correlation is a bounded delta over an accumulating set.** No declaration bounds nothing
  inside one account; a full re-declaration must fit in a bounded batch and so caps the set at one
  batch's worth. Deltas keep every declaration bounded while letting the accumulation be as large
  as the caller's own retain-and-release discipline makes it. The same arithmetic rules out a
  closing batch that "releases what remains", which is why closing an account carries nothing at
  all and completion sweeps it.

- **D6 — `max_batch_entries` is stated by the session, not implied.** A bound nothing names is an
  adjective. It is an integer of at least one and not a boolean, counts entries plus adoptions
  plus each delta's values, does not change while the session is open, and is readable so a caller
  sizes what it builds. The session enforces it, because a batch that knows only itself cannot
  know it.

- **D7 — An account completes inside a batch, never through an operation of its own.** A separate
  completion operation gave one fact two sources and left the case of a handle retained by the
  very batch that completes its account undefined. The signals are all carried by one atomic
  batch: `continuing` says the account stays open, `closing` says it ends here, and a legitimate
  touch without either says the same — each settled with the batch that carries it, so nothing
  completes an account outside a transition. Retaining a handle of an account the batch does not
  carry onward is refused as the contradiction it is.

- **D8 — A completion that fails is not terminal.** `S1` stays `OPEN` and the rest is unchanged,
  so a caller that committed with an account still open closes it and commits again. Only a
  successful completion or an abort ends a session, and every operation after that is refused
  explicitly rather than ignored.

- **D9 — A batch says how the open account ends, and silence is not an answer.** An account
  cannot always be closed by touching it: its live handles may outnumber `max_batch_entries`, so a
  closing batch may have nothing it is able to carry. The batch therefore carries an explicit
  `closing` declaration beside `continuing`. Without it the boundary would have to read a batch
  that says nothing about the open account as either "close it" or "an accident", and it cannot
  tell those apart — which is how an earlier draft produced a rule nothing could falsify, and then
  a rule that made an empty close impossible.

- **D10 — Completion branches on the outcome's disposition.** The outcome is fixed in `S0`, so a
  caller may stage records and then complete a run the outcome says was rejected. A single
  "records and outcome become durable together" transition would persist them, and nothing
  downstream would catch it. The rejected branch records the outcome and discards the records; the
  already-complete branch discards them too, rather than merging them into the earlier load.

## Constraints

- No new dependency in `property-tax-application`.
- No migration, no adapter change, and no orchestration change.
- No port names a schema, table, cursor, connection, transaction, bulk-load mechanism, conflict
  clause, or surrogate key.
- The accepted `canonical-silver-persistence` contract is authoritative for what persists: this
  change adds no key over observed values and weakens no cardinality it settled.

## Non-goals

- The PostgreSQL implementation, its staging tables, its merge SQL, and its choice of
  `max_batch_entries` — bootstrap 3.5.
- The containerised proof of the transitions against a real database — bootstrap 3.6.
- The use cases that mint handles and build batches — bootstrap 2.4.
- The four remaining scopes of PR #120, which resume once this capability is accepted.

## Unresolved decisions

None. The findings that were open against this scope in PR #120's ledger are all closed here, and
the three still-open findings in that PR belong to `run-and-manifest`, `registry-and-discovery`,
and `quality-publication-clock`.
