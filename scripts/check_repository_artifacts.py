"""Reject county source artifacts and unexpected large files from the repository."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_FILE = ROOT / ".artifact-allowlist"
MAX_FILE_BYTES = 5 * 1024 * 1024

PROHIBITED_DIRECTORY_NAMES = frozenset({"bronze", "data", "extracted", "quarantine", "raw"})
PROHIBITED_SUFFIXES = frozenset(
    {
        ".7z",
        ".accdb",
        ".csv",
        ".cpg",
        ".dat",
        ".dbf",
        ".gdb",
        ".gz",
        ".mdb",
        ".ods",
        ".parquet",
        ".prj",
        ".psv",
        ".rar",
        ".sbn",
        ".sbx",
        ".shp",
        ".shx",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".tsv",
        ".xls",
        ".xlsx",
        ".zip",
    }
)
PROHIBITED_MAGIC = (
    (b"PK\x03\x04", "ZIP container"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"\x1f\x8b", "gzip archive"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE database or spreadsheet"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"PAR1", "Parquet file"),
    (b"\x00\x00\x27\x0a", "ESRI shapefile"),
)


def load_allowlist(path: Path = ALLOWLIST_FILE) -> set[str]:
    """Return reviewed exact repository-relative exceptions."""

    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def repository_paths(arguments: list[str]) -> list[Path]:
    """Resolve hook arguments or all tracked and non-ignored repository files."""

    if arguments:
        return [Path(argument) for argument in arguments]
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [Path(item.decode()) for item in result.stdout.split(b"\x00") if item]


def violations_for_path(path: Path, allowlist: set[str], root: Path = ROOT) -> list[str]:
    """Return policy violations for one repository-relative path."""

    absolute = path if path.is_absolute() else root / path
    if not absolute.exists() or absolute.is_dir() or absolute.is_symlink():
        return []

    try:
        relative = absolute.resolve().relative_to(root.resolve())
    except ValueError:
        return [f"{path}: path resolves outside the repository"]

    relative_text = relative.as_posix()
    if relative_text in allowlist:
        return []

    violations: list[str] = []
    directory_names = {part.casefold() for part in relative.parts[:-1]}
    blocked_directories = sorted(directory_names & PROHIBITED_DIRECTORY_NAMES)
    if blocked_directories:
        violations.append(f"path uses prohibited source-data directory: {blocked_directories[0]}")
    if any(part.casefold().endswith(".gdb") for part in relative.parts[:-1]):
        violations.append("path is inside a prohibited geodatabase directory")

    suffix = relative.suffix.casefold()
    if suffix in PROHIBITED_SUFFIXES:
        violations.append(f"prohibited source-artifact extension: {suffix}")

    size = absolute.stat().st_size
    if size > MAX_FILE_BYTES:
        violations.append(f"file is {size} bytes; limit is {MAX_FILE_BYTES}")

    with absolute.open("rb") as handle:
        prefix = handle.read(16)
    for magic, description in PROHIBITED_MAGIC:
        if prefix.startswith(magic):
            violations.append(f"prohibited content signature: {description}")
            break

    return [f"{relative_text}: {violation}" for violation in violations]


def main(arguments: list[str] | None = None) -> int:
    """Return nonzero when any candidate file violates repository policy."""

    paths = repository_paths(list(arguments if arguments is not None else sys.argv[1:]))
    allowlist = load_allowlist()
    failures = [violation for path in paths for violation in violations_for_path(path, allowlist)]
    if failures:
        print("Prohibited repository artifacts:")
        print("\n".join(sorted(failures)))
        print("Use runtime Bronze storage. Safe fixture exceptions require allowlist review.")
        return 1
    print(f"Validated {len(paths)} repository files against the artifact policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
