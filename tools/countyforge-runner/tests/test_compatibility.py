"""Image, CLI, posture, request-builder, and legacy command compatibility."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from countyforge_runner.contracts import JsonObject
from countyforge_runner.resolver import Kernel


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def test_codex_pin_and_catalog_version_gates_agree() -> None:
    build = Path(".ai/codex/01-build-codex-image.sh").read_text(encoding="utf-8")
    profile = json.loads(
        Path(".ai/profiles/review.packet-only.v1.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(Path(".ai/providers/catalog.v1.json").read_text(encoding="utf-8"))
    pin = profile["container"]["codex_cli_version"]
    assert f"ARG CODEX_VERSION={pin}" in build
    assert profile["container"]["provider_images"] == {
        "openai": "property-tax-codex-reviewer-openai:local",
        "sakana": "property-tax-codex-reviewer:local",
    }
    assert version_tuple(pin) >= (0, 144, 0)
    assert all(
        version_tuple(pin) >= version_tuple(model["minimum_codex_cli_version"])
        for model in catalog["models"]
    )


def test_review_executable_posture_matches_profile() -> None:
    build = Path(".ai/codex/01-build-codex-image.sh").read_text(encoding="utf-8")
    runner = Path(".ai/codex/02-run-prepr-review-docker.sh").read_text(encoding="utf-8")
    for tool in (
        "shell_tool",
        "unified_exec",
        "browser_use",
        "computer_use",
        "apps",
        "image_generation",
    ):
        assert f"  {tool}" in runner or f"{tool} = false" in build
    for flag in ("--read-only", "--cap-drop ALL", "no-new-privileges:true"):
        assert flag in runner
    assert "CODEX_PROVIDER:-sakana" in runner
    assert 'PROVIDER_CREDENTIAL="OPENAI_API_KEY"' in runner
    assert 'PROVIDER_CREDENTIAL="SAKANA_API_KEY"' in runner


def test_image_compatibility_gate_precedes_provider_credential_resolution() -> None:
    runner = Path(".ai/codex/02-run-prepr-review-docker.sh").read_text(encoding="utf-8")
    gate = runner.index("# --- Image/model compatibility before credential resolution")
    credential_resolution = runner.index("# --- Resolve the selected provider key")
    assert gate < credential_resolution
    for label in (
        "codex-cli-version",
        "provider",
        "profile-id",
        "profile-sha256",
    ):
        assert runner.index(label, gate) < credential_resolution
    assert 'if [ -n "${COUNTYFORGE_PROFILE_SHA256:-}" ]' in runner
    assert '[ "$IMAGE_PROFILE_SHA" != "$EXPECTED_PROFILE_SHA" ]' in runner
    assert '[ -n "${COUNTYFORGE_PROFILE_SHA256:-}" ] &&' not in runner
    smoke = Path(".ai/codex/03-smoke-test.sh").read_text(encoding="utf-8")
    assert 'COUNTYFORGE_PROFILE_SHA256="$PROFILE_SHA256"' in smoke


def test_legacy_prepr_routes_through_kernel() -> None:
    script = Path("scripts/dev-loop/prepr.sh").read_text(encoding="utf-8")
    assert "build-review-packet.sh" in script
    assert "build-countyforge-review-request.py" in script
    assert "countyforge-runner run" in script
    assert ".ai/codex/02-run-prepr-review-docker.sh" not in script


def test_request_builder_produces_resolvable_review(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    packet = Path(str(request_factory("review")["input"]["packet_path"]))
    result = subprocess.run(
        [
            "python3",
            "scripts/dev-loop/build-countyforge-review-request.py",
            "--repo-root",
            str(Path.cwd()),
            "--packet",
            str(packet),
            "--run-id",
            "builder-fixture",
            "--base-sha",
            "a" * 40,
            "--head-sha",
            "b" * 40,
            "--branch",
            "feature/kernel",
            "--actor",
            "fixture",
            "--provider",
            "sakana",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(result.stdout, encoding="utf-8")
    assert Kernel().resolve_path(request_path).profile["profile_id"] == "review.packet-only.v1"
