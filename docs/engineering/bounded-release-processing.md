# Bounded Release Processing

The production boundary a county release passes through: a single-pass reader, a
caller-supplied atomic stage, and a processor that stages records which stay invisible until
exactly one commit. The
[OpenSpec delta](../../openspec/changes/add-bounded-release-processing/specs/bounded-release-processing/spec.md)
is the normative contract.

This implements issue #43 decisions **D1, D2, D3, D4, D6, D8**, and the diagnostic portion of
**D5**.

## Why a Stage, Not an Iterator

PR #42 measured 663 MiB retained on 200,000 rows against a 4 GiB scheduler running four tasks,
because the Dallas entry point takes `bytes | str` and keeps both native and converted tuples.

Swapping that for an iterator is not enough. Every accepted county contract requires a failed
logical release to publish **zero** accepted records, and an iterator has already yielded by the
time a later row fails. So the boundary is a reader *plus* a stage.

## The Four Protocols

| protocol | owes |
| --- | --- |
| `PreparedReader` | `__enter__`/`__exit__`, `prepare() -> PreparedRelease`, `__iter__` yielding one envelope per physical row |
| `ReleaseStage` | `__enter__`/`__exit__`, `write(records)`, `finalize()`, `abort()`, `commit()` |
| `ProgressCallback` | `__call__(event) -> None`, synchronous |
| `ResourceGuard` | `check(rows, staged) -> None`, raising to reject |

`prepare()` is a **named method** rather than an implicit phase, because the diagnostic table
assigns `source_open_failed` to entry and `layout_rejected` to preparation. Without a call to
attribute each failure to, an implementation could only guess which applied.

`__exit__` is annotated as returning `None` rather than `bool` on both context managers. A `None`
return is always falsy, so the prohibition on suppressing an exception is carried by the signature
rather than by prose — a suppressed failure is one the processor cannot map to a code.

## The Lifecycle

```
 1  enter the county reader
 2  prepare, validate the layout, capture PreparedRelease   <- before any stage exists
 3  enter the stage
 4  guard checkpoint, before the first write
 5  per row envelope: verify agreement, write records       <- progress + guard every 100,000
 6  end-of-input: guard checkpoint, then the final progress event
 7  exit the reader                                         <- last failable cleanup
 8  finalize
 9  commit exactly once
10  exit the stage                                          <- may not fail, by contract
```

Three orderings are load-bearing:

**Layout validation precedes the stage** (step 2 before 3), so a misidentified member never opens
one. A pre-stage failure therefore calls no `abort` — there is nothing to abort.

**The final progress event precedes finalize and commit** (step 6 before 8). A final callback that
raises must be able to reject the release, and it can only do that while zero records are visible.
Emitting it after the commit would leave a callback reporting a failure it can no longer prevent.

**The reader is closed before the commit** (step 7 before 9), so nothing failable follows the only
step that changes visibility. A stage's `__exit__` may not fail after either a commit or an abort,
which is what makes step 10 safe where it is; a stage that raises there regardless is a
trusted-code defect and propagates, exactly as a malformed layout raises rather than diagnosing.

**The reader is closed exactly once, and only if it opened.** `__exit__` is a lifecycle call, not
an idempotent cleanup hook: a reader whose `__enter__` raised holds no resource to release, and one
already closed may not be closed again. Rejection cleanup therefore closes only a reader that both
opened and has not yet been closed. A close that fails during that cleanup is recorded as a second
`source_close_failed` diagnostic rather than suppressed — a source left open is a fact the caller
needs, and the failure that rejected the release is not a licence to lose it.

## Rows, Records, and Rejections

An envelope is one **physical row**, not one record, because the two are different counts: an
accepted Collin row already produces one record per observed family, and a row may produce none.

| envelope | meaning |
| --- | --- |
| records, not rejected | the row produced output |
| no records, not rejected | the row legitimately produced none |
| rejected | the row is invalid |

A reader signals invalidity by **marking** the envelope, never by raising. Raising ends iteration
at the first bad row, which would report one defect for a member with many and make the retention
cap unreachable.

On the first rejection the processor **stops writing and keeps reading**, then aborts at
end-of-input. Continuing the traversal is what makes a member's full diagnostic picture available;
ceasing writes keeps a doomed release from doing stage work that will be discarded. This mirrors
the accepted county parsers, which continue past a bad row and decide blocking at the end.

## Agreement

Before a record is written, its jurisdiction, release identifier, source member name, parser
contract version, layout fingerprint, and row number must equal the prepared release's and its
envelope's. A disagreement rejects the row and is never corrected: a record that disagrees with the
release it arrived in is evidence of a reader defect, and staging it would attribute a row to a
release or a position it did not come from.

## Duplicates Belong to the Stage

The processor retains no key set — that is the one thing that would reintroduce linear growth. A
stage signals a repeated key by raising the typed `DuplicateRecordKey`, from `write` where its
index is eager or from `finalize` where it is deferred; both map to `duplicate_record_key`.
Requiring one point would exclude bulk-loaded stages, which is most relational ones.

The distinction is carried **by type** rather than by message, because inspecting exception text is
forbidden by the privacy rules and could not be relied on across implementations.

## The Failure Vocabulary

Twelve codes, exactly. Issue #43 D5 names eight as a minimum; four more exist because the boundary
can genuinely reach them and a failure with no code would borrow one naming a different phase.

| failure | code |
| --- | --- |
| reader `__enter__` | `source_open_failed` |
| reader preparation or layout validation | `layout_rejected` |
| reader iteration, a rejected envelope, or a record disagreement | `record_rejected` |
| stage `__enter__` | `stage_open_failed` |
| `DuplicateRecordKey` from `write` or `finalize` | `duplicate_record_key` |
| any other `write` exception | `stage_write_failed` |
| any other `finalize` exception | `stage_finalize_failed` |
| `commit` | `stage_commit_failed` |
| `abort` | `stage_abort_failed` |
| reader `__exit__` | `source_close_failed` |
| a progress callback | `progress_callback_failed` |
| the resource guard | `resource_limit_exceeded` |

At most 100 diagnostics are retained, in encounter order, with the total preserved and truncation
marked. No exception text is retained, from any source.

## Notices Are Not Failures

A **diagnostic** is a failure, and a release is accepted exactly when it produced none. A
**notice** is a warning that does not reject.

Two channels rather than one because the accepted Dallas contract requires unknown columns to be
*accepted* and reported with `extra_columns_present`. With one channel a conforming Dallas reader
would have to refuse a valid layout or discard a warning its own contract requires.

The boundary enumerates no notice codes — they are county vocabulary, closed by county contracts —
so a code is a county-supplied identifier of 1 to 64 characters matching `[a-z][a-z0-9_]*`. The
bound is what stops free text arriving where a code belongs.

Each carrier bounds what it **retains**, not what it accepts: a `NoticeSet` holds the first 100 and
counts the rest, built incrementally rather than materialized and trimmed. Raising past the bound
would make a non-fatal notice fatal, and Dallas emits one per unknown header with no limit in its
contract — a release with 101 extra columns would be refused for having too many warnings.

## The Outcome

Fourteen fields, with the invariants stated rather than implied. Notably:

- `disposition` is `accepted` exactly when `total_diagnostic_count` is zero.
- `parser_contract_version` and `layout_fingerprint` are `None` unless `prepare()` returned, and
  are set together or not at all. A `source_open_failed` outcome has no reader to have produced
  either, and a fabricated placeholder would be indistinguishable from a real fingerprint.
- `committed_record_count` is zero unless accepted, and equals `staged_record_count` when it is. A
  staged record is not an accepted one until the commit that makes it visible.
- `diagnostics` and `notices` are checked **element by element**, not merely for being tuples of the
  right length. The element type is the carrier: a correctly-counted tuple of strings would satisfy
  every count above while holding exactly the free text these types exist to make unrepresentable.

## The Release-Identity Bound

`jurisdiction_code`, `release_identifier`, and `source_member_name` are bounded identifiers — the
bound the accepted Tarrant contract already sets. The alphabet admits no path separator, so an
absolute path, a UNC path, a drive-qualified path, and a parent-directory traversal are
*unrepresentable* rather than merely discouraged.

`ReleaseProgressEvent` applies the same bound as `PreparedRelease`, not a weaker one. An identity a
reader may not hold but an event may is not a bound, and a progress stream is precisely where a
host-local path would otherwise reach a log.

## Dependency Direction

`release` imports no county module. A county **may** import the release records and protocols — a
reader has to construct `PreparedRelease` and `SourceRowEnvelope` values to conform at all — and
**may not** import the processor: driving a release is the caller's job, and a county able to
invoke one from inside a parser would invert the boundary.

## What This Change Excludes

The resource half of issue #43 D5 is a separate change that depends on this one:

- the **900 MiB** peak-RSS target, which supersedes the issue body's 1 GiB because the scheduler's
  measured 400 MiB peak shares the same 4 GiB container — see
  [the Airflow runtime notes](airflow-implementation.md);
- the requirement that memory not grow linearly with row count;
- the cgroup `memory.peak` and `ru_maxrss` measurement method;
- the reproducible 1,000,000-row, 90-column benchmark.

`ResourceGuard` is the seam that change plugs into: this boundary fixes **when** it asks and never
**what** is measured.

Also excluded: durable quarantine persistence and the production unique index, owned by bootstrap
tasks 3.4 and 3.5. The SQLite stage in the test suite is a **fixture** proving the conformance
suite has a passing implementation — it is not a production stage.

That fixture takes the key it indexes on **from its caller**. Reading `source_account_id` itself
would assert that the field is a record's canonical identifier, which the accepted Collin contract
prohibits: Collin sets it to `None` and preserves `prop_id` and `geo_id` under their own source
names. A stage that chose for the caller would report a conforming Collin release as a duplicate.
The fixture also removes its file on success, on failure, and on a partial `__enter__`, since a
caller who supplied a directory did not ask to be left a database in it.

`parse_dallas_appraisal_csv` remains a synthetic fixture helper. No production processor imports or
invokes it, and all its contract cases still collect unchanged.

## Detecting Read-Ahead

The conformance suite detects **input-proportional** accumulation, not buffering. It drives a
candidate reader from a guarded pull source, computes the lead as pulls minus **envelopes
consumed**, and requires the maximum to stay within a declared constant *and* be identical across
fixtures of 1,000 and 8,000 envelopes.

Records are the wrong denominator twice over: a row may produce zero or several, and the processor
stops writing at the first rejected row while it keeps reading, so a conforming reader on a
rejected release would show a lead climbing against a frozen write count.

A reader holding a constant-size buffer conforms. One that materializes its member does not,
because only its lead grows with the member. The check reads no resident set size, cgroup file, or
allocation counter — read-ahead is observable without them, which is what keeps the two changes
separable.
