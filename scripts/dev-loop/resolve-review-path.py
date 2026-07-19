#!/usr/bin/env python3
"""Resolve a review-output path and enforce the default artifact boundary."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Print the resolved path or reject a nonstandard location."""

    if len(sys.argv) != 5:
        print(
            "usage: resolve-review-path.py REPO_ROOT REQUESTED ALLOW_NONSTANDARD LABEL",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(sys.argv[1]).resolve()
    requested = Path(sys.argv[2])
    allow_nonstandard = sys.argv[3]
    label = sys.argv[4]

    if allow_nonstandard not in {"0", "1"}:
        print(
            f"{label}: ALLOW_NONSTANDARD_REVIEW_DIR must be 0 or 1 (got {allow_nonstandard!r})",
            file=sys.stderr,
        )
        return 2

    candidate = requested if requested.is_absolute() else repo_root / requested
    path = candidate.resolve()
    reviews_entry = repo_root / ".ai" / "reviews"
    reviews_root = reviews_entry.resolve()

    if reviews_root != reviews_entry and allow_nonstandard != "1":
        print(
            f"{label}: standard review root must not be redirected by a symlink: "
            f"{reviews_entry} -> {reviews_root}",
            file=sys.stderr,
        )
        return 2

    try:
        path.relative_to(reviews_root)
        inside_reviews = True
    except ValueError:
        inside_reviews = False

    if not inside_reviews and allow_nonstandard != "1":
        print(
            f"{label} must resolve under {reviews_root}: {sys.argv[2]} -> {path}",
            file=sys.stderr,
        )
        print(
            "Set ALLOW_NONSTANDARD_REVIEW_DIR=1 only for an intentional "
            "nonstandard output location.",
            file=sys.stderr,
        )
        return 2

    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
