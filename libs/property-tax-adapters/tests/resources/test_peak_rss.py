"""The probe's source selection and the guard's grain, limit, and carrier.

Bounded and deterministic: nothing here allocates at acceptance scale, and
nothing depends on the host having a readable cgroup — the cgroup mount is
injected, so both the present and absent cases are reachable on any machine.
"""

from __future__ import annotations

import ast
import pathlib
import resource

import pytest
from property_tax_adapters.release import ResourceGuard, process_release
from property_tax_adapters.resources import (
    PeakRssGuard,
    PeakRssLimitExceeded,
    PeakRssSample,
    PeakRssSource,
    PeakRssSourceUnavailable,
    read_peak_rss,
    resolve_cgroup_peak_path,
)
from property_tax_adapters.resources import peak_rss as peak_rss_module
from release.support import Reader, RecordingStage, envelopes

MIB = 1024 * 1024


def cgroup_at(tmp_path: pathlib.Path, peak: int | None) -> pathlib.Path:
    """A mount whose resolved `memory.peak` holds `peak`, or is absent."""

    mount = tmp_path / "cgroup"
    target = resolve_cgroup_peak_path(mount)
    target.parent.mkdir(parents=True, exist_ok=True)
    if peak is not None:
        target.write_text(f"{peak}\n", encoding="utf-8")
    return mount


# --------------------------------------------------------------------------
# Source selection
# --------------------------------------------------------------------------


def test_the_preference_reads_the_cgroup_when_it_is_readable(tmp_path: pathlib.Path) -> None:
    sample = read_peak_rss(mount=cgroup_at(tmp_path, 123 * MIB))

    assert sample.source is PeakRssSource.CGROUP_V2
    assert sample.peak_bytes == 123 * MIB


def test_the_fallback_applies_where_no_cgroup_file_exists(tmp_path: pathlib.Path) -> None:
    """A missing file is not an error when the caller named no source."""

    sample = read_peak_rss(mount=cgroup_at(tmp_path, None))

    assert sample.source is PeakRssSource.RUSAGE
    assert sample.peak_bytes > 0


def test_a_named_source_is_honoured_over_the_preference(tmp_path: pathlib.Path) -> None:
    """Naming `rusage` must work on the host the cgroup preference would win on."""

    mount = cgroup_at(tmp_path, 4_000 * MIB)

    named = read_peak_rss(PeakRssSource.RUSAGE, mount=mount)
    preferred = read_peak_rss(mount=mount)

    assert named.source is PeakRssSource.RUSAGE
    assert preferred.source is PeakRssSource.CGROUP_V2
    assert named.peak_bytes != preferred.peak_bytes, "the injected cgroup figure was returned"


def test_a_named_source_that_cannot_be_read_raises_rather_than_substituting(
    tmp_path: pathlib.Path,
) -> None:
    """Substituting would reproduce the vacuous ratio naming exists to prevent."""

    with pytest.raises(PeakRssSourceUnavailable) as raised:
        read_peak_rss(PeakRssSource.CGROUP_V2, mount=cgroup_at(tmp_path, None))

    assert raised.value.source is PeakRssSource.CGROUP_V2
    assert "/" not in str(raised.value), "a host path reached the exception"


def test_the_rusage_figure_is_the_documented_maximum() -> None:
    sample = read_peak_rss(PeakRssSource.RUSAGE)
    expected = (
        max(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        )
        * 1024
    )

    assert sample.peak_bytes == expected


# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------


def test_a_nested_cgroup_resolves_beneath_the_mount(tmp_path: pathlib.Path) -> None:
    """The measured host had no file at the root while one existed below it."""

    resolved = resolve_cgroup_peak_path(tmp_path / "cgroup")

    assert resolved.name == "memory.peak"
    assert resolved.is_relative_to(tmp_path / "cgroup")


def test_a_cgroup_namespace_reporting_root_resolves_to_the_mount_root(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reporting `/` is the ordinary container case, and the root is correct there."""

    reported = tmp_path / "proc-self-cgroup"
    reported.write_text("0::/\n", encoding="utf-8")
    monkeypatch.setattr(peak_rss_module, "_PROC_SELF_CGROUP", reported)

    assert resolve_cgroup_peak_path(tmp_path / "cgroup") == tmp_path / "cgroup" / "memory.peak"


def test_a_nested_relative_path_is_joined_not_assumed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reported = tmp_path / "proc-self-cgroup"
    reported.write_text("0::/user.slice/session.scope\n", encoding="utf-8")
    monkeypatch.setattr(peak_rss_module, "_PROC_SELF_CGROUP", reported)

    resolved = resolve_cgroup_peak_path(tmp_path / "cgroup")

    assert resolved == tmp_path / "cgroup" / "user.slice" / "session.scope" / "memory.peak"


# --------------------------------------------------------------------------
# The sample carrier
# --------------------------------------------------------------------------


def test_a_sample_declares_exactly_its_two_fields() -> None:
    assert set(PeakRssSample.__dataclass_fields__) == {"peak_bytes", "source"}

    sample = PeakRssSample(peak_bytes=1, source=PeakRssSource.RUSAGE)
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        sample.peak_bytes = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"peak_bytes": -1}, "must not be negative"),
        ({"peak_bytes": True}, "must be an int"),
        ({"peak_bytes": 1.5}, "must be an int"),
        ({"source": "rusage"}, "must be a PeakRssSource"),
    ],
    ids=["negative", "bool", "float", "raw-string-source"],
)
def test_an_incoherent_sample_is_refused(kwargs: dict, message: str) -> None:
    fields = {"peak_bytes": 1, "source": PeakRssSource.RUSAGE, **kwargs}
    with pytest.raises(ValueError, match=message):
        PeakRssSample(**fields)  # type: ignore[arg-type]


def test_the_source_vocabulary_is_exactly_two() -> None:
    assert {member.value for member in PeakRssSource} == {"cgroup_v2", "rusage"}


def test_no_code_path_returns_a_bare_integer() -> None:
    """A figure that does not name its source cannot be compared with another."""

    for sample in (read_peak_rss(PeakRssSource.RUSAGE), read_peak_rss()):
        assert isinstance(sample, PeakRssSample)


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------


def test_the_guard_conforms_to_the_accepted_protocol() -> None:
    guard = PeakRssGuard(900 * MIB)

    assert isinstance(guard, ResourceGuard)


def test_the_guard_reads_rusage_and_offers_no_source_selection() -> None:
    """No configuration makes it read the cgroup, so no subtree precondition applies."""

    import inspect

    parameters = set(inspect.signature(PeakRssGuard.__init__).parameters) - {"self"}
    assert parameters == {"limit_bytes"}

    guard = PeakRssGuard(900 * MIB)
    guard.check(0, 0)
    assert guard.last_sample is not None
    assert guard.last_sample.source is PeakRssSource.RUSAGE


def test_a_shared_cgroup_above_the_limit_does_not_reject_a_process_under_it(
    tmp_path: pathlib.Path,
) -> None:
    """The measured case: a 28 MiB task in a cgroup peaking past 1 GiB."""

    crowded = read_peak_rss(mount=cgroup_at(tmp_path, 1_072 * MIB))
    assert crowded.peak_bytes > 900 * MIB, "the premise failed"

    guard = PeakRssGuard(900 * MIB)
    guard.check(0, 0)

    assert guard.last_sample is not None
    assert guard.last_sample.peak_bytes < 900 * MIB
    assert guard.last_sample.source is PeakRssSource.RUSAGE


def test_the_guard_raises_at_and_above_its_limit_and_not_below() -> None:
    """The exact-limit boundary: a peak of exactly the limit is refused."""

    observed = read_peak_rss(PeakRssSource.RUSAGE).peak_bytes

    PeakRssGuard(observed + 1).check(0, 0)  # below: no raise

    with pytest.raises(PeakRssLimitExceeded):
        PeakRssGuard(observed).check(0, 0)  # exactly at the limit

    with pytest.raises(PeakRssLimitExceeded):
        PeakRssGuard(max(observed // 2, 1)).check(0, 0)  # above


def test_last_sample_is_none_before_the_first_check() -> None:
    assert PeakRssGuard(900 * MIB).last_sample is None


def test_a_rejection_exposes_the_sample_that_caused_it() -> None:
    """Not the previous checkpoint's, which would attribute the failure wrongly."""

    guard = PeakRssGuard(1)
    with pytest.raises(PeakRssLimitExceeded) as raised:
        guard.check(0, 0)

    assert guard.last_sample is not None
    assert guard.last_sample is raised.value.sample
    assert guard.last_sample.peak_bytes >= 1


def test_the_guard_retains_no_history() -> None:
    guard = PeakRssGuard(900 * MIB)
    for rows in (0, 100_000, 200_000):
        guard.check(rows, 0)

    held = [name for name in dir(guard) if not name.startswith("__")]
    assert "last_sample" in held
    assert not any(isinstance(getattr(guard, name, None), list | tuple | dict) for name in held)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5], ids=["zero", "negative", "bool", "float"])
def test_an_unusable_limit_is_refused_at_construction(limit: object) -> None:
    with pytest.raises(ValueError):
        PeakRssGuard(limit)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Through the accepted boundary
# --------------------------------------------------------------------------


def test_a_raising_guard_surfaces_as_resource_limit_exceeded() -> None:
    """The boundary maps any guard raise to that code and to nothing else."""

    stage = RecordingStage()
    outcome = process_release(reader=Reader(envelopes(3)), stage=stage, guard=PeakRssGuard(1))

    assert [entry.code.value for entry in outcome.diagnostics] == ["resource_limit_exceeded"]
    assert outcome.committed_record_count == 0
    assert "abort" in stage.calls


def test_a_passing_guard_leaves_an_accepted_release_accepted() -> None:
    outcome = process_release(
        reader=Reader(envelopes(3)), stage=RecordingStage(), guard=PeakRssGuard(900 * MIB)
    )

    assert outcome.disposition.value == "accepted"
    assert outcome.total_diagnostic_count == 0


def test_no_peak_figure_reaches_the_outcome() -> None:
    """A diagnostic has no field for a measurement, and none is smuggled in."""

    outcome = process_release(
        reader=Reader(envelopes(2)), stage=RecordingStage(), guard=PeakRssGuard(1)
    )

    rendered = repr(outcome)
    assert "peak" not in rendered.casefold()
    assert "rusage" not in rendered.casefold()


# --------------------------------------------------------------------------
# Architecture
# --------------------------------------------------------------------------


def _code_without_docstrings(path: pathlib.Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_tracemalloc_appears_nowhere_in_the_module() -> None:
    """663 MiB traced against 2,079 MiB resident is why."""

    source = _code_without_docstrings(pathlib.Path(peak_rss_module.__file__))

    assert "tracemalloc" not in source


def test_the_release_package_imports_nothing_from_resources() -> None:
    """The dependency runs one way: the boundary owns no measurement."""

    release_dir = pathlib.Path(peak_rss_module.__file__).parent.parent / "release"
    for module in sorted(release_dir.glob("*.py")):
        assert "resources" not in _code_without_docstrings(module), module.name


def test_no_module_under_release_was_modified() -> None:
    """This change adds a package beside the boundary and touches none of it."""

    import subprocess

    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(peak_rss_module.__file__).parents[5],
    ).stdout.split()

    touched = [p for p in changed if "/property_tax_adapters/release/" in p]
    assert touched == [], f"the accepted boundary was modified: {touched}"
