"""Validate local Markdown links in maintained documentation."""

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
DOC_PATTERNS = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "docs/**/*.md",
    "dags/*.md",
    "libs/**/*.md",
    "services/**/*.md",
    "openspec/AGENTS.md",
)


def _documentation_files() -> set[Path]:
    return {path for pattern in DOC_PATTERNS for path in ROOT.glob(pattern)}


def main() -> int:
    """Return nonzero when a maintained document contains a broken local link."""

    failures: list[str] = []
    for document in sorted(_documentation_files()):
        for raw_target in LINK_PATTERN.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip().strip("<>")
            if target.startswith(("#", "https://", "http://", "mailto:")):
                continue
            relative_target = unquote(target.split("#", maxsplit=1)[0])
            if not relative_target:
                continue
            resolved = (document.parent / relative_target).resolve()
            if not resolved.exists():
                failures.append(
                    f"{document.relative_to(ROOT)} -> {raw_target} ({resolved} does not exist)"
                )

    if failures:
        print("Broken documentation links:")
        print("\n".join(failures))
        return 1
    print(f"Validated local links in {len(_documentation_files())} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
