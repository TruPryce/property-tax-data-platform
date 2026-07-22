"""Immutable trigger and semantic identity construction."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from countyforge_github.contracts import ControlContracts, JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError


def iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_trigger(
    *,
    event: JsonObject,
    command: JsonObject,
    authorization: JsonObject,
    target: JsonObject,
    trusted_tool_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    delivery_id: str | None = None,
    planning_context_sha256: str | None = None,
    implementation_change_sha256: str | None = None,
    timestamp: str | None = None,
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Construct the bounded immutable trigger envelope from resolved facts."""

    repository = event.get("repository")
    comment = event.get("comment")
    if not isinstance(repository, dict) or not isinstance(comment, dict):
        raise ControlPlaneError("invalid_event", "GitHub event facts are incomplete.")
    if event.get("action") != "created":
        raise ControlPlaneError(
            "invalid_event_action", "Only newly created comments may build a trigger."
        )
    actor = authorization["actor"]
    trigger: JsonObject = {
        "contract_version": 1,
        "repository": {
            "id": int(repository["id"]),
            "full_name": str(repository["full_name"]),
        },
        "target": {
            "type": str(target["type"]),
            "number": int(target["number"]),
            "source_repository": {
                "id": int(target["source_repository"]["id"]),
                "full_name": str(target["source_repository"]["full_name"]),
            },
            "base_sha": str(target["base_sha"]),
            "head_sha": str(target["head_sha"]),
        },
        "comment": {
            "id": int(comment["id"]),
            "event_action": "created",
            "delivery_id": delivery_id,
        },
        "actor": {
            "login": str(actor["login"]),
            "id": int(actor["id"]),
            "type": str(actor["type"]),
        },
        "authorization": {
            "permission": str(authorization["permission"]),
            "policy_version": int(authorization["policy_version"]),
            "outcome": str(authorization["outcome"]),
            "reason_code": str(authorization["reason_code"]),
        },
        "command": command,
        "trusted_tool_sha": trusted_tool_sha,
        "workflow": {"run_id": workflow_run_id, "run_attempt": workflow_run_attempt},
        "timestamp": timestamp or iso_now(),
    }
    if planning_context_sha256 is not None:
        trigger["planning_context_sha256"] = planning_context_sha256
    if implementation_change_sha256 is not None:
        trigger["implementation_change_sha256"] = implementation_change_sha256
    issue = event.get("issue")
    if isinstance(issue, dict):
        metadata: JsonObject = {}
        if isinstance(issue.get("title"), str):
            metadata["title"] = str(issue["title"])[:256]
        if isinstance(issue.get("html_url"), str):
            metadata["url"] = str(issue["html_url"])[:1024]
        if metadata:
            trigger["display_metadata"] = metadata
    resolved = contracts or ControlContracts()
    resolved.validate("trigger", trigger)
    if trigger["authorization"]["outcome"] != "allowed":
        raise ControlPlaneError(
            "authorization_denied",
            "CountyForge command authorization was denied.",
            exit_code=3,
        )
    return trigger


def semantic_idempotency_key(
    trigger: JsonObject,
    execution_policy: JsonObject,
) -> str:
    """Hash semantic command facts and exclude webhook delivery identity."""

    command = str(trigger["command"]["command"])
    if command not in execution_policy["commands"]:
        raise ControlPlaneError(
            "not_execution_command", "The selected command has no runner execution identity."
        )
    selection = execution_policy["commands"][command]
    facts: JsonObject = {
        "contract_version": 1,
        "repository_id": trigger["repository"]["id"],
        "target_type": trigger["target"]["type"],
        "target_number": trigger["target"]["number"],
        "command": command,
        "arguments": trigger["command"]["arguments"],
        "profile_id": selection["profile_id"],
        "profile_version": selection["profile_version"],
        "target_head_sha": trigger["target"]["head_sha"],
    }
    if command == "plan" and "planning_context_sha256" in trigger:
        facts["planning_context_sha256"] = trigger["planning_context_sha256"]
    if command == "implement" and "implementation_change_sha256" in trigger:
        facts["implementation_change_sha256"] = trigger["implementation_change_sha256"]
    return hashlib.sha256(canonical_bytes(facts)).hexdigest()


def retry_idempotency_key(original_key: str, attempt: int) -> str:
    """Create an explicit retry identity without changing the original key."""

    return hashlib.sha256(
        canonical_bytes(
            {"contract_version": 1, "original_idempotency_key": original_key, "attempt": attempt}
        )
    ).hexdigest()


def effective_idempotency_key(
    trigger: JsonObject,
    execution_policy: JsonObject,
) -> str:
    """Resolve a first attempt or explicit retry to its dispatch identity."""

    original_key = semantic_idempotency_key(trigger, execution_policy)
    retry = trigger.get("retry")
    if retry is None:
        return original_key
    if not isinstance(retry, dict):
        raise ControlPlaneError("invalid_retry", "Retry provenance is invalid.")
    if retry["original_idempotency_key"] != original_key:
        raise ControlPlaneError(
            "retry_identity_mismatch", "Retry provenance does not match the original command."
        )
    attempt = int(retry["attempt"])
    return retry_idempotency_key(original_key, attempt)


def execution_run_id(trigger: JsonObject, execution_policy: JsonObject) -> str:
    """Return the run identifier bound to the effective dispatch identity."""

    key = effective_idempotency_key(trigger, execution_policy)
    retry = trigger.get("retry")
    attempt = int(retry["attempt"]) if isinstance(retry, dict) else 1
    return f"gh-{key[:24]}-a{attempt}"
