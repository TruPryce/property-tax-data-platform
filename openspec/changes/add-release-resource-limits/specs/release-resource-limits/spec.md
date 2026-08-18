## ADDED Requirements

### Requirement: Read peak resident set size from a defined source precedence

The library SHALL provide `read_peak_rss()` returning a frozen `PeakRssSample` whose fields, types, and invariants are exactly these:

| field | type | invariant |
| --- | --- | --- |
| `peak_bytes` | `int` | not negative |
| `source` | `PeakRssSource` | a `StrEnum` of exactly `cgroup_v2` and `rusage` |

The source precedence SHALL be: the cgroup v2 `memory.peak` resolved from the relative path `/proc/self/cgroup` reports when it is readable, reported as `cgroup_v2`; otherwise `resource.getrusage`, taking the maximum of `RUSAGE_SELF` and `RUSAGE_CHILDREN` and multiplying by 1024 because `ru_maxrss` is KiB on Linux, reported as `rusage`.

`tracemalloc` SHALL NOT be a source. One measured run recorded 663 MiB traced against 2,079 MiB resident — a factor of three — and the OOM killer reads resident set size, so a traced figure can sit comfortably under budget while the task is killed.

`read_peak_rss()` SHALL accept an explicit source and SHALL return a sample from that source when one is named, falling back to the documented precedence only when none is.

A preference that cannot be overridden makes the benchmark unimplementable. Its three comparative measurements require the per-process source, and on any host where the cgroup file is readable — the production-style host the benchmark exists to model — an unconditional preference would hand back the shared cgroup figure instead. A caller that names a source and cannot get it has no way to obtain a comparable measurement at all.

#### Scenario: A named source is honoured over the preference
- **GIVEN** a host whose cgroup file is readable
- **WHEN** `read_peak_rss()` is called naming `rusage`
- **THEN** it returns a `rusage` sample rather than the preferred cgroup one

A named source that cannot be read SHALL raise `PeakRssSourceUnavailable`, a typed exception the library declares, rather than fall back.

The type is named here rather than left to the implementation because the benchmark has to catch it: a caller that must distinguish "the cgroup is unreadable" from any other error, in order to report the absolute indeterminate rather than crash, cannot do so against an exception whose type is unspecified — it would either catch too broadly and swallow real defects, or match on message text, which the privacy rules forbid and which no two implementations spell alike. The exception SHALL carry the requested `PeakRssSource` and no host path, since a path is host-local detail this boundary does not preserve.

Falling back would return a figure from a source the caller did not ask for, under a call that asked for a specific one. The benchmark's whole reason for naming `rusage` is comparability across processes, so a silent cgroup substitution would produce exactly the vacuous ratio the naming exists to prevent — and it would do so with no signal at all. `rusage` is available on every Linux host, so in practice this raises only for `cgroup_v2`.

#### Scenario: A named source that cannot be read fails rather than substituting
- **GIVEN** a host with no readable cgroup file
- **WHEN** `read_peak_rss()` is called naming `cgroup_v2`
- **THEN** it raises `PeakRssSourceUnavailable`, carrying the requested source
- **THEN** it does not return a `rusage` sample under a request for a cgroup one

#### Scenario: The preference applies when no source is named
- **GIVEN** a host whose cgroup file *is* readable
- **WHEN** `read_peak_rss()` is called naming nothing
- **THEN** it returns a `cgroup_v2` sample

#### Scenario: The fallback applies where no cgroup file exists
- **GIVEN** a host with no readable cgroup file
- **WHEN** `read_peak_rss()` is called naming nothing
- **THEN** it returns a `rusage` sample, which the preference permits because no source was named

Every reported measurement SHALL name its source. The cgroup is the authority the container limit is enforced against; `ru_maxrss` is a per-process high-water mark that does not account for unreaped children or sibling processes. Two numbers from different sources are not comparable, and a bare integer hides which one it is.

The cgroup path SHALL be **resolved** by joining the cgroup mount with the relative path `/proc/self/cgroup` reports, and SHALL NOT be *assumed* to be `/sys/fs/cgroup/memory.peak`.

Resolving is not the same as refusing the root. A process in a cgroup namespace — which is the ordinary case inside a container — legitimately sees `/proc/self/cgroup` report `/`, and there the resolved path **is** the mount root. What must never happen is reading the root without resolving, because a process in a nested cgroup — every process under systemd, and every container under a delegated slice — has no `memory.peak` there. On a measured host the root path was absent entirely while the file existed beneath the reported relative path, and a probe hard-coding the root would silently fall back to `rusage` on exactly the hosts the cgroup source exists to serve.

#### Scenario: A cgroup namespace resolves to the mount root
- **GIVEN** a containerized process whose `/proc/self/cgroup` reports `/`
- **WHEN** the probe resolves the cgroup path
- **THEN** it reads `memory.peak` at the mount root, which is the correct resolution here
- **THEN** it does not treat the root as invalid merely because it is the root

#### Scenario: The cgroup file is found beneath a nested path
- **GIVEN** a host whose `/proc/self/cgroup` reports a non-root relative path
- **WHEN** `read_peak_rss()` resolves the cgroup file
- **THEN** it reads `/sys/fs/cgroup` joined with that relative path
- **THEN** it reports `cgroup_v2` rather than falling back

#### Scenario: The cgroup is preferred where it exists
- **GIVEN** a host where the resolved cgroup `memory.peak` is readable
- **WHEN** `read_peak_rss()` is called
- **THEN** the sample's source is `cgroup_v2`
- **THEN** `peak_bytes` is the value that file reports

#### Scenario: The documented fallback is used where it does not
- **GIVEN** a host where that path is absent or unreadable
- **WHEN** `read_peak_rss()` is called
- **THEN** the sample's source is `rusage`
- **THEN** `peak_bytes` is `max(RUSAGE_SELF, RUSAGE_CHILDREN) * 1024`

#### Scenario: A sample always names its source
- **GIVEN** any `PeakRssSample`
- **WHEN** its fields are enumerated
- **THEN** it declares exactly `peak_bytes` and `source`
- **THEN** no code path returns a bare integer in its place

### Requirement: Keep the measurement out of the boundary package

The probe and the guard SHALL live in `property_tax_adapters.resources`, a package beside `property_tax_adapters.release` rather than inside it.

The accepted boundary asserts, per module, that `property_tax_adapters.release` imports only `__future__`, `re`, `collections`, `contextlib`, `dataclasses`, `enum`, `types`, and `typing`. Reading a peak requires `resource` for `getrusage` and a filesystem read for the cgroup path, so a probe placed inside that package fails an accepted test that this change does not modify.

That constraint is also the correct architecture rather than an obstacle worked around: the boundary declares *when* it asks and deliberately owns no measurement, so a package that acquires operating-system dependencies is exactly what must stay outside it. The dependency runs one way — `resources` imports the release protocols, and `release` imports nothing from `resources`.

#### Scenario: The boundary package stays free of measurement imports
- **GIVEN** the accepted per-module import allowlist for `property_tax_adapters.release`
- **WHEN** this change adds the probe and the guard
- **THEN** no module under `property_tax_adapters.release` is added or modified
- **THEN** the accepted architecture test passes unchanged

#### Scenario: The dependency runs one way
- **WHEN** the two packages are inspected
- **THEN** `property_tax_adapters.resources` imports the release protocols
- **THEN** no module under `property_tax_adapters.release` imports `property_tax_adapters.resources`

### Requirement: Enforce a peak-RSS limit through the accepted guard protocol

The library SHALL provide `PeakRssGuard`, implementing the `ResourceGuard` protocol that the `bounded-release-processing` capability declares, taking a limit in bytes and implementing `check(physical_rows_processed: int, staged_record_count: int) -> None`.

`PeakRssGuard` SHALL measure at the grain its limit is expressed in, and SHALL default to the per-process `rusage` source rather than to the probe's cgroup preference.

The 900 MiB budget is **per task**, derived as `(4096 MiB − 419 MiB) / 4 tasks`, where 419 MiB is the scheduler container's `memory.peak` with no task running — a subtree charge that only ever rises, so an upper bound on the scheduler's share rather than a measurement of it. That arithmetic describes a container holding a scheduler and four concurrent tasks, so in the deployment the budget came from, the cgroup measures the container and the limit measures one task inside it. They are different grains, and a guard reading the cgroup against a per-task limit compares the wrong pair.

The consequence is not theoretical. Measured on one host, a process whose own peak was 28.0 MiB sat in a cgroup whose sticky peak was 1,072.3 MiB; a `PeakRssGuard(900 MiB)` reading the cgroup would have rejected that task, and every other compliant task sharing the container, while a `rusage` reading accepted it correctly. A guard that rejects compliant work is worse than no guard, because it converts a healthy release into a failed one and does so more reliably the busier the container is.

The guard SHALL read `rusage` and SHALL NOT offer a cgroup mode.

An earlier draft admitted one for deployments giving each task its own cgroup. It is removed for two reasons, and the first is decisive. A cgroup figure is only per-task while the subtree stays empty, and the guard is called at every 100,000-row checkpoint — so honouring that condition means verifying the subtree at each checkpoint, and verifying it once at construction proves nothing, because a process may join the cgroup afterwards. A mode whose precondition cannot be held for the life of the run is a mode that silently stops being true. Second, an unimplemented mode still costs a verification contract, and this change would have owned one nothing tested.

What the guard therefore enforces SHALL be stated plainly rather than implied, because `RUSAGE_CHILDREN` measures less than its name suggests.

On Linux it counts only children that have **terminated and been waited for**, and its `ru_maxrss` is the resident set of the *largest* such child — never a sum, and never a live one. Measured here: two children each holding 300 MiB reported `children = 0 MiB` while alive, and `308 MiB` after both were reaped — the larger of the two, not the 600 MiB they occupied together.

So the guard is a **runtime tripwire for the process it runs in**, and its accounting is:

| case | what the guard sees |
| --- | --- |
| memory held by the process the guard runs in | covered |
| a live child of that process | invisible |
| reaped children | the largest one, never the sum |
| an unrelated sibling in the same container | invisible, which is correct — it is not this task |

The guard's coverage SHALL be described as **the current process, plus a partial signal for reaped children**, and SHALL NOT be described as complete for anything.

There is no single-process guarantee to appeal to. `PreparedReader` and `ReleaseStage` are protocols the caller supplies, and nothing in them or in `process_release` forbids an implementation from spawning a subprocess — a decoder, an extractor, a database client. `process_release` being synchronous says only that it does not return until the work is done, not that the work happened in one process. A county reader that shells out is a conforming reader, and its child's memory is exactly what the guard cannot see.

The isolated-cgroup benchmark remains the authority, and it is authoritative *because* a cgroup charges the whole subtree — which is the property the guard gives up by measuring per-process. The guard exists to stop this process before the OOM killer does, on partial evidence, which is worth having and is not worth overstating.

`RUSAGE_CHILDREN` stays in the maximum because it can only raise the figure and so can only make the tripwire fire sooner, which is the safe direction for a limit. It is kept as a partial signal, not as coverage.

#### Scenario: The guard's accounting is partial whenever a collaborator forks
- **GIVEN** a conforming reader or stage that spawns a subprocess to do its work
- **WHEN** the guard samples while that subprocess is alive
- **THEN** the subprocess's memory does not appear in the sample
- **THEN** the plan does not claim the guard bounds the task's total footprint, and does not assume the boundary is single-process

Container-level enforcement is a **separate limit at a separate grain** and is not this guard's responsibility. The kernel already enforces the container's own ceiling, and the OOM killer acts on it; this guard exists to reject one task before that happens, not to duplicate it.

The guard SHALL expose the most recent sample it acted on as `last_sample: PeakRssSample | None`, and SHALL retain **no history**.

It SHALL be `None` before the first `check`, and SHALL be set to the sample just taken **before** that call raises. A rejection whose `last_sample` still held the previous checkpoint's figure would attribute the failure to a measurement that did not cause it, which is worse than exposing nothing: the reader would have a number, and it would be the wrong one.

That is the whole carrier, and it is deliberately small. `ResourceGuard.check` returns `None`, a `ReleaseDiagnostic` has no field for a source, and D33 forbids adding boundary-visible state, so a claim that the guard "records" its source needed somewhere to record it or it was unimplementable. One attribute on the guard the caller constructed is inspectable by that caller, invisible to the boundary, and bounded by construction — where a list of every sample would grow with the release, which is the defect this whole change exists to prevent.

`check` SHALL sample the peak and SHALL raise when the sample is **at or above** the configured limit. The boundary maps that raise to `resource_limit_exceeded` and rejects the release.

#### Scenario: The default guard measures one task, not its container
- **GIVEN** a task whose own peak is well under the limit, in a shared container whose cgroup peak exceeds it
- **WHEN** `PeakRssGuard` samples at a checkpoint
- **THEN** it reads the per-process `rusage` source by default
- **THEN** it does not reject the compliant task

#### Scenario: The guard offers no cgroup mode to misconfigure
- **GIVEN** the guard's constructor
- **WHEN** its parameters are inspected
- **THEN** it accepts a limit and no source selection
- **THEN** no configuration makes it read the cgroup, so no subtree precondition needs holding across checkpoints

#### Scenario: A rejection exposes the sample that caused it
- **GIVEN** a guard whose next sample is at or above the limit
- **WHEN** `check` raises
- **THEN** `last_sample` holds the sample that triggered the raise, not the previous checkpoint's
- **THEN** before the first `check`, `last_sample` is `None`

#### Scenario: The last sample is inspectable and singular
- **GIVEN** a guard that has been called at several checkpoints
- **WHEN** `last_sample` is read
- **THEN** it is the most recent `PeakRssSample`, naming its source
- **THEN** no earlier sample is retained, so the guard's own footprint does not grow with the release

The comparison is `>=` rather than `>` so that the guard and the acceptance target agree exactly. The target is a peak strictly **under** 900 MiB; a guard raising only above its limit would admit a peak of exactly 900 MiB, which the benchmark then fails. One boundary condition cannot be a pass under one rule and a failure under the other.

#### Scenario: The limit itself is not admitted
- **GIVEN** a `PeakRssGuard` limited to 900 MiB and a sample of exactly 900 MiB
- **WHEN** `check` is called
- **THEN** it raises, because the target requires a peak strictly under the limit

The guard SHALL NOT warn instead of raising. The alternative to rejecting a release that has exceeded its budget is being killed by the OOM killer, which produces no outcome, no diagnostic, and no progress event — a silent death is not a safer failure than a reported one.

The guard SHALL add nothing to the accepted protocol: no additional checkpoint, no state the boundary can observe, and no field on any boundary type. It is called at the checkpoints the boundary already fixed and at no others.

The guard's exception text SHALL NOT be retained, as the accepted boundary already requires.

#### Scenario: A breach rejects the release through the accepted code
- **GIVEN** a `PeakRssGuard` whose limit is below the observed peak
- **WHEN** a release is processed with it
- **THEN** the outcome reports `resource_limit_exceeded`
- **THEN** the stage is aborted and `committed_record_count` is zero

#### Scenario: A guard within its limit changes nothing
- **GIVEN** a `PeakRssGuard` whose limit is above the observed peak
- **WHEN** an otherwise valid release is processed
- **THEN** the release is accepted
- **THEN** no `resource_limit_exceeded` diagnostic is produced

#### Scenario: The guard adds no checkpoint
- **GIVEN** a `PeakRssGuard` recording each call, and a release of 250,000 rows
- **WHEN** the release is processed
- **THEN** it is called after the stage is entered, at 100,000, at 200,000, and once at end-of-input
- **THEN** the call sequence is the one the accepted boundary already fixes, with no addition

### Requirement: Generate a release at scale without writing one

The synthetic release generator SHALL produce at least 1,000,000 physical rows with at least 90 source columns, and SHALL yield `SourceRowEnvelope` values directly rather than writing a file.

It SHALL NOT write the release to disk, and no fixture of that size SHALL be committed. A million rows at ninety columns is roughly a gigabyte of text: committing it is forbidden by the artifact policy, and staging it in a temporary file would measure the filesystem rather than the boundary.

The generator SHALL retain no accumulated state across rows, so the instrument does not itself hold the release it is measuring.

#### Scenario: The generator meets the declared floor
- **GIVEN** the generator configured for the acceptance run
- **WHEN** its output is inspected
- **THEN** it produces at least 1,000,000 physical rows
- **THEN** each row carries at least 90 source columns

#### Scenario: Nothing of that size is written or committed
- **GIVEN** a completed benchmark run
- **WHEN** the working tree and temporary directories are inspected
- **THEN** no generated release file remains
- **THEN** no fixture approaching that size exists in the repository

#### Scenario: The instrument holds nothing
- **GIVEN** the generator driven to exhaustion
- **WHEN** its retained state is inspected
- **THEN** it holds no row it has already yielded
- **THEN** its own footprint does not grow with the number of rows produced

### Requirement: Prove boundedness by shape, not by a single number

The acceptance benchmark SHALL evaluate two independent checks, and they do not read the same measurements.

The **scaling** check SHALL take **three** `rusage` measurements, each in its own subprocess, and SHALL fail closed if the three samples do not all report the same source. The **absolute** check SHALL take a **fourth** measurement, from the cgroup, described under its own heading below. Four measurements in total, three of which are comparable to each other and one of which is authoritative about the limit.

A figure from one group SHALL NOT be used to satisfy a check belonging to the other. That is the same incomparability this change states elsewhere, and it applies to the benchmark's own arithmetic first.

A separate process is necessary but not sufficient, and the reason is specific. A peak is a high-water mark, so two sizes measured in one process report the larger under both names. But sibling processes share a cgroup, and the cgroup high-water mark is sticky and per-cgroup rather than per-process: on a measured host it stood at 4.88 GB from unrelated earlier work and did not move for a child that allocated 300 MiB. Three subprocesses reading `memory.peak` therefore report figures that track the shared subtree rather than the reader — measured on the deployment host as 306.0, 449.5, and 454.2 MiB for siblings allocating 100, 200, and 400 MiB. Not one of those numbers describes the process that read it, and the spread between them is a function of when each read happened rather than of what each allocated.

No ratio is computed from those three figures here, and none should be: they are not `B`, `P1` and `P2`, having come from siblings allocating fixed amounts rather than from a baseline and two release sizes, so putting them through the scaling formula would be answering a question they were not measurements of. (For the record, they yield 1.031 through that formula; the 1.48 an earlier draft reported was `454.2 / 306.0`, the raw maximum over the raw minimum, which is not the quantity this specification defines.)

The disqualification does not need a ratio. A source whose reading depends on when a sibling happened to be scheduled cannot produce the same answer twice on one workload, and a check built on it would pass or fail by timing. Nondeterminism disqualifies the source more surely than any single computed value would.

`ru_maxrss` under `RUSAGE_SELF` is genuinely per-process: on the same host the 300 MiB child reported 314.6 MiB against a sibling's 17.0 MiB. It is therefore the only source of the three comparative measurements, and the benchmark SHALL NOT read the cgroup for them. The fourth, which the absolute check reads, is a cgroup figure by the same reasoning inverted.

This does not demote the cgroup source generally; it assigns each reader the grain its question needs. The benchmark's ratio needs comparability between three processes, so it takes `rusage`. Its absolute needs the authority the limit is enforced against, so it takes the cgroup — which is a per-task figure precisely because isolation is required and verified first. The guard needs the grain its per-task budget is expressed in, so it takes `rusage` and offers no cgroup mode at all, as the guard requirement above states.

Requiring one source across all three is separate from choosing which. `ru_maxrss` and a cgroup figure account for different things — unreaped children and sibling processes among them — so a ratio taken across a mixed pair is arithmetic on incomparable quantities. The benchmark SHALL compare `PeakRssSample.source` across `B`, `P1`, and `P2` and SHALL fail rather than report a ratio when they differ.

The three comparative measurements are:

| symbol | rows | what it measures |
| --- | --- | --- |
| `B` | 0 | the baseline: interpreter, imports, and harness |
| `P1` | 250,000 | baseline plus the working set at the smaller size |
| `P2` | 1,000,000 | baseline plus the working set at the acceptance size |

All three are `rusage` figures and feed the scaling ratio only. The absolute check takes its own cgroup measurement, described below.

The working set at each size SHALL be computed by subtracting the baseline, floored at zero because measurement noise can place a peak below it:

```
W1 = max(P1 - B, 0)
W2 = max(P2 - B, 0)
```

The scaling ratio SHALL be computed with a fixed degenerate-ratio guard `F` of **2 MiB** added to both terms:

```
scaling_ratio = (W2 + F) / (W1 + F)
```

The floor is what makes the ratio stable when both working sets are small: without it, two nearly-identical bounded measurements a few kilobytes apart can produce an arbitrarily large quotient, and the check would fail on noise rather than on growth. That case is the expected one rather than an edge. Measured on the deployment host, a boundary retaining nothing held a working set of 0.02 MiB at both 25,000 and 100,000 rows, where the unfloored quotient is `0.02 / 0.02` and means nothing.

`F` is a **degenerate-ratio guard**, not a noise floor, and SHALL be called one wherever it appears. Its job is to keep the quotient defined where a correct boundary puts it — a working set measured at 0.02 MiB, where the unfloored quotient is `0.02 / 0.02` and means nothing. Run-to-run variance was 0.00 MiB across twelve churn repetitions and 0.20 MiB across forty allocation repetitions, so even 2 MiB clears observed noise tenfold and is plainly not sized from it.

What the value costs is sensitivity, and that cost SHALL be stated as measured rather than derived. Sweeping an accumulator that retains a known number of bytes per row, at 250,000 and 1,000,000 rows:

| retained bytes/row | ratio at `F` = 2 MiB, five repeats | verdict |
| ---: | --- | --- |
| 1 | 1.000 every run | invisible |
| 2 | 1.000 every run | invisible |
| 3 | 1.219 – 1.342 | invisible |
| 4 | 1.598 – 1.770, and 1.480 on a separate run | **straddles the threshold** |
| 5 | 2.121 – 2.301 | detected |
| 6 | 2.635 – 2.779 | detected |
| 8 | 3.490 – 3.717 | detected |
| 128 | 4.07 | detected |

Every rate was measured, including the ones that only confirm the boundary; none is interpolated. Each row is five repeated three-subprocess runs, because a single run does not establish where a boundary sits: four bytes per row read 1.480 on one earlier run and 1.598–1.770 across the five, which is the difference between a rate that is detected and a rate that is *usually* detected.

`F` is 2 MiB because that table is the only reason to choose a value. At 8 MiB a container retaining four bytes per row — an `array("I")` of row numbers — passed at 1.20 while growing perfectly linearly. Six repeated bounded runs produced a ratio of exactly 1.000 at every floor down to 0.25 MiB, so the tightening costs no false failures; there was no reason to leave it at 8 beyond the number having been written down first.

Detection SHALL be described as **reliable from five retained bytes per row**, not from four. Four is the boundary and has been observed on both sides of the threshold; describing a straddling rate as detected would claim a guarantee the measurements do not support.

At three bytes per row and below the binding constraint is **not** the floor but measurement resolution: one and two bytes per row register `W1 = W2 = 0.00 MiB`, because a megabyte or two of growth against an eighteen-megabyte baseline does not move `ru_maxrss` at all, and three moves it 0.25 MiB. No choice of `F` detects that, and the specification SHALL NOT claim otherwise.

That residual SHALL be stated rather than argued away. An implementation retaining two bytes per row holds 4 MiB at the largest release this platform has measured, which the 900 MiB budget absorbs without noticing; and it is not the defect this check exists to find. What the check detects, and what the platform's failure mode actually looks like, is **record retention**: a `set` of key tuples measured 28.9 MiB at 250,000 rows and failed at 3.55, and a list of per-row dicts measured 61.2 MiB and failed at 3.74. The check is a detector of retained records, not of all linear growth, and describing it as the latter would be the same overclaim this change has already had to withdraw twice.

The benchmark SHALL apply both checks and SHALL fail if either fails:

1. **Absolute.** A peak at 1,000,000 rows SHALL be under 900 MiB, measured from the **cgroup**. This supersedes the issue body's 1 GiB because the scheduler 419 MiB container peak with no task running shares the same 4 GiB container at a parallelism of four.

   The absolute check SHALL NOT use the `rusage` figures the ratio is built from. Issue #43 D5 makes the cgroup the authority the limit is enforced against, it is what the OOM killer reads, and this change states in its own text that the two sources are incomparable — so reporting a `rusage` number against a cgroup-derived budget would be the same defect the source-agreement rule exists to prevent, committed one paragraph later.

   Because a cgroup peak is per-cgroup and sticky, the absolute measurement SHALL be taken in a cgroup containing only that run, and the benchmark SHALL **verify** that rather than assume it.

   The benchmark SHALL **require** caller-provided isolation and SHALL NOT attempt to create a cgroup itself. Creating one needs delegation the benchmark cannot assume it has, and a command that silently acquires privileges to measure itself is a worse instrument than one that states its precondition.

   The reproducible invocation on a systemd host is:

   ```
   systemd-run --user --scope -p MemoryAccounting=yes make benchmark-release-peak-rss
   ```

   which places the run in a fresh scope of its own. Measured on one host, the ambient shell's cgroup held six processes and a peak of 964 MB inherited from unrelated work, while the same probe inside such a scope reported three processes — its own tree — and a peak of 2.2 MB. A **purpose-built** container whose cgroup holds only this run may satisfy the requirement in place of the wrapper, subject to the same `cgroup.procs` verification — never by assumption, and never merely because the run is containerized.

   The Airflow container specifically does **not** satisfy it. The 900 MiB figure is derived from that container holding a scheduler and four concurrent task processes, so its cgroup contains siblings by construction; a peak read there is the container's, not this run's. A rule that treated any container as isolated would be contradicted by the very deployment the budget was computed from. The `make` target SHALL document this invocation, and SHALL NOT wrap itself in it, so that the isolation a result depended on is visible in the command a reader ran.

   Verification SHALL check the **whole subtree**, not the one cgroup's direct membership.

   `cgroup.procs` lists only processes attached directly to that cgroup, while `memory.peak` charges the cgroup **and all of its descendants**. A foreign process in a child cgroup therefore raises the peak while appearing nowhere in `cgroup.procs`, so a check reading only that file would certify isolation it does not have — the same defect as the shared-cgroup ratio, arriving through the absolute check and through the file that was supposed to prevent it.

   Verification SHALL therefore require, for the cgroup named by `/proc/self/cgroup`:

   1. `cgroup.procs` lists only this run's own process tree, and
   2. `cgroup.stat` reports `nr_descendants 0` **and** `nr_dying_descendants 0`.

   A dying descendant is included because a cgroup being torn down can still hold charges against the peak, so a non-zero count leaves the figure unattributable in exactly the way a live descendant would. Measured on one host, a fresh `systemd-run --user --scope` reported `nr_descendants 0`, `nr_dying_descendants 0`, and three directly-listed processes — its own tree — so the rule is satisfiable by the invocation this specification recommends, and is not a bar nothing can clear.

   Where a host does not expose `cgroup.stat`, the subtree cannot be shown empty and the absolute is indeterminate; the benchmark SHALL NOT fall back to the weaker `cgroup.procs`-only check, which is the check that fails to see the case that matters.

   Where the benchmark cannot establish or verify such a cgroup, it SHALL report the absolute check as **indeterminate**, naming why, and SHALL NOT substitute a source that was not asked for.

   An indeterminate absolute SHALL NOT be reported as a pass, and the command SHALL exit **non-zero**. A run that could not measure the thing it exists to measure has not demonstrated the target, and an exit status a caller reads as success is how an unproven claim becomes a settled one.

#### Scenario: A shared container does not count as isolation
- **GIVEN** a run inside the Airflow container, whose cgroup also holds the scheduler and sibling task processes
- **WHEN** the benchmark verifies isolation
- **THEN** `cgroup.procs` lists processes outside this run and the check fails
- **THEN** the absolute is reported indeterminate rather than reporting the container's peak as this run's

#### Scenario: Isolation is required of the caller, not created by the run
- **GIVEN** a host where the benchmark is invoked without a scope or container of its own
- **WHEN** it checks isolation
- **THEN** it reports the absolute indeterminate and names the invocation that would provide isolation
- **THEN** it does not create a cgroup or acquire privileges to measure itself

#### Scenario: Isolation is verified rather than assumed
- **GIVEN** a cgroup whose `cgroup.procs` lists a process outside this run
- **WHEN** the benchmark checks isolation before the absolute measurement
- **THEN** it treats the absolute as indeterminate rather than reporting a neighbour's peak

#### Scenario: A foreign process in a child cgroup is caught
- **GIVEN** a cgroup whose own `cgroup.procs` lists only this run, but which has a descendant cgroup holding another process
- **WHEN** the benchmark verifies isolation
- **THEN** `cgroup.stat` reports a non-zero `nr_descendants` and the check fails
- **THEN** the absolute is indeterminate, rather than reporting a peak that charges the descendant's memory

#### Scenario: A cgroup being torn down still blocks attribution
- **GIVEN** a cgroup reporting `nr_dying_descendants` above zero
- **WHEN** the benchmark verifies isolation
- **THEN** the check fails, because a dying cgroup can still hold charges against the peak

#### Scenario: An indeterminate absolute fails the command
- **GIVEN** a run that could not establish an isolated cgroup
- **WHEN** the benchmark finishes
- **THEN** it names the absolute check indeterminate
- **THEN** it exits non-zero rather than reporting success
2. **Scaling.** `scaling_ratio` SHALL be at most **1.5**, computed from the three `rusage` measurements, which is the only source that isolates one process from its siblings.

The threshold of 1.5 follows from what each implementation shape produces. Rows increase fourfold between the two sizes, so a boundary retaining every row has `W2 ≈ 4 × W1` and a scaling ratio approaching **4.0**, while a boundary retaining nothing has `W2 ≈ W1` and a ratio approaching **1.0**. A limit of 1.5 permits the working set to grow by half while the row count grows by three hundred percent — at most one sixth of proportional growth — which is far below the linear signal and well above allocator variance and the generator's own per-row transients.

A single absolute figure SHALL NOT be treated as evidence of boundedness. An implementation retaining every row can pass one absolute on a large enough machine and fail at the next order of magnitude with no warning.

The guard value also bounds what the scaling check can detect, and that limit is recorded in the measured table above rather than derived from the threshold: detection is reliable from five retained bytes per row, four straddles the threshold across repeats, and three or fewer are invisible to `ru_maxrss` at these sizes regardless of `F`. The arithmetic bound is looser than the measured one — solving `(4W + F) / (W + F) = 1.5` with `F` = 2 MiB gives a 0.4 MiB working set, about 1.7 bytes per row at 250,000 — so the measurement, not the algebra, is what the specification states.

#### Scenario: A bounded implementation passes both checks
- **GIVEN** a boundary that retains no row after writing it, in an isolated cgroup
- **WHEN** the benchmark takes its measurements
- **THEN** the cgroup peak at 1,000,000 rows is under 900 MiB
- **THEN** `scaling_ratio`, from the `rusage` samples, is at most 1.5

#### Scenario: The absolute cannot be measured against its authority
- **GIVEN** a host where the benchmark cannot establish a cgroup containing only its run
- **WHEN** the benchmark evaluates the absolute check
- **THEN** it reports the check as indeterminate and names why
- **THEN** it does not substitute a `rusage` figure
- **THEN** the indeterminate result is not reported as a pass

#### Scenario: The linearity requirement is answered by two things, not one
- **GIVEN** issue #43 D5's requirement that memory not grow linearly with row count
- **WHEN** the evidence for it is assembled
- **THEN** the structural half comes from the accepted `bounded-release-processing` capability — a reader lead bounded by a constant and identical across two fixture lengths, and carriers retaining at most a hundred entries — which are checks on shape with no measurement floor
- **THEN** this change's benchmark supplies the budget half, and is described as evidence rather than proof
- **THEN** no document in this change claims the benchmark alone establishes that memory does not grow linearly

#### Scenario: A linear implementation fails even when it fits
- **GIVEN** a boundary that accumulates rows, whose **cgroup** peak at 1,000,000 rows happens to fall under 900 MiB
- **WHEN** the benchmark takes its four measurements
- **THEN** `W2` is approximately four times `W1`
- **THEN** `scaling_ratio` exceeds 1.5 and the benchmark fails on the scaling check even though the absolute check passed
- **THEN** the passing absolute is read from the cgroup figure and not from `P2`, which is a `rusage` measurement and settles nothing about the limit

#### Scenario: Two bounded measurements a few kilobytes apart do not fail on noise
- **GIVEN** a bounded boundary whose two working sets differ only by allocator variance
- **WHEN** the scaling ratio is computed with the 2 MiB degenerate-ratio guard added to both terms
- **THEN** the ratio remains near 1.0 rather than being amplified by the small denominator

#### Scenario: Each size is measured in its own process, with a per-process source
- **GIVEN** a peak that is a high-water mark for the life of a process
- **WHEN** the benchmark measures 0, 250,000, and 1,000,000 rows
- **THEN** each measurement runs in a separate subprocess
- **THEN** each is taken from `rusage`, which is per-process
- **THEN** neither reported peak includes another size's allocations

#### Scenario: A shared cgroup peak is nondeterministic, not merely wrong
- **GIVEN** three subprocesses in one cgroup whose `memory.peak` is sticky and shared
- **WHEN** all three read that file
- **THEN** none of them reports a figure describing its own process
- **THEN** repeating the same workload does not reproduce the same three figures, because each depends on when its reader was scheduled
- **THEN** the benchmark SHALL NOT use the cgroup source for these measurements

#### Scenario: Mixed sources are refused rather than ratioed
- **GIVEN** three samples of which at least one names a different source
- **WHEN** the benchmark computes the scaling ratio
- **THEN** it fails closed and reports the disagreement
- **THEN** no ratio across incomparable quantities is published

### Requirement: Make the acceptance run reproducible, offline, and self-describing

The benchmark SHALL be a `make` target rather than a `pytest` test, because issue #43 D5 separates deterministic bounded CI tests from the reproducible acceptance command.

It SHALL require no network.

It SHALL report the row count, the column count, the baseline `B`, the two size peaks `P1` and `P2`, the derived working sets `W1` and `W2`, the computed `scaling_ratio`, the separate cgroup figure the absolute check used, the source of every measurement, whether the three comparative sources agreed, whether the cgroup was verified isolated, and the verdict of each of the two checks **separately** — including `indeterminate` where that is the answer.

A result that does not say what was run cannot be checked by a reader; a peak that does not name its source cannot be compared with another; and two checks reported as one verdict hide which of them actually passed.

Regular CI SHALL run deterministic bounded contract tests for the probe, the guard, and the generator, and SHALL NOT run the million-row benchmark.

#### Scenario: The report says what was run
- **GIVEN** a completed benchmark run
- **WHEN** its output is read
- **THEN** it states the row count, column count, and measured peak for each size
- **THEN** it names the measurement source for each, and whether the 900 MiB target was met

#### Scenario: CI stays bounded
- **GIVEN** the ordinary test suite
- **WHEN** it runs
- **THEN** the probe, guard, and generator are covered by deterministic bounded tests
- **THEN** no million-row run occurs

### Requirement: State what the benchmark does not establish

Documentation SHALL state that the benchmark measures one process on the machine that runs it, and does **not** establish behaviour under four concurrent tasks inside a 4 GiB container, which is the arithmetic that produced the 900 MiB per-task figure.

It SHALL state that what the benchmark does establish is that one task's peak fits the per-task budget and does not scale with release size.

It SHALL state that the resource half of issue #43 D5 lands here while the boundary itself — the protocols, the lifecycle, the vocabulary, and the outcome — is owned by the `bounded-release-processing` capability and is not modified.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, or archive locations.

#### Scenario: The limit of the evidence is stated
- **GIVEN** the resource document
- **WHEN** it is read
- **THEN** it says the benchmark measures one process, not four concurrent tasks in a container
- **THEN** it says what the measurement does establish, rather than leaving the scope to be inferred

#### Scenario: Ownership is attributed
- **GIVEN** the resource document
- **WHEN** its scope section is read
- **THEN** the boundary's protocols, lifecycle, vocabulary, and outcome are attributed to the `bounded-release-processing` capability
- **THEN** this change is described as supplying an implementation of an already-declared protocol
