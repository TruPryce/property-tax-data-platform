"""Strict JSON contract loading and canonical hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from countyforge_runner.errors import KernelError

JsonObject = dict[str, Any]


def load_json_object(path: Path, *, kind: str) -> JsonObject:
    """Load a JSON object without surfacing file contents in failures."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise KernelError(
            "invalid_json",
            f"{kind} is not readable valid JSON.",
            {"kind": kind, "error_type": type(error).__name__},
        ) from None
    if not isinstance(value, dict):
        raise KernelError("invalid_json_type", f"{kind} must be a JSON object.", {"kind": kind})
    return value


def validate_document(document: JsonObject, schema: JsonObject, *, kind: str) -> None:
    """Validate against Draft 2020-12 and report only safe structural facts."""

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as error:  # noqa: BLE001 - normalized into a stable failure
        raise KernelError(
            "invalid_schema",
            "A repository JSON Schema is invalid.",
            {"kind": kind, "error_type": type(error).__name__},
        ) from None

    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: (list(item.absolute_path), item.validator or ""),
    )
    if errors:
        validation_error = errors[0]
        pointer = "/" + "/".join(str(part) for part in validation_error.absolute_path)
        raise KernelError(
            "schema_validation_failed",
            f"{kind} does not satisfy its strict contract.",
            {"kind": kind, "path": pointer, "validator": validation_error.validator},
        )


def canonical_bytes(document: JsonObject) -> bytes:
    """Return deterministic UTF-8 bytes for a JSON object."""

    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def document_sha256(document: JsonObject) -> str:
    """Hash the canonical representation of a JSON document."""

    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash a repository contract or prompt file."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise KernelError(
            "contract_file_missing",
            "A declared repository contract file is unavailable.",
            {"name": path.name},
        ) from None
    return digest.hexdigest()
