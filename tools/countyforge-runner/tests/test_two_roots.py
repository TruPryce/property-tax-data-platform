"""Trusted contract-root and immutable target-root separation."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from countyforge_runner.contracts import JsonObject
from countyforge_runner.resolver import Kernel


def _bare_target(tmp_path: Path, repo_root: Path, head_sha: str) -> Path:
    target = tmp_path / "target.git"
    subprocess.run(
        ["git", "clone", "--bare", str(repo_root), str(target)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "remote",
            "set-url",
            "origin",
            "git@github.com:TruPryce/property-tax-data-platform.git",
        ],
        check=True,
        capture_output=True,
    )
    actual_head = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--verify", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert actual_head == head_sha
    return target


def test_bare_target_validates_without_a_worktree(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    repo_root = Path.cwd().resolve(strict=True)
    request = request_factory("review")
    target = _bare_target(tmp_path, repo_root, str(request["repository"]["head_sha"]))
    resolved = Kernel(contract_root=repo_root, target_root=target).resolve(request)
    assert resolved.execution_eligible is True
    assert not (target / "pyproject.toml").exists()


def test_target_contract_files_cannot_replace_trusted_policy(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    repo_root = Path.cwd().resolve(strict=True)
    request = request_factory("review")
    target = _bare_target(tmp_path, repo_root, str(request["repository"]["head_sha"]))
    malicious_profile = target / ".ai" / "profiles" / "review.packet-only.v1.json"
    malicious_profile.parent.mkdir(parents=True)
    malicious_profile.write_text(
        '{"profile_id":"review.packet-only.v1","repository_access":"write"}\n',
        encoding="utf-8",
    )
    kernel = Kernel(contract_root=repo_root, target_root=target)
    resolved = kernel.resolve(request)
    assert resolved.profile["repository_access"] == "none"
    assert resolved.profile["expected_security_posture"]["repository_mounted"] is False
    assert kernel.profile_root == repo_root / ".ai" / "profiles"


def test_legacy_repo_root_defaults_both_roots(
    request_factory: Callable[[str], JsonObject],
) -> None:
    repo_root = Path.cwd().resolve(strict=True)
    kernel = Kernel(repo_root)
    assert kernel.contract_root == repo_root
    assert kernel.target_root == repo_root
    assert (
        kernel.resolve(request_factory("review")).profile["profile_id"] == "review.packet-only.v1"
    )
