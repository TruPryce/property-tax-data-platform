"""Peak-RSS measurement and the guard that enforces a per-task limit.

Beside the release boundary rather than inside it: the boundary fixes when a
guard is asked and owns no measurement, so the operating-system dependencies
live here.  The dependency runs one way — this package imports the release
protocols, and no release module imports this one.
"""

from property_tax_adapters.resources.peak_rss import (
    CGROUP_MOUNT,
    PeakRssGuard,
    PeakRssLimitError,
    PeakRssSample,
    PeakRssSource,
    PeakRssSourceUnavailable,
    read_peak_rss,
    resolve_cgroup_peak_path,
)

__all__ = [
    "CGROUP_MOUNT",
    "PeakRssGuard",
    "PeakRssLimitError",
    "PeakRssSample",
    "PeakRssSource",
    "PeakRssSourceUnavailable",
    "read_peak_rss",
    "resolve_cgroup_peak_path",
]
