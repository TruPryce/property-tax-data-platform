"""Import-level enforcement for the hexagonal dependency direction."""

import ast
from pathlib import Path

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
