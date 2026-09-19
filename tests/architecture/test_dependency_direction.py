"""Import-level enforcement for the hexagonal dependency direction."""

import ast
import dataclasses
import subprocess
import sys
import typing
from collections.abc import Mapping, Sequence
from pathlib import Path

from property_tax_domain import RECORD_CLASSIFICATIONS, GeometryObservation

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_IMPORTS = {
    "property_tax_domain": {
        "airflow",
        "boto3",
        "httpx",
        "property_tax_adapters",
        "property_tax_application",
        "property_tax_ingestion",
        "psycopg",
        "pyproj",
        "shapely",
    },
    "property_tax_application": {
        "airflow",
        "boto3",
        "property_tax_adapters",
        "property_tax_ingestion",
        "psycopg",
    },
    "property_tax_adapters": {"airflow", "property_tax_ingestion"},
}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", maxsplit=1)[0])
    return imports


def test_package_dependency_direction() -> None:
    violations: list[str] = []
    for package, forbidden in FORBIDDEN_IMPORTS.items():
        package_root = next(ROOT.glob(f"libs/*/src/{package}"))
        for path in package_root.rglob("*.py"):
            disallowed = _top_level_imports(path) & forbidden
            if disallowed:
                violations.append(f"{path.relative_to(ROOT)} imports {sorted(disallowed)}")

    assert not violations, "Hexagonal dependency violations:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# The canonical identity vocabulary
# ---------------------------------------------------------------------------

ADAPTER_VOCABULARY = (
    "table_name",
    "source_family",
    "source_status",
    "observed_fields",
    "normalized_fields",
)

COUNTY_NAMES = ("dallas", "collin", "tarrant", "denton", "rockwall", "ellis")

DOMAIN_TEST_MODULES = (
    "tests/unit/property_tax_domain/test_identity.py",
    "tests/unit/property_tax_domain/test_binding.py",
    "tests/unit/property_tax_domain/test_serialization.py",
    "tests/unit/property_tax_domain/test_provenance.py",
    "tests/unit/property_tax_domain/test_public_surface.py",
    "tests/unit/property_tax_domain/test_account.py",
    "tests/unit/property_tax_domain/test_owner.py",
    "tests/unit/property_tax_domain/test_value.py",
    "tests/unit/property_tax_domain/test_exemption.py",
    "tests/unit/property_tax_domain/test_children.py",
    "tests/unit/property_tax_domain/test_appraisal_provenance.py",
)


def _domain_sources() -> list[Path]:
    return sorted((ROOT / "libs/property-tax-domain/src/property_tax_domain").rglob("*.py"))


def test_the_domain_imports_only_the_standard_library_and_itself() -> None:
    """Constructible without boto3, psycopg, Airflow, or any county adapter.

    The direction test above forbids specific packages by name. This asserts the
    stronger property the capability requires: nothing outside the standard
    library and the domain package itself is imported at all, so a dependency
    added later is caught without anyone remembering to name it.
    """

    allowed = set(sys.stdlib_module_names) | {"property_tax_domain"}
    violations: list[str] = []
    for path in _domain_sources():
        for module in _top_level_imports(path):
            if module not in allowed:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert not violations, "Domain reached outside the standard library:\n" + "\n".join(violations)


def test_adapter_vocabulary_does_not_leak_into_the_domain() -> None:
    """County-shaped lineage stays at the adapter boundary."""

    violations: list[str] = []
    for path in _domain_sources():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in ADAPTER_VOCABULARY:
                    violations.append(f"{path.relative_to(ROOT)} declares {node.target.id}")
            elif isinstance(node, ast.arg) and node.arg in ADAPTER_VOCABULARY:
                violations.append(f"{path.relative_to(ROOT)} accepts {node.arg}")

    assert not violations, "Adapter vocabulary in the domain:\n" + "\n".join(violations)


def _strip_docstrings(tree: ast.AST) -> None:
    """A docstring may legitimately name a county; code may not.

    The same distinction the adapter contract suite draws: an example reading
    `tx-collin` explains the shape, while a county literal in code is the
    vocabulary leaking.
    """

    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]


def test_the_domain_names_no_county_in_code() -> None:
    """The registry names counties; the identity vocabulary must not."""

    registry = ROOT / "libs/property-tax-domain/src/property_tax_domain/counties.py"
    violations: list[str] = []
    for path in _domain_sources():
        if path == registry:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _strip_docstrings(tree)
        lowered = ast.unparse(tree).lower()
        for county in COUNTY_NAMES:
            if county in lowered:
                violations.append(f"{path.relative_to(ROOT)} mentions {county} in code")

    assert not violations, "County names outside the registry:\n" + "\n".join(violations)


def test_appraisal_records_have_no_general_purpose_carrier() -> None:
    """Every record field is a named fact with a declared bounded shape."""

    forbidden_names = {
        "annotation",
        "annotations",
        "detail",
        "details",
        "extra",
        "extras",
        "metadata",
    }
    violations: list[str] = []
    for value_type in RECORD_CLASSIFICATIONS:
        hints = typing.get_type_hints(value_type)
        for field in dataclasses.fields(value_type):
            if field.name in forbidden_names:
                violations.append(f"{value_type.__name__}.{field.name} is a generic carrier")
            if _carries_general_purpose_type(hints[field.name]):
                violations.append(f"{value_type.__name__}.{field.name} carries {hints[field.name]}")
            if field.name == "payload" and value_type is not GeometryObservation:
                violations.append(f"{value_type.__name__}.payload is not geometry")

    assert not violations, "General-purpose appraisal fields:\n" + "\n".join(violations)


def _carries_general_purpose_type(annotation: object) -> bool:
    if annotation is typing.Any or annotation is object:
        return True
    origin = typing.get_origin(annotation)
    if origin in {dict, list, set, tuple, Mapping, Sequence}:
        return True
    return any(_carries_general_purpose_type(argument) for argument in typing.get_args(annotation))


def test_the_new_domain_suites_are_collected_by_the_default_configuration() -> None:
    """A test that cannot be collected is not a test.

    These suites once sat under `libs/property-tax-domain/tests`, which
    `testpaths` does not include: a test raising unconditionally there left the
    gate reporting every other test passing. Collection is therefore asserted by
    running the default collection and looking for each module, rather than by
    reasoning about the configuration.
    """

    for relative in DOMAIN_TEST_MODULES:
        assert (ROOT / relative).is_file(), f"{relative} is missing"

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]

    missing = [relative for relative in DOMAIN_TEST_MODULES if relative not in completed.stdout]
    assert not missing, "Default pytest collection does not reach:\n" + "\n".join(missing)


def test_the_application_mirrors_the_adapters_boundary_contract_version() -> None:
    """The copy cannot drift, because a drifted copy is worse than no copy.

    The application may not import the adapters, so it holds its own constant.
    This suite may import both, and that is the whole reason it exists: a value
    the boundary accepts would otherwise fail the persisted check that pins it.
    """

    from property_tax_adapters.release import outcome as adapters
    from property_tax_application import (
        BOUNDARY_CONTRACT_VERSION,
        DIAGNOSTIC_CODES,
        DIAGNOSTIC_RETENTION_LIMIT,
    )

    assert BOUNDARY_CONTRACT_VERSION == adapters.BOUNDARY_CONTRACT_VERSION
    assert DIAGNOSTIC_RETENTION_LIMIT == adapters.DIAGNOSTIC_RETENTION_LIMIT
    assert DIAGNOSTIC_CODES == {member.value for member in adapters.ReleaseDiagnosticCode}


def test_the_processing_run_values_are_reachable_from_the_package_root() -> None:
    import property_tax_application as application

    for name in (
        "ProcessingRunRef",
        "ReleaseDisposition",
        "ReleaseDiagnosticRecord",
        "ReleaseNoticeRecord",
        "ReleaseProcessingOutcome",
        "BOUNDARY_CONTRACT_VERSION",
    ):
        assert name in application.__all__, name
        assert hasattr(application, name), name


def test_the_run_module_names_no_infrastructure() -> None:
    """Docstrings stripped first: this module explains what it refuses to name."""

    module = ROOT / "libs/property-tax-application/src/property_tax_application/runs.py"
    forbidden = ("psycopg", "boto3", "cursor", "connection", "run_key", "GENERATED ALWAYS")
    found = [
        f"{name!r} in {text!r}"
        for text in _strings_and_identifiers(module)
        for name in forbidden
        if name in text
    ]
    assert not found, found


def _strings_and_identifiers(path: Path) -> list[str]:
    """Every name and literal in a module, with docstrings removed."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append(node.value)
        elif isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            found.append(node.name)
    return found


def test_the_canonical_port_is_reachable_from_the_package_root() -> None:
    import property_tax_application as application

    for name in (
        "CanonicalReleaseRepository",
        "ReleaseLoadSession",
        "CanonicalRecordBatch",
        "CorrelatedRecord",
        "CorrelationHandle",
        "AdoptedParent",
        "AdoptableSnapshot",
        "AccountSnapshotRef",
        "ReleaseLoadCompletion",
        "UnknownAccountSnapshot",
        "AdoptableSnapshotMismatch",
    ):
        assert name in application.__all__, name
        assert hasattr(application, name), name
    assert application.__all__ == sorted(application.__all__)


def test_the_canonical_port_carries_the_owned_run_and_outcome_types() -> None:
    """No substitute. The empty protocols that accepted every object are gone.

    An empty runtime-checkable protocol returns True for isinstance(None, ...),
    isinstance(7, ...) and isinstance("raw-run-id", ...), so it accepted exactly
    the raw persistence value the reference type exists to keep out.
    """

    import property_tax_application.canonical as canonical
    from property_tax_application.runs import ProcessingRunRef, ReleaseProcessingOutcome

    assert canonical.ProcessingRunRef is ProcessingRunRef
    assert canonical.ReleaseProcessingOutcome is ReleaseProcessingOutcome
    for raw in (None, 7, "raw-run-id"):
        assert not isinstance(raw, ProcessingRunRef)


def test_the_canonical_module_names_no_infrastructure() -> None:
    module = ROOT / "libs/property-tax-application/src/property_tax_application/canonical.py"
    forbidden = (
        "canonical.",
        "silver.",
        "ingestion.",
        "psycopg",
        "boto3",
        "cursor",
        "ON CONFLICT",
        "snapshot_key",
        "load_key",
    )
    found = [
        f"{name!r} in {text!r}"
        for text in _strings_and_identifiers(module)
        for name in forbidden
        if name in text
    ]
    assert not found, found
