"""Sanitized generic CountyForge evidence and low-cardinality metrics."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from countyforge_runner.contracts import JsonObject, file_sha256, validate_document
from countyforge_runner.errors import KernelError
from countyforge_runner.resolver import Kernel, ResolvedRun

GENERIC_ARTIFACTS = (
    "countyforge-request.provenance.json",
    "countyforge-profile.snapshot.json",
    "countyforge-run-event.ndjson",
    "countyforge-run-summary.json",
    "countyforge-run-metrics.prom",
)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _assert_secret_free(text: str, secret_values: tuple[str, ...]) -> None:
    if any(value in text for value in secret_values):
        raise KernelError(
            "secret_leak_detected",
            "A provider credential value was detected in generic evidence.",
            exit_code=5,
        )


def _write_json(path: Path, document: JsonObject, secret_values: tuple[str, ...]) -> None:
    body = json.dumps(document, indent=2, sort_keys=True) + "\n"
    _assert_secret_free(body, secret_values)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(path)


def _input_fact(path_value: str) -> JsonObject:
    path = Path(path_value)
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def sanitized_request(resolved: ResolvedRun) -> JsonObject:
    """Return immutable request facts without host-local input paths."""

    request = resolved.request
    input_facts: JsonObject = {}
    for key, path_value in resolved.canonical_input_paths.items():
        input_facts[key.removesuffix("_path")] = _input_fact(path_value)
    for key in (
        "packet_sha256",
        "packet_provenance_sha256",
        "selected_finding_ids",
        "expected_head_sha",
    ):
        if key in request["input"]:
            input_facts[key] = request["input"][key]
    return {
        "request_contract_version": request["contract_version"],
        "run_id": resolved.run_id,
        "trigger": request["trigger"],
        "repository": request["repository"],
        "openspec_change": request.get("openspec_change"),
        "mode": request["mode"],
        "profile": request["profile"],
        "prompt": request["prompt"],
        "provider": request["provider"],
        "reasoning_effort": request["reasoning_effort"],
        "budget_overrides": request["budget_overrides"],
        "input": input_facts,
        "expected_output_schema": request["expected_output_schema"],
        "requested_artifacts": request["requested_artifacts"],
    }


class EvidenceWriter:
    """Write one self-contained generic evidence bundle."""

    def __init__(
        self,
        kernel: Kernel,
        resolved: ResolvedRun,
        run_dir: Path,
        *,
        owns_claim: bool,
        secret_values: tuple[str, ...] = (),
    ) -> None:
        self.kernel = kernel
        self.resolved = resolved
        self.run_dir = run_dir
        self.owns_claim = owns_claim
        self.secret_values = tuple(value for value in secret_values if len(value) >= 8)
        self.claim = run_dir / ".countyforge-claim"

    def claim_directory(self) -> None:
        """Atomically claim a generic-only run directory without overwriting evidence."""

        if not self.owns_claim:
            return
        if self.run_dir.is_dir() and any(self.run_dir.iterdir()):
            raise KernelError(
                "run_directory_collision",
                "The CountyForge run directory already contains evidence.",
                exit_code=2,
            )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.claim.mkdir()
        except FileExistsError:
            raise KernelError(
                "run_directory_collision",
                "The CountyForge run directory is already claimed.",
                exit_code=2,
            ) from None

    def release_claim(self) -> None:
        """Release this writer's atomic claim after evidence is complete."""

        if self.owns_claim:
            try:
                self.claim.rmdir()
            except OSError:
                pass

    def write(
        self,
        *,
        started_at: str,
        duration_seconds: float,
        outcome: str,
        disposition: str,
        exit_code: int,
        attempts: int,
        input_bytes: int,
        output_bytes: int,
        error_code: str | None,
        legacy_provenance: JsonObject | None = None,
    ) -> JsonObject:
        """Write provenance, one event, summary, and metrics."""

        self.run_dir.mkdir(parents=True, exist_ok=True)
        finished_at = _iso_now()
        provider_id = None if self.resolved.provider is None else self.resolved.provider["id"]
        model_ref = None if self.resolved.model is None else self.resolved.model["logical_ref"]
        configured_model = (
            None if self.resolved.model is None else self.resolved.model["configured_model_id"]
        )
        credential_names = (
            []
            if self.resolved.provider is None
            else [str(self.resolved.provider["credential_name"])]
        )
        container = self.resolved.profile["container"]
        provider_images = container.get("provider_images", {})
        selected_image = provider_images.get(provider_id, container["image"])
        image_digest = None
        codex_cli_version = container["codex_cli_version"]
        if legacy_provenance is not None:
            image_digest = legacy_provenance.get("image_id")
            codex_cli_version = legacy_provenance.get("codex_cli_version", codex_cli_version)
        mounts = [
            f"{mount['source']}:{mount['target']}:{mount['access']}"
            for mount in self.resolved.profile["filesystem_mounts"]
        ]
        all_disabled = [
            "shell_tool",
            "unified_exec",
            "browser_use",
            "computer_use",
            "apps",
            "image_generation",
            "web_search",
        ]
        usage: JsonObject = {
            "wall_clock_seconds": duration_seconds,
            "attempts": attempts,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
            "tokens": {"state": "unavailable", "value": None},
            "cost_usd": {"state": "unavailable", "value": None},
        }
        event: JsonObject = {
            "event_contract_version": 1,
            "request_contract_version": self.resolved.request["contract_version"],
            "event_type": "countyforge_run",
            "run_id": self.resolved.run_id,
            "mode": self.resolved.request["mode"],
            "profile_id": self.resolved.profile["profile_id"],
            "profile_version": self.resolved.profile["profile_version"],
            "profile_sha256": self.resolved.profile_sha256,
            "provider": provider_id,
            "model_ref": model_ref,
            "configured_model_id": configured_model,
            "execution_state": "finished",
            "lifecycle_stage": "completed" if outcome == "succeeded" else "failed",
            "outcome": outcome,
            "disposition": disposition,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "budget_usage": usage,
            "base_sha": self.resolved.request["repository"]["base_sha"],
            "head_sha": self.resolved.request["repository"]["head_sha"],
            "output_schema_sha256": self.resolved.output_schema_sha256,
            "prompt_sha256": self.resolved.prompt_sha256,
            "capability_snapshot_sha256": self.resolved.profile_sha256,
            "image": selected_image,
            "image_digest": image_digest,
            "codex_cli_version": codex_cli_version,
            "enabled_tools": self.resolved.profile["model_tools"],
            "disabled_tools": [] if self.resolved.profile["model_tools"] else all_disabled,
            "mounts": mounts,
            "network_policy": self.resolved.profile["network"]["policy"],
            "credential_names": credential_names,
            "secret_leak_detected": False,
            "artifact_export_status": "complete",
        }
        event_schema = self.kernel._load_schema("countyforge-run-event.schema.json")
        validate_document(event, event_schema, kind="generic run event")

        request_provenance = sanitized_request(self.resolved)
        profile_snapshot: JsonObject = {
            "profile_sha256": self.resolved.profile_sha256,
            "profile": self.resolved.profile,
        }
        artifacts = {name: True for name in GENERIC_ARTIFACTS}
        summary: JsonObject = {
            "summary_contract_version": 1,
            "request_contract_version": self.resolved.request["contract_version"],
            "run_id": self.resolved.run_id,
            "mode": self.resolved.request["mode"],
            "profile_id": self.resolved.profile["profile_id"],
            "profile_version": self.resolved.profile["profile_version"],
            "profile_sha256": self.resolved.profile_sha256,
            "execution_eligible": self.resolved.execution_eligible,
            "outcome": outcome,
            "disposition": disposition,
            "exit_code": exit_code,
            "error_code": error_code,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "effective_budgets": self.resolved.effective_budgets,
            "budget_usage": usage,
            "result_schema": self.resolved.profile["output_schema"],
            "artifacts": artifacts,
        }
        summary_schema = self.kernel._load_schema("countyforge-run-summary.schema.json")
        validate_document(summary, summary_schema, kind="generic run summary")

        _write_json(self.run_dir / GENERIC_ARTIFACTS[0], request_provenance, self.secret_values)
        _write_json(self.run_dir / GENERIC_ARTIFACTS[1], profile_snapshot, self.secret_values)
        event_body = json.dumps(event, sort_keys=True) + "\n"
        _assert_secret_free(event_body, self.secret_values)
        (self.run_dir / GENERIC_ARTIFACTS[2]).write_text(event_body, encoding="utf-8")
        _write_json(self.run_dir / GENERIC_ARTIFACTS[3], summary, self.secret_values)
        metrics = self._metrics(event)
        _assert_secret_free(metrics, self.secret_values)
        (self.run_dir / GENERIC_ARTIFACTS[4]).write_text(metrics, encoding="utf-8")
        return summary

    @staticmethod
    def _metrics(event: JsonObject) -> str:
        labels = {
            "mode": event["mode"],
            "profile": event["profile_id"],
            "provider": event["provider"] or "none",
            "model": event["model_ref"] or "none",
            "outcome": event["outcome"],
            "disposition": event["disposition"],
        }
        label_text = ",".join(f'{key}="{value}"' for key, value in labels.items())
        duration = event["duration_seconds"]
        return (
            "# HELP countyforge_runner_run_duration_seconds CountyForge run wall-clock duration.\n"
            "# TYPE countyforge_runner_run_duration_seconds gauge\n"
            f"countyforge_runner_run_duration_seconds{{{label_text}}} {duration}\n"
            "# HELP countyforge_runner_run_info CountyForge low-cardinality run outcome.\n"
            "# TYPE countyforge_runner_run_info gauge\n"
            f"countyforge_runner_run_info{{{label_text}}} 1\n"
        )
