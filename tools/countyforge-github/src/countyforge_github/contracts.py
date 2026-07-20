"""Load strict repository-owned GitHub control-plane contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from countyforge_runner.contracts import (
    canonical_bytes,
    document_sha256,
    load_json_object,
    validate_document,
)
from countyforge_runner.paths import find_repo_root
from jsonschema import Draft202012Validator

from countyforge_github.errors import ControlPlaneError

JsonObject = dict[str, Any]


class ControlContracts:
    """Resolved schemas and versioned policies from one trusted contract root."""

    def __init__(self, contract_root: Path | None = None) -> None:
        self.contract_root = find_repo_root(contract_root)
        schema_root = self.contract_root / ".ai" / "schemas"
        policy_root = self.contract_root / ".ai" / "policies"
        names = (
            "command",
            "trigger",
            "authorization-policy",
            "execution-policy",
            "state",
            "lease",
            "transition",
            "event",
        )
        self.schemas = {
            name: load_json_object(
                schema_root / f"countyforge-github-{name}.schema.json",
                kind=f"GitHub control schema {name}",
            )
            for name in names
        }
        for name, schema in self.schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as error:  # noqa: BLE001 - normalized safe contract failure
                raise ControlPlaneError(
                    "invalid_schema",
                    "A GitHub control-plane JSON Schema is invalid.",
                    {"name": name, "error_type": type(error).__name__},
                ) from None
        self.authorization_policy = load_json_object(
            policy_root / "countyforge-github-authorization.v1.json",
            kind="GitHub authorization policy",
        )
        self.execution_policy = load_json_object(
            policy_root / "countyforge-github-execution.v1.json",
            kind="GitHub execution policy",
        )
        self.validate("authorization-policy", self.authorization_policy)
        self.validate("execution-policy", self.execution_policy)

    def validate(self, name: str, document: JsonObject) -> None:
        """Validate one document against its strict repository schema."""

        validate_document(document, self.schemas[name], kind=f"GitHub {name}")


__all__ = [
    "ControlContracts",
    "JsonObject",
    "canonical_bytes",
    "document_sha256",
    "load_json_object",
]
