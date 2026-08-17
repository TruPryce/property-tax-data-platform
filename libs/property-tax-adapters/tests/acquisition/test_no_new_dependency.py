"""Acquisition adds no dependency, and reaches no further than its port.

The repository's dependency-direction test is a denylist of names already known
to be third party, so a package nobody has thought of yet would pass it. This is
the allowlist: every import in the acquisition modules is named here or the test
fails, which is what makes "no new dependency" checkable rather than asserted.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from property_tax_adapters import acquisition

PACKAGE = pathlib.Path(acquisition.__file__).parent
PORT = (
    pathlib.Path(acquisition.__file__).parents[4]
    / "property-tax-application"
    / "src"
    / "property_tax_application"
    / "acquisition.py"
)

PERMITTED_ADAPTER_IMPORTS = {
    "__future__",
    "collections",
    "contextlib",
    "dataclasses",
    "hashlib",
    "http",
    "re",
    "ssl",
    "typing",
    "urllib",
    "property_tax_adapters",
    "property_tax_application",
}

#: The port is stricter still: it performs no I/O, so it needs no transport.
PERMITTED_PORT_IMPORTS = {
    "__future__",
    "collections",
    "dataclasses",
    "enum",
    "re",
    "types",
    "typing",
}


def _code_without_docstrings(path: pathlib.Path) -> str:
    """Source with every docstring removed.

    A docstring may legitimately name the thing the code must not use — this
    module's transport explains at length why it is not `urllib.request` — so
    asserting against raw text would fail on the explanation rather than on the
    defect.
    """

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


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("module", sorted(PACKAGE.glob("*.py")), ids=lambda path: path.name)
def test_the_adapter_imports_only_the_standard_library_and_its_port(
    module: pathlib.Path,
) -> None:
    unexpected = _imports(module) - PERMITTED_ADAPTER_IMPORTS

    assert not unexpected, f"{module.name} imports {sorted(unexpected)}"


def test_the_port_performs_no_io_and_names_no_transport() -> None:
    """A port that imported a client would be an adapter wearing a port's name."""

    unexpected = _imports(PORT) - PERMITTED_PORT_IMPORTS

    assert PORT.exists(), "the acquisition port moved"
    assert not unexpected, f"the port imports {sorted(unexpected)}"


def test_no_object_store_or_persistence_reaches_this_task() -> None:
    """Task 3.2 owns S3; this one owns the boundary it will implement."""

    for module in sorted(PACKAGE.glob("*.py")) + [PORT]:
        text = _code_without_docstrings(module).casefold()
        for forbidden in ("boto3", "botocore", "psycopg", "airflow", "requests", "httpx"):
            assert forbidden not in text, f"{module.name} names {forbidden}"


def test_the_transport_does_not_follow_redirects_for_the_caller() -> None:
    """urllib follows redirects; that is precisely why it is not used here.

    A followed redirect is a request already delivered to a destination no rule
    examined, so the module that issues requests must not contain the machinery
    that would follow one.
    """

    transport = _code_without_docstrings(PACKAGE / "transport.py")

    assert "urllib.request" not in transport
    assert "HTTPRedirectHandler" not in transport
    assert "build_opener" not in transport
