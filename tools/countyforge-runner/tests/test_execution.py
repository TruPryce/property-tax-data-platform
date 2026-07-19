"""Fail-closed execution, evidence, credentials, and legacy adapter dispatch."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from countyforge_runner.cli import main
from countyforge_runner.contracts import JsonObject
from countyforge_runner.errors import KernelError
from countyforge_runner.executor import Runner, _output_bytes, _safe_branch
from countyforge_runner.resolver import Kernel


@pytest.mark.parametrize("mode", ["plan", "implement", "fix", "validate"])
def test_unimplemented_profiles_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
    mode: str,
) -> None:
    sentinel = "provider-sentinel-value-that-must-never-leak"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("SAKANA_API_KEY", sentinel)
    kernel = Kernel()
    resolved = kernel.resolve(request_factory(mode))
    document, exit_code = Runner(kernel, evidence_root=tmp_path / "evidence").run(resolved)
    assert exit_code == 4
    assert document["disposition"] == "profile_not_implemented"
    assert document["summary"]["outcome"] == "not_executed"
    run_dir = tmp_path / "evidence" / mode / f"fixture-{mode}"
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    assert sentinel not in all_text


def test_unimplemented_execution_has_no_global_credential_lookup() -> None:
    evidence_source = Path("tools/countyforge-runner/src/countyforge_runner/evidence.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("OPENAI_API_KEY"' not in evidence_source
    assert 'os.environ.get("SAKANA_API_KEY"' not in evidence_source


def _fake_adapter(path: Path, expected_provider: str) -> Path:
    credential_check = (
        'test -n "${SAKANA_API_KEY:-}" && test -z "${OPENAI_API_KEY:-}"'
        if expected_provider == "sakana"
        else 'test -n "${OPENAI_API_KEY:-}" && test -z "${SAKANA_API_KEY:-}"'
    )
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{credential_check}\n"
        'mkdir -p "$OUT_DIR"\n'
        'cp "$PACKET_PATH" "$OUT_DIR/review-packet.md"\n'
        'printf \'%s\\n\' \'{"verdict":"pass"}\' > "$OUT_DIR/codex-prepr-review.md"\n'
        "printf '%s\\n' "
        '\'{"image_id":"sha256:fixture","codex_cli_version":"0.144.6"}\' '
        '> "$OUT_DIR/container.provenance.json"\n'
        'printf \'%s\\n\' \'{"status":"succeeded","exit_code":0}\' > "$OUT_DIR/run.summary.json"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    ("provider", "model_ref"),
    [("sakana", "sakana.fugu-ultra"), ("openai", "openai.gpt-5.6")],
)
def test_review_dispatches_existing_adapter_with_one_provider_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
    provider: str,
    model_ref: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fixture-secret-value")
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-fixture-secret-value")
    request = request_factory("review")
    request["run_id"] = f"review-{provider}"
    request["provider"] = {
        "id": provider,
        "model_ref": model_ref,
        "codex_cli_version": "0.144.6",
    }
    kernel = Kernel()
    adapter = _fake_adapter(tmp_path / f"adapter-{provider}.sh", provider)
    document, exit_code = Runner(
        kernel,
        evidence_root=tmp_path / "evidence",
        review_adapter=adapter,
    ).run(kernel.resolve(request))
    assert exit_code == 0
    assert document["disposition"] == "completed"
    run_dir = Path(document["run_dir"])
    assert (run_dir / "codex-prepr-review.md").is_file()
    assert (run_dir / "countyforge-run-event.ndjson").is_file()
    legacy = json.loads((run_dir / "run.summary.json").read_text(encoding="utf-8"))
    generic = json.loads((run_dir / "countyforge-run-summary.json").read_text(encoding="utf-8"))
    assert legacy["status"] == "succeeded"
    assert generic["outcome"] == "succeeded"
    assert generic["run_id"] == request["run_id"]
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    assert "openai-fixture-secret-value" not in all_text
    assert "sakana-fixture-secret-value" not in all_text


def test_generic_metrics_are_low_cardinality(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("validate"))
    document, _ = Runner(kernel, evidence_root=tmp_path).run(resolved)
    run_dir = tmp_path / "validate" / resolved.run_id
    metrics = (run_dir / "countyforge-run-metrics.prom").read_text(encoding="utf-8")
    forbidden = ["run_id=", "branch=", "sha=", "issue=", "path=", "error="]
    assert not any(label in metrics for label in forbidden)
    assert document["summary"]["disposition"] == "profile_not_implemented"


def test_generic_run_directory_collision_preserves_evidence(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("validate"))
    runner = Runner(kernel, evidence_root=tmp_path)
    runner.run(resolved)
    run_dir = tmp_path / "validate" / resolved.run_id
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    with pytest.raises(KernelError, match="run directory"):
        runner.run(resolved)
    after = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    assert after == before


def test_review_profile_declares_no_repository_mount() -> None:
    profile = json.loads(
        Path(".ai/profiles/review.packet-only.v1.json").read_text(encoding="utf-8")
    )
    assert profile["repository_access"] == "none"
    assert profile["expected_security_posture"]["repository_mounted"] is False
    assert all(mount["source"] != "repository" for mount in profile["filesystem_mounts"])
    runner = Path(".ai/codex/02-run-prepr-review-docker.sh").read_text(encoding="utf-8")
    assert '-v "$SCHEMA_DIR:/workspace/.ai/schemas:ro"' in runner
    assert '-v "$RUN_DIR:/out:rw"' in runner
    assert '-v "$REPO_ROOT' not in runner


def test_kernel_preserves_declared_host_docker_environment_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "ssh://docker.example.test")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/fixture")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-must-not-be-selected")
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-selected-fixture")
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("review"))
    environment = Runner(kernel)._scoped_environment(resolved, tmp_path / "run")
    assert environment["DOCKER_HOST"] == "ssh://docker.example.test"
    assert environment["XDG_RUNTIME_DIR"] == "/run/user/fixture"
    assert environment["SAKANA_API_KEY"] == "sakana-selected-fixture"  # pragma: allowlist secret
    assert "OPENAI_API_KEY" not in environment


def test_packet_binding_is_revalidated_before_credential_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("review")
    kernel = Kernel()
    resolved = kernel.resolve(request)
    packet = Path(str(request["input"]["packet_path"]))
    packet.write_text("changed after resolution\n", encoding="utf-8")
    runner = Runner(kernel, evidence_root=tmp_path / "evidence")

    def fail_if_credentials_are_selected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("provider credentials were selected before packet revalidation")

    monkeypatch.setattr(runner, "_scoped_environment", fail_if_credentials_are_selected)
    with pytest.raises(KernelError) as raised:
        runner.run(resolved)
    assert raised.value.code == "packet_hash_mismatch"


def test_output_budget_counts_only_model_provider_artifacts(tmp_path: Path) -> None:
    (tmp_path / "codex-prepr-review.md").write_bytes(b"r" * 100)
    (tmp_path / "codex-prepr-review.stderr").write_bytes(b"e" * 20)
    (tmp_path / "container.provenance.json").write_bytes(b"p" * 5000)
    (tmp_path / "countyforge-run-event.ndjson").write_bytes(b"o" * 5000)
    assert _output_bytes(tmp_path) == 120


def test_safe_branch_uses_documented_ascii_character_class(
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("review")
    request["display_metadata"]["branch"] = "feature/café"
    resolved = Kernel().resolve(request)
    assert _safe_branch(resolved) == "feature__caf__"


def test_review_wall_clock_timeout_never_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-timeout-fixture-secret")
    adapter = tmp_path / "timeout-adapter.sh"
    adapter.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p "$OUT_DIR"\nsleep 5\n',
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    request = request_factory("review")
    request["run_id"] = "review-timeout"
    request["budget_overrides"]["wall_clock_seconds"] = 1
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", review_adapter=adapter
    ).run(kernel.resolve(request))
    assert exit_code == 5
    assert document["disposition"] == "timed_out"
    assert document["summary"]["outcome"] == "failed"


def test_review_output_budget_never_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-output-fixture-secret")
    adapter = tmp_path / "output-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'mkdir -p "$OUT_DIR"\n'
        'head -c 4096 /dev/zero > "$OUT_DIR/codex-prepr-review.md"\n',
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    request = request_factory("review")
    request["run_id"] = "review-output-budget"
    request["budget_overrides"]["max_output_bytes"] = 1024
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", review_adapter=adapter
    ).run(kernel.resolve(request))
    assert exit_code == 5
    assert document["disposition"] == "budget_exceeded"
    assert document["summary"]["outcome"] == "failed"


def test_signal_failure_is_normalized_and_diagnostic_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    secret = "sakana-signal-fixture-secret"  # pragma: allowlist secret
    monkeypatch.setenv("SAKANA_API_KEY", secret)
    adapter = tmp_path / "signal-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'mkdir -p "$OUT_DIR"\n'
        "printf 'adapter failed near %s\\n' \"$SAKANA_API_KEY\" >&2\n"
        "kill -TERM $$\n",
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    request = request_factory("review")
    request["run_id"] = "review-signal"
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", review_adapter=adapter
    ).run(kernel.resolve(request))
    assert exit_code == 143
    assert document["disposition"] == "adapter_failed"
    assert secret not in document["adapter_stderr_tail"]
    assert "***REDACTED-CREDENTIAL***" in document["adapter_stderr_tail"]


def test_unexpected_cli_failure_is_sanitized_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request_factory: Callable[[str], JsonObject],
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_factory("validate")), encoding="utf-8")

    def fail_unexpectedly(*_args: object, **_kwargs: object) -> None:
        raise OSError("/private/host/path")

    monkeypatch.setattr("countyforge_runner.cli.Runner.run", fail_unexpectedly)
    assert main(["run", "--request", str(request_path), "--json"]) == 5
    result = json.loads(capsys.readouterr().out)
    assert result["disposition"] == "internal_error"
    assert "/private/host/path" not in json.dumps(result)
