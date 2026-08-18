"""The benchmark's decisions, tested with injected samples rather than measured.

Injection is what makes these deterministic, and it is not a convenience:
`ru_maxrss` does not reproduce the detection threshold at small sizes, so a test
that allocated its way to a verdict would have to run at acceptance scale to
mean anything. Task 3.3 owns producing real ratios; this owns the logic over
them.

Nothing here allocates at acceptance scale, and nothing depends on the host
having a readable cgroup.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
from property_tax_adapters.resources import PeakRssSample, PeakRssSource

_BENCHMARK = pathlib.Path(__file__).resolve().parents[4] / "benchmarks" / "release_peak_rss.py"
_spec = importlib.util.spec_from_file_location("release_peak_rss", _BENCHMARK)
assert _spec and _spec.loader
bench = importlib.util.module_from_spec(_spec)
sys.modules["release_peak_rss"] = bench
_spec.loader.exec_module(bench)

MIB = 1024 * 1024


def sample(mib: float, source: PeakRssSource = PeakRssSource.RUSAGE) -> PeakRssSample:
    return PeakRssSample(peak_bytes=int(mib * MIB), source=source)


# --------------------------------------------------------------------------
# Ratio arithmetic
# --------------------------------------------------------------------------


def test_working_sets_floor_a_negative_difference_at_zero() -> None:
    """Noise can place a later peak below the baseline; that is not growth."""

    assert bench.working_sets(100, 90, 120) == (0, 20)


def test_the_guard_holds_the_quotient_at_one_when_both_sets_are_zero() -> None:
    """The expected case for a correct boundary, not an edge."""

    assert bench.scaling_ratio(50 * MIB, 50 * MIB, 50 * MIB) == 1.0


def test_the_guard_keeps_a_tiny_denominator_from_exploding() -> None:
    """0.02 MiB against 0.02 MiB is what a bounded boundary actually measures."""

    unfloored = (0.02 + 0.0) / (0.02 + 0.0)
    floored = bench.scaling_ratio(0, int(0.02 * MIB), int(0.02 * MIB))

    assert unfloored == 1.0
    assert floored == pytest.approx(1.0)
    assert bench.scaling_ratio(0, 1, 4096) == pytest.approx(1.0, abs=0.01)


def test_a_linear_working_set_approaches_the_row_ratio() -> None:
    """Fourfold rows, fourfold retention: the ratio the threshold is set against."""

    ratio = bench.scaling_ratio(0, 100 * MIB, 400 * MIB)

    assert ratio == pytest.approx((400 + 2) / (100 + 2), rel=1e-6)
    assert ratio > bench.SCALING_THRESHOLD


def test_the_guard_value_and_threshold_are_the_accepted_ones() -> None:
    assert bench.DEGENERATE_RATIO_GUARD_BYTES == 2 * MIB
    assert bench.SCALING_THRESHOLD == 1.5
    assert bench.ABSOLUTE_LIMIT_BYTES == 900 * MIB


# --------------------------------------------------------------------------
# Source agreement
# --------------------------------------------------------------------------


def test_three_rusage_samples_are_comparable() -> None:
    assert bench.samples_are_comparable((sample(1), sample(2), sample(3))) is True


def test_three_matching_cgroup_samples_are_refused() -> None:
    """Agreeing is what makes them useless, not what makes them comparable."""

    cgroups = (
        sample(300, PeakRssSource.CGROUP_V2),
        sample(300, PeakRssSource.CGROUP_V2),
        sample(300, PeakRssSource.CGROUP_V2),
    )

    assert bench.samples_are_comparable(cgroups) is False
    verdict = bench.evaluate_scaling(cgroups)
    assert verdict.result == bench.INDETERMINATE
    assert "must all be rusage" in verdict.detail


def test_a_mixed_triple_fails_closed_rather_than_reporting_a_ratio() -> None:
    """A ratio across a mixed pair is arithmetic on incomparable quantities."""

    mixed = (sample(1), sample(2), sample(3, PeakRssSource.CGROUP_V2))

    assert bench.samples_are_comparable(mixed) is False
    verdict = bench.evaluate_scaling(mixed)
    assert verdict.result == bench.INDETERMINATE
    assert "must all be rusage" in verdict.detail
    assert "ratio" not in verdict.detail


def test_a_bounded_triple_passes_the_scaling_check() -> None:
    verdict = bench.evaluate_scaling((sample(20), sample(20), sample(20)))

    assert verdict.result == bench.PASS


def test_a_five_byte_per_row_retainer_fails_the_scaling_check() -> None:
    """Injected samples for the calibrated rate: 250k and 1M rows at 5 bytes."""

    baseline = 20.0
    w1 = 250_000 * 5 / MIB
    w2 = 1_000_000 * 5 / MIB
    verdict = bench.evaluate_scaling(
        (sample(baseline), sample(baseline + w1), sample(baseline + w2))
    )

    assert verdict.result == bench.FAIL


# --------------------------------------------------------------------------
# Isolation
# --------------------------------------------------------------------------


def test_one_complete_tree_containing_this_run_with_an_empty_subtree_is_isolated() -> None:
    empty = {"nr_descendants": 0, "nr_dying_descendants": 0}

    assert bench.evaluate_isolation({100: 1, 101: 100}, empty, own_pid=101).verified is True


def test_a_sibling_of_the_same_run_does_not_break_isolation() -> None:
    """A shell pipeline puts one in the cgroup; it belongs to the run."""

    empty = {"nr_descendants": 0, "nr_dying_descendants": 0}
    isolation = bench.evaluate_isolation({100: 1, 101: 100, 102: 100}, empty, own_pid=101)

    assert isolation.verified is True


def test_a_cgroup_that_does_not_contain_this_process_is_not_isolation() -> None:
    """One tidy tree that is not ours says nothing about the figure we read."""

    empty = {"nr_descendants": 0, "nr_dying_descendants": 0}
    isolation = bench.evaluate_isolation({100: 1, 101: 100}, empty, own_pid=999)

    assert isolation.verified is False
    assert "not in the cgroup" in isolation.detail


def test_an_incomplete_membership_map_is_refused() -> None:
    """A dropped member is how a foreign tree becomes a clean-looking single one."""

    empty = {"nr_descendants": 0, "nr_dying_descendants": 0}
    isolation = bench.evaluate_isolation(None, empty, own_pid=101)

    assert isolation.verified is False
    assert "unreadable" in isolation.detail


def test_two_process_trees_are_not_this_run_alone() -> None:
    """The Airflow container's shape: a scheduler and tasks, several roots."""

    empty = {"nr_descendants": 0, "nr_dying_descendants": 0}
    isolation = bench.evaluate_isolation({100: 1, 200: 1}, empty, own_pid=100)

    assert isolation.verified is False
    assert "process trees" in isolation.detail


@pytest.mark.parametrize(
    "stat",
    [
        {"nr_descendants": 1, "nr_dying_descendants": 0},
        {"nr_descendants": 0, "nr_dying_descendants": 2},
    ],
    ids=["live-descendant", "dying-descendant"],
)
def test_a_descendant_cgroup_breaks_isolation(stat: dict[str, int]) -> None:
    """`memory.peak` charges descendants that `cgroup.procs` never lists."""

    isolation = bench.evaluate_isolation({100: 1}, stat, own_pid=100)

    assert isolation.verified is False
    assert "nr_descendants" in isolation.detail


def test_absent_cgroup_stat_is_not_downgraded_to_the_weaker_check() -> None:
    """The procs-only check is the one that cannot see the case that matters."""

    isolation = bench.evaluate_isolation({100: 1}, None, own_pid=100)

    assert isolation.verified is False
    assert "subtree cannot be shown empty" in isolation.detail


def test_an_empty_cgroup_is_not_isolation() -> None:
    assert bench.evaluate_isolation({}, {"nr_descendants": 0}, own_pid=1).verified is False


# --------------------------------------------------------------------------
# The absolute check, bracketed
# --------------------------------------------------------------------------


def isolated(verified: bool = True) -> object:
    return bench.Isolation(verified, "test")


def test_a_run_that_stays_under_the_limit_passes() -> None:
    verdict = bench.evaluate_absolute(20 * MIB, 300 * MIB, isolated())

    assert verdict.result == bench.PASS
    assert "before" in verdict.detail and "after" in verdict.detail


def test_a_run_that_crosses_the_limit_fails() -> None:
    """Initial below and final at or above: nothing else could have crossed it."""

    assert bench.evaluate_absolute(20 * MIB, 900 * MIB, isolated()).result == bench.FAIL
    assert bench.evaluate_absolute(20 * MIB, 901 * MIB, isolated()).result == bench.FAIL
    assert bench.evaluate_absolute(20 * MIB, 899 * MIB, isolated()).result == bench.PASS


def test_a_cgroup_already_over_the_limit_is_indeterminate_not_a_failure() -> None:
    """The measured ambient case: 4,566.8 MiB of unrelated earlier work.

    Age cannot answer this — a fresh shell with seconds of prior work defeats it
    — and the bracket does not need to, because a contaminated start makes any
    reading unattributable regardless of how the cgroup came to be.
    """

    verdict = bench.evaluate_absolute(4566 * MIB, 4566 * MIB, isolated())

    assert verdict.result == bench.INDETERMINATE
    assert "before this run" in verdict.detail


def test_the_absolute_is_indeterminate_without_isolation() -> None:
    assert (
        bench.evaluate_absolute(20 * MIB, 300 * MIB, isolated(False)).result == bench.INDETERMINATE
    )


@pytest.mark.parametrize(
    ("initial", "final"),
    [(None, 300 * MIB), (20 * MIB, None), (None, None)],
    ids=["no-initial", "no-final", "neither"],
)
def test_an_unreadable_bracket_is_indeterminate(initial: int | None, final: int | None) -> None:
    assert bench.evaluate_absolute(initial, final, isolated()).result == bench.INDETERMINATE


# --------------------------------------------------------------------------
# Calibration verdict
# --------------------------------------------------------------------------


def test_all_controls_passing_and_all_retainers_failing_validates_the_threshold() -> None:
    verdict = bench.evaluate_calibration([1.0] * 5, [2.2] * 5)

    assert verdict.result == bench.PASS
    assert "controls" in verdict.detail and "retainers" in verdict.detail


def test_a_failed_control_yields_indeterminate_and_leaves_the_threshold_unvalidated() -> None:
    """Not resolved by adjusting the threshold, which is what a run would reach for."""

    verdict = bench.evaluate_calibration([1.0, 1.0, 1.6, 1.0, 1.0], [2.2] * 5)

    assert verdict.result == bench.INDETERMINATE
    assert "unvalidated" in verdict.detail
    assert "not adjusted" in verdict.detail


def test_a_passed_retainer_yields_indeterminate_for_the_same_reason() -> None:
    verdict = bench.evaluate_calibration([1.0] * 5, [2.2, 2.2, 1.4, 2.2, 2.2])

    assert verdict.result == bench.INDETERMINATE
    assert "unvalidated" in verdict.detail


def test_too_few_repeats_is_indeterminate() -> None:
    """A boundary measured once is a point estimate; the decision fixed five."""

    assert bench.evaluate_calibration([1.0] * 4, [2.2] * 5).result == bench.INDETERMINATE
    assert bench.evaluate_calibration([1.0] * 5, [2.2] * 4).result == bench.INDETERMINATE
    assert bench.CALIBRATION_REPEATS == 5
    assert bench.CALIBRATION_RETAINER_BYTES_PER_ROW == 5


# --------------------------------------------------------------------------
# Exit status and reporting
# --------------------------------------------------------------------------


def test_every_pass_exits_zero() -> None:
    assert bench.exit_status([bench.Verdict("a", bench.PASS), bench.Verdict("b", bench.PASS)]) == 0


@pytest.mark.parametrize("result", [bench.FAIL, bench.INDETERMINATE], ids=["fail", "indeterminate"])
def test_anything_other_than_a_pass_exits_non_zero(result: str) -> None:
    """An indeterminate read as success is how an unproven claim becomes settled."""

    assert bench.exit_status([bench.Verdict("a", bench.PASS), bench.Verdict("b", result)]) == 1


def test_a_verdict_refuses_an_invented_result() -> None:
    with pytest.raises(ValueError, match="pass, fail, indeterminate"):
        bench.Verdict("a", "probably")


def test_the_report_names_every_figure_a_verdict_came_from() -> None:
    report = bench.Report(
        rows=1_000_000,
        columns=90,
        baseline_bytes=20 * MIB,
        small_bytes=20 * MIB,
        large_bytes=21 * MIB,
        comparative_sources=("rusage", "rusage", "rusage"),
        comparable=True,
        initial_cgroup_bytes=20 * MIB,
        cgroup_bytes=300 * MIB,
        isolation_verified=True,
        isolation_detail="subtree empty",
        verdicts=[bench.Verdict("absolute", bench.PASS), bench.Verdict("scaling", bench.PASS)],
    )

    rendered = report.render()
    for required in (
        "rows",
        "columns",
        "B ",
        "P1",
        "P2",
        "W1",
        "W2",
        "scaling_ratio",
        "measurement sources",
        "comparable samples",
        "cgroup peak",
        "isolation verified",
    ):
        assert required in rendered, required
    # The two verdicts appear separately rather than as one line.
    assert "absolute" in rendered and "scaling" in rendered


def test_the_report_shows_an_indeterminate_verdict_as_such() -> None:
    report = bench.Report(verdicts=[bench.Verdict("absolute", bench.INDETERMINATE, "no cgroup")])

    assert "indeterminate" in report.render()


def test_the_report_survives_an_unreadable_cgroup() -> None:
    assert "unreadable" in bench.Report(cgroup_bytes=None).render()


# --------------------------------------------------------------------------
# The report suppresses what the check refused
# --------------------------------------------------------------------------


def test_an_incomparable_run_publishes_no_ratio() -> None:
    """A number a reader can quote is worse than none where the check declined."""

    rendered = bench.Report(
        baseline_bytes=20 * MIB, small_bytes=20 * MIB, large_bytes=90 * MIB, comparable=False
    ).render()

    assert "not computed" in rendered
    assert "incomparable" in rendered
    for forbidden in ("1.000", "3.5", "4.0"):
        assert f"scaling_ratio        {forbidden}" not in rendered


def test_a_comparable_run_publishes_its_ratio() -> None:
    rendered = bench.Report(
        baseline_bytes=0, small_bytes=0, large_bytes=0, comparable=True
    ).render()

    assert "1.000" in rendered


# --------------------------------------------------------------------------
# Identity, and per-measurement sources
# --------------------------------------------------------------------------


def test_a_replacement_cgroup_at_the_same_path_is_not_the_pinned_one() -> None:
    """Behavioural, not structural: a field list would pass against `return True`.

    A scope torn down and restarted carries the same name and a fresh, unrelated
    peak. Comparing names calls those one cgroup; comparing device and inode
    does not.
    """

    pinned = bench.PinnedCgroup(pathlib.Path("/sys/fs/cgroup/x/memory.peak"), device=1, inode=100)
    same_name_new_object = bench.PinnedCgroup(pinned.peak_path, device=1, inode=999)
    same_object = bench.PinnedCgroup(pinned.peak_path, device=1, inode=100)

    def current(replacement: bench.PinnedCgroup):
        return lambda: replacement

    original = bench.pin_cgroup
    try:
        bench.pin_cgroup = current(same_name_new_object)  # type: ignore[assignment]
        assert pinned.still_current() is False, "a replacement at the same path was accepted"

        bench.pin_cgroup = current(same_object)  # type: ignore[assignment]
        assert pinned.still_current() is True

        bench.pin_cgroup = lambda: None  # type: ignore[assignment]
        assert pinned.still_current() is False, "an unavailable cgroup was treated as current"
    finally:
        bench.pin_cgroup = original  # type: ignore[assignment]


def test_a_different_device_at_the_same_inode_is_not_the_pinned_one() -> None:
    """Inode numbers are only unique within a device."""

    pinned = bench.PinnedCgroup(pathlib.Path("/sys/fs/cgroup/x/memory.peak"), device=1, inode=100)
    original = bench.pin_cgroup
    try:
        bench.pin_cgroup = lambda: bench.PinnedCgroup(pinned.peak_path, device=2, inode=100)  # type: ignore[assignment]
        assert pinned.still_current() is False
    finally:
        bench.pin_cgroup = original  # type: ignore[assignment]


def test_a_run_with_no_cgroup_reports_indeterminate_rather_than_crashing() -> None:
    """The whole path when `pin_cgroup()` returns `None`."""

    original_pin, original_measure = bench.pin_cgroup, bench.measure
    try:
        bench.pin_cgroup = lambda: None  # type: ignore[assignment]
        bench.measure = lambda rows, columns, retain=0: PeakRssSample(  # type: ignore[assignment]
            peak_bytes=20 * MIB, source=PeakRssSource.RUSAGE
        )
        report = bench.run_acceptance(1_000, 90)
    finally:
        bench.pin_cgroup, bench.measure = original_pin, original_measure  # type: ignore[assignment]

    absolute = next(v for v in report.verdicts if v.name == "absolute")
    assert absolute.result == bench.INDETERMINATE
    assert report.initial_cgroup_bytes is None and report.cgroup_bytes is None
    assert bench.exit_status(report.verdicts) == 1
    assert "unreadable" in report.render()


def test_the_report_names_each_measurement_source_rather_than_collapsing_them() -> None:
    """ "mixed" hides which of the three was the odd one, which is the actionable part."""

    rendered = bench.Report(
        comparative_sources=("rusage", "rusage", "cgroup_v2"), comparable=False
    ).render()

    assert "B=rusage P1=rusage P2=cgroup_v2" in rendered
    assert "mixed" not in rendered


def test_the_report_survives_having_no_sources_yet() -> None:
    assert "B=none" in bench.Report().render()
