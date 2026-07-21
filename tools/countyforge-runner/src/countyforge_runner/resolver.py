"""Profile, provider, compatibility, and budget resolution."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from countyforge_runner.contracts import (
    JsonObject,
    document_sha256,
    file_sha256,
    load_json_object,
    validate_document,
)
from countyforge_runner.errors import KernelError
from countyforge_runner.paths import find_repo_root

PACKET_METADATA_PREFIX = "<!-- countyforge-review-packet-metadata-v1 "
PACKET_METADATA_SUFFIX = " -->"


def _version_tuple(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError:
        raise KernelError("invalid_codex_version", "Codex CLI version is invalid.") from None
    if len(parts) != 3:
        raise KernelError("invalid_codex_version", "Codex CLI version is invalid.")
    return parts


def _git_environment() -> dict[str, str]:
    """Return only non-secret host values needed by read-only Git checks."""

    allowed = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "SYSTEMROOT",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _github_repository_name(remote_url: str) -> str | None:
    """Normalize one GitHub SSH/HTTPS origin without exposing its raw value."""

    host: str | None
    path: str
    if remote_url.startswith("git@github.com:"):
        host = "github.com"
        path = remote_url.removeprefix("git@github.com:")
    else:
        parsed = urlparse(remote_url)
        host = parsed.hostname
        path = parsed.path
    if host is None or host.casefold() != "github.com":
        return None
    normalized = path.strip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if len(normalized.split("/")) != 2:
        return None
    return normalized


def _packet_metadata(path: Path) -> JsonObject:
    """Load the fixed machine-readable binding from the first packet line."""

    try:
        with path.open(encoding="utf-8") as handle:
            first_line = handle.readline().rstrip("\n")
    except (OSError, UnicodeError):
        raise KernelError(
            "packet_provenance_mismatch",
            "Review packet provenance is unavailable.",
        ) from None
    if not first_line.startswith(PACKET_METADATA_PREFIX) or not first_line.endswith(
        PACKET_METADATA_SUFFIX
    ):
        raise KernelError(
            "packet_provenance_mismatch",
            "Review packet provenance does not agree with the immutable request.",
        )
    encoded = first_line[len(PACKET_METADATA_PREFIX) : -len(PACKET_METADATA_SUFFIX)]
    try:
        document: Any = json.loads(encoded)
    except json.JSONDecodeError:
        raise KernelError(
            "packet_provenance_mismatch",
            "Review packet provenance does not agree with the immutable request.",
        ) from None
    expected_keys = {
        "contract_version",
        "builder_id",
        "builder_version",
        "repository_full_name",
        "base_sha",
        "head_sha",
    }
    if not isinstance(document, dict) or set(document) != expected_keys:
        raise KernelError(
            "packet_provenance_mismatch",
            "Review packet provenance does not agree with the immutable request.",
        )
    return document


@dataclass(frozen=True, slots=True)
class ResolvedRun:
    """An immutable, fully validated execution resolution."""

    request: JsonObject
    profile: JsonObject
    provider: JsonObject | None
    model: JsonObject | None
    effective_budgets: JsonObject
    canonical_input_paths: dict[str, str]
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
            "input_policy": self.profile["input_policy"],
            "repository_policy": self.profile["repository_policy"],
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

    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        contract_root: Path | None = None,
        target_root: Path | None = None,
    ) -> None:
        if repo_root is not None and contract_root is not None:
            raise KernelError(
                "conflicting_repository_roots",
                "Use either the compatibility repository root or an explicit contract root.",
            )
        self.contract_root = find_repo_root(contract_root or repo_root)
        self.repo_root = self.contract_root
        target_candidate = target_root or self.contract_root
        try:
            self.target_root = target_candidate.resolve(strict=True)
        except OSError:
            raise KernelError(
                "target_repository_unavailable",
                "The immutable target repository is unavailable.",
            ) from None
        if not self.target_root.is_dir():
            raise KernelError(
                "target_repository_unavailable",
                "The immutable target repository is unavailable.",
            )
        self.schema_root = self.contract_root / ".ai" / "schemas"
        self.profile_root = self.contract_root / ".ai" / "profiles"
        self.provider_root = self.contract_root / ".ai" / "providers"
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
            prompt_path = self.contract_root / str(profile["prompt"]["path"])
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
            provenance_schema = profile["input_policy"]["packet_provenance_schema"]
            if (
                provenance_schema is not None
                and not (self.schema_root / str(provenance_schema)).is_file()
            ):
                raise KernelError(
                    "contract_file_missing",
                    "A profile packet-provenance contract is unavailable.",
                )
            if profile["mode"] == "review" and provenance_schema is None:
                raise KernelError(
                    "invalid_profile_input_policy",
                    "The review profile lacks packet provenance policy.",
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

        canonical_inputs = self._resolve_inputs(request, profile)
        self._validate_repository_binding(request, profile)
        self._validate_packet_binding(request, profile, canonical_inputs)
        provider, model = self._resolve_provider(request, profile)
        effective_budgets = self._resolve_budgets(request, profile)
        self._validate_mode_facts(request)
        self._validate_input_budget(canonical_inputs, effective_budgets)

        if "run_id" in request:
            run_id = str(request["run_id"])
        else:
            seed = str(request["idempotency_seed"]).encode("utf-8")
            run_id = "seed-" + hashlib.sha256(seed).hexdigest()[:24]
        output_schema_path = self.schema_root / str(profile["output_schema"])
        prompt_path = self.contract_root / str(profile["prompt"]["path"])
        return ResolvedRun(
            request=request,
            profile=profile,
            provider=provider,
            model=model,
            effective_budgets=effective_budgets,
            canonical_input_paths={key: str(path) for key, path in canonical_inputs.items()},
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

    def _resolve_inputs(self, request: JsonObject, profile: JsonObject) -> dict[str, Path]:
        path_keys = (
            "packet_path",
            "packet_provenance_path",
            "context_manifest_path",
            "planning_packet_path",
        )
        requested = {key: request["input"][key] for key in path_keys if key in request["input"]}
        if not requested:
            return {}

        try:
            repository_root = self.contract_root.resolve(strict=True)
        except OSError:
            raise KernelError(
                "repository_unavailable", "The repository root is unavailable."
            ) from None
        approved_roots: list[Path] = []
        for declared_root in profile["input_policy"]["approved_roots"]:
            try:
                root = (repository_root / str(declared_root)).resolve(strict=True)
            except OSError:
                raise KernelError(
                    "approved_input_root_unavailable",
                    "A profile-approved input root is unavailable.",
                ) from None
            if not root.is_dir() or not root.is_relative_to(repository_root):
                raise KernelError(
                    "invalid_profile_input_root",
                    "A profile-approved input root is invalid.",
                )
            approved_roots.append(root)

        canonical: dict[str, Path] = {}
        for key, raw_value in requested.items():
            raw_path = Path(str(raw_value))
            if ".." in raw_path.parts:
                raise KernelError(
                    "input_path_not_approved",
                    "A declared input path is outside the profile-approved boundary.",
                )
            candidate = raw_path if raw_path.is_absolute() else repository_root / raw_path
            try:
                path = candidate.resolve(strict=True)
                mode = path.stat().st_mode
            except (OSError, RuntimeError):
                raise KernelError(
                    "input_not_found", "A declared input file is unavailable."
                ) from None
            if not any(path.is_relative_to(root) for root in approved_roots):
                raise KernelError(
                    "input_path_not_approved",
                    "A declared input path is outside the profile-approved boundary.",
                )
            if not stat.S_ISREG(mode):
                raise KernelError("input_not_regular", "A declared input must be a regular file.")
            canonical[key] = path
        return canonical

    def _run_git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed git executable and validated SHA arguments
            ["git", *arguments],
            cwd=self.target_root,
            env=_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )

    def _validate_repository_binding(self, request: JsonObject, profile: JsonObject) -> None:
        policy = profile["repository_policy"]
        requested_repository = str(request["repository"]["full_name"])
        expected_repository = str(policy["expected_full_name"])
        if requested_repository.casefold() != expected_repository.casefold():
            raise KernelError(
                "repository_identity_mismatch",
                "Requested repository identity does not match the profile policy.",
            )

        remote = self._run_git("remote", "get-url", str(policy["remote_name"]))
        actual_repository = (
            _github_repository_name(remote.stdout.strip()) if remote.returncode == 0 else None
        )
        if (
            actual_repository is None
            or actual_repository.casefold() != expected_repository.casefold()
        ):
            raise KernelError(
                "repository_identity_mismatch",
                "Configured repository identity does not match the profile policy.",
            )

        head = self._run_git("rev-parse", "--verify", "HEAD^{commit}")
        actual_head = head.stdout.strip() if head.returncode == 0 else ""
        requested_head = str(request["repository"]["head_sha"])
        if actual_head != requested_head:
            raise KernelError(
                "repository_head_mismatch",
                "Requested head SHA does not match the checked-out HEAD.",
            )

        requested_base = str(request["repository"]["base_sha"])
        base = self._run_git("cat-file", "-e", f"{requested_base}^{{commit}}")
        if base.returncode != 0:
            raise KernelError(
                "repository_base_not_found",
                "Requested base SHA is not an available commit.",
            )
        ancestor = self._run_git("merge-base", "--is-ancestor", requested_base, requested_head)
        if ancestor.returncode != 0:
            raise KernelError(
                "repository_base_not_ancestor",
                "Requested base SHA is not an ancestor of the checked-out head.",
            )

    def _validate_packet_binding(
        self,
        request: JsonObject,
        profile: JsonObject,
        canonical_inputs: dict[str, Path],
    ) -> None:
        if request["mode"] == "plan":
            packet = canonical_inputs.get("planning_packet_path")
            manifest = canonical_inputs.get("context_manifest_path")
            if packet is None or manifest is None:
                raise KernelError(
                    "planning_context_required",
                    "Planning requires a frozen packet and context manifest.",
                )
            if file_sha256(packet) != request["input"]["planning_packet_sha256"]:
                raise KernelError(
                    "planning_packet_hash_mismatch",
                    "Planning packet hash does not match the request.",
                )
            if file_sha256(manifest) != request["input"]["context_manifest_sha256"]:
                raise KernelError(
                    "context_manifest_hash_mismatch",
                    "Planning context manifest hash does not match the request.",
                )
            packet_document = load_json_object(packet, kind="planning packet")
            manifest_document = load_json_object(manifest, kind="planning context manifest")
            validate_document(
                packet_document,
                self._load_schema("countyforge-planning-packet.schema.json"),
                kind="planning packet",
            )
            validate_document(
                manifest_document,
                self._load_schema("countyforge-planning-context-manifest.schema.json"),
                kind="planning context manifest",
            )
            repository = request["repository"]
            issue = request["trigger"].get("issue_number")
            expected = {
                "contract_version": 1,
                "run_id": str(request.get("run_id", "")),
                "repository_full_name": repository["full_name"],
                "target_sha": repository["head_sha"],
                "issue_number": issue,
            }
            if packet_document["run_id"] != expected["run_id"]:
                raise KernelError(
                    "planning_provenance_mismatch",
                    "Planning packet is not bound to the requested run.",
                )
            packet_repository = packet_document["repository"]
            if (
                packet_repository["full_name"] != expected["repository_full_name"]
                or packet_repository["target_sha"] != expected["target_sha"]
                or (issue is not None and packet_document["issue"]["number"] != issue)
            ):
                raise KernelError(
                    "planning_provenance_mismatch",
                    "Planning packet does not agree with immutable request facts.",
                )
            if (
                manifest_document["run_id"] != expected["run_id"]
                or manifest_document["repository_full_name"] != expected["repository_full_name"]
                or manifest_document["target_sha"] != expected["target_sha"]
                or (issue is not None and manifest_document["issue_number"] != issue)
                or manifest_document["packet_sha256"] != request["input"]["planning_packet_sha256"]
            ):
                raise KernelError(
                    "planning_provenance_mismatch",
                    "Planning context manifest does not agree with immutable request facts.",
                )
            return
        if request["mode"] != "review":
            return
        packet = canonical_inputs["packet_path"]
        provenance_path = canonical_inputs["packet_provenance_path"]
        if file_sha256(packet) != request["input"]["packet_sha256"]:
            raise KernelError(
                "packet_hash_mismatch", "Review packet hash does not match the request."
            )
        if file_sha256(provenance_path) != request["input"]["packet_provenance_sha256"]:
            raise KernelError(
                "packet_provenance_hash_mismatch",
                "Packet provenance hash does not match the request.",
            )
        provenance = load_json_object(provenance_path, kind="review packet provenance")
        schema_name = profile["input_policy"]["packet_provenance_schema"]
        if schema_name is None:
            raise KernelError(
                "invalid_profile_input_policy",
                "The review profile lacks packet provenance policy.",
            )
        validate_document(
            provenance,
            self._load_schema(str(schema_name)),
            kind="review packet provenance",
        )
        repository_binding = {
            "repository_full_name": request["repository"]["full_name"],
            "base_sha": request["repository"]["base_sha"],
            "head_sha": request["repository"]["head_sha"],
        }
        packet_metadata = _packet_metadata(packet)
        if packet_metadata != {
            "contract_version": 1,
            "builder_id": "repository-review-packet",
            "builder_version": 1,
            **repository_binding,
        }:
            raise KernelError(
                "packet_provenance_mismatch",
                "Packet provenance does not agree with the immutable request.",
            )
        expected = {
            **repository_binding,
            "packet_sha256": request["input"]["packet_sha256"],
            "packet_bytes": packet.stat().st_size,
        }
        if any(provenance[field] != value for field, value in expected.items()):
            raise KernelError(
                "packet_provenance_mismatch",
                "Packet provenance does not agree with the immutable request.",
            )

    def revalidate_execution_context(self, resolved: ResolvedRun) -> None:
        """Recheck mutable host facts immediately before credential selection."""

        canonical_inputs = self._resolve_inputs(resolved.request, resolved.profile)
        current = {key: str(path) for key, path in canonical_inputs.items()}
        if current != resolved.canonical_input_paths:
            raise KernelError(
                "input_binding_changed",
                "A declared input binding changed after request resolution.",
            )
        self._validate_repository_binding(resolved.request, resolved.profile)
        self._validate_packet_binding(resolved.request, resolved.profile, canonical_inputs)

    @staticmethod
    def _validate_input_budget(inputs: dict[str, Path], budgets: JsonObject) -> None:
        total = sum(path.stat().st_size for path in inputs.values())
        if total > int(budgets["max_input_bytes"]):
            raise KernelError(
                "input_budget_exceeded", "Input context exceeds the effective byte budget."
            )
