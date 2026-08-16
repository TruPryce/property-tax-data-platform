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

### Requirement: Enforce a peak-RSS limit through the accepted guard protocol

The library SHALL provide `PeakRssGuard`, implementing the `ResourceGuard` protocol that `add-bounded-release-processing` declares, taking a limit in bytes and implementing `check(physical_rows_processed: int, staged_record_count: int) -> None`.

`check` SHALL sample the peak and SHALL raise when it exceeds the configured limit. The boundary maps that raise to `resource_limit_exceeded` and rejects the release.

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

The acceptance benchmark SHALL run the boundary at **two** release sizes, 250,000 and 1,000,000 physical rows, and SHALL require that the measured peak does not scale with the row count.

A single absolute figure SHALL NOT be treated as evidence of boundedness. An implementation retaining every row can pass one absolute on a large enough machine and fail at the next order of magnitude with no warning; the fourfold row increase between the two sizes is what distinguishes a flat peak from a linear one.

The peak at 1,000,000 rows SHALL be under 900 MiB, which supersedes the issue body's 1 GiB because the scheduler's measured 400 MiB peak shares the same 4 GiB container at a parallelism of four.

#### Scenario: A bounded implementation passes both checks
- **GIVEN** a boundary that retains no row after writing it
- **WHEN** the benchmark runs at 250,000 and 1,000,000 rows
- **THEN** the peak at 1,000,000 rows is under 900 MiB
- **THEN** the two peaks are close enough that the fourfold row increase did not scale memory

#### Scenario: A linear implementation fails even when it fits
- **GIVEN** a boundary that accumulates rows, whose peak at 1,000,000 rows happens to fall under 900 MiB
- **WHEN** the benchmark runs at both sizes
- **THEN** the peak grows in proportion to the rows
- **THEN** the benchmark fails on the ratio even though the absolute passed

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

It SHALL state that the resource half of issue #43 D5 lands here while the boundary itself — the protocols, the lifecycle, the vocabulary, and the outcome — is owned by `add-bounded-release-processing` and is not modified.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, or archive locations.

#### Scenario: The limit of the evidence is stated
- **GIVEN** the resource document
- **WHEN** it is read
- **THEN** it says the benchmark measures one process, not four concurrent tasks in a container
- **THEN** it says what the measurement does establish, rather than leaving the scope to be inferred

#### Scenario: Ownership is attributed
- **GIVEN** the resource document
- **WHEN** its scope section is read
- **THEN** the boundary's protocols, lifecycle, vocabulary, and outcome are attributed to `add-bounded-release-processing`
- **THEN** this change is described as supplying an implementation of an already-declared protocol
