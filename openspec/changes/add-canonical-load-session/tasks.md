# Tasks

Every module below lives in `libs/property-tax-application/src/property_tax_application/`. Where a
task says a type is **frozen**, it means a frozen slotted dataclass validating in `__post_init__`
and raising `ValueError`, matching the established style of `AcquiredArtifact` and the canonical
record model. Where it says a port is a **Protocol**, it means `@runtime_checkable class
X(Protocol)`, matching `ArtifactSink` and `BronzeStore`.

**The transition table in
[`specs/canonical-load-session/spec.md`](specs/canonical-load-session/spec.md) is the
authoritative specification of this capability**, and it is in the spec rather than in
`design.md` because the spec is what promotion keeps. The fixed context is `S0`; state components
are `S1`–`S6`; intrinsic preconditions are `B1`–`B10`; session preconditions are `W1`–`W12`,
`C1`–`C2`, `A1`, and the general rule `G1`. `design.md` carries the reasoning and the
falsification matrix, and restates no transition. No task below restates one either, and none may
be implemented from this file alone: where a task names an ID, the spec says what it means, and
where the two ever disagree the spec wins and the task is the defect.

No task adds a dependency to `property-tax-application`. No task edits a migration, an adapter, or
any orchestration code. This change and `add-application-port-boundary` both extend
`__init__.py`, the application documentation, and the architecture test; whichever lands first
creates what it needs and the other adds to it, without changing what is already there.

**Review scope** — one scope, `canonical-load`, covering every task in this change, per
[`reviews/README.md`](reviews/README.md). Implementation waits for an accepting round or a
recorded authorization.

## 1. The values

<!-- countyforge-task: 1.1 paths=libs/property-tax-application/src/property_tax_application/canonical.py checks=repo.check risk=higher_risk prerequisites=D1,D4,D5,D6 -->

- [ ] 1.1 Add the batch, its correlation, and the adoption candidate — Add `canonical.py` carrying `CorrelationHandle`, `CorrelatedRecord`, `CanonicalRecordBatch`, `AccountSnapshotRef`, `AdoptableSnapshot`, `AdoptedParent` (one candidate paired with the one handle the batch binds to it, so no binding is inferred from position), `ReleaseLoadCompletion`, `UnknownAccountSnapshot` (a locator resolving to no snapshot of the release being loaded), and `AdoptableSnapshotMismatch` (a locator resolving to a snapshot other than the one its candidate carries) — two different facts, and a caller that cannot separate them cannot tell a stale locator from an assembly mistake. `CanonicalRecordBatch` carries entries, `AdoptedParent` adoptions, `continuing`, `closing` (the account it deliberately completes, which an account with more live handles than the maximum can only be closed by), and the two deltas, and validates exactly `B1`–`B10` and nothing else: it is a frozen value that knows only itself, so it judges neither `S4`, `S6`, nor `max_batch_entries`. `B1` governs an entry's shape only — add no rule that two entries' canonical records must differ, which would be the deduplication over observed values this capability forbids. `CorrelationHandle` is an integer of at least one that is not a bool, guarded as `isinstance(value, bool) or not isinstance(value, int)`, matching `archives.py`. `AccountSnapshotRef` is an opaque locator documented on the same terms as `ProcessingRunRef`; `AdoptableSnapshot` pairs one with the `AccountSnapshot` it locates. `ReleaseLoadCompletion` carries the `ProcessingRunRef` and `already_complete` and deliberately no per-account locator. Use no generic mapping, JSON payload, free-form metadata attribute, or database-shaped row type, and define no key over observed values.

<!-- countyforge-task: 1.2 paths=libs/property-tax-application/src/property_tax_application/canonical.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D3,D6,D7,D8,1.1 -->

- [ ] 1.2 Add the session and the repository — In `canonical.py`, add `ReleaseLoadSession`, a Protocol with `__enter__` and `__exit__` annotated `-> None` so a failure cannot be suppressed; `max_batch_entries`; and exactly the three operations `write(batch)`, `commit()`, and `abort()` — no fourth, and specifically no operation that adopts a parent or declares an account complete, both of which the transition table deliberately has no row for. Open a session in the initial state the table names — `S1` open, `S2` none, `S3` and `S4` empty, `S6` with no handle yet introduced, `S0` complete — and implement `G1`, `W1`–`W12`, `C1`–`C2`, and `A1` as the table states them, with the success rows applying together at the batch boundary and **every failure row leaving `S1`–`S6` untouched**, staged records and `S6` included. `commit()` takes the branch the `S0` outcome's disposition selects, so a rejected outcome is recorded and its staged records are discarded rather than persisted, and an already-complete pairing discards them rather than merging them. Refuse to open a session whose `S0` cannot be completed, leaving no session behind, and keep locator resolution the repository's, scoped to `S0`'s release and exposed as no operation of its own. Add `CanonicalReleaseRepository`, opening a session for a `ReleaseIdentity`, `ProcessingRunRef`, and `ReleaseProcessingOutcome`, and offering an account and release's adoptable snapshots as a lazy `Iterator[AdoptableSnapshot]`, never all drawn before the first is consumed. Name no schema, table, cursor, connection, transaction, bulk-load mechanism, conflict clause, or surrogate key.

## 2. Proof

<!-- countyforge-task: 2.1 paths=libs/property-tax-application/tests/test_canonical_load_session.py checks=repo.check risk=standard prerequisites=D1,D2,1.1,1.2 -->

- [ ] 2.1 Prove the state machine by falsification — Add `libs/property-tax-application/tests/test_canonical_load_session.py` with an in-memory fake session, and implement **every case in the falsification matrix** in [`design.md`](design.md). The matrix is the authoritative list; do not treat this line as a summary of it, and add a case there rather than here when one is missing. Three properties are what this suite exists for and none may be asserted indirectly: every `B` refusal happens at construction with no session at all; each of `W10`'s three satisfiers is exercised, including an **empty** batch closing an account whose live handles outnumber the maximum; and after every refusal each of `S1`–`S6` is what it was — proven positively, by a corrected retry reusing the rejected batch's handles and by a completion that holds no record from the rejected attempt, not merely by asserting an exception. Assert `AccountSnapshotRef` supports equality and not ordering. Ensure the module is collected by the default configuration.

<!-- countyforge-task: 2.2 paths=libs/property-tax-application/src/property_tax_application/__init__.py,tests/architecture/test_dependency_direction.py checks=repo.check risk=standard prerequisites=1.1,1.2 -->

- [ ] 2.2 Publish the surface and prove it names no infrastructure — Export every type this change adds from `__init__.py` through the explicit `__all__`, adding to what is there rather than reordering or removing it. Extend `tests/architecture/test_dependency_direction.py` so `canonical.py` is covered by the existing rule that no identifier, annotation, or string literal in the public surface names a database schema, table, or driver, stripping docstrings first so an explanatory comment naming PostgreSQL is not read as a dependency.

## 3. Documentation

<!-- countyforge-task: 3.1 paths=docs checks=repo.check,repo.docs risk=standard prerequisites=1.1,1.2,2.1 -->

- [ ] 3.1 Document the session and its handoffs — Describe the canonical load port in the application area's documentation: what it owns, what it deliberately does not, and the transition table by reference to the promoted spec rather than by copy, since a second copy is the failure this change exists to correct. State the three handoffs by name: bootstrap 3.5 implements the port with COPY-to-staging and set-based operations, chooses `max_batch_entries`, and owns durable maintenance of `S4` without extending it; bootstrap 3.6 proves the transitions against a real database; bootstrap 2.4 mints handles and carries adoptions in the batches it builds. Add no new document tree and no diagram that restates the table.
