# Release Resource Limits

The memory half of issue #43 decision D5: a per-task budget, a probe that names
its source, a guard that rejects before the OOM killer acts, and an acceptance
benchmark that must calibrate itself before its verdict counts. The
[OpenSpec delta](../../openspec/changes/add-release-resource-limits/specs/release-resource-limits/spec.md)
is the normative contract until this change is archived and the capability is promoted.

The boundary this measures — the protocols, the lifecycle, the vocabulary, and
the outcome — belongs to the
[bounded-release-processing capability](../../openspec/specs/bounded-release-processing/spec.md)
and is not modified here. This change supplies an implementation of a
`ResourceGuard` that capability already declares.

## The Budget, and Where Its Margin Runs Out

Tasks run inside the scheduler container, capped at 4 GiB with a parallelism of
four. The scheduler's own footprint comes out of that ceiling first, so the
per-task budget is not `4096 / 4`:

```
(4096 MiB − 419 MiB) / 4 tasks ≈ 919 MiB per task
```

The target is **900 MiB**, which supersedes issue #43's body figure of 1 GiB and
leaves 19 MiB of headroom.

**The 419 MiB is the scheduler container's `memory.peak` read with no task
running.** It is not an isolated measurement of the scheduler process: a cgroup
peak charges the whole subtree and only ever rises. Both properties matter. It
bounds the scheduler's share from above rather than measuring it, which is the
safe direction for a subtraction — and it can drift upward with nothing
watching. **A scheduler peaking at 496 MiB would leave exactly 900 MiB**, and
nothing currently alerts on that.

## Two Sources, Which Are Not Comparable

| source | what it measures | who reads it |
| --- | --- | --- |
| `cgroup_v2` | the cgroup and its whole subtree | the benchmark's absolute check |
| `rusage` | one process, plus a partial reaped-child signal | the guard, and the benchmark's ratio |

Every sample names its source, because a number that does not cannot be compared
with another. `read_peak_rss()` prefers the cgroup when no source is named and
honours a named one; a named source that cannot be read raises
`PeakRssSourceUnavailable` rather than substituting, since substituting silently
produces the vacuous ratio that naming exists to prevent.

The cgroup path is **resolved** by joining the mount with what
`/proc/self/cgroup` reports, never assumed. A nested cgroup — every process
under systemd, every container under a delegated slice — has no `memory.peak` at
the root. Resolving is not the same as refusing the root: a process in a cgroup
namespace legitimately reports `/`, and there the resolved path *is* the root.

`tracemalloc` is never a source. One measured run reported 663 MiB traced
against 2,079 MiB resident, and the OOM killer reads resident set size.

## The Guard Measures One Task

`PeakRssGuard` reads `rusage` and offers **no cgroup mode**. The 900 MiB budget
is per task while a shared container's cgroup measures the container: on one
host a process whose own peak was 28.0 MiB sat in a cgroup peaking at
1,072.3 MiB, so a cgroup-reading guard would have rejected it — and every other
compliant task there, more reliably the busier the container got. A guard that
rejects compliant work is worse than no guard.

A cgroup mode would also need its subtree precondition re-verified at every
checkpoint, since a process can join afterwards; verifying once at construction
proves nothing.

It raises at **or above** its limit, so a peak of exactly 900 MiB is refused by
the guard and by the acceptance target alike. It exposes `last_sample`, the most
recent sample and no history, set *before* an over-limit check raises so a
rejection carries the figure that caused it.

### What the guard does not see

`RUSAGE_CHILDREN` counts only children that have terminated and been waited for,
and reports the largest of them rather than a sum — measured at 0 MiB while two
300 MiB children were alive and 308 MiB once both were reaped.

| case | what the guard sees |
| --- | --- |
| memory held by the process it runs in | covered |
| a live child of that process | invisible |
| reaped children | the largest, never the sum |
| an unrelated sibling in the container | invisible, which is correct — not this task |

There is **no single-process guarantee** to appeal to: `PreparedReader` and
`ReleaseStage` are caller-supplied protocols, and nothing forbids a conforming
reader from spawning a decoder or an extractor. `RUSAGE_CHILDREN` stays in the
maximum because it can only make the tripwire fire sooner, which is the safe
direction — as a partial signal, not as coverage.

## Two Checks, Reading Different Measurements

The **scaling** check takes three `rusage` measurements — a baseline at 0 rows,
`P1` at 250,000, `P2` at 1,000,000 — each in its own subprocess, and fails
closed if their sources disagree. The **absolute** check takes a fourth
measurement from the cgroup. A figure from one group never satisfies a check
belonging to the other.

```
W1 = max(P1 − B, 0)
W2 = max(P2 − B, 0)
scaling_ratio = (W2 + F) / (W1 + F)      F = 2 MiB
```

A separate process per measurement is necessary but not sufficient. Siblings
share a cgroup whose peak is sticky and per-cgroup: measured at 4.88 GB on one
host and unmoved by a child allocating 300 MiB. Three subprocesses reading it
report figures that track read timing rather than what each allocated —
306.0, 449.5 and 454.2 MiB for siblings allocating 100, 200 and 400 MiB — and a
source that cannot answer the same workload twice disqualifies itself.

`F` is a **degenerate-ratio guard**, not a noise floor. Its job is keeping the
quotient defined where a correct boundary puts it: a working set measured at
0.02 MiB, where the unfloored quotient is `0.02 / 0.02`. Run-to-run variance was
0.00 MiB over twelve churn repetitions and 0.20 MiB over forty allocation
repetitions, so 2 MiB clears observed noise tenfold and was not sized from it.

### What the ratio can and cannot see

| retained bytes/row | ratio at `F` = 2 MiB, five repeats | verdict |
| ---: | --- | --- |
| 1–2 | 1.000 every run | invisible |
| 3 | 1.219 – 1.342 | invisible |
| 4 | 1.598 – 1.770, and 1.480 on a separate run | straddles |
| 5 | 2.121 – 2.301 | detected |
| 8 | 3.490 – 3.717 | detected |
| 128 | ≈ 4.07 | detected |

Detection is **reliable from five retained bytes per row**. Four straddles the
threshold and has been observed on both sides of it. Below that the binding
constraint is measurement resolution rather than the guard value: one and two
bytes per row register no `ru_maxrss` change at all, and no choice of `F`
detects them.

**Retention below that floor is not approved because RSS cannot see it.** Issue
#43 D5 is unchanged and was not narrowed: repository-owned release processors
and production readers must retain no source rows, converted records,
source-native maps, or per-row key collections after staging; any cache must be
bounded independently of row count; cross-row state belongs in the bounded
external stage. The floor is a limit on the instrument, not a permission, and
every production reader still owes structural evidence that it retains no
row-proportional state — which no accepted check currently supplies. The
capability's reader-lead check detects read-ahead rather than retention after
yielding, and its hundred-entry caps bound only notices and diagnostics.

## Isolation Is the Caller's to Provide

The absolute check needs a cgroup holding only this run, and the benchmark
**requires** rather than creates one: creating a cgroup needs delegation the run
cannot assume it has, and a command that silently acquired privileges to measure
itself would be a worse instrument than one that states its precondition.

```
systemd-run --user --scope -p MemoryAccounting=yes make benchmark-release-peak-rss
```

A purpose-built container holding only this run serves equally, subject to the
same verification. **The Airflow container does not**: the 900 MiB figure is
derived from it holding a scheduler and four concurrent tasks, so its cgroup
contains siblings by construction and a peak read there is the container's.

Isolation is **verified, never assumed**:

1. the membership map must be **complete** — every pid in `cgroup.procs` has a
   readable parent, and one that does not invalidates the map rather than being
   dropped, since a dropped member is how a foreign tree becomes a
   clean-looking single one;
2. **this process must be a member** — one tidy tree that is not ours says
   nothing about the figure being read;
3. the members must form a **single process tree** — several roots is the shape
   a shared container has;
4. `cgroup.stat` must report `nr_descendants 0` **and**
   `nr_dying_descendants 0`, because `memory.peak` charges descendants that
   `cgroup.procs` never lists, and a cgroup being torn down still holds charges.

None of that establishes that the cgroup was created *for* this run, and the
benchmark no longer tries to. Attribution comes from **bracketing** instead: the
cgroup peak is read before the measurements and after them.

| initial | final | verdict |
| --- | --- | --- |
| ≥ 900 MiB | any | indeterminate — the cgroup arrived contaminated |
| < 900 MiB | < 900 MiB | pass — the run stayed inside the budget |
| < 900 MiB | ≥ 900 MiB | fail — nothing else could have crossed it |

An implementation attempt compared the age of the cgroup's root process, on the
measurement that a dedicated scope's root starts 0.04 s before the run while an
ambient shell's was 74,759 s older. Review rejected it, correctly: a freshly
started shell carrying a few seconds of prior work passes an age test while
still holding someone else's peak. Bracketing needs no claim about the cgroup's
history, which is why it holds where age does not — measured, the ambient shell
reports 4,566.8 MiB before the run and is called indeterminate, while a
dedicated scope reports 19.3 MiB before and 30.4 MiB after and passes.

Where isolation cannot be established or verified, the absolute is reported
**indeterminate**, no `rusage` figure is substituted for it, and the command
exits non-zero. A run that could not measure what it exists to measure has not
demonstrated the target.

## Calibration

A threshold that has not been shown to discriminate is a number, not a check.
`make calibrate-release-peak-rss` runs **five bounded controls** and **five
retainers holding five bytes per row**; every control must pass and every
retainer must fail.

Five rather than four because four straddles. Repeats rather than single runs
because a boundary measured once is a point estimate — this specification has
already had to withdraw one detection claim derived from a single measurement.

Where calibration cannot establish that sensitivity, the result is
**indeterminate** and the threshold is recorded as unvalidated on that host. It
is never adjusted to fit, which is the one response the requirement forbids and
the one an implementation would reach for first.

## What This Does Not Establish

The benchmark measures **one process on the machine that runs it**, not four
concurrent tasks inside a 4 GiB container — which is the arithmetic the 900 MiB
figure came from. It is mandatory evidence for D5 and not exhaustive proof of
it, and it must not be claimed to prove D5 for every reader implementation.

What it does establish: a peak within the per-task budget, the ratio met at the
tested sizes, and calibrated retention detected.

## Running It

```bash
systemd-run --user --scope -p MemoryAccounting=yes make benchmark-release-peak-rss
systemd-run --user --scope -p MemoryAccounting=yes make calibrate-release-peak-rss
```

Both are outside `make check` and the ordinary suite: they allocate at
acceptance scale and take minutes, and issue #43 D5 separates deterministic
bounded CI tests from the reproducible acceptance command. Neither uses the
network.
