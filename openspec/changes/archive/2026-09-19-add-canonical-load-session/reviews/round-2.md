# Round 2 — implementation review — findings at d5e024f

The first implementation round, reviewed on [PR #121](https://github.com/TruPryce/property-tax-data-platform/pull/121).
Three blockers and two contract defects, and two of the five are planning defects that only writing
the code could have exposed. The reviewer's verdict was REQUEST CHANGES with a narrowed path:
correct the plan, land the owned `processing-run` value slice, then rebase the implementation onto
concrete contracts.

## Reviewer's report (summary, findings verbatim in the PR)

- **BLOCKER — the cited run/outcome contracts are replaced by incompatible local substitutes.** The
  empty runtime-checkable `ProcessingRunRef` accepted every object, `isinstance(None, ...)`,
  `isinstance(7, ...)` and `isinstance("raw-run-id", ...)` all returning `True`, which defeats the
  very requirement that a port accept the reference type rather than a raw persistence value. The
  local outcome required `.accepted` where the owning task specifies `disposition:
  ReleaseDisposition`. And they could not be replaced "without collision" after all: the
  annotations on `ReleaseLoadCompletion.run` and `open_load` close over the local objects whether
  or not `__all__` mentions them.
- **BLOCKER — `W8` was simultaneously a write precondition, an unreachable invariant, and a
  required refusal.** The table still listed it, the prose said it could not be reached, two
  scenarios demanded refusals for it, the design said every `W` rule refuses on write, and the fake
  still contained a `W8` raise no test could reach.
- **BLOCKER — the implementation exceeded every accepted task path.** Task 2.1 authorized one test
  file; the implementation added `_fake_load.py` and edited `pyproject.toml`. Nothing authorized
  the bootstrap task-file edit or the CountyForge planning-test repair. One commit added the plan,
  changed it after implementation exposed `W8`, and checked all five tasks.
- **HIGH — a rejected completion was not retry-idempotent.** Completion was decided from persisted
  rows, and the rejected branch persists none: a retry rewrote the recorded outcome, and a retry
  carrying an accepted disposition manufactured a canonical load for a run whose durable outcome
  said rejected.
- **HIGH — `AccountSnapshotRef` admitted mutable and unhashable values.** `AccountSnapshotRef([])`
  constructed, then failed under `hash()`, and mutating the payload changed equality after
  construction — while the store indexes candidates by exactly these locators.

## Dispositions

1. **[P1] OPEN — carried by the implementation PR.** No substitute protocols. The proposal now
   states that tasks 1.2 and 2.1 wait for the owned `processing-run` slice and that no structural
   stand-in is permitted, with the reason: an empty runtime-checkable protocol accepts the raw
   persistence value the reference type exists to exclude.

2. **[P1] RESOLVED in this correction.** `W8` is retired rather than reused, and the rule it was
   trying to state is now `I1`, a **derived invariant**: every handle in `S4` belongs to the account
   `S2` names, at every point between operations. The table no longer lists it, no scenario demands
   a refusal for it, and the attempt lands on `W9` when retained and `W7` when released, which is
   what the scenarios now say. The obligation that replaces it has teeth in the other direction: an
   implementation holds `I1` after every operation, accepted or refused.

3. **[P1] RESOLVED in this correction.** Task 2.1 authorizes `_fake_load.py` and `pyproject.toml`
   and says why each is needed; new task 3.2 carries the bootstrap handoff edit. The CountyForge
   planning-test repair stays with PR #120, where it was made. This correction is a planning PR of
   its own, so the plan lands before anything implements it.

4. **[P2] RESOLVED in this correction.** A pairing is complete once **any** completion of it has
   succeeded, whatever branch it took, and completion is explicitly not inferred from the presence
   of canonical records. Three scenarios cover it, including a retry whose supplied disposition
   differs from the recorded one.

5. **[P2] RESOLVED in this correction.** `AccountSnapshotRef` wraps a value that is immutable and
   hashable and refuses one that is not at construction, with scenarios for both the refusal and
   the key-and-compare use. Opacity is not permission to carry anything.

```json
{
	"contract": "implementation-review-v1",
	"reviewed_commit": "d5e024f",
	"scope_id": "canonical-load",
	"verdict": "REQUEST_CHANGES",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```
