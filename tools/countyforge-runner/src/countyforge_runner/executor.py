"""Fail-closed execution dispatch for CountyForge profiles."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from countyforge_runner.contracts import JsonObject, load_json_object
from countyforge_runner.errors import KernelError
from countyforge_runner.evidence import EvidenceWriter
from countyforge_runner.resolver import Kernel, ResolvedRun

MODEL_OUTPUT_ARTIFACTS = (
    "codex-prepr-review.md",
    "codex-events.ndjson",
    "codex-prepr-review.stdout",
    "codex-prepr-review.stderr",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_branch(resolved: ResolvedRun) -> str:
    display = resolved.request.get("display_metadata", {})
    branch = str(display.get("branch", "detached"))
    return "".join(
        char if char.isascii() and (char.isalnum() or char in "._-") else "__" for char in branch
    )


def _input_bytes(resolved: ResolvedRun) -> int:
    return sum(Path(path).stat().st_size for path in resolved.canonical_input_paths.values())


def _output_bytes(run_dir: Path) -> int:
    return sum(
        path.stat().st_size for name in MODEL_OUTPUT_ARTIFACTS if (path := run_dir / name).is_file()
    )


def _redacted_tail(text: str, environment: dict[str, str], limit: int = 4000) -> str:
    secret_names = {
        "OPENAI_API_KEY",
        "SAKANA_API_KEY",
        "BITWARDEN_TOKEN",
        "BWS_ACCESS_TOKEN",
    }
    redacted = text
    for name in secret_names:
        value = environment.get(name, "")
        if value:
            redacted = redacted.replace(value, "***REDACTED-CREDENTIAL***")
    return redacted[-limit:]


class Runner:
    """Dispatch only implemented immutable profiles."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        evidence_root: Path | None = None,
        review_adapter: Path | None = None,
    ) -> None:
        self.kernel = kernel
        self.evidence_root = evidence_root
        self.review_adapter = review_adapter or (
            kernel.repo_root / ".ai" / "codex" / "02-run-prepr-review-docker.sh"
        )

    def run(self, resolved: ResolvedRun) -> tuple[JsonObject, int]:
        """Execute review or emit a fail-closed unimplemented disposition."""

        if not resolved.execution_eligible:
            return self._not_implemented(resolved)
        if resolved.request["mode"] != "review":
            raise KernelError(
                "executor_not_available",
                "No executor is available for the selected implemented profile.",
            )
        return self._run_review(resolved)

    def _generic_run_dir(self, resolved: ResolvedRun) -> Path:
        root = self.evidence_root or (self.kernel.repo_root / ".ai" / "reviews" / "countyforge")
        return root / str(resolved.request["mode"]) / resolved.run_id

    def _review_run_dir(self, resolved: ResolvedRun) -> Path:
        if self.evidence_root is not None:
            return self.evidence_root / "codex-prepr" / _safe_branch(resolved) / resolved.run_id
        return (
            self.kernel.repo_root
            / ".ai"
            / "reviews"
            / "codex-prepr"
            / _safe_branch(resolved)
            / resolved.run_id
        )

    def _not_implemented(self, resolved: ResolvedRun) -> tuple[JsonObject, int]:
        started_at = _iso_now()
        started = time.monotonic()
        run_dir = self._generic_run_dir(resolved)
        writer = EvidenceWriter(self.kernel, resolved, run_dir, owns_claim=True)
        writer.claim_directory()
        try:
            summary = writer.write(
                started_at=started_at,
                duration_seconds=max(time.monotonic() - started, 0.0),
                outcome="not_executed",
                disposition="profile_not_implemented",
                exit_code=4,
                attempts=0,
                input_bytes=_input_bytes(resolved),
                output_bytes=0,
                error_code="profile_not_implemented",
            )
        finally:
            writer.release_claim()
        return {
            "ok": False,
            "disposition": "profile_not_implemented",
            "run_id": resolved.run_id,
            "mode": resolved.request["mode"],
            "profile_id": resolved.profile["profile_id"],
            "execution_eligible": False,
            "summary": summary,
        }, 4

    def _scoped_environment(self, resolved: ResolvedRun, run_dir: Path) -> dict[str, str]:
        known_credentials = {
            "OPENAI_API_KEY",
            "SAKANA_API_KEY",
            "BITWARDEN_TOKEN",
            "BWS_ACCESS_TOKEN",
        }
        environment: dict[str, str] = {}
        for name in resolved.profile["environment_allowlist"]:
            if name not in known_credentials and name in os.environ:
                environment[name] = os.environ[name]
        if resolved.provider is not None:
            credential = str(resolved.provider["credential_name"])
            if credential in os.environ:
                environment[credential] = os.environ[credential]
            for broker in resolved.profile["host_credential_broker_names"]:
                if broker in os.environ:
                    environment[str(broker)] = os.environ[str(broker)]
        packet = Path(resolved.canonical_input_paths["packet_path"])
        model = resolved.model
        if resolved.provider is None or model is None:
            raise KernelError(
                "provider_required",
                "The executable review profile requires a resolved provider and model.",
            )
        provider_images = resolved.profile["container"].get("provider_images", {})
        selected_image = provider_images.get(
            resolved.provider["id"], resolved.profile["container"]["image"]
        )
        environment.update(
            {
                "PACKET_PATH": str(packet),
                "OUT_DIR": str(run_dir),
                "RUN_ID": resolved.run_id,
                "COMPAT_DIR": str(self.kernel.repo_root / ".ai" / "reviews"),
                "REVIEW_BASE": str(resolved.request["repository"]["base_sha"]),
                "CODEX_PROVIDER": str(resolved.provider["id"]),
                "CODEX_MODEL": str(model["configured_model_id"]),
                "CODEX_IMAGE": str(selected_image),
                "CODEX_REASONING_EFFORT": str(resolved.request["reasoning_effort"]),
                "MAX_PACKET_BYTES": str(resolved.effective_budgets["max_input_bytes"]),
                "MAX_OUTPUT_BYTES": str(resolved.effective_budgets["max_output_bytes"]),
                "EXPECTED_PACKET_SHA256": str(resolved.request["input"]["packet_sha256"]),
                "COUNTYFORGE_PROFILE_SHA256": resolved.profile_sha256,
                "MIN_CODEX_CLI_VERSION": str(resolved.profile["minimum_codex_cli_version"]),
            }
        )
        return environment

    def _run_review(self, resolved: ResolvedRun) -> tuple[JsonObject, int]:
        run_dir = self._review_run_dir(resolved)
        if run_dir.is_dir() and any(run_dir.iterdir()):
            raise KernelError(
                "run_directory_collision",
                "The review run directory already contains evidence.",
            )
        started_at = _iso_now()
        started = time.monotonic()
        self.kernel.revalidate_execution_context(resolved)
        environment = self._scoped_environment(resolved, run_dir)
        process = subprocess.Popen(  # noqa: S603 - fixed repository adapter path
            [str(self.review_adapter)],
            cwd=self.kernel.repo_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        adapter_stderr = ""
        try:
            _, adapter_stderr = process.communicate(
                timeout=float(resolved.effective_budgets["wall_clock_seconds"])
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                _, adapter_stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                _, adapter_stderr = process.communicate()
        duration = max(time.monotonic() - started, 0.0)
        raw_adapter_code = int(process.returncode or 0)
        adapter_code = 128 + abs(raw_adapter_code) if raw_adapter_code < 0 else raw_adapter_code
        disposition = (
            "timed_out" if timed_out else ("completed" if adapter_code == 0 else "adapter_failed")
        )
        exit_code = 5 if timed_out else adapter_code
        outcome = "succeeded" if exit_code == 0 else "failed"
        output_bytes = _output_bytes(run_dir) if run_dir.is_dir() else 0
        if output_bytes > int(resolved.effective_budgets["max_output_bytes"]):
            disposition = "budget_exceeded"
            outcome = "failed"
            exit_code = 5

        legacy_provenance: JsonObject | None = None
        provenance_path = run_dir / "container.provenance.json"
        if provenance_path.is_file():
            legacy_provenance = load_json_object(
                provenance_path, kind="legacy container provenance"
            )
        if run_dir.is_dir():
            secret_names = {
                "OPENAI_API_KEY",
                "SAKANA_API_KEY",
                "BITWARDEN_TOKEN",
                "BWS_ACCESS_TOKEN",
            }
            writer = EvidenceWriter(
                self.kernel,
                resolved,
                run_dir,
                owns_claim=False,
                secret_values=tuple(
                    value for name, value in environment.items() if name in secret_names
                ),
            )
            summary = writer.write(
                started_at=started_at,
                duration_seconds=duration,
                outcome=outcome,
                disposition=disposition,
                exit_code=exit_code,
                attempts=1,
                input_bytes=_input_bytes(resolved),
                output_bytes=output_bytes,
                error_code=None if exit_code == 0 else disposition,
                legacy_provenance=legacy_provenance,
            )
        else:
            summary = {
                "outcome": outcome,
                "disposition": disposition,
                "exit_code": exit_code,
            }
        result: JsonObject = {
            "ok": exit_code == 0,
            "disposition": disposition,
            "run_id": resolved.run_id,
            "mode": "review",
            "profile_id": resolved.profile["profile_id"],
            "run_dir": str(run_dir),
            "summary": summary,
        }
        if exit_code != 0 and adapter_stderr:
            result["adapter_stderr_tail"] = _redacted_tail(adapter_stderr, environment)
        final_review = run_dir / "codex-prepr-review.md"
        if final_review.is_file():
            try:
                result["review"] = json.loads(final_review.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return result, exit_code
