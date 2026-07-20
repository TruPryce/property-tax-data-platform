"""GitHub-native canonical status, deduplication, and cancellation operations."""

from __future__ import annotations

from countyforge_github.contracts import ControlContracts, JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.state import (
    ACTIVE_STATES,
    check_status,
    decode_marker,
    render_status,
    transition_state,
)

FEEDBACK_MARKER = "<!-- countyforge-feedback:v1 -->"


def find_canonical_state(
    comments: list[JsonObject],
    *,
    trusted_bot_id: int,
    expected_repository_id: int,
    expected_target_type: str,
    expected_target_number: int,
    contracts: ControlContracts | None = None,
) -> tuple[int, JsonObject] | None:
    """Find at most one trusted canonical comment and ignore user forgeries."""

    found: list[tuple[int, JsonObject]] = []
    for comment in comments:
        user = comment.get("user")
        if not isinstance(user, dict):
            continue
        state = decode_marker(
            str(comment.get("body", "")),
            author_id=int(user.get("id", 0)),
            author_type=str(user.get("type", "")),
            trusted_bot_id=trusted_bot_id,
            contracts=contracts,
        )
        if state is not None:
            if (
                state["repository_id"] != expected_repository_id
                or state["target_type"] != expected_target_type
                or state["target_number"] != expected_target_number
            ):
                raise ControlPlaneError(
                    "canonical_target_mismatch",
                    "Canonical CountyForge state belongs to another target.",
                )
            found.append((int(comment["id"]), state))
    if len(found) > 1:
        raise ControlPlaneError(
            "multiple_canonical_comments", "CountyForge canonical state is ambiguous."
        )
    return found[0] if found else None


def upsert_canonical_status(
    github: GitHubPort,
    *,
    repository: str,
    target_number: int,
    trusted_bot_id: int,
    state: JsonObject,
    expected_state: JsonObject | None,
) -> JsonObject:
    """Create once or compare/re-read immediately before a canonical state write."""

    body = render_status(state)
    existing = find_canonical_state(
        github.list_comments(repository, target_number),
        trusted_bot_id=trusted_bot_id,
        expected_repository_id=int(state["repository_id"]),
        expected_target_type=str(state["target_type"]),
        expected_target_number=target_number,
    )
    if existing is None:
        if expected_state is not None:
            raise ControlPlaneError(
                "state_write_conflict", "Canonical CountyForge state changed before publication."
            )
        return github.create_comment(repository, target_number, body)
    if expected_state is None:
        raise ControlPlaneError(
            "state_write_conflict", "Canonical CountyForge state changed before publication."
        )
    comment = github.get_comment(repository, existing[0])
    user = comment.get("user")
    if not isinstance(user, dict):
        raise ControlPlaneError(
            "state_write_conflict", "Canonical CountyForge state changed before publication."
        )
    current = decode_marker(
        str(comment.get("body", "")),
        author_id=int(user.get("id", 0)),
        author_type=str(user.get("type", "")),
        trusted_bot_id=trusted_bot_id,
    )
    if current is None or canonical_bytes(current) != canonical_bytes(expected_state):
        raise ControlPlaneError(
            "state_write_conflict", "Canonical CountyForge state changed before publication."
        )
    return github.update_comment(repository, existing[0], body)


def update_check_for_state(github: GitHubPort, repository: str, state: JsonObject) -> None:
    """Publish one sanitized check state whenever canonical lifecycle changes."""

    check_id = state["check_run_id"]
    if check_id is None:
        return
    status, conclusion = check_status(str(state["lifecycle_state"]))
    payload: JsonObject = {
        "status": status,
        "output": {
            "title": f"CountyForge {state['command']}: {state['lifecycle_state']}",
            "summary": "CountyForge status is published from sanitized canonical state.",
        },
    }
    if conclusion is not None:
        payload["conclusion"] = conclusion
    github.update_check(repository, int(check_id), payload)


def publish_canonical_state(
    github: GitHubPort,
    *,
    repository: str,
    target_number: int,
    trusted_bot_id: int,
    expected_state: JsonObject | None,
    state: JsonObject,
) -> JsonObject:
    """Compare/publish canonical comment state and mirror its existing PR check."""

    comment = upsert_canonical_status(
        github,
        repository=repository,
        target_number=target_number,
        trusted_bot_id=trusted_bot_id,
        state=state,
        expected_state=expected_state,
    )
    update_check_for_state(github, repository, state)
    return comment


def upsert_control_feedback(
    github: GitHubPort,
    *,
    repository: str,
    target_number: int,
    trusted_bot_id: int,
    message: str,
) -> JsonObject:
    """Reuse one bounded bot-owned feedback comment for non-execution outcomes."""

    body = f"{message}\n\n{FEEDBACK_MARKER}"
    for comment in github.list_comments(repository, target_number):
        user = comment.get("user")
        if (
            isinstance(user, dict)
            and int(user.get("id", 0)) == trusted_bot_id
            and str(user.get("type", "")) == "Bot"
            and FEEDBACK_MARKER in str(comment.get("body", ""))
        ):
            return github.update_comment(repository, int(comment["id"]), body)
    return github.create_comment(repository, target_number, body)


def is_duplicate(existing: JsonObject | None, idempotency_key: str) -> bool:
    """Semantic identities remain duplicates even after a terminal outcome."""

    if existing is None:
        return False
    if existing["idempotency_key"] == idempotency_key:
        return True
    return any(item["idempotency_key"] == idempotency_key for item in existing["history"])


def request_cancellation(
    github: GitHubPort,
    *,
    repository: str,
    repository_id: int,
    target_type: str,
    target_number: int,
    state: JsonObject,
    at: str,
) -> JsonObject:
    """Cancel only the exact active CountyForge execution owned by this target."""

    if (
        state["repository_id"] != repository_id
        or state["target_type"] != target_type
        or state["target_number"] != target_number
    ):
        raise ControlPlaneError(
            "cancellation_target_mismatch", "Cancellation target does not own this run."
        )
    if state["lifecycle_state"] == "cancel_requested":
        return state
    if state["lifecycle_state"] == "cancelled":
        return state
    if state["lifecycle_state"] not in ACTIVE_STATES:
        raise ControlPlaneError(
            "cancellation_not_active", "No active CountyForge run can be cancelled."
        )
    run_id = state["workflow_run_id"]
    if run_id is None:
        raise ControlPlaneError(
            "cancellation_run_unclaimed", "The active CountyForge workflow is not yet claimable."
        )
    workflow = github.workflow_run(repository, int(run_id))
    workflow_repository = workflow.get("repository")
    actual_repository_id = (
        int(workflow_repository.get("id", 0)) if isinstance(workflow_repository, dict) else 0
    )
    if (
        int(workflow.get("id", 0)) != run_id
        or actual_repository_id != repository_id
        or str(workflow.get("event", "")) != "workflow_dispatch"
        or str(workflow.get("path", "")) != ".github/workflows/countyforge-run.yml"
        or str(workflow.get("display_title", "")).find(str(state["run_id"])) < 0
    ):
        raise ControlPlaneError(
            "cancellation_workflow_mismatch",
            "Workflow run is not owned by this CountyForge target.",
        )
    updated = transition_state(
        state,
        {
            "contract_version": 1,
            "from": state["lifecycle_state"],
            "to": "cancel_requested",
            "at": at,
            "reason_code": "cancellation_requested",
        },
    )
    github.cancel_workflow(repository, int(run_id))
    return updated
