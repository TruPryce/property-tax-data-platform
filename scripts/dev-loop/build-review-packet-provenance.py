"""Emit deterministic provenance for one frozen repository review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

PACKET_METADATA_PREFIX = "<!-- countyforge-review-packet-metadata-v1 "
PACKET_METADATA_SUFFIX = " -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    return parser.parse_args()


def git_output(repo_root: Path, *arguments: str) -> str:
    environment = {
        name: os.environ[name]
        for name in ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT")
        if name in os.environ
    }
    result = subprocess.run(  # noqa: S603 - fixed git executable and operator base ref
        ["git", *arguments],
        cwd=repo_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def packet_metadata(path: Path) -> dict[str, object]:
    first_line = path.open(encoding="utf-8").readline().rstrip("\n")
    if not first_line.startswith(PACKET_METADATA_PREFIX) or not first_line.endswith(
        PACKET_METADATA_SUFFIX
    ):
        raise SystemExit("review packet is missing its machine-readable metadata")
    raw_document = first_line[len(PACKET_METADATA_PREFIX) : -len(PACKET_METADATA_SUFFIX)]
    try:
        document = json.loads(raw_document)
    except json.JSONDecodeError:
        raise SystemExit("review packet metadata is invalid JSON") from None
    expected_keys = {
        "contract_version",
        "builder_id",
        "builder_version",
        "repository_full_name",
        "base_sha",
        "head_sha",
    }
    if not isinstance(document, dict) or set(document) != expected_keys:
        raise SystemExit("review packet metadata has an invalid shape")
    for field in ("base_sha", "head_sha"):
        value = document[field]
        if (
            not isinstance(value, str)
            or len(value) != 40
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise SystemExit("review packet metadata has an invalid commit SHA")
    return document


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve(strict=True)
    packet = args.packet.resolve(strict=True)
    metadata = packet_metadata(packet)
    head_sha = git_output(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    base_sha = str(metadata["base_sha"])
    base_check = subprocess.run(  # noqa: S603 - fixed git executable and packet SHA
        ["git", "merge-base", "--is-ancestor", base_sha, head_sha],
        cwd=repo_root,
        env={
            name: os.environ[name]
            for name in ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT")
            if name in os.environ
        },
        check=False,
        capture_output=True,
        text=True,
    )
    expected_metadata = {
        "contract_version": 1,
        "builder_id": "repository-review-packet",
        "builder_version": 1,
        "repository_full_name": args.repository,
        "base_sha": base_sha,
        "head_sha": head_sha,
    }
    if metadata != expected_metadata or base_check.returncode != 0:
        raise SystemExit("review packet metadata does not match the repository checkout")
    document = {
        **expected_metadata,
        "packet_sha256": file_sha256(packet),
        "packet_bytes": packet.stat().st_size,
    }
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
