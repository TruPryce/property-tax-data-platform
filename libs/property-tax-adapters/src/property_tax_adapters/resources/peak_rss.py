"""Read a peak resident set size, and reject a release that exceeds a limit.

Beside `property_tax_adapters.release` rather than inside it.  That package
asserts per module that it imports only `__future__`, `re`, `collections`,
`contextlib`, `dataclasses`, `enum`, `types`, and `typing`, and a probe needs
`resource` and a filesystem read.  The separation is the right architecture
rather than a way around a test: the boundary owns *when* it asks and
deliberately owns no measurement, so the package that acquires operating-system
dependencies is exactly the one that belongs outside it.

`tracemalloc` is never a source here.  One measured run reported 663 MiB traced
against 2,079 MiB resident, and the OOM killer reads resident set size, so a
traced figure can sit comfortably under budget while the task is killed.
"""

from __future__ import annotations

import resource
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from property_tax_adapters.release import ResourceGuard

__all__ = [
    "CGROUP_MOUNT",
    "PeakRssGuard",
    "PeakRssSample",
    "PeakRssSource",
    "PeakRssSourceUnavailable",
    "read_peak_rss",
    "resolve_cgroup_peak_path",
]

#: Where cgroup v2 is mounted.  A constant rather than a literal at each use so
#: a test can point the resolver somewhere else without patching the filesystem.
CGROUP_MOUNT = Path("/sys/fs/cgroup")

#: `ru_maxrss` is kilobytes on Linux, bytes on macOS.  This platform is Linux —
#: the boundary runs in a Linux container — and the conversion is stated here
#: rather than inline so the assumption is findable.
_RU_MAXRSS_UNIT_BYTES = 1024

_PROC_SELF_CGROUP = Path("/proc/self/cgroup")


class PeakRssSource(StrEnum):
    """Where a peak figure came from.  Exactly two, and they are not comparable.

    The cgroup charges a whole subtree and is the authority a container limit is
    enforced against.  `ru_maxrss` is per-process.  A number that does not say
    which it is cannot be compared with another, which is why every sample
    carries one.
    """

    CGROUP_V2 = "cgroup_v2"
    RUSAGE = "rusage"


class PeakRssSourceUnavailable(Exception):  # noqa: N818 - the accepted change fixes this name
    """A named source could not be read.

    Typed because the benchmark must catch exactly this to report an
    indeterminate absolute rather than crash.  Matching on message text would be
    both unstable across implementations and forbidden by the privacy rules.

    It carries the requested source and no host path: a path is host-local
    detail that does not belong in anything this boundary reports.
    """

    def __init__(self, source: PeakRssSource) -> None:
        self.source = source
        super().__init__(f"peak-RSS source unavailable: {source.value}")


@dataclass(frozen=True, slots=True)
class PeakRssSample:
    """One peak figure and the source that produced it.

    A sample rather than a bare integer, so a figure always names its source and
    two measurements can be compared — or refused as incomparable, which is the
    case this type exists to make visible.
    """

    peak_bytes: int
    source: PeakRssSource

    def __post_init__(self) -> None:
        if isinstance(self.peak_bytes, bool) or not isinstance(self.peak_bytes, int):
            raise ValueError("peak_bytes must be an int")
        if self.peak_bytes < 0:
            raise ValueError("peak_bytes must not be negative")
        if not isinstance(self.source, PeakRssSource):
            raise ValueError("source must be a PeakRssSource")


def resolve_cgroup_peak_path(mount: Path = CGROUP_MOUNT) -> Path | None:
    """Join the cgroup mount with the relative path `/proc/self/cgroup` reports.

    Returns `None` when that file is unreadable or carries no cgroup v2 entry.
    **Not** the mount root: assuming the root is precisely what the contract
    forbids, and doing it as a fallback would read some *other* cgroup's figure
    under the name of this one — the failure the resolution rule exists to
    prevent, arrived at by the error path instead of the happy path.

    Resolving is not the same as refusing the root.  A process in a cgroup
    namespace — the ordinary case inside a container — legitimately reports `/`,
    and there the resolved path *is* the mount root.  What must never happen is
    reading the root without resolving: a process in a nested cgroup, which is
    every process under systemd and every container under a delegated slice, has
    no `memory.peak` there.
    """

    try:
        reported = _PROC_SELF_CGROUP.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in reported.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0":
            return mount / parts[2].strip().lstrip("/") / "memory.peak"
    return None


def _read_cgroup_peak(mount: Path) -> int | None:
    path = resolve_cgroup_peak_path(mount)
    if path is None:
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_rusage_peak() -> int:
    # The maximum of the two, not a sum. `RUSAGE_CHILDREN` counts only children
    # that have terminated and been waited for, and reports the largest of them
    # rather than their total: measured at 0 MiB while two 300 MiB children were
    # alive and 308 MiB once both were reaped. It is kept because it can only
    # raise the figure, and so can only make a limit fire sooner, which is the
    # safe direction — as a partial signal, not as coverage of children.
    return (
        max(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        )
        * _RU_MAXRSS_UNIT_BYTES
    )


def read_peak_rss(
    source: PeakRssSource | None = None, *, mount: Path = CGROUP_MOUNT
) -> PeakRssSample:
    """Sample the peak, from the named source or by the documented precedence.

    A named source that cannot be read raises rather than falling back.
    Substituting a source the caller did not ask for is how a benchmark ends up
    comparing three identical cgroup figures and reporting a ratio of 1.0 for a
    linear implementation — the vacuous pass that naming a source exists to
    prevent, arrived at silently.
    """

    if source is PeakRssSource.RUSAGE:
        return PeakRssSample(peak_bytes=_read_rusage_peak(), source=PeakRssSource.RUSAGE)

    if source is PeakRssSource.CGROUP_V2:
        peak = _read_cgroup_peak(mount)
        if peak is None:
            raise PeakRssSourceUnavailable(PeakRssSource.CGROUP_V2)
        return PeakRssSample(peak_bytes=peak, source=PeakRssSource.CGROUP_V2)

    peak = _read_cgroup_peak(mount)
    if peak is not None:
        return PeakRssSample(peak_bytes=peak, source=PeakRssSource.CGROUP_V2)
    return PeakRssSample(peak_bytes=_read_rusage_peak(), source=PeakRssSource.RUSAGE)


class PeakRssGuard(ResourceGuard):
    """Reject a release whose process peak reaches a per-task limit.

    Measures at the grain its limit is expressed in.  The 900 MiB budget is
    *per task*, derived as one quarter of what remains of a 4 GiB container
    after the scheduler's share — arithmetic that describes a container holding
    five processes.  A guard reading that container's cgroup against a per-task
    limit compares the wrong pair: measured on one host, a process whose own
    peak was 28.0 MiB sat in a cgroup peaking at 1,072.3 MiB, and a cgroup
    reading would have rejected it along with every other compliant task there.

    So there is no cgroup mode to configure.  Beyond the grain, a cgroup figure
    is per-task only while its subtree stays empty, and this runs at every
    checkpoint — verifying once at construction proves nothing, because a
    process can join afterwards.

    What it covers is the current process plus a partial reaped-child signal,
    and no more.  `PreparedReader` and `ReleaseStage` are caller-supplied, and
    nothing forbids a conforming one from spawning a subprocess whose memory
    this cannot see.  The isolated-cgroup benchmark remains authoritative,
    because a cgroup charges the whole subtree — which is exactly what
    per-process measurement gives up.
    """

    __slots__ = ("_limit_bytes", "last_sample")

    def __init__(self, limit_bytes: int) -> None:
        if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int):
            raise ValueError("limit_bytes must be an int")
        if limit_bytes < 1:
            raise ValueError("limit_bytes must be positive")
        self._limit_bytes = limit_bytes
        #: The most recent sample acted on, and no history: a list would grow
        #: with the release, which is the defect this whole change exists to
        #: prevent. `None` until the first check.
        self.last_sample: PeakRssSample | None = None

    @property
    def limit_bytes(self) -> int:
        return self._limit_bytes

    def check(self, physical_rows_processed: int, staged_record_count: int) -> None:
        """Sample, record, and raise at or above the limit.

        Recorded *before* raising, so a rejection exposes the sample that caused
        it rather than the previous checkpoint's — a number that is wrong is
        worse than no number, because the reader has something to trust.

        `>=` rather than `>`: the acceptance target is a peak strictly under the
        limit, and a guard admitting exactly the limit would pass what the
        benchmark then fails.
        """

        del physical_rows_processed, staged_record_count  # the grain is memory, not rows
        sample = read_peak_rss(PeakRssSource.RUSAGE)
        self.last_sample = sample
        if sample.peak_bytes >= self._limit_bytes:
            raise PeakRssLimitExceeded(sample, self._limit_bytes)


class PeakRssLimitExceeded(Exception):  # noqa: N818 - reads with its contract-named sibling
    """Raised by `PeakRssGuard` when the peak reaches its limit.

    The boundary maps any raise from a guard to `resource_limit_exceeded` and
    rejects the release.  Warning instead would leave the task to the OOM
    killer, which produces no outcome, no diagnostic, and no progress event: a
    silent death is not a safer failure than a reported one.
    """

    def __init__(self, sample: PeakRssSample, limit_bytes: int) -> None:
        self.sample = sample
        self.limit_bytes = limit_bytes
        super().__init__(
            f"peak {sample.peak_bytes} bytes from {sample.source.value} "
            f"reached the {limit_bytes}-byte limit"
        )
