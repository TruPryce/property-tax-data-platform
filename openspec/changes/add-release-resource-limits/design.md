## Current-state evidence

Read on `main` at the time of drafting.

`docs/engineering/airflow-implementation.md` already carries the budget and the method, and this change implements what that document describes rather than inventing it:

- The scheduler container is capped at 4 GiB with `AIRFLOW__CORE__PARALLELISM=4`, and the scheduler's own measured peak is 400 MiB. `(4096 − 400) / 4 ≈ 900 MiB` per task.
- It already gives the `ru_maxrss` probe verbatim — `max(RUSAGE_SELF, RUSAGE_CHILDREN) × 1024` — and notes that `RUSAGE_CHILDREN` accounts only for reaped children.
- It names the cgroup as the authority inside a container: `memory.peak` beneath the cgroup `/proc/self/cgroup` reports, cgroup v2, bytes.
- It rejects `tracemalloc` with a measurement: 663 MiB traced against 2,079 MiB resident on the same run.

The `bounded-release-processing` capability, introduced by the now-archived `add-bounded-release-processing` change and implemented on `main`, declares the seam this change fills: a `ResourceGuard` with `check(physical_rows_processed: int, staged_record_count: int) -> None`, called after the stage is entered, at every 100,000-row boundary, and once at end-of-input, with a raise mapping to `resource_limit_exceeded`. It states in as many words that what is measured belongs to a second change.

Nothing in `libs/property-tax-adapters/` measures memory today, and there is no benchmark target in the `Makefile`.

## Proposed architecture

```
resources/peak_rss.py   PeakRssSample, PeakRssSource, read_peak_rss, PeakRssGuard
tests/release/scale.py  synthetic_release(rows, columns) -> PreparedReader
benchmarks/release_peak_rss.py   the acceptance command behind `make release-benchmark`
```

`read_peak_rss()` returns a `PeakRssSample` carrying the byte figure **and** which source produced it (D32). Returning a bare integer would make two measurements incomparable, since the cgroup and `ru_maxrss` do not measure the same thing.

`PeakRssGuard` holds a limit in bytes and implements `check` by sampling and comparing. It adds nothing to the protocol (D33): no extra checkpoint, no state the boundary can see, no field on any boundary type.

## Why a ratio, not a threshold

Issue #43 D5 requires two different things, and only one of them is a number:

1. peak RSS under 900 MiB at a million rows — an absolute;
2. memory must not grow linearly with row count — a **shape**.

A single absolute cannot establish the second. An implementation that retained every row could still pass at a million rows on a large enough machine, and would then fail at ten million with no warning that anything was wrong. So the benchmark runs twice, at 250,000 and 1,000,000 rows, and requires the peak to grow by far less than the fourfold row increase (D36). A bounded implementation's peak is roughly flat across the two; a linear one's quadruples.

Reporting both figures also makes the result falsifiable by a reader: one number invites trust, two numbers and a ratio invite checking.

## Generating a million rows without a million-row file

The generator yields `SourceRowEnvelope` values directly from a counter (D35). Nothing is written to disk, so nothing measures the filesystem, and no fixture that size can reach the repository — which the artifact policy forbids anyway.

Ninety columns is the floor issue #43 D5 sets, so the generator's default meets it and the benchmark states the count it used.

## Dependency direction

`resources.peak_rss` → `release.protocols` → `sources.contracts` → standard library. The probe sits beside `release` rather than within it: that package's accepted tests assert per module that it imports only eight standard-library names, and a probe needs `resource` and a filesystem read. The benchmark and the generator live outside the library, in `benchmarks/` and `tests/`, so nothing shipped imports them.

The guard is the only new implementation of an accepted protocol, and it is a *caller-supplied* collaborator: `process_release` takes it as a keyword argument and works without one. Nothing in the boundary imports `resources`, and the dependency runs one way only.

## What this cannot show

The benchmark measures one process on the machine that runs it. It does not prove behaviour under four concurrent tasks inside a 4 GiB container — the arithmetic that produced 900 MiB assumes four such tasks, and running four is a runtime exercise this change does not take. What it does establish is that one task's peak fits the per-task budget and does not scale with release size, which is the part a library can be responsible for.

Stating that limit here is deliberate. A benchmark whose scope is overclaimed is worse than none, because it invites the conclusion that the container question is settled.

## Alternatives considered

- **`tracemalloc`.** Rejected by issue #43 D5 and by measurement: 663 traced against 2,079 resident. It misses native buffers, memory-mapped files, child processes, and freed-but-unreturned arenas.
- **An absolute threshold alone.** Cannot distinguish bounded from linear, per the ratio argument above.
- **Committing a million-row fixture.** Forbidden by the artifact policy and by issue #43's constraints, and it would measure file reading rather than the boundary.
- **Running the benchmark in `pytest`.** Rejected under D37: issue #43 D5 separates deterministic bounded CI tests from the acceptance command, and a multi-minute allocation-heavy run would be paid on every commit.
- **A warn-only guard.** Rejected under D34. The alternative to rejecting is being killed by the OOM killer, which yields no outcome, no diagnostic, and no progress event.

## Decisions and assumptions

D31 through D39 are stated in the proposal. Two assumptions, both checkable at implementation time:

- A cgroup v2 host exposes `memory.peak` beneath the relative path `/proc/self/cgroup` reports, and readability of *that* path — not of the mount root, which a nested cgroup does not populate — is a sufficient test for which source applies when none is named. Where it is unreadable the `ru_maxrss` fallback is used and named; where a caller named `cgroup_v2` explicitly, an unreadable path raises instead, per D38.
- A synthetic generator producing ninety-column rows exercises the boundary's memory behaviour representatively. It does not exercise any county's parsing, which is deliberate: this measures the boundary, and a county reader's own costs belong to that county's work.

## Unresolved decisions

- None.

## Risks and compatibility

Nothing existing changes behaviour. The guard is optional, the generator is a test fixture, and the benchmark is a separate target.

The real risk is a benchmark that passes for the wrong reason — a run that never actually exercised the boundary, or one whose two sizes were too close to distinguish shapes. The plan therefore requires the benchmark to report every figure it derived a verdict from — the baseline, both size peaks, both working sets, the ratio, the separate cgroup measurement the absolute used, the source of each, whether the comparative sources agreed, whether the cgroup was verified isolated, and the two verdicts separately — so a reader can tell what was run rather than trusting that something was.

## Testing strategy

CI tests are deterministic and bounded, never the million-row run. They cover the probe's source precedence with the nested cgroup path present and absent, the explicit-source path including a named source that cannot be read, which raises the typed `PeakRssSourceUnavailable` the benchmark catches to report an indeterminate absolute, that a sample always names its source, that the guard raises at and above its limit and not below, including the exact-limit boundary, and that a raising guard surfaces as `resource_limit_exceeded` through the accepted boundary rather than as anything else.

The generator is tested for shape at small sizes — row count, column count, envelope well-formedness — and for the property that it holds no accumulated state, so the thing measuring memory does not itself retain the release.
