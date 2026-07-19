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


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_branch(resolved: ResolvedRun) -> str:
    display = resolved.request.get("display_metadata", {})
    branch = str(display.get("branch", "detached"))
    return "".join(char if char.isalnum() or char in "._-" else "__" for char in branch)


def _input_bytes(resolved: ResolvedRun, repo_root: Path) -> int:
    total = 0
    for key in ("packet_path", "context_manifest_path"):
        raw_path = resolved.request["input"].get(key)
        if raw_path is None:
            continue
        path = Path(str(raw_path))
        if not path.is_absolute():
            path = repo_root / path
        total += path.stat().st_size
    return total


def _output_bytes(run_dir: Path) -> int:
    excluded = {"review-packet.md"}
    return sum(
        path.stat().st_size
        for path in run_dir.iterdir()
        if path.is_file() and path.name not in excluded
    )


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
                input_bytes=_input_bytes(resolved, self.kernel.repo_root),
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
        packet = Path(str(resolved.request["input"]["packet_path"]))
        if not packet.is_absolute():
            packet = self.kernel.repo_root / packet
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
        try:
            process.communicate(timeout=float(resolved.effective_budgets["wall_clock_seconds"]))
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
        duration = max(time.monotonic() - started, 0.0)
        adapter_code = int(process.returncode or 0)
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
                input_bytes=_input_bytes(resolved, self.kernel.repo_root),
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
        final_review = run_dir / "codex-prepr-review.md"
        if final_review.is_file():
            try:
                result["review"] = json.loads(final_review.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return result, exit_code
