"""Repository path discovery for the developer-tool package."""

from __future__ import annotations

from pathlib import Path

from countyforge_runner.errors import KernelError


def find_repo_root(start: Path | None = None) -> Path:
    """Find the nearest repository containing the CountyForge policy directories."""

    candidate = (start or Path.cwd()).resolve()
    for path in (candidate, *candidate.parents):
        if (path / ".ai" / "profiles").is_dir() and (path / "pyproject.toml").is_file():
            return path
    raise KernelError(
        "repository_not_found",
        "Could not locate the CountyForge repository root.",
    )
