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
| memory must not grow linearly with release row count | **this change** |
| cgroup `memory.peak` when available, `ru_maxrss` as documented fallback, `tracemalloc` insufficient | **this change** |
| regular CI uses deterministic bounded contract tests | **this change** |
| the million-row benchmark is a reproducible no-network acceptance command reporting the measured peak | **this change** |
| the 100-diagnostic cap, the stable codes, the privacy prohibitions | already landed in change one |

D5's 900 MiB supersedes the issue body's 1 GiB, because the scheduler's measured 400 MiB peak shares the same 4 GiB container: `(4096 - 400) / 4 ≈ 900`.

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

- **D31**: peak RSS is read from the cgroup v2 `memory.peak` resolved from the relative path `/proc/self/cgroup` reports — never from the mount root, which a nested cgroup does not populate — when that path is readable, and otherwise from `resource.getrusage`, taking the maximum of `RUSAGE_SELF` and `RUSAGE_CHILDREN` and multiplying by 1024 because `ru_maxrss` is KiB on Linux. `tracemalloc` is never the source. The engineering document already records why: one measured run reported 663 MiB traced against 2,079 MiB resident, a factor of three, and the OOM killer reads resident set size. A measurement that can sit comfortably under budget while the task is killed is not a measurement.
- **D32**: every reported measurement names its source. A number that does not say whether it came from the cgroup or from `ru_maxrss` cannot be compared with another, because the two do not measure the same thing — the cgroup is the authority the limit is enforced against, and `ru_maxrss` is a per-process high-water mark that misses siblings.
- **D33**: `PeakRssGuard` implements the accepted `ResourceGuard` protocol and adds nothing to it. It measures at the grain its limit is expressed in: the 900 MiB budget is **per task**, so it reads per-process `rusage` by default, and the cgroup only where a deployment gives each task its own verified cgroup. A shared container's cgroup measures the container, not the task — measured on one host, a process peaking at 28.0 MiB sat in a cgroup peaking at 1,072.3 MiB, so a cgroup-reading guard would have rejected compliant work, and more reliably the busier the container was. Container-level enforcement is a separate limit at a separate grain, already performed by the kernel. It is called at the checkpoints the boundary already fixed — after the stage opens, at every 100,000-row boundary, and once at end-of-input — and reads the peak at each. Reading a pseudo-file once per 100,000 rows is not a cost worth optimizing, and adding checkpoints would change an accepted contract from the outside.
- **D34**: the guard raises when the observed peak is **at or above** its configured limit — `>=`, not `>`, so that a peak of exactly the limit is not a pass under the guard and a failure under an acceptance target that requires a peak strictly under it — which the boundary maps to `resource_limit_exceeded` and treats as a release rejection. A guard that only warned would leave a task to be killed by the OOM killer instead, which produces no outcome, no diagnostic, and no progress event.
- **D35**: the synthetic release is generated and streamed, never written. A million rows at ninety columns is roughly a gigabyte of text; committing it is forbidden, and writing it to a temporary file would measure the filesystem rather than the boundary. The generator yields envelopes directly.
- **D36**: "memory must not grow linearly" is tested as a **ratio between two release sizes**, not as an absolute. The benchmark runs at 250,000 and at 1,000,000 rows and requires the peak to grow by less than a stated fraction of the fourfold row increase. An absolute threshold cannot distinguish a bounded implementation from a linear one that happened to fit.
- **D37**: the benchmark is a `make` target, not a `pytest` test. Issue #43 D5 says regular CI uses deterministic bounded contract tests and the million-row run is a separate reproducible acceptance command. A multi-minute allocation-heavy run in the ordinary suite would be paid on every commit for a signal that changes rarely.
- **D38**: the probe takes an explicit source when the caller needs a specific one. `read_peak_rss()` prefers the cgroup, which is right for the guard because the cgroup is what the limit is enforced against; the benchmark's three comparative measurements need a per-process source and request `rusage` outright. A preference that cannot be overridden would make the benchmark unimplementable on any host where the cgroup file is readable, which is the production-style host it exists to model.
- **D39**: the two checks use different sources, because they answer different questions. The **scaling ratio** uses `rusage`, the only per-process source: siblings share a cgroup whose peak is sticky, so three subprocesses reading it report one identical figure and the ratio passes vacuously. The **900 MiB absolute** uses the cgroup, because issue #43 D5 makes the cgroup authoritative for the limit and it is the number the OOM killer acts on. Reporting a rusage figure against a cgroup-derived budget would compare quantities the change itself calls incomparable. The absolute check therefore requires the benchmark to run in a cgroup containing only that run.

  That isolation is **the caller's to provide, not the benchmark's to create**: creating a cgroup needs delegation the run cannot assume it has, and a command that silently acquires privileges in order to measure itself is a worse instrument than one that states its precondition. The reproducible invocation on a systemd host is `systemd-run --user --scope -p MemoryAccounting=yes` around the `make` target, measured here rather than proposed — a fresh scope reported three processes and a 2.2 MB peak where the ambient cgroup held six processes and 964 MB inherited from unrelated work. The `make` target documents that wrapper rather than applying it, so the isolation a result depended on stays visible in the command a reader ran.

  Isolation is **verified, never assumed**, and over the whole subtree: `memory.peak` charges a cgroup and all of its descendants while `cgroup.procs` lists only direct members, so the benchmark requires both that `cgroup.procs` hold only its own process tree and that `cgroup.stat` report `nr_descendants 0` and `nr_dying_descendants 0`. Where it cannot establish or verify one, it reports the absolute as **indeterminate** rather than substituting a source that was not asked for, and the command **exits non-zero** — a run that could not measure the thing it exists to measure has not demonstrated the target, and an exit status read as success is how an unproven claim becomes a settled one.

**Provenance.** Issue #43 D5 is the authoritative input. D31 through D39 are this change's own and no prior maintainer selection is claimed for them. D31's precedence and D36's ratio approach follow the measurement guidance already recorded in `docs/engineering/airflow-implementation.md`.

## Unresolved decisions

- None.

## Ordering, and what this change waits for

Both changes belong to issue #43, so this is a sibling dependency rather than a cross-issue one.

`add-bounded-release-processing` is now **implemented and archived**, and its eighteen requirements are the durable `bounded-release-processing` capability. That is what makes this change implementable rather than merely plannable: `PeakRssGuard` implements the `ResourceGuard` protocol that capability declares, and the benchmark drives the `process_release` it specifies, both of which now exist on `main`.

One consequence is load-bearing. The capability's accepted tests assert, per module, which imports `property_tax_adapters.release` may contain, and a peak-RSS probe needs `resource` and a filesystem read. The probe therefore lands in `property_tax_adapters.resources`, beside the boundary rather than inside it, and this change modifies no module and no test belonging to that capability.

Per the review sequencing, DAG work remains blocked until both changes merge and are implemented.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
