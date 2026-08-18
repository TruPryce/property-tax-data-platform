"""Acceptance benchmark for the bounded release boundary, and its calibration.

Two checks, reading different measurements because they answer different
questions.  The **scaling** check compares three `rusage` figures taken in
separate subprocesses, because that is the only source that isolates one process
from its siblings.  The **absolute** check reads the cgroup, because issue #43
D5 makes it the authority a limit is enforced against — and it is a per-task
figure only because isolation is required and verified first.

Isolation is the caller's to provide.  Creating a cgroup needs delegation this
command cannot assume it has, and one that silently acquired privileges to
measure itself would be a worse instrument than one that states its
precondition.  On a systemd host:

    systemd-run --user --scope -p MemoryAccounting=yes make benchmark-release-peak-rss

A purpose-built container holding only this run may serve instead, subject to
the same verification.  The Airflow container does not: the 900 MiB figure is
derived from it holding a scheduler and four tasks, so its cgroup contains
siblings by construction.

The decision logic below takes samples as arguments and measures nothing, so it
can be tested deterministically with injected values.  `ru_maxrss` does not
reproduce the detection threshold at small sizes, so a test that allocated its
way to a verdict would have to run at acceptance scale to mean anything.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs/property-tax-adapters/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs/property-tax-adapters/tests"))

from property_tax_adapters.resources import (  # noqa: E402
    PeakRssSample,
    PeakRssSource,
    PeakRssSourceUnavailable,
    read_peak_rss,
    resolve_cgroup_peak_path,
)

MIB = 1024 * 1024

#: The acceptance shape and the two thresholds, from the accepted change.
BASELINE_ROWS = 0
SMALL_ROWS = 250_000
ACCEPTANCE_ROWS = 1_000_000
ACCEPTANCE_COLUMNS = 90
ABSOLUTE_LIMIT_BYTES = 900 * MIB
SCALING_THRESHOLD = 1.5

#: A degenerate-ratio guard, not a noise floor.  It keeps the quotient defined
#: where a correct boundary puts it — a working set measured near 0.02 MiB,
#: where the unfloored quotient is 0.02/0.02 and means nothing.  Two rather than
#: eight because a swept accumulator retaining four bytes per row passed at 1.20
#: under eight and fails under two, while repeated bounded runs held at exactly
#: 1.000 at every value down to 0.25 MiB.
DEGENERATE_RATIO_GUARD_BYTES = 2 * MIB

#: Calibration terms fixed by the issue #43 decision.
CALIBRATION_REPEATS = 5
CALIBRATION_RETAINER_BYTES_PER_ROW = 5

INDETERMINATE = "indeterminate"
PASS = "pass"
FAIL = "fail"


# ---------------------------------------------------------------------------
# Decision logic.  Pure: takes samples, measures nothing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Verdict:
    """One check's outcome, with the reason it reached it."""

    name: str
    result: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.result not in (PASS, FAIL, INDETERMINATE):
            raise ValueError(f"result must be one of pass, fail, indeterminate; got {self.result}")

    @property
    def is_pass(self) -> bool:
        return self.result == PASS


def working_sets(baseline: int, small: int, large: int) -> tuple[int, int]:
    """Subtract the baseline, floored at zero: noise can place a peak below it."""

    return max(small - baseline, 0), max(large - baseline, 0)


def scaling_ratio(
    baseline: int, small: int, large: int, guard_bytes: int = DEGENERATE_RATIO_GUARD_BYTES
) -> float:
    """`(W2 + F) / (W1 + F)`, the quantity this specification defines."""

    w1, w2 = working_sets(baseline, small, large)
    return (w2 + guard_bytes) / (w1 + guard_bytes)


def sources_agree(samples: tuple[PeakRssSample, ...]) -> bool:
    """All three comparative measurements must name one source.

    `ru_maxrss` and a cgroup figure account for different things, so a ratio
    across a mixed pair is arithmetic on incomparable quantities.
    """

    return len({sample.source for sample in samples}) == 1


def evaluate_scaling(
    samples: tuple[PeakRssSample, PeakRssSample, PeakRssSample],
    *,
    threshold: float = SCALING_THRESHOLD,
    guard_bytes: int = DEGENERATE_RATIO_GUARD_BYTES,
) -> Verdict:
    """Fail closed on disagreement; otherwise compare the ratio to the threshold."""

    if not sources_agree(samples):
        named = ", ".join(sorted({sample.source.value for sample in samples}))
        return Verdict("scaling", INDETERMINATE, f"sources disagree: {named}")
    baseline, small, large = (sample.peak_bytes for sample in samples)
    ratio = scaling_ratio(baseline, small, large, guard_bytes)
    result = PASS if ratio <= threshold else FAIL
    return Verdict("scaling", result, f"ratio {ratio:.3f} against threshold {threshold}")


@dataclass(frozen=True, slots=True)
class Isolation:
    """Whether the cgroup this run sits in holds only this run."""

    verified: bool
    detail: str


def evaluate_isolation(
    parents: dict[int, int] | None, stat: dict[str, int] | None, own_pid: int
) -> Isolation:
    """Require one complete process tree containing this run, and an empty subtree.

    `parents` maps every pid in `cgroup.procs` to its parent, and must be
    **complete**: a pid whose parent could not be read is dropped from the map,
    and dropping one is how a foreign tree turns into a clean-looking single
    one.  A caller that could not read them all passes `None`.

    This process must be in the set.  A cgroup holding one tidy tree that is not
    ours is not isolation, and membership is the only thing tying the figure
    being read to the run reading it.

    A single tree, because a shared cgroup — the Airflow container with a
    scheduler and four tasks — has several roots.  Not every member need be an
    ancestor of this process: a shell pipeline puts a sibling in the cgroup and
    it belongs to the run.

    The subtree must be empty.  `cgroup.procs` lists only processes attached
    directly to a cgroup while `memory.peak` charges that cgroup *and all of its
    descendants*, so a foreign process one level down raises the peak while
    appearing nowhere in the file meant to catch it.

    Nothing here establishes that the cgroup was created *for* this run, and
    this function no longer tries.  An earlier version compared the root
    process's age, which a fresh shell with a few seconds of prior work defeats.
    That question is answered by bracketing the peak instead — see
    `evaluate_absolute`.
    """

    if parents is None:
        return Isolation(False, "cgroup.procs or a member's parent was unreadable")
    if not parents:
        return Isolation(False, "cgroup.procs is empty")
    members = set(parents)
    if own_pid not in members:
        return Isolation(False, "this process is not in the cgroup being measured")
    roots = sorted(pid for pid, parent in parents.items() if parent not in members)
    if len(roots) != 1:
        return Isolation(
            False, f"{len(roots)} process trees in the cgroup, so it is not this run alone"
        )
    if stat is None:
        # The weaker procs-only check is exactly the one that cannot see the
        # case that matters, so it is not substituted here.
        return Isolation(False, "cgroup.stat unavailable, so the subtree cannot be shown empty")
    descendants = stat.get("nr_descendants", -1)
    dying = stat.get("nr_dying_descendants", -1)
    if descendants != 0 or dying != 0:
        # Dying included: a cgroup being torn down can still hold charges.
        return Isolation(False, f"nr_descendants={descendants}, nr_dying_descendants={dying}")
    return Isolation(True, "one complete tree containing this run, and an empty subtree")


def evaluate_absolute(
    initial_bytes: int | None,
    final_bytes: int | None,
    isolation: Isolation,
    *,
    limit_bytes: int = ABSOLUTE_LIMIT_BYTES,
) -> Verdict:
    """Bracket the run: read the cgroup peak before it and after it.

    A cgroup peak is monotonic and charges whatever ran there earlier, so the
    question is not whether the cgroup is *fresh* — which cannot be established
    from inside, and which an age comparison only appears to answer.  It is
    whether the final figure is attributable to this run, and bracketing settles
    that without knowing anything about the cgroup's history:

    * an initial peak already at or above the limit means the cgroup arrived
      contaminated and no reading from it can be attributed — **indeterminate**;
    * initial below and final below means this run stayed inside the budget,
      whatever used the cgroup before it — **pass**;
    * initial below and final at or above means this run crossed it, because
      nothing else could have — **fail**.
    """

    if not isolation.verified:
        return Verdict("absolute", INDETERMINATE, f"isolation not established: {isolation.detail}")
    if initial_bytes is None or final_bytes is None:
        return Verdict("absolute", INDETERMINATE, "cgroup peak unreadable")
    if initial_bytes >= limit_bytes:
        return Verdict(
            "absolute",
            INDETERMINATE,
            f"the cgroup already peaked at {initial_bytes / MIB:.1f} MiB before this run, "
            "so no reading from it is attributable",
        )
    result = PASS if final_bytes < limit_bytes else FAIL
    return Verdict(
        "absolute",
        result,
        f"{initial_bytes / MIB:.1f} MiB before, {final_bytes / MIB:.1f} MiB after, "
        f"against a {limit_bytes / MIB:.0f} MiB limit",
    )


def evaluate_calibration(
    control_ratios: list[float],
    retainer_ratios: list[float],
    *,
    threshold: float = SCALING_THRESHOLD,
    repeats: int = CALIBRATION_REPEATS,
) -> Verdict:
    """Every control must pass and every retainer must fail.

    A threshold that has not been shown to discriminate is a number, not a
    check.  Where it cannot be shown, the answer is indeterminate — never the
    threshold adjusted to fit, which is the one response the requirement forbids
    and the one an implementation would reach for first.
    """

    if len(control_ratios) < repeats or len(retainer_ratios) < repeats:
        return Verdict(
            "calibration",
            INDETERMINATE,
            f"needs at least {repeats} of each, got "
            f"{len(control_ratios)} and {len(retainer_ratios)}",
        )
    stray_controls = [r for r in control_ratios if r > threshold]
    if stray_controls:
        return Verdict(
            "calibration",
            INDETERMINATE,
            f"{len(stray_controls)} bounded control(s) failed the scaling check; "
            "the threshold is unvalidated on this host and is not adjusted to fit",
        )
    stray_retainers = [r for r in retainer_ratios if r <= threshold]
    if stray_retainers:
        return Verdict(
            "calibration",
            INDETERMINATE,
            f"{len(stray_retainers)} retainer(s) passed the scaling check; "
            "the threshold is unvalidated on this host and is not adjusted to fit",
        )
    return Verdict(
        "calibration",
        PASS,
        f"controls {min(control_ratios):.3f}-{max(control_ratios):.3f}, "
        f"retainers {min(retainer_ratios):.3f}-{max(retainer_ratios):.3f}",
    )


def exit_status(verdicts: list[Verdict]) -> int:
    """Non-zero unless every verdict passed.

    An indeterminate result exits non-zero: a run that could not measure the
    thing it exists to measure has not demonstrated the target, and an exit
    status a caller reads as success is how an unproven claim becomes a settled
    one.
    """

    return 0 if all(verdict.is_pass for verdict in verdicts) else 1


@dataclass(slots=True)
class Report:
    """Everything a verdict was derived from, so a reader can check it."""

    rows: int = ACCEPTANCE_ROWS
    columns: int = ACCEPTANCE_COLUMNS
    baseline_bytes: int = 0
    small_bytes: int = 0
    large_bytes: int = 0
    comparative_source: str = ""
    sources_agreed: bool = False
    initial_cgroup_bytes: int | None = None
    cgroup_bytes: int | None = None
    isolation_verified: bool = False
    isolation_detail: str = ""
    verdicts: list[Verdict] = field(default_factory=list)

    def render(self) -> str:
        w1, w2 = working_sets(self.baseline_bytes, self.small_bytes, self.large_bytes)
        ratio = scaling_ratio(self.baseline_bytes, self.small_bytes, self.large_bytes)
        cgroup = "unreadable" if self.cgroup_bytes is None else f"{self.cgroup_bytes / MIB:.1f} MiB"
        before = (
            "unreadable"
            if self.initial_cgroup_bytes is None
            else f"{self.initial_cgroup_bytes / MIB:.1f} MiB"
        )
        lines = [
            "release peak-RSS acceptance benchmark",
            f"  rows                 {self.rows:,}",
            f"  columns              {self.columns}",
            f"  B  (0 rows)          {self.baseline_bytes / MIB:.2f} MiB",
            f"  P1 ({SMALL_ROWS:,} rows) {self.small_bytes / MIB:.2f} MiB",
            f"  P2 ({self.rows:,} rows) {self.large_bytes / MIB:.2f} MiB",
            f"  W1                   {w1 / MIB:.2f} MiB",
            f"  W2                   {w2 / MIB:.2f} MiB",
            f"  scaling_ratio        {ratio:.3f}",
            f"  comparative source   {self.comparative_source or 'none'}",
            f"  sources agreed       {self.sources_agreed}",
            f"  cgroup peak before   {before}",
            f"  cgroup peak after    {cgroup}",
            f"  isolation verified   {self.isolation_verified} ({self.isolation_detail})",
            "  verdicts",
        ]
        lines.extend(f"    {v.name:<12} {v.result:<14} {v.detail}" for v in self.verdicts)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Measurement.  Everything below performs I/O and is exercised by the make
# targets rather than by the ordinary suite.
# ---------------------------------------------------------------------------

_WORKER = Path(__file__).with_name("_release_peak_rss_worker.py")


def measure(rows: int, columns: int, retain_bytes_per_row: int = 0) -> PeakRssSample:
    """One measurement in its own subprocess.

    A separate process per size because a peak is a high-water mark: two sizes
    measured in one process report the larger under both names.
    """

    completed = subprocess.run(
        [sys.executable, str(_WORKER), str(rows), str(columns), str(retain_bytes_per_row)],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    return PeakRssSample(peak_bytes=payload["peak_bytes"], source=PeakRssSource(payload["source"]))


def read_cgroup_peak_bytes() -> int | None:
    """The cgroup peak now, or `None` if it cannot be read."""

    try:
        return read_peak_rss(PeakRssSource.CGROUP_V2).peak_bytes
    except PeakRssSourceUnavailable:
        return None


def _read_cgroup_isolation() -> tuple[Isolation, PeakRssSample | None]:
    peak_path = resolve_cgroup_peak_path()
    cgroup_dir = peak_path.parent
    try:
        procs = cgroup_dir.joinpath("cgroup.procs").read_text(encoding="utf-8").split()
    except OSError:
        procs = None
    try:
        raw = cgroup_dir.joinpath("cgroup.stat").read_text(encoding="utf-8")
        stat = {
            parts[0]: int(parts[1])
            for parts in (line.split() for line in raw.splitlines())
            if len(parts) == 2 and parts[1].lstrip("-").isdigit()
        }
    except OSError:
        stat = None

    parents: dict[int, int] | None = None
    if procs is not None:
        collected: dict[int, int] = {}
        for raw in procs:
            pid = int(raw)
            parent = _parent_of(pid)
            if parent is None:
                # Incomplete rather than partial: a dropped member is how a
                # foreign tree becomes a clean-looking single one.
                collected = {}
                parents = None
                break
            collected[pid] = parent
        else:
            parents = collected
    isolation = evaluate_isolation(parents, stat, os.getpid())
    try:
        sample = read_peak_rss(PeakRssSource.CGROUP_V2)
    except PeakRssSourceUnavailable:
        sample = None
    return isolation, sample


def _start_ticks(pid: int) -> int | None:
    try:
        after_comm = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1]
    except (OSError, IndexError):
        return None
    fields = after_comm.split()
    return int(fields[19]) if len(fields) > 19 else None


def _parent_of(pid: int) -> int | None:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    return None


def run_acceptance(rows: int, columns: int) -> Report:
    # Read before anything is measured: the bracket is what makes the final
    # figure attributable without needing to know the cgroup's history.
    initial_cgroup = read_cgroup_peak_bytes()
    baseline = measure(BASELINE_ROWS, columns)
    small = measure(SMALL_ROWS, columns)
    large = measure(rows, columns)
    samples = (baseline, small, large)

    isolation, cgroup_sample = _read_cgroup_isolation()
    report = Report(
        rows=rows,
        columns=columns,
        baseline_bytes=baseline.peak_bytes,
        small_bytes=small.peak_bytes,
        large_bytes=large.peak_bytes,
        comparative_source=baseline.source.value if sources_agree(samples) else "mixed",
        sources_agreed=sources_agree(samples),
        initial_cgroup_bytes=initial_cgroup,
        cgroup_bytes=None if cgroup_sample is None else cgroup_sample.peak_bytes,
        isolation_verified=isolation.verified,
        isolation_detail=isolation.detail,
    )
    report.verdicts = [
        evaluate_absolute(
            initial_cgroup, None if cgroup_sample is None else cgroup_sample.peak_bytes, isolation
        ),
        evaluate_scaling(samples),
    ]
    return report


def run_calibration(columns: int) -> tuple[Verdict, list[float], list[float]]:
    """Five bounded controls and five five-byte-per-row retainers.

    Repeats rather than single runs because a boundary measured once is a point
    estimate: four bytes per row read 1.480 on one run and 1.598 to 1.770 across
    five, which is the difference between a rate that is detected and one that
    is usually detected.
    """

    controls: list[float] = []
    retainers: list[float] = []
    for _ in range(CALIBRATION_REPEATS):
        b = measure(BASELINE_ROWS, columns)
        controls.append(
            scaling_ratio(
                b.peak_bytes,
                measure(SMALL_ROWS, columns).peak_bytes,
                measure(ACCEPTANCE_ROWS, columns).peak_bytes,
            )
        )
        rb = measure(BASELINE_ROWS, columns, CALIBRATION_RETAINER_BYTES_PER_ROW)
        retainers.append(
            scaling_ratio(
                rb.peak_bytes,
                measure(SMALL_ROWS, columns, CALIBRATION_RETAINER_BYTES_PER_ROW).peak_bytes,
                measure(ACCEPTANCE_ROWS, columns, CALIBRATION_RETAINER_BYTES_PER_ROW).peak_bytes,
            )
        )
    return evaluate_calibration(controls, retainers), controls, retainers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=ACCEPTANCE_ROWS)
    parser.add_argument("--columns", type=int, default=ACCEPTANCE_COLUMNS)
    parser.add_argument("--calibrate", action="store_true", help="run the calibration mode")
    args = parser.parse_args(argv)

    if args.calibrate:
        verdict, controls, retainers = run_calibration(args.columns)
        print("release peak-RSS calibration")
        print(f"  repeats              {CALIBRATION_REPEATS}")
        print(f"  retainer bytes/row   {CALIBRATION_RETAINER_BYTES_PER_ROW}")
        print(f"  control ratios       {' '.join(f'{r:.3f}' for r in controls)}")
        print(f"  retainer ratios      {' '.join(f'{r:.3f}' for r in retainers)}")
        print(f"  verdict              {verdict.result}  {verdict.detail}")
        return exit_status([verdict])

    report = run_acceptance(args.rows, args.columns)
    print(report.render())
    return exit_status(report.verdicts)


if __name__ == "__main__":
    raise SystemExit(main())
