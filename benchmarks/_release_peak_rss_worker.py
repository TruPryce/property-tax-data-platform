"""One measurement in its own process: drive the boundary, report the peak.

Separate from the benchmark so each size gets a fresh high-water mark. A
`retain_bytes_per_row` above zero makes this a deliberate retainer, which is
what calibration needs to prove the scaling check can still see one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs/property-tax-adapters/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs/property-tax-adapters/tests"))

from property_tax_adapters.release import process_release  # noqa: E402
from property_tax_adapters.resources import PeakRssSource, read_peak_rss  # noqa: E402
from release.scale import SyntheticReleaseReader  # noqa: E402


class _Stage:
    """Counts what it was handed and keeps none of it."""

    def __init__(self, retain_bytes_per_row: int) -> None:
        self.written = 0
        self._retain_bytes_per_row = retain_bytes_per_row
        self._retained = bytearray()

    def __enter__(self) -> _Stage:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def write(self, records: object) -> None:
        self.written += len(records)  # type: ignore[arg-type]
        if self._retain_bytes_per_row:
            self._retained += bytes(self._retain_bytes_per_row * len(records))  # type: ignore[arg-type]

    def finalize(self) -> None:
        return None

    def abort(self) -> None:
        return None

    def commit(self) -> str:
        return "memory://benchmark"


if __name__ == "__main__":
    rows, columns, retain = (int(value) for value in sys.argv[1:4])
    stage = _Stage(retain)
    process_release(reader=SyntheticReleaseReader(rows, columns=columns), stage=stage)
    sample = read_peak_rss(PeakRssSource.RUSAGE)
    print(json.dumps({"peak_bytes": sample.peak_bytes, "source": sample.source.value}))
