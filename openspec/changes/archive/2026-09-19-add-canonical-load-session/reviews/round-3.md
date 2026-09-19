# Round 3 — implementation review — findings at d5e024f and 77b4565

Two implementation rounds against the same scope, recorded together because the second is what the
first's fixes exposed. The reviewer's verdict both times was REQUEST CHANGES, and both times two of
the findings were defects in an accepted plan rather than in the code written against it.

## At `d5e024f` — the first implementation

Three blockers and two contract defects: local structural protocols standing in for the cited run
and outcome types; `W8` simultaneously a precondition, an unreachable invariant and a required
refusal; task paths that did not authorize what the implementation wrote; a rejected completion that
was not retry-idempotent; and a locator admitting mutable payloads.

Resolved by three merged changes rather than inside the implementation: PR #122 corrected the plan
(`W8` retired for `I1`, completion never inferred from rows, the locator contract, the task paths),
PRs #123 and #125 added and implemented the `processing-run-values` capability the session cites,
and PR #124 took the repository-dependent planning test out of capability work.

## At `77b4565` — the implementation against those corrections

Three blockers and two gaps, all accepted:

1. **[P1] RESOLVED by PR #126.** The plan still cited `processing-run` and named
   `add-application-port-boundary` as owner, after the value slice moved to `processing-run-values`.
   Promotion preserves what the plan says, so the promoted capability would have cited a capability
   that does not own what it cites.

2. **[P1] RESOLVED in this implementation.** The concrete types were imported and the boundary still
   accepted the raw substitutes: `open_load` checked only `is None`, and `ReleaseLoadCompletion`
   validated only its flag, so a raw run id reached a session and failed much later at the first
   attribute access. The architecture test proved raw values are not *instances of* the reference
   type and never that the port refuses them — the test and the boundary were checking different
   things. Both now require the owned types, and the raw values are driven through both boundaries.

3. **[P1] RESOLVED by PR #127, applied here.** `hash(value)` establishes nothing: an object whose
   `__hash__` reads a mutable attribute passes the probe and then moves, and the entry filed under it
   becomes unreachable with nothing raising. The owner now admits a payload by **exact type** — a
   `str`, an `int`, or a flat non-empty tuple of those, since `isinstance` admits a subclass that
   overrides `__hash__` — and `AccountSnapshotRef` borrows that rule rather than restating it.

4. **[P2] RESOLVED in this implementation.** Task 2.1 was checked while two authoritative
   falsification cases were absent. The fake gained durable-write failure injection, without which
   the failure row of `commit` cannot be reached at all and its atomicity is a description rather
   than a proof; the suite gained the failed completion, the retry after the write recovers, and the
   abandoned session that leaves an earlier load untouched.

5. **[P3] RESOLVED in this implementation.** Seven active descriptions still said `W1`–`W12` or
   credited `W8` with account scope. They are the route by which a retired precondition comes back,
   so all seven now read `W1`–`W7`, `W9`–`W12` with `I1` derived. The deliberate historical passages
   — "there is no `W8`", and why — are kept.

## At `d0c2231` — a fourth round on the injection itself

One blocker and one stale heading, both accepted:

6. **[P1] RESOLVED.** The failure injection was hidden session state and raised *before* any durable
   write. Two defects in one: a seventh component on a session whose contract says it holds `S1`-`S6`
   and nothing else, and a "failed completion" that never touched the store, so "leaves zero
   records" passed without a rollback ever happening. The knob now lives on the **store** — where a
   durable write actually fails — and the failure lands **between** writes, with the records already
   stored. What the suite observes is the rollback, asserted positively: `partial_write_applied` is
   true and the store is empty again. Mutation-checked both ways — remove the restore, or fail
   before the first write, and the suite fails.

7. **[P3] RESOLVED.** One active `W1-W12` heading remained in the suite.

## At `b5e539f` — a fifth round on the rollback itself

8. **[P1] RESOLVED.** The rollback **rebound** the store's attributes to snapshot copies rather
   than restoring the containers. Anything holding a reference taken before the transaction — a
   component, a caller, a test that captured `store.loads` — kept looking at the original, which
   still held the failed write, so the rollback existed only for whoever reached it through the
   store object. Reproduced before fixing: the held reference showed the failed load while
   `store.loads` showed `{}`. The restore now mutates in place, and a test asserts the container is
   the same object *and* empty.

9. **[P3] RESOLVED.** Two gaps in the evidence. `partial_write_applied` was never reset, so a later
   assertion could pass on what an earlier transaction observed; it is cleared at the start of each
   transaction. And the already-complete branch had no regression against a failing store — a store
   set to fail on its first write is the sharpest way to say the branch persists nothing, since any
   write at all would raise instead of reporting the retry.

## At `f3539df` — a sixth round on the same rollback

10. **[P1] RESOLVED.** The rollback proof covered `loads` and neither of the other two containers.
    Confirmed before fixing: rebinding `outcomes`, and removing the `completed` restore entirely,
    both survived the whole suite. The failure point is now parameterised over **every** durable
    mutation in each branch, and each case asserts identity and contents for all three containers,
    with one case that has an earlier load to lose rather than only asserting emptiness.

    Reaching the last mutation's rollback needed a failure that does not exist yet in the fake: a
    transaction where every write lands and the commit itself fails, which is what a database does
    when COMMIT is what goes wrong. Without it, restoring the completion marker was code no test
    could exercise — the same unreachable-rule defect as `W8`, this time in the suite rather than
    the spec. Each container's restore now fails the suite when removed.

## Found while implementing

The `I1` assertion was first written **inside** the fake session, and deleting it changed nothing:
99 tests still passed. A subject that checks its own invariant fails together with the thing it
checks. Moved outside, breaking the sweep of a completed account's handles fails five tests. The
fake's docstring now says why it deliberately does not self-check.

```json
{
	"contract": "implementation-review-v1",
	"reviewed_commit": "77b4565",
	"scope_id": "canonical-load",
	"verdict": "REQUEST_CHANGES",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 0
}
```
