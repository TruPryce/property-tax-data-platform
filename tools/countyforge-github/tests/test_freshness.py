"""Live default-branch freshness in canonical status, and its hard boundaries."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from countyforge_github.contracts import ControlContracts, JsonObject, canonical_bytes
from countyforge_github.errors import ControlPlaneError
from countyforge_github.freshness import resolve_default_branch, unavailable_freshness
from countyforge_github.maintenance import audit_expired_leases
from countyforge_github.state import decode_marker, render_status, retry_eligibility, retry_state

TARGET = "a" * 40
ADVANCED = "b" * 40
AT = "2026-07-31T00:00:00Z"


class _FreshnessGitHub:
    """The two reads the resolver needs, plus the comment surface it refreshes."""

    def __init__(self, default_branch: str | None = "main", head: str = TARGET) -> None:
        self.default_branch = default_branch
        self.head = head
        self.fail_profile = False
        self.comments: list[JsonObject] = []
        self.updated: list[tuple[int, str]] = []

    def repository_profile(self, repository: str) -> JsonObject:
        if self.fail_profile:
            raise ControlPlaneError(
                "github_api_error", "GitHub API request failed.", {"status": 503}, exit_code=5
            )
        return {"full_name": repository, "default_branch": self.default_branch}

    def get_git_ref(self, repository: str, ref: str) -> JsonObject | None:
        if ref != f"refs/heads/{self.default_branch}":
            return None
        return {"ref": ref, "object": {"sha": self.head, "type": "commit"}}

    def list_repository_comments(self, repository: str) -> list[JsonObject]:
        return copy.deepcopy(self.comments)

    def get_comment(self, repository: str, comment_id: int) -> JsonObject:
        return copy.deepcopy(next(item for item in self.comments if item["id"] == comment_id))

    def update_comment(self, repository: str, comment_id: int, body: str) -> JsonObject:
        self.updated.append((comment_id, body))
        for item in self.comments:
            if item["id"] == comment_id:
                item["body"] = body
                return copy.deepcopy(item)
        raise AssertionError("refresh must update an existing canonical comment")


def _issue_state(
    queued_state_factory: Callable[[str], JsonObject], **overrides: object
) -> JsonObject:
    """A terminal issue-target run: the shape whose retry comparand is main."""

    state = copy.deepcopy(queued_state_factory("plan"))
    state.update(
        {
            "target_type": "issue",
            "target_number": 17,
            "lifecycle_state": "failed",
            "disposition": "planning_publication_failed",
            "target_head_sha": TARGET,
            "trusted_tool_sha": TARGET,
        }
    )
    state.update(overrides)  # type: ignore[arg-type]
    return state


def _row(body: str, field: str) -> str:
    line = next(row for row in body.splitlines() if row.startswith(f"| {field} |"))
    return line.split("|")[2].strip().strip("`")


def test_main_equal_to_target_reports_retry_eligible(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    github = _FreshnessGitHub(head=TARGET)
    freshness = resolve_default_branch(github, repository="TruPryce/x", at=AT)
    body = render_status(_issue_state(queued_state_factory), None, freshness)
    assert _row(body, "Target SHA") == TARGET[:12]
    assert _row(body, "Default branch") == "main"
    assert _row(body, "Current default-branch SHA") == TARGET[:12]
    assert _row(body, "Retry eligible") == "true"
    assert _row(body, "Main checked") == AT
    assert "/countyforge retry" in body


def test_advanced_main_reports_ineligible_and_redirects_the_operator(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    github = _FreshnessGitHub(head=ADVANCED)
    freshness = resolve_default_branch(github, repository="TruPryce/x", at=AT)
    body = render_status(_issue_state(queued_state_factory), None, freshness)
    assert _row(body, "Current default-branch SHA") == ADVANCED[:12]
    assert _row(body, "Retry eligible") == "false"
    # The guidance must not keep advertising a retry that will be refused.
    assert "`/countyforge retry` will be refused" in body
    assert "/countyforge plan" in body


def test_default_branch_need_not_be_named_main(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    github = _FreshnessGitHub(default_branch="trunk", head=TARGET)
    freshness = resolve_default_branch(github, repository="TruPryce/x", at=AT)
    assert freshness["default_branch"] == "trunk"
    body = render_status(_issue_state(queued_state_factory), None, freshness)
    assert _row(body, "Default branch") == "trunk"
    assert _row(body, "Retry eligible") == "true"


@pytest.mark.parametrize("failure", ["api_error", "missing_branch", "malformed_branch"])
def test_github_lookup_failure_degrades_to_unavailable(
    queued_state_factory: Callable[[str], JsonObject], failure: str
) -> None:
    """Canonical status must still publish, and must not show a stale value."""

    github = _FreshnessGitHub(head=TARGET)
    if failure == "api_error":
        github.fail_profile = True
    elif failure == "missing_branch":
        github.default_branch = None
    else:
        github.default_branch = "bad branch name"
    freshness = resolve_default_branch(github, repository="TruPryce/x", at=AT)
    assert freshness == unavailable_freshness(AT)
    body = render_status(_issue_state(queued_state_factory), None, freshness)
    assert _row(body, "Default branch") == "unavailable"
    assert _row(body, "Current default-branch SHA") == "unavailable"
    assert _row(body, "Retry eligible") == "unknown"


def test_pull_request_targets_report_unknown_rather_than_guessing(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    """A pull request is retried against its own head, not the default branch."""

    state = _issue_state(queued_state_factory, target_type="pull_request")
    freshness = resolve_default_branch(_FreshnessGitHub(head=TARGET), repository="x/y", at=AT)
    assert retry_eligibility(state, freshness) == "unknown"


def test_non_retryable_state_is_never_reported_eligible(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = _issue_state(queued_state_factory, lifecycle_state="running", disposition=None)
    freshness = resolve_default_branch(_FreshnessGitHub(head=TARGET), repository="x/y", at=AT)
    assert retry_eligibility(state, freshness) == "false"


def test_freshness_never_enters_the_marker_or_semantic_identity(
    queued_state_factory: Callable[[str], JsonObject], contracts: ControlContracts
) -> None:
    state = _issue_state(queued_state_factory)
    equal = render_status(
        state, None, resolve_default_branch(_FreshnessGitHub(), repository="x/y", at=AT)
    )
    advanced = render_status(
        state,
        None,
        resolve_default_branch(_FreshnessGitHub(head=ADVANCED), repository="x/y", at=AT),
    )
    decoded = [
        decode_marker(body, author_id=41898282, author_type="Bot", trusted_bot_id=41898282)
        for body in (equal, advanced)
    ]
    assert canonical_bytes(decoded[0]) == canonical_bytes(decoded[1]) == canonical_bytes(state)


def test_a_stale_displayed_sha_cannot_authorize_retry(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    """The display is evidence for a human; retry resolves the live target itself."""

    state = _issue_state(queued_state_factory)
    stale = {
        "available": True,
        "default_branch": "main",
        "default_branch_sha": TARGET,
        "checked_at": AT,
    }
    body = render_status(state, None, stale)
    assert _row(body, "Retry eligible") == "true"
    # Main has actually moved. Retry compares the live value, not the rendering.
    with pytest.raises(ControlPlaneError, match="retry_stale_head|Target changed"):
        retry_state(state, current_head_sha=ADVANCED, at=AT)
    resumed = retry_state(state, current_head_sha=TARGET, at=AT)
    assert resumed["attempt"] == int(state["attempt"]) + 1


def test_maintenance_refresh_updates_display_without_touching_identity(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = _issue_state(queued_state_factory)
    github = _FreshnessGitHub(head=TARGET)
    github.comments = [
        {
            "id": 500,
            "body": render_status(state, None, unavailable_freshness("2026-07-30T00:00:00Z")),
            "user": {"id": 41898282, "type": "Bot", "login": "github-actions[bot]"},
        }
    ]
    before = copy.deepcopy(github.comments[0]["body"])
    result = audit_expired_leases(
        github,  # type: ignore[arg-type]
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=41898282,
        at=AT,
        refresh_displays=True,
    )
    assert result["displays_refreshed"] == 1
    assert result["mutation"] == "display_refresh"
    assert result["dispatched"] == 0
    assert len(github.updated) == 1
    refreshed = str(github.comments[0]["body"])
    assert refreshed != before
    assert _row(refreshed, "Retry eligible") == "true"
    assert _row(refreshed, "Main checked") == AT
    # The marker is byte-identical: no lifecycle, history, revision, or
    # idempotency change accompanied the display write.
    decoded = decode_marker(
        refreshed, author_id=41898282, author_type="Bot", trusted_bot_id=41898282
    )
    assert canonical_bytes(decoded) == canonical_bytes(state)
    assert decoded is not None
    assert decoded["revision"] == state["revision"]
    assert decoded["idempotency_key"] == state["idempotency_key"]
    assert decoded["history"] == state["history"]


def test_maintenance_refresh_is_a_no_op_without_the_flag(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    state = _issue_state(queued_state_factory)
    github = _FreshnessGitHub(head=TARGET)
    github.comments = [
        {
            "id": 500,
            "body": render_status(state, None, unavailable_freshness("2026-07-30T00:00:00Z")),
            "user": {"id": 41898282, "type": "Bot", "login": "github-actions[bot]"},
        }
    ]
    result = audit_expired_leases(
        github,  # type: ignore[arg-type]
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=41898282,
        at=AT,
    )
    assert result["displays_refreshed"] == 0
    assert result["mutation"] == "audit_only"
    assert github.updated == []


def test_maintenance_refresh_leaves_a_concurrently_changed_state_alone(
    queued_state_factory: Callable[[str], JsonObject],
) -> None:
    """A repository-wide sweep must not overwrite a per-target lane's write."""

    state = _issue_state(queued_state_factory)
    moved = copy.deepcopy(state)
    moved["revision"] = int(state["revision"]) + 1
    github = _FreshnessGitHub(head=TARGET)
    github.comments = [
        {
            "id": 500,
            "body": render_status(state, None, unavailable_freshness("2026-07-30T00:00:00Z")),
            "user": {"id": 41898282, "type": "Bot", "login": "github-actions[bot]"},
        }
    ]

    listed = github.list_repository_comments

    def _race(repository: str) -> list[JsonObject]:
        comments = listed(repository)
        github.comments[0]["body"] = render_status(
            moved, None, unavailable_freshness("2026-07-30T00:00:00Z")
        )
        return comments

    github.list_repository_comments = _race  # type: ignore[method-assign]
    result = audit_expired_leases(
        github,  # type: ignore[arg-type]
        repository="TruPryce/property-tax-data-platform",
        trusted_bot_id=41898282,
        at=AT,
        refresh_displays=True,
    )
    assert result["displays_refreshed"] == 0
    assert github.updated == []
