## ADDED Requirements

### Requirement: Read peak resident set size from a defined source precedence

The library SHALL provide `read_peak_rss()` returning a frozen `PeakRssSample` whose fields, types, and invariants are exactly these:

| field | type | invariant |
| --- | --- | --- |
| `peak_bytes` | `int` | not negative |
| `source` | `PeakRssSource` | a `StrEnum` of exactly `cgroup_v2` and `rusage` |

The source precedence SHALL be: cgroup v2 `/sys/fs/cgroup/memory.peak` when it is readable, reported as `cgroup_v2`; otherwise `resource.getrusage`, taking the maximum of `RUSAGE_SELF` and `RUSAGE_CHILDREN` and multiplying by 1024 because `ru_maxrss` is KiB on Linux, reported as `rusage`.

`tracemalloc` SHALL NOT be a source. One measured run recorded 663 MiB traced against 2,079 MiB resident — a factor of three — and the OOM killer reads resident set size, so a traced figure can sit comfortably under budget while the task is killed.

Every reported measurement SHALL name its source. The cgroup is the authority the container limit is enforced against; `ru_maxrss` is a per-process high-water mark that does not account for unreaped children or sibling processes. Two numbers from different sources are not comparable, and a bare integer hides which one it is.

The cgroup path SHALL be resolved from `/proc/self/cgroup` rather than assumed to be `/sys/fs/cgroup/memory.peak`.

A process in a nested cgroup — which is every process under systemd, and every container under a delegated slice — has no `memory.peak` at the mount root. On a measured host the root path was absent entirely while the file existed beneath the relative path `/proc/self/cgroup` reports. A probe hard-coding the root would silently fall back to `rusage` on exactly the hosts the cgroup source exists to serve.

#### Scenario: The cgroup file is found beneath a nested path
- **GIVEN** a host whose `/proc/self/cgroup` reports a non-root relative path
- **WHEN** `read_peak_rss()` resolves the cgroup file
- **THEN** it reads `/sys/fs/cgroup` joined with that relative path
- **THEN** it reports `cgroup_v2` rather than falling back

#### Scenario: The cgroup is preferred where it exists
- **GIVEN** a host where `/sys/fs/cgroup/memory.peak` is readable
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

`check` SHALL sample the peak and SHALL raise when the sample is **at or above** the configured limit. The boundary maps that raise to `resource_limit_exceeded` and rejects the release.

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

The acceptance benchmark SHALL take **three** peak-RSS measurements, each in its own subprocess, and SHALL evaluate two independent checks against them.

Each measurement SHALL run in a separate subprocess **and** SHALL be taken with the `rusage` source, and the benchmark SHALL fail closed if the three samples do not all report the same source.

A separate process is necessary but not sufficient, and the reason is specific. A peak is a high-water mark, so two sizes measured in one process report the larger under both names. But sibling processes share a cgroup, and the cgroup high-water mark is sticky and per-cgroup rather than per-process: on a measured host it stood at 4.88 GB from unrelated earlier work and did not move for a child that allocated 300 MiB. Three subprocesses reading `memory.peak` would therefore report one identical number, and the ratio would be exactly 1.0 for a linear implementation as readily as for a bounded one — the check would not merely be contaminated, it would pass vacuously.

`ru_maxrss` under `RUSAGE_SELF` is genuinely per-process: on the same host the 300 MiB child reported 314.6 MiB against a sibling's 17.0 MiB. It is therefore the only source of the three measurements, and the benchmark SHALL NOT read the cgroup for them.

This does not demote the cgroup source generally. The guard keeps preferring it, because in production the cgroup **is** the container and its number is what the OOM killer acts on. The benchmark needs comparability between three processes; the guard needs the authority a limit is enforced against. Those are different requirements and they select different sources.

Requiring one source across all three is separate from choosing which. `ru_maxrss` and a cgroup figure account for different things — unreaped children and sibling processes among them — so a ratio taken across a mixed pair is arithmetic on incomparable quantities. The benchmark SHALL compare `PeakRssSample.source` across `B`, `P1`, and `P2` and SHALL fail rather than report a ratio when they differ.

The three measurements are:

| symbol | rows | what it measures |
| --- | --- | --- |
| `B` | 0 | the baseline: interpreter, imports, and harness |
| `P1` | 250,000 | baseline plus the working set at the smaller size |
| `P2` | 1,000,000 | baseline plus the working set at the acceptance size |

The working set at each size SHALL be computed by subtracting the baseline, floored at zero because measurement noise can place a peak below it:

```
W1 = max(P1 - B, 0)
W2 = max(P2 - B, 0)
```

The scaling ratio SHALL be computed with a fixed noise floor `F` of 8 MiB added to both terms:

```
scaling_ratio = (W2 + F) / (W1 + F)
```

The floor is what makes the ratio stable when both working sets are small: without it, two nearly-identical bounded measurements a few kilobytes apart can produce an arbitrarily large quotient, and the check would fail on noise rather than on growth.

The benchmark SHALL apply both checks and SHALL fail if either fails:

1. **Absolute.** `P2` SHALL be under 900 MiB. This supersedes the issue body's 1 GiB because the scheduler's measured 400 MiB peak shares the same 4 GiB container at a parallelism of four.
2. **Scaling.** `scaling_ratio` SHALL be at most **1.5**.

The threshold of 1.5 follows from what each implementation shape produces. Rows increase fourfold between the two sizes, so a boundary retaining every row has `W2 ≈ 4 × W1` and a scaling ratio approaching **4.0**, while a boundary retaining nothing has `W2 ≈ W1` and a ratio approaching **1.0**. A limit of 1.5 permits the working set to grow by half while the row count grows by three hundred percent — at most one sixth of proportional growth — which is far below the linear signal and well above allocator variance and the generator's own per-row transients.

A single absolute figure SHALL NOT be treated as evidence of boundedness. An implementation retaining every row can pass one absolute on a large enough machine and fail at the next order of magnitude with no warning.

The floor also bounds what the scaling check can detect, and that limit SHALL be stated rather than left implied. Solving `(4·W1 + F) / (W1 + F) ≤ 1.5` gives `W1 ≤ F/5`, so a genuinely linear implementation escapes the check only if its working set at 250,000 rows is under 1.6 MiB — about 6.7 bytes per row. No implementation retaining record objects can be that small, so the blind spot is unreachable by the defect the check exists to catch, but it is a blind spot and the document SHALL say so.

#### Scenario: A bounded implementation passes both checks
- **GIVEN** a boundary that retains no row after writing it
- **WHEN** the benchmark takes all three measurements
- **THEN** `P2` is under 900 MiB
- **THEN** `scaling_ratio` is at most 1.5

#### Scenario: A linear implementation fails even when it fits
- **GIVEN** a boundary that accumulates rows, whose `P2` happens to fall under 900 MiB
- **WHEN** the benchmark takes all three measurements
- **THEN** `W2` is approximately four times `W1`
- **THEN** `scaling_ratio` exceeds 1.5 and the benchmark fails on the scaling check even though the absolute check passed

#### Scenario: Two bounded measurements a few kilobytes apart do not fail on noise
- **GIVEN** a bounded boundary whose two working sets differ only by allocator variance
- **WHEN** the scaling ratio is computed with the 8 MiB floor added to both terms
- **THEN** the ratio remains near 1.0 rather than being amplified by the small denominator

#### Scenario: Each size is measured in its own process, with a per-process source
- **GIVEN** a peak that is a high-water mark for the life of a process
- **WHEN** the benchmark measures 0, 250,000, and 1,000,000 rows
- **THEN** each measurement runs in a separate subprocess
- **THEN** each is taken from `rusage`, which is per-process
- **THEN** neither reported peak includes another size's allocations

#### Scenario: A shared cgroup peak would make the check vacuous
- **GIVEN** three subprocesses in one cgroup whose `memory.peak` is sticky and shared
- **WHEN** all three read that file
- **THEN** they report one identical figure
- **THEN** the scaling ratio is 1.0 for a linear implementation as readily as for a bounded one
- **THEN** the benchmark SHALL NOT use the cgroup source for these measurements

#### Scenario: Mixed sources are refused rather than ratioed
- **GIVEN** three samples of which at least one names a different source
- **WHEN** the benchmark computes the scaling ratio
- **THEN** it fails closed and reports the disagreement
- **THEN** no ratio across incomparable quantities is published

### Requirement: Make the acceptance run reproducible, offline, and self-describing

The benchmark SHALL be a `make` target rather than a `pytest` test, because issue #43 D5 separates deterministic bounded CI tests from the reproducible acceptance command.

It SHALL require no network.

It SHALL report the row count, the column count, the measured peak for each size, the source of each measurement, and whether the target was met. A result that does not say what was run cannot be checked by a reader, and a peak that does not name its source cannot be compared with another.

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
