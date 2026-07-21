"""Canonical state, transitions, leases, retry, cancellation, and reconciliation."""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import Callable

import pytest
from countyforge_github.contracts import JsonObject
from countyforge_github.control import (
    find_canonical_state,
    is_duplicate,
    request_cancellation,
    upsert_canonical_status,
)
from countyforge_github.errors import ControlPlaneError
from countyforge_github.identity import retry_idempotency_key
from countyforge_github.leases import acquire_lease, heartbeat_lease, mark_expired_stale
from countyforge_github.state import (
    MARKER_PREFIX,
    MARKER_SUFFIX,
    MAX_MARKER_BYTES,
    bump_revision,
    check_status,
    decode_marker,
    encode_marker,
    reconcile_workflow,
    render_status,
    retry_state,
    transition_state,
)


class FakeGitHub:
    """In-memory GitHub port with observable mutations."""

    def __init__(self) -> None:
        self.comments: list[JsonObject] = []
        self.cancelled: list[int] = []
        self.workflow: JsonObject = {}
        self.replace_on_get: JsonObject | None = None

    def repository_permission(self, repository: str, actor: str) -> JsonObject:
        return {"permission": "write", "role_name": "write"}

    def list_comments(self, repository: str, target_number: int) -> list[JsonObject]:
        return copy.deepcopy(self.comments)

    def create_comment(self, repository: str, target_number: int, body: str) -> JsonObject:
        comment: JsonObject = {
            "id": len(self.comments) + 100,
            "body": body,
            "user": {"id": 41898282, "type": "Bot", "login": "github-actions[bot]"},
        }
        self.comments.append(comment)
        return copy.deepcopy(comment)

    def get_comment(self, repository: str, comment_id: int) -> JsonObject:
        comment = next(item for item in self.comments if item["id"] == comment_id)
        # Model a competing state-lane winner that committed just before this reread. The
        # shared countyforge-state-* lane serializes writers, so a loser observes the newer
        # persisted state at reread and its compare-before-write fails closed.
        if self.replace_on_get is not None:
            comment["body"] = render_status(self.replace_on_get)
            self.replace_on_get = None
        return copy.deepcopy(comment)

    def update_comment(self, repository: str, comment_id: int, body: str) -> JsonObject:
        for comment in self.comments:
            if comment["id"] == comment_id:
                comment["body"] = body
                return copy.deepcopy(comment)
        raise AssertionError("comment not found")

    def workflow_run(self, repository: str, run_id: int) -> JsonObject:
        return copy.deepcopy(self.workflow)

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> JsonObject:
        raise AssertionError("not used")

    def cancel_workflow(self, repository: str, run_id: int) -> None:
        self.cancelled.append(run_id)

    def dispatch_workflow(
        self, repository: str, workflow: str, ref: str, inputs: JsonObject
    ) -> None:
        raise AssertionError("not used")

    def create_check(self, repository: str, payload: JsonObject) -> JsonObject:
        return {"id": 1, **payload}

    def update_check(self, repository: str, check_id: int, payload: JsonObject) -> JsonObject:
        return {"id": check_id, **payload}


def _transition(state: JsonObject, target: str, at: str, reason: str) -> JsonObject:
    return transition_state(
        state,
        {
            "contract_version": 1,
            "from": state["lifecycle_state"],
            "to": target,
            "at": at,
            "reason_code": reason,
        },
    )


def test_marker_requires_trusted_bot_identity(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    body = render_status(state)
    assert decode_marker(body, author_id=7, author_type="User", trusted_bot_id=41898282) is None
    assert (
        decode_marker(body, author_id=41898282, author_type="Bot", trusted_bot_id=41898282) == state
    )


def test_legacy_state_without_planning_metadata_remains_readable(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    for field in (
        "planning_revision",
        "planning_change_name",
        "planning_branch",
        "planning_pr_number",
        "planning_predecessor_run_id",
        "planning_context_sha256",
        "planning_result_sha256",
        "implementation_eligible",
    ):
        state.pop(field, None)
    body = render_status(state)
    decoded = decode_marker(body, author_id=41898282, author_type="Bot", trusted_bot_id=41898282)
    assert decoded == state


def test_forged_user_marker_is_ignored(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    comments = [
        {
            "id": 1,
            "body": encode_marker(state),
            "user": {"id": 777, "type": "User", "login": "attacker"},
        }
    ]
    assert (
        find_canonical_state(
            comments,
            trusted_bot_id=41898282,
            expected_repository_id=state["repository_id"],
            expected_target_type=state["target_type"],
            expected_target_number=state["target_number"],
        )
        is None
    )


@pytest.mark.parametrize(
    "body_factory",
    [
        lambda state: f"{MARKER_PREFIX}not+base64{MARKER_SUFFIX}",
        lambda state: f"{encode_marker(state)}\n{encode_marker(state)}",
        lambda state: f"{MARKER_PREFIX}{'A' * (MAX_MARKER_BYTES * 2 + 1)}{MARKER_SUFFIX}",
    ],
)
def test_malformed_or_duplicate_trusted_marker_fails_closed(
    queued_state_factory: Callable[[str], JsonObject],
    body_factory: Callable[[JsonObject], str],
) -> None:
    state = queued_state_factory("review")
    with pytest.raises(ControlPlaneError) as raised:
        decode_marker(
            body_factory(state),
            author_id=41898282,
            author_type="Bot",
            trusted_bot_id=41898282,
        )
    assert raised.value.code in {"invalid_status_marker", "state_too_large"}


def test_schema_invalid_trusted_marker_fails_closed(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    state.pop("command")
    raw = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(ControlPlaneError) as raised:
        decode_marker(
            f"{MARKER_PREFIX}{encoded}{MARKER_SUFFIX}",
            author_id=41898282,
            author_type="Bot",
            trusted_bot_id=41898282,
        )
    assert raised.value.code == "invalid_status_marker"


@pytest.mark.parametrize("field", ["repository_id", "target_type", "target_number"])
def test_canonical_state_must_match_current_repository_target(
    queued_state_factory: Callable[[str], JsonObject], field: str
) -> None:
    expected = queued_state_factory("review")
    mismatched = copy.deepcopy(expected)
    mismatched[field] = {
        "repository_id": 999,
        "target_type": "issue",
        "target_number": 999,
    }[field]
    comments = [
        {
            "id": 1,
            "body": render_status(mismatched),
            "user": {"id": 41898282, "type": "Bot", "login": "github-actions[bot]"},
        }
    ]
    with pytest.raises(ControlPlaneError) as raised:
        find_canonical_state(
            comments,
            trusted_bot_id=41898282,
            expected_repository_id=expected["repository_id"],
            expected_target_type=expected["target_type"],
            expected_target_number=expected["target_number"],
        )
    assert raised.value.code == "canonical_target_mismatch"


def test_status_comment_is_updated_without_spam(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    github = FakeGitHub()
    state = queued_state_factory("review")
    first = upsert_canonical_status(
        github,
        repository="TruPryce/property-tax-data-platform",
        target_number=11,
        trusted_bot_id=41898282,
        state=state,
        expected_state=None,
    )
    updated = copy.deepcopy(state)
    updated = bump_revision(updated, at="2026-07-19T12:00:03Z")
    upsert_canonical_status(
        github,
        repository="TruPryce/property-tax-data-platform",
        target_number=11,
        trusted_bot_id=41898282,
        state=updated,
        expected_state=state,
    )
    assert len(github.comments) == 1
    assert github.comments[0]["id"] == first["id"]


def test_serialized_writers_have_one_state_lane_winner(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    # The shared countyforge-state-* lane runs writers one at a time. The first writer
    # commits; the second rereads the newer persisted state, sees its expected predecessor
    # no longer matches, and fails closed rather than overwriting the winner.
    github = FakeGitHub()
    predecessor = queued_state_factory("review")
    upsert_canonical_status(
        github,
        repository="TruPryce/property-tax-data-platform",
        target_number=11,
        trusted_bot_id=41898282,
        state=predecessor,
        expected_state=None,
    )
    writer_a = _transition(predecessor, "running", "2026-07-19T12:01:00Z", "started")
    writer_b = _transition(predecessor, "preparing", "2026-07-19T12:01:01Z", "preparing")
    upsert_canonical_status(
        github,
        repository="TruPryce/property-tax-data-platform",
        target_number=11,
        trusted_bot_id=41898282,
        state=writer_a,
        expected_state=predecessor,
    )
    with pytest.raises(ControlPlaneError) as raised:
        upsert_canonical_status(
            github,
            repository="TruPryce/property-tax-data-platform",
            target_number=11,
            trusted_bot_id=41898282,
            state=writer_b,
            expected_state=predecessor,
        )
    assert raised.value.code == "state_write_conflict"
    current = decode_marker(
        github.comments[0]["body"],
        author_id=41898282,
        author_type="Bot",
        trusted_bot_id=41898282,
    )
    assert current is not None
    assert current["lifecycle_state"] == "running"
    assert current["revision"] == predecessor["revision"] + 1


def test_stale_predecessor_after_concurrent_win_fails_closed(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    # A writer prepares a transition, but a competing state-lane winner commits a newer
    # state before this writer's reread. Revision/marker stale-detection must refuse the
    # obsolete write so a newer state is never overwritten.
    github = FakeGitHub()
    predecessor = queued_state_factory("review")
    upsert_canonical_status(
        github,
        repository="TruPryce/property-tax-data-platform",
        target_number=11,
        trusted_bot_id=41898282,
        state=predecessor,
        expected_state=None,
    )
    desired = _transition(
        predecessor,
        "cancel_requested",
        "2026-07-19T12:01:00Z",
        "cancellation_requested",
    )
    newer = _transition(predecessor, "preparing", "2026-07-19T12:01:01Z", "preparing")
    github.replace_on_get = newer
    with pytest.raises(ControlPlaneError) as raised:
        upsert_canonical_status(
            github,
            repository="TruPryce/property-tax-data-platform",
            target_number=11,
            trusted_bot_id=41898282,
            state=desired,
            expected_state=predecessor,
        )
    assert raised.value.code == "state_write_conflict"
    current = decode_marker(
        github.comments[0]["body"],
        author_id=41898282,
        author_type="Bot",
        trusted_bot_id=41898282,
    )
    assert current is not None
    assert current["lifecycle_state"] == "preparing"
    assert current["revision"] == newer["revision"]


def test_illegal_transition_and_terminal_mutation_fail(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    with pytest.raises(ControlPlaneError, match="illegal"):
        _transition(state, "authorized", "2026-07-19T12:01:00Z", "moved_backwards")
    running = _transition(state, "running", "2026-07-19T12:01:00Z", "workflow_running")
    succeeded = _transition(running, "succeeded", "2026-07-19T12:02:00Z", "workflow_success")
    with pytest.raises(ControlPlaneError, match="illegal"):
        _transition(succeeded, "running", "2026-07-19T12:03:00Z", "mutate_terminal")


def test_revision_must_match_predecessor_and_advance_once(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    transition = {
        "contract_version": 1,
        "from": "queued",
        "to": "running",
        "at": "2026-07-19T12:01:00Z",
        "reason_code": "workflow_running",
        "expected_revision": state["revision"] + 1,
    }
    with pytest.raises(ControlPlaneError, match="revision"):
        transition_state(state, transition)
    transition["expected_revision"] = state["revision"]
    running = transition_state(state, transition)
    assert running["revision"] == state["revision"] + 1


def test_single_winner_lease_and_heartbeat(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    leased = acquire_lease(
        state,
        owner_workflow_run_id=1001,
        owner_run_attempt=1,
        at="2026-07-19T12:00:03Z",
        ttl_seconds=3600,
        nonce="single-winner-nonce",
    )
    with pytest.raises(ControlPlaneError) as raised:
        acquire_lease(
            leased,
            owner_workflow_run_id=1002,
            owner_run_attempt=1,
            at="2026-07-19T12:00:04Z",
            nonce="losing-race-nonce",
        )
    assert raised.value.code == "lease_held"
    renewed = heartbeat_lease(
        leased,
        owner_workflow_run_id=1001,
        nonce="single-winner-nonce",
        at="2026-07-19T12:10:00Z",
    )
    assert renewed["lease"]["heartbeat_at"] == "2026-07-19T12:10:00Z"


def test_expired_active_lease_becomes_stale_but_terminal_evidence_is_unchanged(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = acquire_lease(
        queued_state_factory("review"),
        owner_workflow_run_id=1001,
        owner_run_attempt=1,
        at="2026-07-19T12:00:03Z",
        ttl_seconds=60,
        nonce="expired-lease-nonce",
    )
    stale = mark_expired_stale(state, at="2026-07-19T12:02:00Z")
    assert stale["lifecycle_state"] == "stale"
    assert stale["lease"] is None
    before = copy.deepcopy(stale)
    assert mark_expired_stale(stale, at="2026-07-20T12:02:00Z") == before


def test_unclaimed_queue_gets_a_bounded_terminal_deadline(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    assert mark_expired_stale(state, at="2026-07-19T12:29:59Z") == state
    failed = mark_expired_stale(state, at="2026-07-19T12:30:00Z")
    assert failed["lifecycle_state"] == "failed"
    assert failed["disposition"] == "workflow_claim_timeout"


def test_retry_preserves_completed_attempt_and_rejects_stale_head(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    running = _transition(state, "running", "2026-07-19T12:01:00Z", "workflow_running")
    failed = _transition(running, "failed", "2026-07-19T12:02:00Z", "workflow_failure")
    retry = retry_state(
        failed,
        current_head_sha=failed["target_head_sha"],
        at="2026-07-19T12:03:00Z",
    )
    assert retry["attempt"] == 2
    assert retry["run_id"] != failed["run_id"]
    assert retry["history"][0]["run_id"] == failed["run_id"]
    assert retry["original_idempotency_key"] == failed["idempotency_key"]
    authorized_retry = _transition(
        retry, "authorized", "2026-07-19T12:04:00Z", "authorization_allowed"
    )
    queued_retry = _transition(
        authorized_retry, "queued", "2026-07-19T12:04:01Z", "workflow_queued"
    )
    running_retry = _transition(queued_retry, "running", "2026-07-19T12:04:02Z", "workflow_running")
    failed_retry = _transition(running_retry, "failed", "2026-07-19T12:05:00Z", "workflow_failure")
    second_retry = retry_state(
        failed_retry,
        current_head_sha=failed_retry["target_head_sha"],
        at="2026-07-19T12:06:00Z",
    )
    assert second_retry["attempt"] == 3
    assert second_retry["idempotency_key"] == retry_idempotency_key(failed["idempotency_key"], 3)
    with pytest.raises(ControlPlaneError) as raised:
        retry_state(failed, current_head_sha="a" * 40, at="2026-07-19T12:03:00Z")
    assert raised.value.code == "retry_stale_head"


def test_cancel_verifies_exact_countyforge_workflow(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    github = FakeGitHub()
    state = copy.deepcopy(queued_state_factory("review"))
    state["workflow_run_id"] = 1001
    github.workflow = {
        "id": 1001,
        "repository": {"id": state["repository_id"]},
        "name": f"CountyForge / review / {state['run_id']}",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {state['run_id']}",
    }
    cancelled = request_cancellation(
        github,
        repository="TruPryce/property-tax-data-platform",
        repository_id=state["repository_id"],
        target_type=state["target_type"],
        target_number=state["target_number"],
        state=state,
        at="2026-07-19T12:05:00Z",
    )
    assert cancelled["lifecycle_state"] == "cancel_requested"
    assert github.cancelled == [1001]


def test_cancel_cannot_target_another_run(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    github = FakeGitHub()
    state = copy.deepcopy(queued_state_factory("review"))
    state["workflow_run_id"] = 1001
    github.workflow = {
        "id": 9999,
        "repository": {"id": state["repository_id"]},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": state["run_id"],
    }
    with pytest.raises(ControlPlaneError):
        request_cancellation(
            github,
            repository="TruPryce/property-tax-data-platform",
            repository_id=state["repository_id"],
            target_type=state["target_type"],
            target_number=state["target_number"],
            state=state,
            at="2026-07-19T12:05:00Z",
        )
    assert github.cancelled == []


def test_workflow_reconciliation_and_check_mapping(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = copy.deepcopy(queued_state_factory("review"))
    state["workflow_run_id"] = 1001
    running = reconcile_workflow(
        state,
        {
            "id": 1001,
            "repository_id": state["repository_id"],
            "name": f"CountyForge / review / {state['run_id']}",
            "event": "workflow_dispatch",
            "path": ".github/workflows/countyforge-run.yml",
            "display_title": state["run_id"],
            "status": "in_progress",
            "conclusion": None,
        },
        "2026-07-19T12:05:00Z",
    )
    assert running["lifecycle_state"] == "running"
    succeeded = reconcile_workflow(
        running,
        {
            "id": 1001,
            "repository_id": state["repository_id"],
            "name": f"CountyForge / review / {state['run_id']}",
            "event": "workflow_dispatch",
            "path": ".github/workflows/countyforge-run.yml",
            "display_title": state["run_id"],
            "status": "completed",
            "conclusion": "success",
        },
        "2026-07-19T12:10:00Z",
    )
    assert succeeded["lifecycle_state"] == "succeeded"
    assert check_status("succeeded") == ("completed", "success")
    assert check_status("not_implemented") == ("completed", "neutral")


def test_workflow_reconciliation_rejects_wrong_path_or_display_identity(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = copy.deepcopy(queued_state_factory("review"))
    state["workflow_run_id"] = 1001
    workflow: JsonObject = {
        "id": 1001,
        "repository_id": state["repository_id"],
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/not-countyforge.yml",
        "display_title": state["run_id"],
        "status": "completed",
        "conclusion": "success",
    }
    with pytest.raises(ControlPlaneError) as wrong_path:
        reconcile_workflow(state, workflow, "2026-07-19T12:10:00Z")
    assert wrong_path.value.code == "workflow_ownership_mismatch"
    workflow["path"] = ".github/workflows/countyforge-run.yml"
    workflow["display_title"] = "CountyForge / review / another-run"
    with pytest.raises(ControlPlaneError) as wrong_display:
        reconcile_workflow(state, workflow, "2026-07-19T12:10:00Z")
    assert wrong_display.value.code == "workflow_ownership_mismatch"


def test_semantic_duplicate_checks_history(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = queued_state_factory("review")
    assert is_duplicate(state, state["idempotency_key"])
    assert not is_duplicate(state, "a" * 64)
