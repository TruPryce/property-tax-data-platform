"""Strict JSON contract loading and canonical hashing."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from countyforge_runner.errors import KernelError

JsonObject = dict[str, Any]
_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_date_time(value: object) -> bool:
    """Validate the date-time format without jsonschema's optional extras."""

    if not isinstance(value, str) or _RFC3339_DATE_TIME.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


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
        Draft202012Validator(schema, format_checker=_FORMAT_CHECKER).iter_errors(document),
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


def workspace_sha256(root: Path) -> str:
    """Hash a workspace's regular files without including Git metadata.

    The implementation workspace is bound before provider credentials are selected.  Git
    metadata is deliberately excluded because it is kept outside the model mount and can
    change as trusted tooling performs checkout/configuration.  Known interpreter/tool
    caches are also excluded because deterministic gates create them as normal runtime
    state; all publishable source files remain part of the hash. Symlinks and non-regular
    files fail closed rather than becoming ambiguous input.
    """

    try:
        resolved = root.resolve(strict=True)
    except OSError:
        raise KernelError(
            "workspace_unavailable", "The implementation workspace is unavailable."
        ) from None
    if not resolved.is_dir():
        raise KernelError("workspace_unavailable", "The implementation workspace is unavailable.")
    volatile_parts = {
        ".git",
        ".venv",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
    volatile_files = {
        Path(".ai/reviews/review-packet.md"),
        Path(".ai/reviews/review-packet.provenance.json"),
    }
    entries: list[JsonObject] = []
    for path in sorted(resolved.rglob("*")):
        relative = path.relative_to(resolved)
        if any(part in volatile_parts for part in relative.parts):
            continue
        if relative in volatile_files:
            continue
        if path.is_symlink() or (path.exists() and not path.is_file() and not path.is_dir()):
            raise KernelError(
                "workspace_binding_invalid",
                "The implementation workspace contains unsafe metadata.",
            )
        if path.is_dir():
            continue
        if not path.exists():
            continue
        raw = path.read_bytes()
        entries.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        )
    return hashlib.sha256(canonical_bytes({"files": entries})).hexdigest()
