"""No-network intake, dispatch, control-operation, and workflow-stage fixtures."""

from __future__ import annotations

import base64
import copy
import json
import subprocess
from collections.abc import Callable

import pytest
from countyforge_github.contracts import ControlContracts, JsonObject
from countyforge_github.errors import ControlPlaneError
from countyforge_github.identity import effective_idempotency_key
from countyforge_github.leases import acquire_lease
from countyforge_github.maintenance import audit_expired_leases
from countyforge_github.orchestrator import process_intake
from countyforge_github.state import decode_marker, render_status, transition_state
from countyforge_github.workflow_control import (
    advance_run,
    claim_run,
    fail_unclaimed_run,
    verify_publication_lease,
)

BOT_ID = 41898282


class FakeGitHub:
    def __init__(self, head_sha: str) -> None:
        self.permission: JsonObject = {"permission": "write", "role_name": "write"}
        self.pull: JsonObject = {
            "base": {"sha": head_sha},
            "head": {
                "sha": head_sha,
                "repo": {
                    "id": 987654,
                    "full_name": "TruPryce/property-tax-data-platform",
                },
            },
        }
        self.comments: list[JsonObject] = []
        self.checks: list[JsonObject] = []
        self.dispatches: list[JsonObject] = []
        self.cancelled: list[int] = []
        self.workflow: JsonObject = {}
        self.replace_on_get: JsonObject | None = None
        self.fail_next_comment_update = False
        self.fail_check_creation = False
        self.fail_target_resolution = False

    def repository_permission(self, repository: str, actor: str) -> JsonObject:
        return copy.deepcopy(self.permission)

    def list_comments(self, repository: str, target_number: int) -> list[JsonObject]:
        return copy.deepcopy(self.comments)

    def list_repository_comments(self, repository: str) -> list[JsonObject]:
        return copy.deepcopy(self.comments)

    def get_comment(self, repository: str, comment_id: int) -> JsonObject:
        comment = next(item for item in self.comments if item["id"] == comment_id)
        if self.replace_on_get is not None:
            comment["body"] = render_status(self.replace_on_get)
            self.replace_on_get = None
        return copy.deepcopy(comment)

    def pull_request(self, repository: str, number: int) -> JsonObject:
        if self.fail_target_resolution:
            raise ControlPlaneError("github_api_unavailable", "GitHub API is unavailable.")
        return copy.deepcopy(self.pull)

    def compare_commits(self, repository: str, base_sha: str, head_sha: str) -> JsonObject:
        if self.fail_target_resolution:
            raise ControlPlaneError("github_api_unavailable", "GitHub API is unavailable.")
        return {"merge_base_commit": {"sha": self.pull["base"]["sha"]}}

    def create_comment(self, repository: str, target_number: int, body: str) -> JsonObject:
        comment: JsonObject = {
            "id": 100 + len(self.comments),
            "body": body,
            "user": {"id": BOT_ID, "type": "Bot", "login": "github-actions[bot]"},
        }
        self.comments.append(comment)
        return copy.deepcopy(comment)

    def update_comment(self, repository: str, comment_id: int, body: str) -> JsonObject:
        if self.fail_next_comment_update:
            self.fail_next_comment_update = False
            raise ControlPlaneError("github_api_error", "GitHub API request failed.")
        comment = next(item for item in self.comments if item["id"] == comment_id)
        comment["body"] = body
        return copy.deepcopy(comment)

    def workflow_run(self, repository: str, run_id: int) -> JsonObject:
        return copy.deepcopy(self.workflow)

    def cancel_workflow(self, repository: str, run_id: int) -> None:
        self.cancelled.append(run_id)

    def dispatch_workflow(
        self, repository: str, workflow: str, ref: str, inputs: JsonObject
    ) -> None:
        self.dispatches.append(
            {"repository": repository, "workflow": workflow, "ref": ref, "inputs": inputs}
        )

    def create_check(self, repository: str, payload: JsonObject) -> JsonObject:
        if self.fail_check_creation:
            raise ControlPlaneError("github_api_error", "GitHub API request failed.")
        check: JsonObject = {"id": 500 + len(self.checks), **copy.deepcopy(payload)}
        self.checks.append(check)
        return copy.deepcopy(check)

    def update_check(self, repository: str, check_id: int, payload: JsonObject) -> JsonObject:
        check = next(item for item in self.checks if item["id"] == check_id)
        check.update(copy.deepcopy(payload))
        return copy.deepcopy(check)


@pytest.fixture
def head_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _intake(
    github: FakeGitHub,
    event: JsonObject,
    head_sha: str,
    *,
    at: str = "2026-07-19T12:00:00Z",
) -> JsonObject:
    return process_intake(
        event,
        github,
        trusted_tool_sha=head_sha,
        workflow_run_id=700,
        workflow_run_attempt=1,
        default_branch="main",
        trusted_bot_id=BOT_ID,
        delivery_id="delivery-1",
        at=at,
    )


def _canonical(github: FakeGitHub) -> tuple[int, JsonObject]:
    comment = next(item for item in github.comments if "countyforge-status:v1" in item["body"])
    state = decode_marker(
        str(comment["body"]), author_id=BOT_ID, author_type="Bot", trusted_bot_id=BOT_ID
    )
    assert state is not None
    return int(comment["id"]), state


def _assert_authorization(result: JsonObject, outcome: str) -> None:
    authorization = result["authorization"]
    assert set(authorization) == {
        "actor",
        "permission",
        "policy_version",
        "outcome",
        "reason_code",
    }
    assert set(authorization["actor"]) == {"login", "id", "type"}
    assert authorization["outcome"] == outcome
    assert authorization["policy_version"] == 1
    serialized_metrics = "\n".join(result["metrics"])
    assert str(authorization["actor"]["id"]) not in serialized_metrics
    assert authorization["actor"]["login"] not in serialized_metrics


def test_unauthorized_actor_never_dispatches_or_creates_check(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    github.permission = {"permission": "read", "role_name": "read"}
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    assert result["status"] == "denied"
    _assert_authorization(result, "denied")
    assert github.dispatches == []
    assert github.checks == []
    assert all("countyforge-status:v1" not in item["body"] for item in github.comments)
    repeated = _intake(github, event_factory("/countyforge review"), head_sha)
    assert repeated["status"] == "denied"
    assert len([item for item in github.comments if "countyforge-feedback:v1" in item["body"]]) == 1


def test_authorized_review_dispatches_once_and_deduplicates(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    event = event_factory("/countyforge review")
    first = _intake(github, event, head_sha)
    assert first["status"] == "dispatched"
    _assert_authorization(first, "allowed")
    assert [item["event_type"] for item in first["events"]] == [
        "command_received",
        "authorization_decided",
        "workflow_dispatched",
    ]
    assert all("actor" not in metric for metric in first["metrics"])
    assert len(github.dispatches) == 1
    assert len(github.checks) == 1
    duplicate = copy.deepcopy(event)
    duplicate["comment"]["id"] = 999
    second = _intake(github, duplicate, head_sha, at="2026-07-19T12:01:00Z")
    assert second["status"] == "duplicate"
    _assert_authorization(second, "allowed")
    assert len(github.dispatches) == 1
    assert len([item for item in github.comments if "countyforge-status:v1" in item["body"]]) == 1


def test_planning_context_change_creates_new_identity_after_terminal_run(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    first_event = event_factory("/countyforge plan")
    first_event["issue"].pop("pull_request")
    first_event["issue"]["title"] = "Feature: bounded planning"
    first_event["issue"]["body"] = "Problem: one. Outcome: plan one."
    first = _intake(github, first_event, head_sha)
    comment_id, queued = _canonical(github)
    assert queued["planning_context_sha256"]
    failed = transition_state(
        queued,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "failed",
            "at": "2026-07-19T12:01:00Z",
            "reason_code": "planning_fixture_failure",
        },
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(failed))
    changed = copy.deepcopy(first_event)
    changed["comment"]["id"] = 999
    changed["issue"]["body"] = "Problem: two. Outcome: plan two."
    second = _intake(github, changed, head_sha, at="2026-07-19T12:02:00Z")
    assert second["status"] == "dispatched"
    assert second["idempotency_key"] != first["idempotency_key"]


def test_check_creation_failure_makes_published_queue_retryable(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    github.fail_check_creation = True
    with pytest.raises(ControlPlaneError):
        _intake(github, event_factory("/countyforge review"), head_sha)
    _, state = _canonical(github)
    assert state["lifecycle_state"] == "failed"
    assert state["disposition"] == "check_initialization_failed"
    assert github.dispatches == []
    assert github.checks == []


def test_check_id_publication_failure_concludes_created_check(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    github.fail_next_comment_update = True
    with pytest.raises(ControlPlaneError):
        _intake(github, event_factory("/countyforge review"), head_sha)
    _, state = _canonical(github)
    assert state["lifecycle_state"] == "failed"
    assert state["check_run_id"] == github.checks[0]["id"]
    assert github.checks[0]["status"] == "completed"
    assert github.checks[0]["conclusion"] == "failure"
    assert github.dispatches == []


def test_status_recovers_dispatch_that_never_claimed_a_lease(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    status_event = event_factory("/countyforge status")
    status_event["comment"]["id"] = 901
    result = _intake(github, status_event, head_sha, at="2026-07-19T12:31:00Z")
    assert result["state"] == "failed"
    _, state = _canonical(github)
    assert state["disposition"] == "workflow_claim_timeout"
    assert github.checks[0]["status"] == "completed"
    assert github.checks[0]["conclusion"] == "failure"


def test_fork_target_is_recorded_as_untrusted_source_without_changing_base_identity(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    github.pull["head"]["repo"] = {"id": 7654321, "full_name": "fork-owner/fork-repo"}
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    encoded_trigger = str(github.dispatches[0]["inputs"]["trigger"])
    trigger: JsonObject = json.loads(
        base64.urlsafe_b64decode(encoded_trigger + "=" * (-len(encoded_trigger) % 4))
    )
    assert result["status"] == "dispatched"
    assert trigger["repository"]["full_name"] == "TruPryce/property-tax-data-platform"
    assert trigger["target"]["source_repository"] == {
        "id": 7654321,
        "full_name": "fork-owner/fork-repo",
    }


def test_status_starts_no_work_and_reconciles_owned_workflow(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    no_run = _intake(github, event_factory("/countyforge status"), head_sha)
    assert no_run["status"] == "no_run"
    _assert_authorization(no_run, "allowed")
    assert github.dispatches == []
    assert github.checks == []

    review_event = event_factory("/countyforge review")
    review_event["comment"]["id"] = 124
    dispatched = _intake(github, review_event, head_sha, at="2026-07-19T12:01:00Z")
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=dispatched["idempotency_key"],
        run_id=dispatched["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:02:00Z",
        nonce="status-owned-nonce",
    )
    github.workflow = {
        "id": 800,
        "repository": {"id": 987654},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {dispatched['run_id']}",
        "status": "in_progress",
        "conclusion": None,
    }
    status_event = event_factory("/countyforge status")
    status_event["comment"]["id"] = 125
    reconciled = _intake(github, status_event, head_sha, at="2026-07-19T12:03:00Z")
    assert {key: reconciled[key] for key in ("ok", "status", "state")} == {
        "ok": True,
        "status": "reconciled",
        "state": "running",
    }
    assert reconciled["events"][-1]["event_type"] == "state_reconciled"
    _assert_authorization(reconciled, "allowed")
    assert len(github.dispatches) == 1
    assert len([item for item in github.comments if "countyforge-status:v1" in item["body"]]) == 1


def test_status_does_not_require_mutable_pull_request_head_resolution(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    github.fail_target_resolution = True
    result = _intake(github, event_factory("/countyforge status"), head_sha)
    assert result["status"] == "no_run"
    _assert_authorization(result, "allowed")


def test_status_preserves_cancel_requested_while_workflow_is_running(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="status-cancel-nonce",
    )
    github.workflow = {
        "id": 800,
        "repository": {"id": 987654},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {result['run_id']}",
        "status": "in_progress",
        "conclusion": None,
    }
    cancel_event = event_factory("/countyforge cancel")
    cancel_event["comment"]["id"] = 211
    assert _intake(github, cancel_event, head_sha)["status"] == "cancel_requested"
    status_event = event_factory("/countyforge status")
    status_event["comment"]["id"] = 212
    reconciled = _intake(github, status_event, head_sha)
    assert reconciled["state"] == "cancel_requested"


def test_status_terminal_reconciliation_concludes_existing_check(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="status-terminal-nonce",
    )
    github.workflow = {
        "id": 800,
        "repository": {"id": 987654},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {result['run_id']}",
        "status": "completed",
        "conclusion": "success",
    }
    status_event = event_factory("/countyforge status")
    status_event["comment"]["id"] = 213
    reconciled = _intake(github, status_event, head_sha, at="2026-07-19T12:03:00Z")
    assert reconciled["state"] == "succeeded"
    assert github.checks[0]["status"] == "completed"
    assert github.checks[0]["conclusion"] == "success"


def test_changed_head_produces_new_eligible_identity_after_terminal_run(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    event = event_factory("/countyforge review")
    first = _intake(github, event, head_sha)
    comment_id, state = _canonical(github)
    failed = transition_state(
        state,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "failed",
            "at": "2026-07-19T12:01:00Z",
            "reason_code": "synthetic_failure",
        },
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(failed))
    github.pull["head"]["sha"] = "a" * 40
    changed = copy.deepcopy(event)
    changed["comment"]["id"] = 777
    second = _intake(github, changed, head_sha, at="2026-07-19T12:02:00Z")
    assert second["status"] == "dispatched"
    assert second["idempotency_key"] != first["idempotency_key"]
    assert len(github.dispatches) == 2


def test_implementation_requires_an_originating_issue_before_dispatch(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge implement"), head_sha)
    assert result["status"] == "refused"
    assert result["disposition"] == "implement_requires_issue"
    assert github.dispatches == []


def test_authorized_refusals_are_visible_and_reuse_feedback_comment(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    cancel = _intake(github, event_factory("/countyforge cancel"), head_sha)
    retry_event = event_factory("/countyforge retry")
    retry_event["comment"]["id"] = 902
    retry = _intake(github, retry_event, head_sha)
    assert cancel["disposition"] == "no_run_found"
    assert retry["disposition"] == "no_run_found"
    _assert_authorization(cancel, "allowed")
    _assert_authorization(retry, "allowed")
    feedback = [item for item in github.comments if "countyforge-feedback:v1" in item["body"]]
    assert len(feedback) == 1
    assert "No CountyForge run found" in feedback[0]["body"]


def test_issue_review_is_refused_before_paid_dispatch(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    event = event_factory("/countyforge review")
    event["issue"].pop("pull_request")
    result = _intake(github, event, head_sha)
    assert result["disposition"] == "review_requires_pull_request"
    _assert_authorization(result, "allowed")
    assert github.dispatches == []
    assert github.checks == []


def test_plan_is_refused_on_pull_request_targets_before_paid_dispatch(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge plan"), head_sha)
    assert result["disposition"] == "plan_requires_issue"
    _assert_authorization(result, "allowed")
    assert github.dispatches == []
    assert github.checks == []


def test_claim_and_terminal_publication_keep_one_status_comment(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge validate"), head_sha)
    comment_id, state = _canonical(github)
    claimed = claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="workflow-owned-nonce",
    )
    assert claimed["lifecycle_state"] == "preparing"
    published = advance_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        nonce="workflow-owned-nonce",
        target_state="not_implemented",
        at="2026-07-19T12:02:00Z",
        disposition="profile_not_implemented",
        evidence_url="https://github.com/TruPryce/property-tax-data-platform/actions/runs/800",
    )
    assert published["lifecycle_state"] == "not_implemented"
    assert github.checks[0]["conclusion"] == "neutral"
    assert len([item for item in github.comments if "countyforge-status:v1" in item["body"]]) == 1
    assert state["run_id"] == published["run_id"]


def test_implementation_terminal_publication_records_branch_and_task_counts(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    """Trusted publication metadata is retained in the canonical state."""

    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge validate"), head_sha)
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=801,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="implementation-publication-nonce",
    )
    published = advance_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=801,
        nonce="implementation-publication-nonce",
        target_state="succeeded",
        at="2026-07-19T12:02:00Z",
        disposition="completed",
        implementation_change_name="add-safe-change",
        implementation_revision=2,
        implementation_branch="countyforge/implement/issue-7-add-safe-change-r2",
        implementation_pr_number=123,
        implementation_completed_task_count=3,
        implementation_incomplete_task_count=1,
        implementation_blocked_task_count=0,
    )
    assert published["implementation_branch"] == "countyforge/implement/issue-7-add-safe-change-r2"
    assert published["implementation_pr_number"] == 123
    assert published["implementation_completed_task_count"] == 3
    assert published["implementation_incomplete_task_count"] == 1


def test_owner_cannot_publish_terminal_result_after_lease_expiry(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    # An expired lease means the owner is no longer the sole writer: an out-of-lane
    # maintenance reclaim may already have marked the run stale, and a plain
    # reread/compare/PATCH cannot atomically settle that race. Publication must therefore
    # fail closed once the lease has expired, leaving stale reclamation as the only recovery.
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    claimed = claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="expired-owner-nonce",
    )
    claimed["lifecycle_state"] = "running"
    claimed["lease"]["expires_at"] = "2026-07-19T12:02:00Z"
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(claimed))
    with pytest.raises(ControlPlaneError) as raised:
        advance_run(
            github,
            repository="TruPryce/property-tax-data-platform",
            status_comment_id=comment_id,
            trusted_bot_id=BOT_ID,
            idempotency_key=result["idempotency_key"],
            run_id=result["run_id"],
            workflow_run_id=800,
            nonce="expired-owner-nonce",
            target_state="succeeded",
            at="2026-07-19T12:03:00Z",
            disposition="completed",
            evidence_url="https://github.com/TruPryce/property-tax-data-platform/actions/runs/800",
        )
    assert raised.value.code == "lease_expired"
    # The canonical run remains recoverable as running; nothing was overwritten.
    _, current = _canonical(github)
    assert current["lifecycle_state"] == "running"


def test_publication_preflight_requires_owned_live_running_lease(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    event = event_factory("/countyforge plan")
    event["issue"].pop("pull_request")
    event["issue"]["title"] = "Feature: bounded planning"
    event["issue"]["body"] = "Problem: planning is missing. Outcome: create a plan."
    event["issue"]["labels"] = []
    result = _intake(github, event, head_sha)
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="planning-publication-nonce",
    )
    running = advance_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        nonce="planning-publication-nonce",
        target_state="running",
        at="2026-07-19T12:01:01Z",
        disposition="workflow_running",
    )
    verified = verify_publication_lease(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        nonce="planning-publication-nonce",
        at="2026-07-19T12:02:00Z",
    )
    assert verified["revision"] == running["revision"]
    cancelled = copy.deepcopy(running)
    cancelled["lifecycle_state"] = "cancel_requested"
    github.update_comment(
        "TruPryce/property-tax-data-platform", comment_id, render_status(cancelled)
    )
    with pytest.raises(ControlPlaneError, match="no longer active"):
        verify_publication_lease(
            github,
            repository="TruPryce/property-tax-data-platform",
            status_comment_id=comment_id,
            trusted_bot_id=BOT_ID,
            idempotency_key=result["idempotency_key"],
            run_id=result["run_id"],
            workflow_run_id=800,
            nonce="planning-publication-nonce",
            at="2026-07-19T12:02:01Z",
        )
    expired = copy.deepcopy(running)
    expired["lease"]["expires_at"] = "2026-07-19T12:01:30Z"
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(expired))
    with pytest.raises(ControlPlaneError, match="live lease"):
        verify_publication_lease(
            github,
            repository="TruPryce/property-tax-data-platform",
            status_comment_id=comment_id,
            trusted_bot_id=BOT_ID,
            idempotency_key=result["idempotency_key"],
            run_id=result["run_id"],
            workflow_run_id=800,
            nonce="planning-publication-nonce",
            at="2026-07-19T12:02:01Z",
        )


def test_preclaim_failure_becomes_retryable_terminal_state(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    failed = fail_unclaimed_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        at="2026-07-19T12:01:00Z",
    )
    assert failed["lifecycle_state"] == "failed"
    assert failed["lease"] is None
    retry_event = event_factory("/countyforge retry")
    retry_event["comment"]["id"] = 913
    retried = _intake(github, retry_event, head_sha, at="2026-07-19T12:02:00Z")
    assert retried["status"] == "dispatched"
    _assert_authorization(retried, "allowed")
    assert retried["run_id"] != result["run_id"]


def test_stale_reclaim_concludes_old_check_before_new_check(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, state = _canonical(github)
    expired = acquire_lease(
        state,
        owner_workflow_run_id=800,
        owner_run_attempt=1,
        at="2026-07-19T12:00:00Z",
        ttl_seconds=60,
        nonce="stale-old-check-nonce",
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(expired))
    next_event = event_factory("/countyforge validate")
    next_event["comment"]["id"] = 914
    result = _intake(github, next_event, head_sha, at="2026-07-19T12:02:00Z")
    assert result["status"] == "dispatched"
    assert len(github.checks) == 2
    assert github.checks[0]["status"] == "completed"
    assert github.checks[0]["conclusion"] == "neutral"
    assert github.checks[1]["status"] == "in_progress"


def test_status_cannot_overwrite_concurrent_claim(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    _, queued = _canonical(github)
    claimed = acquire_lease(
        queued,
        owner_workflow_run_id=800,
        owner_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="concurrent-claim-nonce",
    )
    claimed = transition_state(
        claimed,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "preparing",
            "at": "2026-07-19T12:01:00Z",
            "reason_code": "workflow_claimed",
        },
    )
    github.replace_on_get = claimed
    status_event = event_factory("/countyforge status")
    status_event["comment"]["id"] = 920
    with pytest.raises(ControlPlaneError) as raised:
        _intake(github, status_event, head_sha, at="2026-07-19T12:01:01Z")
    assert raised.value.code == "state_write_conflict"
    assert _canonical(github)[1]["lifecycle_state"] == "preparing"


def test_status_cannot_overwrite_concurrent_terminal_publish(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    _, queued = _canonical(github)
    running = transition_state(
        queued,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "running",
            "at": "2026-07-19T12:01:00Z",
            "reason_code": "workflow_running",
        },
    )
    succeeded = transition_state(
        running,
        {
            "contract_version": 1,
            "from": "running",
            "to": "succeeded",
            "at": "2026-07-19T12:02:00Z",
            "reason_code": "completed",
        },
    )
    github.replace_on_get = succeeded
    status_event = event_factory("/countyforge status")
    status_event["comment"]["id"] = 921
    with pytest.raises(ControlPlaneError) as raised:
        _intake(github, status_event, head_sha, at="2026-07-19T12:02:01Z")
    assert raised.value.code == "state_write_conflict"
    assert _canonical(github)[1]["lifecycle_state"] == "succeeded"


def test_cancel_cannot_overwrite_concurrent_terminal_publish(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    preparing = claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="cancel-publish-race-nonce",
    )
    succeeded = transition_state(
        preparing,
        {
            "contract_version": 1,
            "from": "preparing",
            "to": "succeeded",
            "at": "2026-07-19T12:02:00Z",
            "reason_code": "completed",
        },
    )
    github.workflow = {
        "id": 800,
        "repository": {"id": 987654},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {result['run_id']}",
    }
    github.replace_on_get = succeeded
    cancel_event = event_factory("/countyforge cancel")
    cancel_event["comment"]["id"] = 922
    with pytest.raises(ControlPlaneError) as raised:
        _intake(github, cancel_event, head_sha, at="2026-07-19T12:02:01Z")
    assert raised.value.code == "state_write_conflict"
    assert _canonical(github)[1]["lifecycle_state"] == "succeeded"


def test_maintenance_cannot_overwrite_concurrent_late_publish(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, queued = _canonical(github)
    running = acquire_lease(
        queued,
        owner_workflow_run_id=800,
        owner_run_attempt=1,
        at="2026-07-19T12:00:00Z",
        ttl_seconds=60,
        nonce="maintenance-publish-race",
    )
    running = transition_state(
        running,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "running",
            "at": "2026-07-19T12:00:01Z",
            "reason_code": "workflow_running",
        },
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(running))
    succeeded = transition_state(
        running,
        {
            "contract_version": 1,
            "from": "running",
            "to": "succeeded",
            "at": "2026-07-19T12:02:00Z",
            "reason_code": "completed",
        },
    )
    github.replace_on_get = succeeded
    result = audit_expired_leases(
        github,
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=BOT_ID,
        at="2026-07-19T12:02:01Z",
    )
    assert result["reconciliation_candidates"] == 1
    assert result["marked_stale"] == 0
    assert result["write_conflicts"] == 0
    assert result["mutation"] == "audit_only"
    assert _canonical(github)[1]["lifecycle_state"] == "running"


def test_maintenance_stale_reclaim_blocks_late_owner_terminal_publish(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    # The mirror of the previous race: maintenance (repository-wide lane) reads the same
    # expired running predecessor and marks the run stale first. The owner's late terminal
    # publish must then fail closed on the expired lease instead of overwriting the reclaimed
    # evidence, so a completed reclaim is never silently replaced.
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, queued = _canonical(github)
    running = acquire_lease(
        queued,
        owner_workflow_run_id=800,
        owner_run_attempt=1,
        at="2026-07-19T12:00:00Z",
        ttl_seconds=60,
        nonce="stale-then-publish-race",
    )
    running = transition_state(
        running,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "running",
            "at": "2026-07-19T12:00:01Z",
            "reason_code": "workflow_running",
        },
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(running))

    # Scheduled maintenance only discovers the expired candidate; it cannot write outside
    # the per-target state lane.
    reclaimed = audit_expired_leases(
        github,
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=BOT_ID,
        at="2026-07-19T12:02:00Z",
    )
    assert reclaimed["reconciliation_candidates"] == 1
    assert reclaimed["marked_stale"] == 0
    assert reclaimed["mutation"] == "audit_only"
    assert _canonical(github)[1]["lifecycle_state"] == "running"

    # The owner's late terminal publish fails closed on the expired lease.
    with pytest.raises(ControlPlaneError) as raised:
        advance_run(
            github,
            repository="TruPryce/property-tax-data-platform",
            status_comment_id=comment_id,
            trusted_bot_id=BOT_ID,
            idempotency_key=result["idempotency_key"],
            run_id=result["run_id"],
            workflow_run_id=800,
            nonce="stale-then-publish-race",
            target_state="succeeded",
            at="2026-07-19T12:03:00Z",
            disposition="completed",
            evidence_url="https://github.com/TruPryce/property-tax-data-platform/actions/runs/800",
        )
    assert raised.value.code in {
        "lease_expired",
        "lease_ownership_mismatch",
        "workflow_state_mismatch",
    }
    assert _canonical(github)[1]["lifecycle_state"] == "running"


def test_maintenance_reports_dispatch_that_never_claimed_a_lease(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    result = audit_expired_leases(
        github,
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=BOT_ID,
        at="2026-07-19T12:31:00Z",
    )
    assert result["reconciliation_candidates"] == 1
    assert result["marked_failed"] == 0
    assert result["marked_stale"] == 0
    assert result["mutation"] == "audit_only"
    assert _canonical(github)[1]["lifecycle_state"] == "queued"
    assert github.checks[0].get("conclusion") is None


def test_maintenance_audits_malformed_bot_state_and_continues(head_sha: str) -> None:
    github = FakeGitHub(head_sha)
    github.comments.append(
        {
            "id": 999,
            "body": "<!-- countyforge-status:v1:not+base64 -->",
            "user": {"id": BOT_ID, "type": "Bot", "login": "github-actions[bot]"},
        }
    )
    result = audit_expired_leases(
        github,
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=BOT_ID,
        at="2026-07-19T12:31:00Z",
    )
    assert result["invalid_state"] == 1
    assert result["dispatched"] == 0
    assert result["events"][0]["event_type"] == "invalid_state_detected"
    assert 'command="maintenance"' in result["metrics"][0]


def test_cancel_is_target_bound_and_idempotent_after_request(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="cancel-owned-nonce",
    )
    github.workflow = {
        "id": 800,
        "repository": {"id": 987654},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {result['run_id']}",
    }
    cancel_event = event_factory("/countyforge cancel")
    cancel_event["comment"]["id"] = 222
    cancelled = _intake(github, cancel_event, head_sha, at="2026-07-19T12:02:00Z")
    assert cancelled["status"] == "cancel_requested"
    _assert_authorization(cancelled, "allowed")
    assert github.cancelled == [800]
    repeated_request = _intake(github, cancel_event, head_sha, at="2026-07-19T12:03:00Z")
    assert repeated_request["status"] == "cancel_requested"
    assert github.cancelled == [800]

    cancelled_future = advance_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        nonce="cancel-owned-nonce",
        target_state="not_implemented",
        at="2026-07-19T12:04:00Z",
        disposition="profile_not_implemented",
    )
    assert cancelled_future["lifecycle_state"] == "cancelled"
    assert cancelled_future["disposition"] == "cancelled"


def test_cancel_does_not_require_mutable_pull_request_head_resolution(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    result = _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, _ = _canonical(github)
    claim_run(
        github,
        repository="TruPryce/property-tax-data-platform",
        status_comment_id=comment_id,
        trusted_bot_id=BOT_ID,
        idempotency_key=result["idempotency_key"],
        run_id=result["run_id"],
        workflow_run_id=800,
        workflow_run_attempt=1,
        at="2026-07-19T12:01:00Z",
        nonce="deleted-head-cancel-nonce",
    )
    github.workflow = {
        "id": 800,
        "repository": {"id": 987654},
        "name": "CountyForge run",
        "event": "workflow_dispatch",
        "path": ".github/workflows/countyforge-run.yml",
        "display_title": f"CountyForge / review / {result['run_id']}",
    }
    github.fail_target_resolution = True
    cancel_event = event_factory("/countyforge cancel")
    cancel_event["comment"]["id"] = 923
    cancelled = _intake(github, cancel_event, head_sha, at="2026-07-19T12:02:00Z")
    assert cancelled["status"] == "cancel_requested"
    assert github.cancelled == [800]


def test_repeat_cancel_after_cancelled_is_idempotent(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, state = _canonical(github)
    state["workflow_run_id"] = 800
    cancel_requested = transition_state(
        state,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "cancel_requested",
            "at": "2026-07-19T12:02:00Z",
            "reason_code": "cancellation_requested",
        },
    )
    cancelled = transition_state(
        cancel_requested,
        {
            "contract_version": 1,
            "from": "cancel_requested",
            "to": "cancelled",
            "at": "2026-07-19T12:02:01Z",
            "reason_code": "workflow_cancelled",
        },
    )
    github.update_comment(
        "TruPryce/property-tax-data-platform", comment_id, render_status(cancelled)
    )
    cancel_event = event_factory("/countyforge cancel")
    cancel_event["comment"]["id"] = 444
    repeated = _intake(github, cancel_event, head_sha, at="2026-07-19T12:03:00Z")
    assert repeated["status"] == "cancelled"
    assert github.cancelled == []


def test_retry_requires_unchanged_head_and_preserves_attempt(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, state = _canonical(github)
    failed = transition_state(
        state,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "failed",
            "at": "2026-07-19T12:01:00Z",
            "reason_code": "synthetic_failure",
        },
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(failed))
    retry_event = event_factory("/countyforge retry")
    retry_event["comment"]["id"] = 333
    retried = _intake(github, retry_event, head_sha, at="2026-07-19T12:02:00Z")
    assert retried["status"] == "dispatched"
    _, retry_state = _canonical(github)
    assert retry_state["attempt"] == 2
    assert retry_state["history"][0]["run_id"] == failed["run_id"]
    encoded_trigger = str(github.dispatches[-1]["inputs"]["trigger"])
    raw_trigger = base64.urlsafe_b64decode(encoded_trigger + "=" * (-len(encoded_trigger) % 4))
    retry_trigger: JsonObject = json.loads(raw_trigger)
    assert retry_trigger["retry"]["original_run_id"] == failed["run_id"]
    assert (
        effective_idempotency_key(retry_trigger, ControlContracts().execution_policy)
        == retried["idempotency_key"]
    )

    terminal = transition_state(
        retry_state,
        {
            "contract_version": 1,
            "from": "queued",
            "to": "failed",
            "at": "2026-07-19T12:03:00Z",
            "reason_code": "synthetic_failure",
        },
    )
    github.update_comment(
        "TruPryce/property-tax-data-platform", comment_id, render_status(terminal)
    )
    github.pull["head"]["sha"] = "b" * 40
    refused = _intake(github, retry_event, head_sha, at="2026-07-19T12:04:00Z")
    assert refused["disposition"] == "retry_stale_head"
    assert "issue a new execution command" in github.comments[-1]["body"]


def test_maintenance_reports_expired_lease_without_writing_or_dispatching(
    event_factory: Callable[[str, str, str], JsonObject], head_sha: str
) -> None:
    github = FakeGitHub(head_sha)
    _intake(github, event_factory("/countyforge review"), head_sha)
    comment_id, state = _canonical(github)
    leased = acquire_lease(
        state,
        owner_workflow_run_id=800,
        owner_run_attempt=1,
        at="2026-07-19T12:00:00Z",
        ttl_seconds=60,
        nonce="maintenance-expiry-nonce",
    )
    github.update_comment("TruPryce/property-tax-data-platform", comment_id, render_status(leased))
    before_dispatches = copy.deepcopy(github.dispatches)
    result = audit_expired_leases(
        github,
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=BOT_ID,
        at="2026-07-19T12:02:00Z",
    )
    _, unchanged = _canonical(github)
    assert unchanged["lifecycle_state"] == "queued"
    assert {
        key: result[key]
        for key in (
            "ok",
            "inspected",
            "reconciliation_candidates",
            "marked_stale",
            "dispatched",
            "mutation",
        )
    } == {
        "ok": True,
        "inspected": 1,
        "reconciliation_candidates": 1,
        "marked_stale": 0,
        "dispatched": 0,
        "mutation": "audit_only",
    }
    assert result["events"][0]["event_type"] == "state_reconciled"
    assert github.dispatches == before_dispatches
