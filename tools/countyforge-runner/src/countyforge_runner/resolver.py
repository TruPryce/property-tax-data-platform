"""Profile, provider, compatibility, and budget resolution."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from countyforge_runner.contracts import (
    JsonObject,
    document_sha256,
    file_sha256,
    load_json_object,
    validate_document,
)
from countyforge_runner.errors import KernelError
from countyforge_runner.paths import find_repo_root


def _version_tuple(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError:
        raise KernelError("invalid_codex_version", "Codex CLI version is invalid.") from None
    if len(parts) != 3:
        raise KernelError("invalid_codex_version", "Codex CLI version is invalid.")
    return parts


@dataclass(frozen=True, slots=True)
class ResolvedRun:
    """An immutable, fully validated execution resolution."""

    request: JsonObject
    profile: JsonObject
    provider: JsonObject | None
    model: JsonObject | None
    effective_budgets: JsonObject
    run_id: str
    profile_sha256: str
    prompt_sha256: str
    output_schema_sha256: str
    execution_eligible: bool

    def as_document(self) -> JsonObject:
        """Return a credential-value-free resolution document."""

        capabilities = {
            "filesystem_mounts": self.profile["filesystem_mounts"],
            "repository_access": self.profile["repository_access"],
            "writable_paths": self.profile["writable_paths"],
            "model_tools": self.profile["model_tools"],
            "deterministic_commands": self.profile["deterministic_commands"],
            "network": self.profile["network"],
            "credential_names": self.profile["credential_names"],
            "environment_allowlist": self.profile["environment_allowlist"],
            "container": self.profile["container"],
            "expected_security_posture": self.profile["expected_security_posture"],
        }
        return {
            "ok": True,
            "run_id": self.run_id,
            "mode": self.request["mode"],
            "profile": {
                "id": self.profile["profile_id"],
                "version": self.profile["profile_version"],
                "sha256": self.profile_sha256,
                "implementation_state": self.profile["implementation_state"],
            },
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.request["reasoning_effort"],
            "reasoning_effort_policy": {
                "default": self.profile["default_reasoning_effort"],
                "maximum": self.profile["maximum_reasoning_effort"],
                "choices": self.profile["reasoning_efforts"],
            },
            "effective_budgets": self.effective_budgets,
            "output_schema": self.profile["output_schema"],
            "output_schema_sha256": self.output_schema_sha256,
            "prompt": {
                **self.profile["prompt"],
                "sha256": self.prompt_sha256,
            },
            "allowed_artifacts": self.profile["allowed_artifacts"],
            "capabilities": capabilities,
            "execution_eligible": self.execution_eligible,
        }


class Kernel:
    """Load and enforce repository-owned CountyForge contracts."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.repo_root = find_repo_root(repo_root)
        self.schema_root = self.repo_root / ".ai" / "schemas"
        self.profile_root = self.repo_root / ".ai" / "profiles"
        self.provider_root = self.repo_root / ".ai" / "providers"
        self.request_schema = self._load_schema("countyforge-run-request.schema.json")
        self.profile_schema = self._load_schema("countyforge-profile.schema.json")
        self.catalog_schema = self._load_schema("countyforge-provider-catalog.schema.json")
        self.catalog = load_json_object(
            self.provider_root / "catalog.v1.json", kind="provider catalog"
        )
        validate_document(self.catalog, self.catalog_schema, kind="provider catalog")
        self.profiles = self._load_profiles()
        self.providers = self._index_unique(self.catalog["providers"], "id", "provider")
        self.models = self._index_unique(self.catalog["models"], "logical_ref", "model")
        self._validate_catalog_relations()
        self._validate_profile_relations()

    def _load_schema(self, name: str) -> JsonObject:
        return load_json_object(self.schema_root / name, kind=f"schema {name}")

    def _load_profiles(self) -> dict[tuple[str, int], JsonObject]:
        profiles: dict[tuple[str, int], JsonObject] = {}
        for path in sorted(self.profile_root.glob("*.json")):
            profile = load_json_object(path, kind="capability profile")
            validate_document(profile, self.profile_schema, kind="capability profile")
            key = (str(profile["profile_id"]), int(profile["profile_version"]))
            if key in profiles:
                raise KernelError("duplicate_profile", "Capability profile identity is duplicated.")
            profiles[key] = profile
        if not profiles:
            raise KernelError("profile_catalog_empty", "No capability profiles are defined.")
        return profiles

    @staticmethod
    def _index_unique(items: list[Any], field: str, kind: str) -> dict[str, JsonObject]:
        indexed: dict[str, JsonObject] = {}
        for raw_item in items:
            if not isinstance(raw_item, dict):
                raise KernelError("invalid_catalog_relation", f"A {kind} catalog entry is invalid.")
            item: JsonObject = raw_item
            key = str(item[field])
            if key in indexed:
                raise KernelError(
                    "duplicate_catalog_entry", f"A {kind} catalog identity is duplicated."
                )
            indexed[key] = item
        return indexed

    def _validate_catalog_relations(self) -> None:
        for model in self.models.values():
            if model["provider"] not in self.providers:
                raise KernelError(
                    "invalid_catalog_relation", "A model references an unknown provider."
                )
        expected_credentials = {"openai": "OPENAI_API_KEY", "sakana": "SAKANA_API_KEY"}
        for provider_id, credential in expected_credentials.items():
            provider = self.providers.get(provider_id)
            if provider is None or provider["credential_name"] != credential:
                raise KernelError(
                    "invalid_credential_policy", "Provider credential policy is invalid."
                )

    def _validate_profile_relations(self) -> None:
        effort_rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4}
        for profile in self.profiles.values():
            defaults = profile["budgets"]["defaults"]
            ceilings = profile["budgets"]["ceilings"]
            for name, default in defaults.items():
                ceiling = ceilings[name]
                if default is not None and (ceiling is None or default > ceiling):
                    raise KernelError(
                        "invalid_profile_budget", "A profile default exceeds its ceiling."
                    )
            for ref in profile["permitted_model_refs"]:
                model = self.models.get(ref)
                if model is None or model["provider"] not in profile["permitted_providers"]:
                    raise KernelError(
                        "invalid_profile_model", "A profile permits an incompatible model."
                    )
            default_effort = str(profile["default_reasoning_effort"])
            maximum_effort = str(profile["maximum_reasoning_effort"])
            if (
                default_effort not in profile["reasoning_efforts"]
                or maximum_effort not in profile["reasoning_efforts"]
                or effort_rank[default_effort] > effort_rank[maximum_effort]
            ):
                raise KernelError(
                    "invalid_profile_effort",
                    "A profile reasoning-effort policy is inconsistent.",
                )
            output_schema = self.schema_root / str(profile["output_schema"])
            prompt_path = self.repo_root / str(profile["prompt"]["path"])
            if not output_schema.is_file() or not prompt_path.is_file():
                raise KernelError(
                    "contract_file_missing", "A profile contract file is unavailable."
                )
            if profile["implementation_state"] == "implemented":
                provider_images = profile["container"].get("provider_images", {})
                if any(
                    provider_id not in provider_images
                    for provider_id in profile["permitted_providers"]
                ):
                    raise KernelError(
                        "invalid_profile_image",
                        "An executable profile lacks a provider-specific image.",
                    )

    def list_profiles(self) -> list[JsonObject]:
        """Return stable profile summaries ordered by mode and identity."""

        return [
            {
                "profile_id": profile["profile_id"],
                "profile_version": profile["profile_version"],
                "profile_sha256": document_sha256(profile),
                "mode": profile["mode"],
                "enabled": profile["enabled"],
                "implementation_state": profile["implementation_state"],
                "execution_eligible": profile["enabled"]
                and profile["implementation_state"] == "implemented",
                "output_schema": profile["output_schema"],
            }
            for profile in sorted(
                self.profiles.values(),
                key=lambda item: (str(item["mode"]), str(item["profile_id"])),
            )
        ]

    def load_request(self, request_path: Path) -> JsonObject:
        """Load and schema-validate a request."""

        request = load_json_object(request_path, kind="run request")
        validate_document(request, self.request_schema, kind="run request")
        return request

    def resolve_path(self, request_path: Path) -> ResolvedRun:
        """Load and fully resolve one request path."""

        return self.resolve(self.load_request(request_path))

    def resolve(self, request: JsonObject) -> ResolvedRun:
        """Resolve and enforce every profile/provider/budget compatibility rule."""

        validate_document(request, self.request_schema, kind="run request")
        profile_key = (str(request["profile"]["id"]), int(request["profile"]["version"]))
        profile = self.profiles.get(profile_key)
        if profile is None:
            raise KernelError(
                "profile_not_found", "The requested profile identity is not available."
            )
        if request["mode"] != profile["mode"]:
            raise KernelError(
                "mode_profile_mismatch", "Requested mode does not match the selected profile."
            )
        if not profile["enabled"]:
            raise KernelError("profile_disabled", "The selected profile is disabled.")
        if (
            request["prompt"]["id"] != profile["prompt"]["id"]
            or request["prompt"]["version"] != profile["prompt"]["version"]
        ):
            raise KernelError(
                "prompt_profile_mismatch", "Requested prompt does not match the profile."
            )
        if request["expected_output_schema"] != profile["output_schema"]:
            raise KernelError(
                "output_schema_not_declared",
                "Requested output schema is not declared by the profile.",
            )
        if not set(request["requested_artifacts"]).issubset(profile["allowed_artifacts"]):
            raise KernelError(
                "artifact_not_declared", "A requested artifact is not declared by the profile."
            )

        provider, model = self._resolve_provider(request, profile)
        effective_budgets = self._resolve_budgets(request, profile)
        self._validate_mode_facts(request)
        self._validate_input_budget(request, effective_budgets)

        if "run_id" in request:
            run_id = str(request["run_id"])
        else:
            seed = str(request["idempotency_seed"]).encode("utf-8")
            run_id = "seed-" + hashlib.sha256(seed).hexdigest()[:24]
        output_schema_path = self.schema_root / str(profile["output_schema"])
        prompt_path = self.repo_root / str(profile["prompt"]["path"])
        return ResolvedRun(
            request=request,
            profile=profile,
            provider=provider,
            model=model,
            effective_budgets=effective_budgets,
            run_id=run_id,
            profile_sha256=document_sha256(profile),
            prompt_sha256=file_sha256(prompt_path),
            output_schema_sha256=file_sha256(output_schema_path),
            execution_eligible=profile["implementation_state"] == "implemented",
        )

    def _resolve_provider(
        self, request: JsonObject, profile: JsonObject
    ) -> tuple[JsonObject | None, JsonObject | None]:
        provider_request = request["provider"]
        if provider_request is None:
            if profile["permitted_providers"] or request["reasoning_effort"] != "none":
                raise KernelError("provider_required", "The selected profile requires a provider.")
            return None, None
        provider = self.providers.get(str(provider_request["id"]))
        model = self.models.get(str(provider_request["model_ref"]))
        if provider is None or provider["id"] not in profile["permitted_providers"]:
            raise KernelError("provider_not_permitted", "Provider is not permitted by the profile.")
        if model is None or model["logical_ref"] not in profile["permitted_model_refs"]:
            raise KernelError("model_not_permitted", "Model is not permitted by the profile.")
        if model["provider"] != provider["id"]:
            raise KernelError("provider_model_mismatch", "Provider and model are incompatible.")
        if model["availability"] == "unavailable" or model["live_validation"] == "failed":
            raise KernelError("model_unavailable", "The selected model is unavailable.")
        effort = request["reasoning_effort"]
        effort_rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4}
        if (
            effort not in profile["reasoning_efforts"]
            or effort not in model["supported_reasoning_efforts"]
            or effort_rank[str(effort)] > effort_rank[str(profile["maximum_reasoning_effort"])]
            or effort_rank[str(effort)] > effort_rank[str(profile["default_reasoning_effort"])]
        ):
            raise KernelError(
                "reasoning_effort_not_permitted", "Reasoning effort is not supported."
            )
        cli_version = _version_tuple(str(provider_request["codex_cli_version"]))
        floors = [str(model["minimum_codex_cli_version"])]
        if profile["minimum_codex_cli_version"] is not None:
            floors.append(str(profile["minimum_codex_cli_version"]))
        if any(cli_version < _version_tuple(floor) for floor in floors):
            raise KernelError(
                "codex_cli_too_old", "Codex CLI version is below the compatibility floor."
            )
        if provider["credential_name"] not in profile["credential_names"]:
            raise KernelError(
                "credential_not_declared", "Provider credential is not declared by the profile."
            )
        return provider, model

    @staticmethod
    def _resolve_budgets(request: JsonObject, profile: JsonObject) -> JsonObject:
        defaults: JsonObject = profile["budgets"]["defaults"]
        ceilings: JsonObject = profile["budgets"]["ceilings"]
        overrides: JsonObject = request["budget_overrides"]
        effective = dict(defaults)
        for name, value in overrides.items():
            default = defaults[name]
            ceiling = ceilings[name]
            if value is not None and (ceiling is None or value > ceiling):
                raise KernelError(
                    "budget_ceiling_exceeded",
                    "A requested budget exceeds the profile ceiling.",
                    {"budget": name},
                )
            if default is not None and (value is None or value > default):
                raise KernelError(
                    "budget_expansion_not_permitted",
                    "A request may only tighten the profile's default budget.",
                    {"budget": name},
                )
            effective[name] = value
        return effective

    @staticmethod
    def _validate_mode_facts(request: JsonObject) -> None:
        if (
            request["mode"] == "fix"
            and request["input"]["expected_head_sha"] != request["repository"]["head_sha"]
        ):
            raise KernelError(
                "expected_head_mismatch",
                "Fix expected head SHA does not match the immutable request head.",
            )

    def _validate_input_budget(self, request: JsonObject, budgets: JsonObject) -> None:
        candidates = [
            request["input"].get("packet_path"),
            request["input"].get("context_manifest_path"),
        ]
        total = 0
        for raw_path in candidates:
            if raw_path is None:
                continue
            path = Path(str(raw_path))
            if not path.is_absolute():
                path = self.repo_root / path
            try:
                total += path.stat().st_size
            except OSError:
                raise KernelError(
                    "input_not_found", "A declared input file is unavailable."
                ) from None
        if total > int(budgets["max_input_bytes"]):
            raise KernelError(
                "input_budget_exceeded", "Input context exceeds the effective byte budget."
            )
