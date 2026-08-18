## Why

The `bounded-release-processing` capability fixed the boundary and deliberately left the target unmeasured. It declares a `ResourceGuard` protocol — when the boundary asks, and what it passes — and says explicitly that what is measured belongs here.

So today three things are true at once. The 900 MiB per-task budget exists in `docs/engineering/airflow-implementation.md` and nothing enforces it. The guard seam exists and no implementation measures anything. And the 663 MiB retained on 200,000 rows that motivated all of this was measured against the *old* whole-file API, never against the boundary built to replace it.

## Outcome

Add `property_tax_adapters.resources`, a package beside the boundary rather than inside it: a peak-RSS probe with a defined source precedence, a `PeakRssGuard` implementing the accepted `ResourceGuard` protocol, a streaming synthetic release generator, and a reproducible no-network benchmark command that reports the measured peak.

## Scope

- Originating issue: #43, the resource half of decision **D5**
- Affected capability: release-resource-limits (ADDED)
- Depends on: the `bounded-release-processing` capability, whose `ResourceGuard` protocol this implements (introduced by the archived `add-bounded-release-processing` change)

## What issue #43 D5 assigns here

| D5 states | |
| --- | --- |
| at least 1,000,000 generated synthetic physical rows | **this change** |
| at least 90 source columns | **this change** |
| under 900 MiB parser-task peak RSS at parallelism 4 | **this change** |
| memory must not grow linearly with release row count | **evidence**: mandatory, calibrated, and not exhaustive; D5 unchanged (D40, D41) |
| cgroup `memory.peak` when available, `ru_maxrss` as documented fallback, `tracemalloc` insufficient | **this change** |
| regular CI uses deterministic bounded contract tests | **this change** |
| the million-row benchmark is a reproducible no-network acceptance command reporting the measured peak | **this change** |
| the 100-diagnostic cap, the stable codes, the privacy prohibitions | already landed in change one |

D5's 900 MiB supersedes the issue body's 1 GiB, because the 419 MiB figure — the scheduler container's `memory.peak` with no task running — a subtree charge that only ever rises, so an upper bound on the scheduler's share rather than a measurement of it — shares the same 4 GiB container: `(4096 - 419) / 4 ≈ 919`, and the target is set at 900.

## Constraints

Authorized paths are `libs/property-tax-adapters/`, its tests and synthetic generators, directly related engineering documentation, and this change.

Not authorized, and not present here: DAGs, services, network acquisition, database migrations, durable persistence, publication, infrastructure, deployment, `property_tax_domain` or `property_tax_application` changes, or any production-ready claim.

- No new dependency. `resource` and the cgroup pseudo-filesystem are standard library and kernel respectively.
- No committed million-row fixture. The generator streams; nothing that large is written to disk or to the repository.
- No network. The benchmark is reproducible offline.
- The accepted boundary is not modified. This change supplies an implementation of a protocol it already declares, and adds no checkpoint, no code, and no field to it.
- Synthetic, identity-free, redistribution-safe data only.

## Non-goals

- Changing the boundary. Its checkpoints, vocabulary, and outcome are accepted and are used as they stand.
- A production Dallas or Collin reader. The benchmark drives a synthetic reader, because the point is the boundary's memory behaviour rather than any county's parsing.
- Durable quarantine, the production unique index, or DAG integration.
- Lowering `AIRFLOW__CORE__PARALLELISM` to buy headroom. That is a runtime decision the engineering document already describes and this change does not take it.

## Decisions

These are **this change's** decisions, numbered from D31 so they cannot be confused with issue #43's D1 through D8 or with change one's D9 through D26. Issue decisions are always written in full as "issue #43 D5".

- **D31**: peak RSS is read from the cgroup v2 `memory.peak` at the path **resolved** from `/proc/self/cgroup` — never at an *assumed* mount root — when that path is readable, and otherwise from `resource.getrusage`, taking the maximum of `RUSAGE_SELF` and `RUSAGE_CHILDREN` and multiplying by 1024 because `ru_maxrss` is KiB on Linux. `tracemalloc` is never the source. The engineering document already records why: one measured run reported 663 MiB traced against 2,079 MiB resident, a factor of three, and the OOM killer reads resident set size. A measurement that can sit comfortably under budget while the task is killed is not a measurement.
- **D32**: every reported measurement names its source. A number that does not say whether it came from the cgroup or from `ru_maxrss` cannot be compared with another, because the two do not measure the same thing — the cgroup is the authority the limit is enforced against, and `ru_maxrss` is a per-process high-water mark that misses siblings, live children, and everything beyond the largest reaped one.
- **D33**: `PeakRssGuard` implements the accepted `ResourceGuard` protocol and adds nothing to it. It measures at the grain its limit is expressed in: the 900 MiB budget is **per task**, so it reads per-process `rusage` and offers no cgroup mode at all. A cgroup figure is per-task only while its subtree stays empty, and the guard runs at every 100,000-row checkpoint, so honouring that would mean re-verifying the subtree at each one — verifying at construction proves nothing, because a process can join afterwards. `RUSAGE_CHILDREN` is kept in the maximum but does **not** amount to covering children: on Linux it counts only terminated, waited-for children and reports the largest one rather than a sum, measured here as 0 MiB while two 300 MiB children were alive and 308 MiB once both were reaped. The guard is therefore a runtime tripwire covering **the process it runs in, plus a partial signal for reaped children**, and nothing more. There is no single-process guarantee to lean on: `PreparedReader` and `ReleaseStage` are caller-supplied protocols, and neither they nor `process_release` forbid an implementation from spawning a decoder, an extractor, or a database client, so a conforming reader may fork and its child's memory is exactly what the guard cannot see. The isolated-cgroup benchmark remains the authoritative measurement — authoritative precisely because a cgroup charges the whole subtree, which is what per-process measurement gives up — and this plan does not claim the guard bounds any task's total footprint. The guard exposes only `last_sample`, a single `PeakRssSample` with no history, which is where its source is recorded: `check` returns `None`, a diagnostic carries no source field, and this decision forbids boundary-visible state, so without that attribute the recording claim would have had nowhere to live. A shared container's cgroup measures the container, not the task — measured on one host, a process peaking at 28.0 MiB sat in a cgroup peaking at 1,072.3 MiB, so a cgroup-reading guard would have rejected compliant work, and more reliably the busier the container was. Container-level enforcement is a separate limit at a separate grain, already performed by the kernel. It is called at the checkpoints the boundary already fixed — after the stage opens, at every 100,000-row boundary, and once at end-of-input — and reads the peak at each. Reading a pseudo-file once per 100,000 rows is not a cost worth optimizing, and adding checkpoints would change an accepted contract from the outside.
- **D34**: the guard raises when the observed peak is **at or above** its configured limit — `>=`, not `>`, so that a peak of exactly the limit is not a pass under the guard and a failure under an acceptance target that requires a peak strictly under it — which the boundary maps to `resource_limit_exceeded` and treats as a release rejection. A guard that only warned would leave a task to be killed by the OOM killer instead, which produces no outcome, no diagnostic, and no progress event.
- **D35**: the synthetic release is generated and streamed, never written. A million rows at ninety columns is roughly a gigabyte of text; committing it is forbidden, and writing it to a temporary file would measure the filesystem rather than the boundary. The generator yields envelopes directly.
- **D36**: linearity is tested as a **ratio between two release sizes**, not as an absolute, and what the ratio can establish is bounded by D40 and calibrated under D41: it detects retention at and above the calibrated rate, not all growth, and D5 itself is not narrowed to match. The benchmark runs at 250,000 and at 1,000,000 rows and requires the peak to grow by less than a stated fraction of the fourfold row increase. An absolute threshold cannot distinguish a bounded implementation from a linear one that happened to fit.
- **D37**: the benchmark is a `make` target, not a `pytest` test. Issue #43 D5 says regular CI uses deterministic bounded contract tests and the million-row run is a separate reproducible acceptance command. A multi-minute allocation-heavy run in the ordinary suite would be paid on every commit for a signal that changes rarely.
- **D38**: the probe takes an explicit source when the caller needs a specific one, and its default precedence is a property of the *probe* rather than a recommendation to any caller. `read_peak_rss()` prefers the cgroup when no source is named, because a caller asking simply for "the peak" on a host that has a cgroup figure usually means the container's. Every caller in this change names its source instead: the benchmark's three comparative measurements name `rusage` for per-process comparability, its absolute names the cgroup for the authority a limit is enforced against, and the guard names `rusage` because its budget is per task, per D33. A preference that could not be overridden would make the benchmark unimplementable on any host where the cgroup file is readable, which is the production-style host it exists to model. Nothing here says the default is right for the guard; D33 settles the guard, and it does not use the default.
- **D39**: the two checks use different sources, because they answer different questions. The **scaling ratio** uses `rusage`, the only per-process source: siblings share a cgroup whose peak is sticky and charges the whole subtree, so three subprocesses reading it report figures describing the subtree rather than the reader — 306.0, 449.5, and 454.2 MiB measured for siblings allocating 100, 200, and 400 MiB — none of which describes the process that read it, and whose spread is a function of read timing rather than of what each allocated; no ratio is computed from them, since they are not baseline-and-two-sizes measurements, and nondeterminism disqualifies the source on its own. The **900 MiB absolute** uses the cgroup, because issue #43 D5 makes the cgroup authoritative for the limit and it is the number the OOM killer acts on. Reporting a rusage figure against a cgroup-derived budget would compare quantities the change itself calls incomparable. The absolute check therefore requires the benchmark to run in a cgroup containing only that run.
- **D40**: the benchmark is **mandatory evidence** for issue #43 D5, not exhaustive proof of it, and D5 itself is unchanged. The maintainer decision recorded on issue #43 declines the narrowing an earlier draft of this decision proposed, and states the rule this change implements against: repository-owned release processors and production readers MUST NOT retain source rows, converted records, source-native maps, or per-row key collections in Python memory after staging; any cache MUST be bounded independently of row count; cross-row state belongs in the bounded external stage or index.
  Retention below the measurement floor is **not** approved merely because `ru_maxrss` cannot see it. Three bytes per row and below are invisible and four straddles the threshold, and that is a limit on the instrument rather than a permission. Every production reader still owes structural evidence that it retains no row-proportional state; the benchmark does not supply that and this change does not claim it does.
  An earlier draft also said the accepted capability discharged D5's structural half. It does not: the reader-lead check measures pulls against envelopes consumed and so detects read-ahead, leaving a reader that keeps a compact summary after yielding undetected, and the hundred-entry caps bound only notices and diagnostics.
- **D41**: the scaling check's sensitivity is **calibrated rather than assumed**, on the terms the issue #43 decision fixes. Calibration runs at least five repeated bounded controls and at least five repeated retainers holding five bytes per row; every control must pass and every retainer must fail. Where calibration cannot establish that sensitivity, the run reports **indeterminate** and exits non-zero rather than reporting a threshold it has not shown to discriminate. Repeats rather than single runs because a boundary measured once is a point estimate: four bytes per row read 1.480 on one run and 1.598 to 1.770 across five.

## Unresolved decisions

- None. U1, which proposed narrowing issue #43 D5 to material record retention, was **declined** by the maintainer decision recorded on that issue. D5 stands unchanged; D40 and D41 record what this change implements against it.

## Ordering, and what this change waits for

Both changes belong to issue #43, so this is a sibling dependency rather than a cross-issue one.

`add-bounded-release-processing` is now **implemented and archived**, and its eighteen requirements are the durable `bounded-release-processing` capability. That is what makes this change implementable rather than merely plannable: `PeakRssGuard` implements the `ResourceGuard` protocol that capability declares, and the benchmark drives the `process_release` it specifies, both of which now exist on `main`.

One consequence is load-bearing. The capability's accepted tests assert, per module, which imports `property_tax_adapters.release` may contain, and a peak-RSS probe needs `resource` and a filesystem read. The probe therefore lands in `property_tax_adapters.resources`, beside the boundary rather than inside it, and this change modifies no module and no test belonging to that capability.

Per the review sequencing, DAG work remains blocked until both changes merge and are implemented.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
