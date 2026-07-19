"""Machine-readable CountyForge runner CLI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from countyforge_runner.errors import KernelError
from countyforge_runner.executor import Runner
from countyforge_runner.resolver import Kernel


def _request_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], name: str
) -> None:
    parser = subparsers.add_parser(name)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit JSON (the default contract).")


def build_parser() -> argparse.ArgumentParser:
    """Build the stable command surface."""

    parser = argparse.ArgumentParser(prog="countyforge-runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "validate-request", "resolve-profile", "explain"):
        _request_parser(subparsers, name)
    list_parser = subparsers.add_parser("list-profiles")
    list_parser.add_argument("--repo-root", type=Path)
    list_parser.add_argument(
        "--json", action="store_true", help="Emit JSON (the default contract)."
    )
    return parser


def _emit(document: object) -> None:
    print(json.dumps(document, indent=2, sort_keys=True))


def main(arguments: Sequence[str] | None = None) -> int:
    """Run one CLI command and return a stable exit status."""

    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        kernel = Kernel(args.repo_root)
        if args.command == "list-profiles":
            _emit({"ok": True, "profiles": kernel.list_profiles()})
            return 0
        resolved = kernel.resolve_path(args.request)
        if args.command == "validate-request":
            _emit({"ok": True, "run_id": resolved.run_id, "valid": True})
            return 0
        if args.command in {"resolve-profile", "explain"}:
            _emit(resolved.as_document())
            return 0
        document, exit_code = Runner(kernel).run(resolved)
        _emit(document)
        return exit_code
    except KernelError as error:
        _emit(error.as_document())
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
