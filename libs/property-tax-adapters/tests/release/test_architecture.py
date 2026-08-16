"""The dependency direction, both ways, and the Dallas helper it must not reach for.

Modules are parsed and their docstrings stripped before asserting, because a
docstring may legitimately name a county while the code may not.
"""

from __future__ import annotations

import ast
import pathlib
import sqlite3
import tempfile
from collections.abc import Sequence

import pytest
from property_tax_adapters import release
from property_tax_adapters.release import PreparedRelease, SourceRowEnvelope
from property_tax_adapters.sources.contracts import AppraisalSourceRecord

from release.conformance import (
    APPROVED_MAX_LEAD,
    GuardedPullSource,
    assert_failed_commit_exposes_nothing,
    assert_reader_is_bounded,
    assert_stage_context_is_well_behaved,
    assert_stage_exit_is_safe,
    assert_stage_is_atomic,
    assert_stage_reports_duplicates,
    assert_unrelated_failure_is_not_a_duplicate,
    max_lead_for,
)
from release.sqlite_stage import SqliteReleaseStage
from release.support import (
    Reader,
    account_key,
    collin_shaped,
    envelopes,
    native_identifier_key,
    prepared,
    record,
)

COUNTIES = ("collin", "dallas", "denton", "ellis", "rockwall", "tarrant")
PACKAGE = pathlib.Path(release.__file__).parent
LIBRARY = PACKAGE.parent

PERMITTED_STDLIB = {
    "__future__",
    "re",
    "collections",
    "contextlib",
    "dataclasses",
    "enum",
    "types",
    "typing",
}


def _stripped(path: pathlib.Path) -> ast.Module:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _modules() -> list[pathlib.Path]:
    return sorted(PACKAGE.glob("*.py"))


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_the_boundary_imports_no_county_and_no_third_party(module: pathlib.Path) -> None:
    for node in ast.walk(_stripped(module)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            root = name.split(".")[0]
            if root == "property_tax_adapters":
                assert ".sources.texas" not in name, f"{module.name} imports a county"
                continue
            assert root in PERMITTED_STDLIB, f"{module.name} imports {name}"


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_no_county_name_appears_in_boundary_code(module: pathlib.Path) -> None:
    text = ast.unparse(_stripped(module)).casefold()
    for county in COUNTIES:
        assert county not in text, f"{module.name} names {county}"


def test_a_county_may_import_the_contracts_but_not_the_processor() -> None:
    """A reader must build these values to conform at all; driving is the caller's job."""

    for module in sorted((LIBRARY / "sources" / "texas").glob("*.py")):
        for node in ast.walk(_stripped(module)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "release.processor" not in node.module, (
                    f"{module.name} imports the processor"
                )


def test_the_domain_and_application_packages_are_untouched() -> None:
    for module in _modules():
        text = ast.unparse(_stripped(module))
        assert "property_tax_domain" not in text
        assert "property_tax_application" not in text


def test_the_boundary_does_not_reach_for_the_dallas_helper() -> None:
    for module in _modules():
        text = ast.unparse(_stripped(module))
        assert "parse_dallas_appraisal_csv" not in text, module.name


def test_the_dallas_contract_cases_are_undisturbed() -> None:
    """All 52 remain collected; this work touched none of them."""

    import subprocess
    import sys

    suite = LIBRARY.parent.parent / "tests" / "test_dallas_parser.py"
    assert suite.exists()

    # Collected *items*, not function definitions: a parametrized function is
    # many cases, and the contract counts cases.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(suite), "--collect-only", "-q"],
        capture_output=True,
        text=True,
        cwd=LIBRARY.parent.parent.parent.parent,
    )
    collected = [line for line in result.stdout.splitlines() if "::" in line]
    assert len(collected) >= 52, f"only {len(collected)} Dallas cases collect"

    # And this work imported nothing into them.
    assert "release" not in suite.read_text(encoding="utf-8").split("import")[1][:200]


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_no_network_archive_persistence_or_spool(module: pathlib.Path) -> None:
    text = ast.unparse(_stripped(module)).casefold()
    for forbidden in ("http", "socket", "urllib", "requests", "zipfile", "sqlite", "tempfile"):
        assert forbidden not in text, f"{module.name} contains {forbidden}"


# --------------------------------------------------------------------------
# Conformance: the suite, driven against its passing implementations
# --------------------------------------------------------------------------


class _Conforming:
    """One row of lookahead: bounded, and its lead does not grow."""

    def __init__(self, source: GuardedPullSource) -> None:
        self._source = source

    def __enter__(self) -> _Conforming:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def prepare(self) -> PreparedRelease:
        return prepared()

    def __iter__(self):  # noqa: ANN204
        for number in self._source:
            yield SourceRowEnvelope(physical_row_number=number, records=(record(number),))


class _Eager:
    """Materializes its member first, which is the defect the suite detects."""

    def __init__(self, source: GuardedPullSource) -> None:
        self._source = source

    def __enter__(self) -> _Eager:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def prepare(self) -> PreparedRelease:
        return prepared()

    def __iter__(self):  # noqa: ANN204
        rows = list(self._source)
        for number in rows:
            yield SourceRowEnvelope(physical_row_number=number, records=(record(number),))


def test_a_bounded_reader_conforms() -> None:
    assert_reader_is_bounded(_Conforming)


def test_an_eager_reader_fails_conformance() -> None:
    with pytest.raises(AssertionError):
        assert_reader_is_bounded(_Eager)


def test_the_eager_lead_grows_with_release_size() -> None:
    """The property the ratio check exists to catch, stated directly."""

    short = max_lead_for(_Eager, 1_000)
    long = max_lead_for(_Eager, 8_000)

    assert short > APPROVED_MAX_LEAD and long > short


def test_the_metric_survives_a_rejected_release() -> None:
    """Writing stops at the first rejection; the lead is measured against rows."""

    reader = Reader(envelopes(5, rejected=[1]))
    with reader as opened:
        opened.prepare()
        consumed = sum(1 for _ in opened)

    assert consumed == 5


class _Suppressing:
    """A stage that swallows what happened inside it, and hides its own identity.

    The stage-half counterpart of `_Eager`: the conformance suite is only worth
    running if a stage that breaks the contract fails it.
    """

    def __init__(self) -> None:
        self.records: list[AppraisalSourceRecord] = []

    def __enter__(self) -> object:
        return object()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return True

    def write(self, records: Sequence[AppraisalSourceRecord]) -> None:
        self.records.extend(records)

    def finalize(self) -> None:
        return None

    def abort(self) -> None:
        self.records.clear()

    def commit(self) -> None:
        return None


def test_a_stage_that_suppresses_or_hides_itself_fails_conformance() -> None:
    with pytest.raises(AssertionError, match="other than the stage"):
        assert_stage_context_is_well_behaved(_Suppressing, (record(1),))  # type: ignore[arg-type]


def test_a_stage_exposing_a_failed_commit_fails_conformance() -> None:
    """The suite's own teeth: a stage whose commit failure leaks must not pass."""

    class _Leaky(_Suppressing):
        def __enter__(self) -> _Leaky:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def commit(self) -> None:
            raise RuntimeError("commit failed after exposing the records")

    with pytest.raises(AssertionError, match="a failed commit exposed records"):
        assert_failed_commit_exposes_nothing(  # type: ignore[arg-type]
            _Leaky,
            lambda stage: stage.records,
            (record(1),),
            lambda stage: None,
        )


def test_the_sqlite_stage_passes_the_conformance_suite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)

        def factory() -> SqliteReleaseStage:
            return SqliteReleaseStage(root, key=account_key)

        def visible(stage: SqliteReleaseStage) -> list[tuple[str, int]]:
            return stage.visible_records()

        rows = (record(1), record(2, account="OTHER"))
        assert_stage_is_atomic(factory, visible, rows)  # type: ignore[arg-type]
        assert_stage_reports_duplicates(factory, (record(1), record(2, account="ACCOUNT-000001")))  # type: ignore[arg-type]
        assert_stage_exit_is_safe(factory, rows)  # type: ignore[arg-type]
        assert_failed_commit_exposes_nothing(  # type: ignore[arg-type]
            factory, visible, rows, lambda stage: stage.break_commit()
        )
        assert_stage_context_is_well_behaved(factory, rows)  # type: ignore[arg-type]


def test_the_stage_does_not_decide_what_a_records_key_is() -> None:
    """A Collin-shaped record has no account id, and is not a duplicate.

    A stage that read `source_account_id` itself would refuse two valid shared
    records for a NOT NULL violation and report the refusal as a repeated key,
    which is the accepted Collin contract's prohibition on treating an
    identifier as canonical, arriving as a wrong answer.
    """

    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        first = collin_shaped(1, prop_id="P1")
        second = collin_shaped(2, prop_id="P2")

        with SqliteReleaseStage(root, key=native_identifier_key) as opened:
            opened.write([first, second])
            opened.finalize()
            opened.commit()
            assert len(opened.visible_records()) == 2, "a valid Collin release was refused"

        # The same two records still collide when the caller says they should.
        assert_stage_reports_duplicates(  # type: ignore[arg-type]
            lambda: SqliteReleaseStage(root, key=lambda _: "one-key-for-everything"),
            (first, second),
        )


def test_an_unwritable_record_is_not_reported_as_a_duplicate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        assert_unrelated_failure_is_not_a_duplicate(  # type: ignore[arg-type]
            lambda: SqliteReleaseStage(root, key=lambda _: ""),
            (record(1),),
        )


def test_the_stage_leaves_nothing_behind_on_success_or_on_a_failed_open() -> None:
    """The cleanup half of the fixture contract, which a passing run also owes."""

    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        with SqliteReleaseStage(root, key=account_key) as opened:
            opened.write([record(1)])
            opened.finalize()
            opened.commit()
        assert list(root.iterdir()) == [], "a committed release left its file behind"

        # One page cannot hold the table, so this fails inside __enter__ —
        # after the file was created, which is the case that leaks.
        partial = SqliteReleaseStage(root, key=account_key, max_pages=1)
        with pytest.raises(sqlite3.DatabaseError):
            partial.__enter__()
        assert list(root.iterdir()) == [], "a failed open left its file behind"


def test_the_sqlite_stage_adds_no_dependency() -> None:
    module = pathlib.Path(__file__).parent / "sqlite_stage.py"
    for node in ast.walk(_stripped(module)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            root = name.split(".")[0]
            assert root in {
                "__future__",
                "sqlite3",
                "collections",
                "pathlib",
                "types",
                "property_tax_adapters",
            }, name


def test_a_failed_write_leaves_none_of_its_row_staged() -> None:
    """All or nothing per call, separate from release-level atomicity."""

    with tempfile.TemporaryDirectory() as directory:
        stage = SqliteReleaseStage(pathlib.Path(directory), key=account_key)
        with stage as opened:
            first = record(1, account="SAME")
            second = record(2, account="SAME")
            try:
                opened.write([first, second])
            except Exception:  # noqa: BLE001 - the duplicate inside one row
                pass
            opened.commit()
            # Read inside the context: the stage cleans its file up on exit, so
            # a check afterwards would pass on an absent database rather than an
            # empty one.
            assert opened.visible_records() == [], "a partial row survived the failed write"
