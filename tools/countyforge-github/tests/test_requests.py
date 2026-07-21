"""Runner request construction, future-mode failure, and secret non-disclosure."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from countyforge_github.contracts import JsonObject
from countyforge_github.requests import build_run_request
from countyforge_github.results import resolve_terminal_result
from countyforge_runner.executor import Runner
from countyforge_runner.resolver import Kernel


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bare_target(tmp_path: Path, repo_root: Path, head_sha: str) -> Path:
    target = tmp_path / "synthetic-target.git"
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


@pytest.fixture
def review_inputs(
    tmp_path: Path,
    repo_root: Path,
    trigger_factory: Callable[[str], JsonObject],
) -> Iterator[tuple[Path, Path]]:
    fixture_root = repo_root / ".ai" / "reviews" / "github-test-fixtures" / tmp_path.name
    fixture_root.mkdir(parents=True)
    trigger = trigger_factory("review")
    packet = fixture_root / "packet.md"
    metadata = {
        "base_sha": trigger["target"]["base_sha"],
        "builder_id": "repository-review-packet",
        "builder_version": 1,
        "contract_version": 1,
        "head_sha": trigger["target"]["head_sha"],
        "repository_full_name": trigger["repository"]["full_name"],
    }
    packet.write_text(
        "<!-- countyforge-review-packet-metadata-v1 "
        + json.dumps(metadata, separators=(",", ":"), sort_keys=True)
        + " -->\n# synthetic safe packet\n",
        encoding="utf-8",
    )
    provenance = fixture_root / "packet.provenance.json"
    provenance.write_text(
        json.dumps(
            {
                **metadata,
                "packet_sha256": _sha256(packet),
                "packet_bytes": packet.stat().st_size,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    yield packet, provenance
    shutil.rmtree(fixture_root)


def test_review_request_resolves_through_packet_only_profile(
    repo_root: Path,
    trigger_factory: Callable[[str], JsonObject],
    review_inputs: tuple[Path, Path],
) -> None:
    packet, provenance = review_inputs
    request = build_run_request(
        trigger_factory("review"),
        contract_root=repo_root,
        target_root=repo_root,
        packet_path=packet,
        packet_provenance_path=provenance,
    )
    resolved = Kernel(contract_root=repo_root, target_root=repo_root).resolve(request)
    assert resolved.profile["profile_id"] == "review.packet-only.v1"
    assert resolved.profile["repository_access"] == "none"
    assert resolved.execution_eligible is True


def test_synthetic_workflow_dispatches_two_root_packet_only_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    trigger_factory: Callable[[str], JsonObject],
    review_inputs: tuple[Path, Path],
) -> None:
    trigger = trigger_factory("review")
    target = _bare_target(tmp_path, repo_root, str(trigger["target"]["head_sha"]))
    packet, provenance = review_inputs
    request = build_run_request(
        trigger,
        contract_root=repo_root,
        target_root=target,
        packet_path=packet,
        packet_provenance_path=provenance,
    )
    adapter = tmp_path / "packet-only-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test -n "${SAKANA_API_KEY:-}"\n'
        'test -z "${OPENAI_API_KEY:-}"\n'
        'mkdir -p "$OUT_DIR"\n'
        'cp "$PACKET_PATH" "$OUT_DIR/review-packet.md"\n'
        'printf \'%s\\n\' \'{"verdict":"pass"}\' > "$OUT_DIR/codex-prepr-review.md"\n'
        "printf '%s\\n' "
        '\'{"image_id":"sha256:synthetic","codex_cli_version":"0.144.6"}\' '
        '> "$OUT_DIR/container.provenance.json"\n'
        'printf \'%s\\n\' \'{"status":"succeeded","exit_code":0}\' > "$OUT_DIR/run.summary.json"\n',
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    monkeypatch.setenv("SAKANA_API_KEY", "synthetic-selected-provider-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unselected-provider-secret")
    kernel = Kernel(contract_root=repo_root, target_root=target)
    result, exit_code = Runner(
        kernel,
        evidence_root=tmp_path / "evidence",
        review_adapter=adapter,
    ).run(kernel.resolve(request))
    assert exit_code == 0
    assert result["disposition"] == "completed"
    assert result["review"] == {"verdict": "pass"}
    result_path = tmp_path / "countyforge-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    exit_path = tmp_path / "countyforge-exit-code"
    exit_path.write_text(f"{exit_code}\n", encoding="utf-8")
    assert resolve_terminal_result(
        command="review", result_path=result_path, exit_code_path=exit_path
    ) == {"ok": True, "state": "succeeded", "disposition": "completed"}
    evidence = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "evidence").rglob("*")
        if path.is_file()
    )
    assert "synthetic-selected-provider-secret" not in evidence
    assert "synthetic-unselected-provider-secret" not in evidence


@pytest.mark.parametrize("mode", ["implement", "fix", "validate"])
def test_future_command_reaches_kernel_and_fails_not_implemented(
    tmp_path: Path,
    repo_root: Path,
    trigger_factory: Callable[[str], JsonObject],
    mode: str,
) -> None:
    request = build_run_request(
        trigger_factory(mode), contract_root=repo_root, target_root=repo_root
    )
    kernel = Kernel(contract_root=repo_root, target_root=repo_root)
    result, exit_code = Runner(kernel, evidence_root=tmp_path / "evidence").run(
        kernel.resolve(request)
    )
    assert exit_code == 4
    assert result["disposition"] == "profile_not_implemented"
    assert result["ok"] is False


def test_unimplemented_request_never_exports_provider_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    trigger_factory: Callable[[str], JsonObject],
) -> None:
    sentinel = "provider-secret-must-not-enter-control-artifacts"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("SAKANA_API_KEY", sentinel)
    request = build_run_request(
        trigger_factory("implement"), contract_root=repo_root, target_root=repo_root
    )
    kernel = Kernel(contract_root=repo_root, target_root=repo_root)
    result, _ = Runner(kernel, evidence_root=tmp_path / "evidence").run(kernel.resolve(request))
    content = json.dumps(request) + json.dumps(result)
    for path in (tmp_path / "evidence").rglob("*"):
        if path.is_file():
            content += path.read_text(encoding="utf-8")
    assert sentinel not in content


def test_selected_provider_policy_matches_profile_capabilities(
    repo_root: Path, trigger_factory: Callable[[str], JsonObject]
) -> None:
    for mode in ("implement", "fix", "validate"):
        request = build_run_request(
            trigger_factory(mode), contract_root=repo_root, target_root=repo_root
        )
        resolved = Kernel(contract_root=repo_root, target_root=repo_root).resolve(request)
        if resolved.provider is not None:
            assert resolved.provider["id"] in resolved.profile["permitted_providers"]
