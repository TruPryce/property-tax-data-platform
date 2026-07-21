"""Trusted issue_comment intake orchestration over the fakeable GitHub port."""

from __future__ import annotations

import base64
import copy
import re

from countyforge_github.authorization import authorize
from countyforge_github.commands import parse_event
from countyforge_github.contracts import ControlContracts, JsonObject, canonical_bytes
from countyforge_github.control import (
    find_canonical_state,
    is_duplicate,
    publish_canonical_state,
    request_cancellation,
    upsert_control_feedback,
)
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubPort
from countyforge_github.identity import build_trigger, iso_now, semantic_idempotency_key
from countyforge_github.leases import mark_expired_stale
from countyforge_github.observability import (
    control_event,
    outcome_for_state,
    state_event,
    with_audit,
)
from countyforge_github.planning import classify_issue, planning_context_fingerprint
from countyforge_github.state import (
    ACTIVE_STATES,
    begin_new_state,
    bump_revision,
    check_status,
    reconcile_workflow,
    retry_state,
    transition_state,
)

_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REFUSAL_MESSAGES = {
    "no_run_found": "No CountyForge run found for this target.",
    "retry_not_allowed": "CountyForge retry refused: the latest run is not retry-eligible.",
    "retry_stale_head": (
        "CountyForge retry refused: the target changed; issue a new execution command."
    ),
    "active_run_exists": (
        "CountyForge command refused: active work already exists; use status or cancel."
    ),
    "cancellation_run_unclaimed": (
        "CountyForge cancellation is not yet available while the execution workflow is claiming "
        "the queued run; use status and retry cancel shortly."
    ),
    "cancellation_not_active": "CountyForge cancellation refused: no active run exists.",
    "review_requires_pull_request": (
        "CountyForge review requires a pull request with an immutable diff target."
    ),
    "insufficient_issue_intake": (
        "CountyForge plan refused: the issue needs a supported type, problem statement, "
        "and outcome."
    ),
}


def _commit_sha(value: object) -> str:
    sha = str(value)
    if _COMMIT_SHA.fullmatch(sha) is None:
        raise ControlPlaneError("invalid_target", "GitHub target commit facts are invalid.")
    return sha


def _target_facts(
    event: JsonObject,
    github: GitHubPort,
    repository: str,
    trusted_tool_sha: str,
) -> JsonObject:
    issue = event.get("issue")
    if not isinstance(issue, dict):
        raise ControlPlaneError("invalid_event", "GitHub target facts are incomplete.")
    number = int(issue["number"])
    if isinstance(issue.get("pull_request"), dict):
        pull = github.pull_request(repository, number)
        base = pull.get("base")
        head = pull.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise ControlPlaneError("invalid_target", "Pull request commit facts are incomplete.")
        source_repository = head.get("repo")
        if not isinstance(source_repository, dict):
            raise ControlPlaneError(
                "invalid_target", "Pull request source repository facts are incomplete."
            )
        base_tip_sha = _commit_sha(base["sha"])
        head_sha = _commit_sha(head["sha"])
        comparison = github.compare_commits(repository, base_tip_sha, head_sha)
        merge_base = comparison.get("merge_base_commit")
        if not isinstance(merge_base, dict):
            raise ControlPlaneError(
                "invalid_target", "Pull request merge-base facts are incomplete."
            )
        return {
            "type": "pull_request",
            "number": number,
            "source_repository": {
                "id": int(source_repository["id"]),
                "full_name": str(source_repository["full_name"]),
            },
            "base_sha": _commit_sha(merge_base["sha"]),
            "head_sha": head_sha,
        }
    repository_facts = event.get("repository")
    if not isinstance(repository_facts, dict):
        raise ControlPlaneError("invalid_event", "GitHub repository facts are incomplete.")
    return {
        "type": "issue",
        "number": number,
        "source_repository": {
            "id": int(repository_facts["id"]),
            "full_name": str(repository_facts["full_name"]),
        },
        "base_sha": _commit_sha(trusted_tool_sha),
        "head_sha": _commit_sha(trusted_tool_sha),
    }


def _workflow_facts(raw: JsonObject) -> JsonObject:
    repository = raw.get("repository")
    repository_id = int(repository.get("id", 0)) if isinstance(repository, dict) else 0
    return {
        "id": raw.get("id"),
        "repository_id": repository_id,
        "name": raw.get("name"),
        "event": raw.get("event"),
        "path": raw.get("path"),
        "display_title": raw.get("display_title"),
        "status": raw.get("status"),
        "conclusion": raw.get("conclusion"),
    }


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


def _with_authorization(
    document: JsonObject, events: list[JsonObject], authorization: JsonObject
) -> JsonObject:
    """Attach complete bounded authorization facts without making them metric labels."""

    return {**with_audit(document, events), "authorization": copy.deepcopy(authorization)}


def _refused_result(
    github: GitHubPort,
    *,
    repository: str,
    target_number: int,
    trusted_bot_id: int,
    reason_code: str,
    events: list[JsonObject],
    authorization: JsonObject,
) -> JsonObject:
    message = _REFUSAL_MESSAGES[reason_code]
    upsert_control_feedback(
        github,
        repository=repository,
        target_number=target_number,
        trusted_bot_id=trusted_bot_id,
        message=message,
    )
    received = events[0]
    events.append(
        control_event(
            event_type="terminal_outcome",
            command=received["command"],
            target_type=received["target_type"],
            authorization_outcome="allowed",
            state="failed",
            outcome="failed",
            disposition=reason_code,
            timestamp=received["timestamp"],
            repository_id=received.get("repository_id"),
            target_number=received.get("target_number"),
            run_id=None,
            workflow_run_id=None,
            target_sha=None,
            idempotency_key=None,
            reason_code=reason_code,
        )
    )
    return _with_authorization(
        {
            "ok": False,
            "status": "refused",
            "disposition": reason_code,
            "reason_code": reason_code,
        },
        events,
        authorization,
    )


def _create_check(
    github: GitHubPort, repository: str, state: JsonObject, details_url: str | None
) -> int:
    payload: JsonObject = {
        "name": f"CountyForge / {state['command']}",
        "head_sha": state["target_head_sha"],
        "status": "in_progress",
        "external_id": state["idempotency_key"],
        "output": {
            "title": f"CountyForge {state['command']} queued",
            "summary": "Authorized CountyForge work is queued under its immutable profile.",
        },
    }
    if details_url is not None:
        payload["details_url"] = details_url
    return int(github.create_check(repository, payload)["id"])


def _dispatch(
    github: GitHubPort,
    *,
    repository: str,
    default_branch: str,
    trigger: JsonObject,
    state: JsonObject,
    status_comment_id: int,
) -> None:
    encoded_trigger = base64.urlsafe_b64encode(canonical_bytes(trigger)).decode("ascii")
    github.dispatch_workflow(
        repository,
        "countyforge-run.yml",
        default_branch,
        {
            "trigger": encoded_trigger,
            "status_comment_id": str(status_comment_id),
            "idempotency_key": str(state["idempotency_key"]),
            "run_id": str(state["run_id"]),
            "command": str(state["command"]),
            "target_type": str(state["target_type"]),
            "target_number": str(state["target_number"]),
            "trusted_tool_sha": str(state["trusted_tool_sha"]),
        },
    )


def process_intake(
    event: JsonObject,
    github: GitHubPort,
    *,
    trusted_tool_sha: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    default_branch: str,
    trusted_bot_id: int,
    delivery_id: str | None = None,
    at: str | None = None,
    contracts: ControlContracts | None = None,
) -> JsonObject:
    """Process one created comment without exposing a provider credential."""

    resolved = contracts or ControlContracts()
    parsed = parse_event(event, resolved)
    if parsed["status"] != "parsed":
        return parsed
    repository_raw = event.get("repository")
    comment = event.get("comment")
    if not isinstance(repository_raw, dict) or not isinstance(comment, dict):
        raise ControlPlaneError("invalid_event", "GitHub event facts are incomplete.")
    repository = str(repository_raw["full_name"])
    repository_id = int(repository_raw["id"])
    issue = event.get("issue")
    if not isinstance(issue, dict):
        raise ControlPlaneError("invalid_event", "GitHub target facts are incomplete.")
    target_number = int(issue["number"])
    target_type = "pull_request" if isinstance(issue.get("pull_request"), dict) else "issue"
    command: JsonObject = parsed["command_document"]
    operation = str(command["command"])
    timestamp = at or iso_now()
    events = [
        control_event(
            event_type="command_received",
            command=operation,
            target_type=target_type,
            authorization_outcome="not_applicable",
            state="received",
            outcome="pending",
            disposition="command_received",
            timestamp=timestamp,
            repository_id=repository_id,
            target_number=target_number,
            run_id=None,
            workflow_run_id=None,
            target_sha=None,
            idempotency_key=None,
            reason_code="command_received",
        )
    ]
    actor_raw = comment.get("user")
    if not isinstance(actor_raw, dict):
        raise ControlPlaneError("invalid_event", "GitHub actor facts are incomplete.")
    decision = authorize(
        actor_login=str(actor_raw["login"]),
        actor_id=int(actor_raw["id"]),
        actor_type=str(actor_raw["type"]),
        permission=github.repository_permission(repository, str(actor_raw["login"])),
        contracts=resolved,
    )
    if decision["outcome"] != "allowed":
        upsert_control_feedback(
            github,
            repository=repository,
            target_number=target_number,
            trusted_bot_id=trusted_bot_id,
            message=(
                "CountyForge command refused: an authorized repository maintainer is required."
            ),
        )
        events.append(
            control_event(
                event_type="authorization_decided",
                command=operation,
                target_type=target_type,
                authorization_outcome="denied",
                state="received",
                outcome="denied",
                disposition="authorization_denied",
                timestamp=timestamp,
                repository_id=repository_id,
                target_number=target_number,
                run_id=None,
                workflow_run_id=None,
                target_sha=None,
                idempotency_key=None,
                reason_code=str(decision["reason_code"]),
            )
        )
        return _with_authorization(
            {
                "ok": False,
                "status": "denied",
                "disposition": "authorization_denied",
                "reason_code": decision["reason_code"],
            },
            events,
            decision,
        )
    comments = github.list_comments(repository, target_number)
    canonical = find_canonical_state(
        comments,
        trusted_bot_id=trusted_bot_id,
        expected_repository_id=repository_id,
        expected_target_type=target_type,
        expected_target_number=target_number,
        contracts=resolved,
    )
    comment_id = canonical[0] if canonical is not None else None
    existing = canonical[1] if canonical is not None else None
    if operation in {"status", "cancel"}:
        events.append(
            control_event(
                event_type="authorization_decided",
                command=operation,
                target_type=target_type,
                authorization_outcome="allowed",
                state="authorized",
                outcome="pending",
                disposition="authorization_allowed",
                timestamp=timestamp,
                repository_id=repository_id,
                target_number=target_number,
                run_id=None,
                workflow_run_id=None,
                target_sha=existing["target_head_sha"] if existing is not None else None,
                idempotency_key=None,
                reason_code=str(decision["reason_code"]),
            )
        )
    if operation == "status":
        if existing is None:
            upsert_control_feedback(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                message="No CountyForge run found for this target.",
            )
            return _with_authorization(
                {"ok": True, "status": "no_run", "disposition": "no_run_found"},
                events,
                decision,
            )
        expected = copy.deepcopy(existing)
        existing = mark_expired_stale(existing, at=timestamp)
        if existing["workflow_run_id"] is not None and existing["lifecycle_state"] in ACTIVE_STATES:
            raw = github.workflow_run(repository, int(existing["workflow_run_id"]))
            existing = reconcile_workflow(existing, _workflow_facts(raw), timestamp)
        publish_canonical_state(
            github,
            repository=repository,
            target_number=target_number,
            trusted_bot_id=trusted_bot_id,
            expected_state=expected,
            state=existing,
        )
        events.append(
            state_event(
                existing,
                event_type="state_reconciled",
                authorization_outcome="allowed",
                outcome=outcome_for_state(str(existing["lifecycle_state"])),
                disposition="status_reconciled",
                timestamp=timestamp,
            )
        )
        return _with_authorization(
            {"ok": True, "status": "reconciled", "state": existing["lifecycle_state"]},
            events,
            decision,
        )

    if operation == "cancel":
        if existing is None:
            return _refused_result(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                reason_code="no_run_found",
                events=events,
                authorization=decision,
            )
        already_cancelled = existing["lifecycle_state"] == "cancelled"
        expected = copy.deepcopy(existing)
        try:
            existing = request_cancellation(
                github,
                repository=repository,
                repository_id=repository_id,
                target_type=target_type,
                target_number=target_number,
                state=existing,
                at=timestamp,
            )
        except ControlPlaneError as error:
            if error.code not in _REFUSAL_MESSAGES:
                raise
            return _refused_result(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                reason_code=error.code,
                events=events,
                authorization=decision,
            )
        publish_canonical_state(
            github,
            repository=repository,
            target_number=target_number,
            trusted_bot_id=trusted_bot_id,
            expected_state=expected,
            state=existing,
        )
        events.append(
            state_event(
                existing,
                event_type="state_reconciled" if already_cancelled else "cancellation_requested",
                authorization_outcome="allowed",
                outcome="cancelled" if already_cancelled else "pending",
                disposition="already_cancelled" if already_cancelled else "cancellation_requested",
                timestamp=timestamp,
            )
        )
        return _with_authorization(
            {
                "ok": True,
                "status": "cancelled" if already_cancelled else "cancel_requested",
                "run_id": existing["run_id"],
            },
            events,
            decision,
        )

    planning_context_sha256: str | None = None
    target = _target_facts(event, github, repository, trusted_tool_sha)
    if operation == "plan":
        issue_document = event.get("issue")
        if not isinstance(issue_document, dict):
            return _refused_result(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                reason_code="insufficient_issue_intake",
                events=events,
                authorization=decision,
            )
        planning_context_sha256 = planning_context_fingerprint(issue_document, comments)
        labels = [
            str(label.get("name"))
            for label in issue_document.get("labels", [])
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        ]
        try:
            classify_issue(
                str(issue_document.get("title", "")),
                str(issue_document.get("body", "")),
                labels,
            )
        except ControlPlaneError:
            return _refused_result(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                reason_code="insufficient_issue_intake",
                events=events,
                authorization=decision,
            )
    trigger = build_trigger(
        event=event,
        command=command,
        authorization=decision,
        target=target,
        trusted_tool_sha=trusted_tool_sha,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        delivery_id=delivery_id,
        planning_context_sha256=planning_context_sha256,
        timestamp=timestamp,
        contracts=resolved,
    )
    events.append(
        control_event(
            event_type="authorization_decided",
            command=operation,
            target_type=target_type,
            authorization_outcome="allowed",
            state="authorized",
            outcome="pending",
            disposition="authorization_allowed",
            timestamp=timestamp,
            repository_id=repository_id,
            target_number=target_number,
            run_id=None,
            workflow_run_id=None,
            target_sha=target["head_sha"],
            idempotency_key=None,
            reason_code=str(decision["reason_code"]),
        )
    )
    if operation == "review" and target["type"] != "pull_request":
        return _refused_result(
            github,
            repository=repository,
            target_number=target_number,
            trusted_bot_id=trusted_bot_id,
            reason_code="review_requires_pull_request",
            events=events,
            authorization=decision,
        )

    expected_for_queue: JsonObject | None
    if operation == "retry":
        if existing is None:
            return _refused_result(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                reason_code="no_run_found",
                events=events,
                authorization=decision,
            )
        expected_for_queue = copy.deepcopy(existing)
        previous_run_id = str(existing["run_id"])
        try:
            state = retry_state(existing, current_head_sha=str(target["head_sha"]), at=timestamp)
        except ControlPlaneError as error:
            if error.code not in _REFUSAL_MESSAGES:
                raise
            return _refused_result(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                reason_code=error.code,
                events=events,
                authorization=decision,
            )
        retry_trigger = copy.deepcopy(trigger)
        retry_trigger["command"] = {
            "contract_version": 1,
            "command": state["command"],
            "arguments": state["command_arguments"],
        }
        retry_trigger["retry"] = {
            "original_idempotency_key": state["original_idempotency_key"],
            "original_run_id": previous_run_id,
            "attempt": state["attempt"],
        }
        resolved.validate("trigger", retry_trigger)
        trigger = retry_trigger
        events.append(
            state_event(
                state,
                event_type="retry_started",
                authorization_outcome="allowed",
                outcome="pending",
                disposition="retry_started",
                timestamp=timestamp,
            )
        )
    else:
        key = semantic_idempotency_key(trigger, resolved.execution_policy)
        if is_duplicate(existing, key):
            duplicate_state = existing
            assert duplicate_state is not None
            events.append(
                state_event(
                    duplicate_state,
                    event_type="duplicate_detected",
                    authorization_outcome="allowed",
                    outcome="duplicate",
                    disposition="duplicate_detected",
                    timestamp=timestamp,
                )
            )
            return _with_authorization(
                {"ok": True, "status": "duplicate", "disposition": "duplicate_detected"},
                events,
                decision,
            )
        if existing is not None and existing["lifecycle_state"] in ACTIVE_STATES:
            active = copy.deepcopy(existing)
            stale = mark_expired_stale(existing, at=timestamp)
            if stale["lifecycle_state"] in ACTIVE_STATES:
                return _refused_result(
                    github,
                    repository=repository,
                    target_number=target_number,
                    trusted_bot_id=trusted_bot_id,
                    reason_code="active_run_exists",
                    events=events,
                    authorization=decision,
                )
            publish_canonical_state(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                expected_state=active,
                state=stale,
            )
            existing = stale
            recovered_disposition = str(existing["disposition"] or "lease_expired")
            events.append(
                state_event(
                    existing,
                    event_type=(
                        "lease_reclaimed"
                        if recovered_disposition == "lease_expired"
                        else "terminal_outcome"
                    ),
                    authorization_outcome="allowed",
                    outcome="failed",
                    disposition=recovered_disposition,
                    timestamp=timestamp,
                )
            )
        state = begin_new_state(trigger, resolved.execution_policy, key, existing)
        expected_for_queue = copy.deepcopy(existing) if existing is not None else None

    state = _transition(state, "authorized", timestamp, "authorization_allowed")
    state = _transition(state, "queued", timestamp, "workflow_queued")
    status_comment = publish_canonical_state(
        github,
        repository=repository,
        target_number=target_number,
        trusted_bot_id=trusted_bot_id,
        expected_state=expected_for_queue,
        state=state,
    )
    comment_id = int(status_comment["id"])
    if target["type"] == "pull_request":
        expected_without_check = copy.deepcopy(state)
        check_id: int | None = None
        try:
            check_id = _create_check(
                github,
                repository,
                state,
                str(event.get("issue", {}).get("html_url", "")) or None,
            )
            state = copy.deepcopy(state)
            state["check_run_id"] = check_id
            state = bump_revision(state, at=timestamp)
            resolved.validate("state", state)
            publish_canonical_state(
                github,
                repository=repository,
                target_number=target_number,
                trusted_bot_id=trusted_bot_id,
                expected_state=expected_without_check,
                state=state,
            )
        except ControlPlaneError:
            predecessors = [expected_without_check]
            if check_id is not None:
                with_check = copy.deepcopy(expected_without_check)
                with_check["check_run_id"] = check_id
                predecessors.append(with_check)
            for predecessor in predecessors:
                failed = _transition(
                    predecessor,
                    "failed",
                    timestamp,
                    "check_initialization_failed",
                )
                failed["check_run_id"] = check_id
                resolved.validate("state", failed)
                try:
                    publish_canonical_state(
                        github,
                        repository=repository,
                        target_number=target_number,
                        trusted_bot_id=trusted_bot_id,
                        expected_state=predecessor,
                        state=failed,
                    )
                    break
                except ControlPlaneError as recovery_error:
                    if recovery_error.code != "state_write_conflict":
                        raise
            raise
    try:
        _dispatch(
            github,
            repository=repository,
            default_branch=default_branch,
            trigger=trigger,
            state=state,
            status_comment_id=comment_id,
        )
    except ControlPlaneError:
        failed = _transition(state, "failed", timestamp, "workflow_dispatch_failed")
        publish_canonical_state(
            github,
            repository=repository,
            target_number=target_number,
            trusted_bot_id=trusted_bot_id,
            expected_state=state,
            state=failed,
        )
        raise
    status, conclusion = check_status(state["lifecycle_state"])
    events.append(
        state_event(
            state,
            event_type="workflow_dispatched",
            authorization_outcome="allowed",
            outcome="pending",
            disposition="workflow_dispatched",
            timestamp=timestamp,
        )
    )
    return _with_authorization(
        {
            "ok": True,
            "status": "dispatched",
            "run_id": state["run_id"],
            "idempotency_key": state["idempotency_key"],
            "check_status": status,
            "check_conclusion": conclusion,
            "status_comment_id": comment_id,
        },
        events,
        decision,
    )
