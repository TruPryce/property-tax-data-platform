"""Machine-readable CountyForge GitHub adapter CLI."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from countyforge_runner.command_broker import CommandBroker
from countyforge_runner.contracts import file_sha256, validate_document
from countyforge_runner.errors import KernelError

from countyforge_github.authorization import authorize
from countyforge_github.commands import parse_event
from countyforge_github.contracts import (
    ControlContracts,
    JsonObject,
    load_json_object,
)
from countyforge_github.errors import ControlPlaneError
from countyforge_github.github_api import GitHubRestClient
from countyforge_github.identity import (
    build_trigger,
    effective_idempotency_key,
    execution_run_id,
)
from countyforge_github.implementation import (
    build_implementation_packet,
    freeze_implementation_artifact,
    publish_implementation,
    validate_implementation_artifact,
    validate_implementation_result,
    validate_implementation_tasks,
)
from countyforge_github.maintenance import audit_expired_leases
from countyforge_github.observability import outcome_for_state, state_event, with_audit
from countyforge_github.orchestrator import process_intake
from countyforge_github.planning import (
    DEFAULT_TRUSTED_BOT_ID,
    build_planning_packet,
    materialize_plan,
    publish_plan,
    validate_planning_result,
)
from countyforge_github.requests import build_run_request
from countyforge_github.results import resolve_terminal_result
from countyforge_github.state import reconcile_workflow, render_status, transition_state
from countyforge_github.workflow_control import (
    advance_run,
    claim_run,
    fail_unclaimed_run,
    verify_publication_lease,
)


def _file(parser: argparse.ArgumentParser, name: str, *, required: bool = True) -> None:
    parser.add_argument(f"--{name.replace('_', '-')}", type=Path, required=required)


def _load_command_events(path: Path, schema_path: Path) -> list[JsonObject]:
    """Load and strictly validate trusted broker event lines."""

    try:
        schema = load_json_object(schema_path, kind="implementation command-event schema")
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError, ControlPlaneError):
        raise ControlPlaneError(
            "command_evidence_invalid", "Trusted implementation command evidence is unavailable."
        ) from None
    events: list[JsonObject] = []
    try:
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError
            validate_document(event, schema, kind="implementation command event")
            events.append(event)
    except (ValueError, json.JSONDecodeError, ControlPlaneError):
        raise ControlPlaneError(
            "command_evidence_invalid", "Trusted implementation command evidence is invalid."
        ) from None
    return events


def build_parser() -> argparse.ArgumentParser:
    """Build the stable workflow/operator command surface."""

    parser = argparse.ArgumentParser(prog="countyforge-github")
    parser.add_argument("--contract-root", type=Path)
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    parse = subparsers.add_parser("parse-command")
    _file(parse, "event")

    authorization = subparsers.add_parser("authorize")
    _file(authorization, "event")
    _file(authorization, "permission")
    _file(authorization, "teams", required=False)

    trigger = subparsers.add_parser("build-trigger")
    for name in ("event", "command", "authorization", "target"):
        _file(trigger, name)
    trigger.add_argument("--trusted-tool-sha", required=True)
    trigger.add_argument("--workflow-run-id", type=int, required=True)
    trigger.add_argument("--workflow-run-attempt", type=int, required=True)
    trigger.add_argument("--delivery-id")
    trigger.add_argument("--timestamp")

    identity = subparsers.add_parser("idempotency-key")
    _file(identity, "trigger")

    transition = subparsers.add_parser("transition")
    _file(transition, "state")
    _file(transition, "transition")

    render = subparsers.add_parser("render-status")
    _file(render, "state")

    request = subparsers.add_parser("build-run-request")
    _file(request, "trigger")
    request.add_argument("--target-root", type=Path, required=True)
    request.add_argument("--packet", type=Path)
    request.add_argument("--packet-provenance", type=Path)
    request.add_argument("--planning-packet", type=Path)
    request.add_argument("--context-manifest", type=Path)
    request.add_argument("--implementation-packet", type=Path)
    request.add_argument("--implementation-manifest", type=Path)
    request.add_argument("--implementation-task-plan", type=Path)
    request.add_argument("--workspace", type=Path)
    request.add_argument("--workspace-binding", type=Path)

    planning_packet = subparsers.add_parser("build-planning-packet")
    _file(planning_packet, "trigger")
    _file(planning_packet, "issue")
    _file(planning_packet, "comments", required=False)
    planning_packet.add_argument("--output-dir", type=Path, required=True)
    planning_packet.add_argument("--trusted-bot-id", type=int, default=DEFAULT_TRUSTED_BOT_ID)

    implementation_packet = subparsers.add_parser("build-implementation-packet")
    _file(implementation_packet, "trigger")
    _file(implementation_packet, "issue")
    implementation_packet.add_argument("--change-name", required=True)
    implementation_packet.add_argument("--output-dir", type=Path, required=True)
    implementation_packet.add_argument("--planning-pr-merged", action="store_true")
    implementation_packet.add_argument("--approval-actor-id", type=int)

    materialize = subparsers.add_parser("materialize-plan")
    _file(materialize, "result")
    materialize.add_argument("--publication-root", type=Path, required=True)
    materialize.add_argument("--issue-number", type=int, required=True)
    materialize.add_argument("--run-id", required=True)

    implementation_result = subparsers.add_parser("validate-implementation-result")
    _file(implementation_result, "result")
    _file(implementation_result, "task-plan")
    implementation_result.add_argument("--expected-revision", type=int)
    implementation_result.add_argument("--workspace", type=Path)
    implementation_result.add_argument("--command-events", type=Path, required=True)

    implementation_context = subparsers.add_parser("validate-implementation-context")
    _file(implementation_context, "packet")
    _file(implementation_context, "manifest")
    _file(implementation_context, "task-plan")

    implementation_artifact = subparsers.add_parser("validate-implementation-artifact")
    _file(implementation_artifact, "result")
    _file(implementation_artifact, "manifest")
    implementation_artifact.add_argument("--workspace", type=Path, required=True)
    implementation_artifact.add_argument("--policy-root", type=Path, required=True)
    implementation_artifact.add_argument("--run-id", required=True)
    implementation_artifact.add_argument("--issue-number", type=int, required=True)
    implementation_artifact.add_argument("--change-name", required=True)
    implementation_artifact.add_argument("--base-sha", required=True)

    implementation_freeze = subparsers.add_parser("freeze-implementation-artifact")
    _file(implementation_freeze, "result")
    implementation_freeze.add_argument("--workspace", type=Path, required=True)
    implementation_freeze.add_argument("--policy-root", type=Path, required=True)
    implementation_freeze.add_argument("--output", type=Path, required=True)
    implementation_freeze.add_argument("--run-id", required=True)
    implementation_freeze.add_argument("--issue-number", type=int, required=True)
    implementation_freeze.add_argument("--change-name", required=True)
    implementation_freeze.add_argument("--base-sha", required=True)

    implementation_publish = subparsers.add_parser("publish-implementation")
    implementation_publish.add_argument("--repository", required=True)
    implementation_publish.add_argument("--issue-number", type=int, required=True)
    implementation_publish.add_argument("--change-name", required=True)
    implementation_publish.add_argument("--revision", type=int, required=True)
    implementation_publish.add_argument("--base-sha", required=True)
    implementation_publish.add_argument("--run-id", required=True)
    implementation_publish.add_argument("--workspace", type=Path, required=True)
    implementation_publish.add_argument("--evidence-url")
    implementation_publish.add_argument("--status-comment-id", type=int, required=True)
    implementation_publish.add_argument("--trusted-bot-id", type=int, required=True)
    implementation_publish.add_argument("--idempotency-key", required=True)
    implementation_publish.add_argument("--workflow-run-id", type=int, required=True)
    implementation_publish.add_argument("--nonce", required=True)
    implementation_publish.add_argument("--at", required=True)
    implementation_publish.add_argument("--implementation-result", type=Path, required=True)
    implementation_publish.add_argument("--policy-root", type=Path, required=True)
    implementation_publish.add_argument("--validation-report", type=Path, required=True)

    implementation_report = subparsers.add_parser("validate-implementation-report")
    _file(implementation_report, "report")

    implementation_command = subparsers.add_parser("run-implementation-command")
    implementation_command.add_argument("--command-id", required=True)
    implementation_command.add_argument("--registry", type=Path, required=True)
    implementation_command.add_argument("--schema", type=Path, required=True)
    implementation_command.add_argument("--workspace", type=Path, required=True)
    implementation_command.add_argument("--contract-root", type=Path)
    implementation_command.add_argument("--run-id", default="local")
    implementation_command.add_argument("--workspace-revision")

    publish = subparsers.add_parser("publish-plan")
    _file(publish, "result")
    publish.add_argument("--repository", required=True)
    publish.add_argument("--default-branch", required=True)
    publish.add_argument("--target-sha", required=True)
    publish.add_argument("--issue-number", type=int, required=True)
    publish.add_argument("--run-id", required=True)
    publish.add_argument("--publication-root", type=Path, required=True)
    publish.add_argument("--planning-packet", type=Path, required=True)
    publish.add_argument("--context-manifest", type=Path, required=True)
    publish.add_argument("--evidence-url")
    publish.add_argument("--already-materialized", action="store_true")

    reconcile = subparsers.add_parser("reconcile")
    _file(reconcile, "state")
    _file(reconcile, "workflow")
    reconcile.add_argument("--at", required=True)

    result = subparsers.add_parser("resolve-terminal-result")
    result.add_argument(
        "--command", required=True, choices=["plan", "implement", "validate", "review", "fix"]
    )
    _file(result, "result", required=False)
    _file(result, "exit_code", required=False)

    intake = subparsers.add_parser("intake")
    _file(intake, "event")
    intake.add_argument("--trusted-tool-sha", required=True)
    intake.add_argument("--workflow-run-id", type=int, required=True)
    intake.add_argument("--workflow-run-attempt", type=int, required=True)
    intake.add_argument("--default-branch", required=True)
    intake.add_argument("--trusted-bot-id", type=int, required=True)
    intake.add_argument("--delivery-id")
    intake.add_argument("--at")

    claim = subparsers.add_parser("claim-run")
    claim.add_argument("--repository", required=True)
    claim.add_argument("--status-comment-id", type=int, required=True)
    claim.add_argument("--trusted-bot-id", type=int, required=True)
    claim.add_argument("--idempotency-key", required=True)
    claim.add_argument("--run-id", required=True)
    claim.add_argument("--workflow-run-id", type=int, required=True)
    claim.add_argument("--workflow-run-attempt", type=int, required=True)
    claim.add_argument("--at", required=True)

    advance = subparsers.add_parser("advance-run")
    advance.add_argument("--repository", required=True)
    advance.add_argument("--status-comment-id", type=int, required=True)
    advance.add_argument("--trusted-bot-id", type=int, required=True)
    advance.add_argument("--idempotency-key", required=True)
    advance.add_argument("--run-id", required=True)
    advance.add_argument("--workflow-run-id", type=int, required=True)
    advance.add_argument("--nonce", required=True)
    advance.add_argument(
        "--target-state",
        required=True,
        choices=[
            "running",
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
            "stale",
            "not_implemented",
        ],
    )
    advance.add_argument("--at", required=True)
    advance.add_argument("--disposition", required=True)
    advance.add_argument("--evidence-url")
    advance.add_argument("--planning-change-name")
    advance.add_argument("--planning-branch")
    advance.add_argument("--planning-pr-number", type=int)
    advance.add_argument("--planning-context-sha256")
    advance.add_argument("--planning-result-sha256")
    advance.add_argument("--implementation-change-name")
    advance.add_argument("--implementation-revision", type=int)
    advance.add_argument("--implementation-branch")
    advance.add_argument("--implementation-pr-number", type=int)
    advance.add_argument("--implementation-completed-task-count", type=int)
    advance.add_argument("--implementation-incomplete-task-count", type=int)
    advance.add_argument("--implementation-blocked-task-count", type=int)
    advance.add_argument("--implementation-eligible", choices=("true", "false"))

    fail_unclaimed = subparsers.add_parser("fail-unclaimed-run")
    fail_unclaimed.add_argument("--repository", required=True)
    fail_unclaimed.add_argument("--status-comment-id", type=int, required=True)
    fail_unclaimed.add_argument("--trusted-bot-id", type=int, required=True)
    fail_unclaimed.add_argument("--idempotency-key", required=True)
    fail_unclaimed.add_argument("--run-id", required=True)
    fail_unclaimed.add_argument("--at", required=True)

    verify_publication = subparsers.add_parser("verify-publication")
    verify_publication.add_argument("--repository", required=True)
    verify_publication.add_argument("--status-comment-id", type=int, required=True)
    verify_publication.add_argument("--trusted-bot-id", type=int, required=True)
    verify_publication.add_argument("--idempotency-key", required=True)
    verify_publication.add_argument("--run-id", required=True)
    verify_publication.add_argument("--workflow-run-id", type=int, required=True)
    verify_publication.add_argument("--nonce", required=True)
    verify_publication.add_argument("--at", required=True)

    maintain = subparsers.add_parser("maintain")
    maintain.add_argument("--repository", required=True)
    maintain.add_argument("--trusted-bot-id", type=int, required=True)
    maintain.add_argument("--at", required=True)

    subparsers.add_parser("check")
    return parser


def _emit(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _load(path: Path, kind: str) -> JsonObject:
    return load_json_object(path, kind=kind)


def _load_list(path: Path, kind: str) -> list[JsonObject]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ControlPlaneError(
            "invalid_json",
            f"{kind} is not readable valid JSON.",
            {"error_type": type(error).__name__},
        ) from None
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ControlPlaneError("invalid_json_type", f"{kind} must be a JSON array of objects.")
    return value


def _validate_contract(
    document: JsonObject,
    *,
    contracts: ControlContracts,
    schema_name: str,
    kind: str,
) -> None:
    schema = load_json_object(
        contracts.contract_root / ".ai" / "schemas" / schema_name,
        kind=f"{kind} schema",
    )
    validate_document(document, schema, kind=kind)


def _actor(event: JsonObject) -> JsonObject:
    comment = event.get("comment")
    if isinstance(comment, dict) and isinstance(comment.get("user"), dict):
        actor: JsonObject = comment["user"]
        return actor
    sender = event.get("sender")
    if isinstance(sender, dict):
        return sender
    raise ControlPlaneError("invalid_event", "GitHub event actor facts are incomplete.")


def _github_client() -> GitHubRestClient:
    """Load only the workflow's GitHub token at the API mutation boundary."""

    return GitHubRestClient(
        os.environ.get("GITHUB_TOKEN", ""),
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run one adapter command with sanitized JSON results and stable exits."""

    args = build_parser().parse_args(arguments)
    try:
        contracts = ControlContracts(args.contract_root)
        command_name = str(args.command_name)
        if command_name == "check":
            _emit(
                {
                    "ok": True,
                    "authorization_policy_version": contracts.authorization_policy[
                        "policy_version"
                    ],
                    "execution_policy_version": contracts.execution_policy["policy_version"],
                }
            )
            return 0
        if command_name == "parse-command":
            result = parse_event(_load(args.event, "GitHub event"), contracts)
            _emit(result)
            return 0 if result["ok"] else 2
        if command_name == "authorize":
            event = _load(args.event, "GitHub event")
            actor = _actor(event)
            teams: list[str] = []
            if args.teams is not None:
                team_doc = _load(args.teams, "GitHub teams")
                raw_teams = team_doc.get("teams", [])
                if not isinstance(raw_teams, list) or not all(
                    isinstance(item, str) for item in raw_teams
                ):
                    raise ControlPlaneError("invalid_teams", "GitHub team facts are invalid.")
                teams = raw_teams
            result = authorize(
                actor_login=str(actor["login"]),
                actor_id=int(actor["id"]),
                actor_type=str(actor["type"]),
                permission=_load(args.permission, "GitHub permission"),
                team_slugs=teams,
                contracts=contracts,
            )
            _emit({"ok": result["outcome"] == "allowed", **result})
            return 0 if result["outcome"] == "allowed" else 3
        if command_name == "build-trigger":
            command_result = _load(args.command, "parsed command")
            command = command_result.get("command_document", command_result)
            if not isinstance(command, dict):
                raise ControlPlaneError("invalid_command", "Parsed command is invalid.")
            result = build_trigger(
                event=_load(args.event, "GitHub event"),
                command=command,
                authorization=_load(args.authorization, "authorization decision"),
                target=_load(args.target, "GitHub target"),
                trusted_tool_sha=args.trusted_tool_sha,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
                delivery_id=args.delivery_id,
                timestamp=args.timestamp,
                contracts=contracts,
            )
            _emit(result)
            return 0
        if command_name == "idempotency-key":
            trigger = _load(args.trigger, "GitHub trigger")
            contracts.validate("trigger", trigger)
            _emit(
                {
                    "ok": True,
                    "idempotency_key": effective_idempotency_key(
                        trigger, contracts.execution_policy
                    ),
                    "run_id": execution_run_id(trigger, contracts.execution_policy),
                }
            )
            return 0
        if command_name == "transition":
            _emit(
                transition_state(
                    _load(args.state, "GitHub state"),
                    _load(args.transition, "GitHub transition"),
                    contracts=contracts,
                )
            )
            return 0
        if command_name == "render-status":
            state = _load(args.state, "GitHub state")
            _emit({"ok": True, "body": render_status(state, contracts), "state": state})
            return 0
        if command_name == "build-run-request":
            contract_root = contracts.contract_root
            _emit(
                build_run_request(
                    _load(args.trigger, "GitHub trigger"),
                    contract_root=contract_root,
                    target_root=args.target_root,
                    packet_path=args.packet,
                    packet_provenance_path=args.packet_provenance,
                    planning_packet_path=args.planning_packet,
                    context_manifest_path=args.context_manifest,
                    implementation_packet_path=args.implementation_packet,
                    implementation_manifest_path=args.implementation_manifest,
                    implementation_task_plan_path=args.implementation_task_plan,
                    workspace_path=args.workspace,
                    workspace_binding_path=args.workspace_binding,
                )
            )
            return 0
        if command_name == "build-planning-packet":
            trigger = _load(args.trigger, "GitHub trigger")
            issue = _load(args.issue, "GitHub issue")
            comments = _load_list(args.comments, "GitHub issue comments") if args.comments else []
            result = build_planning_packet(
                trigger=trigger,
                issue=issue,
                contract_root=contracts.contract_root,
                output_dir=args.output_dir,
                run_id=str(
                    trigger.get("run_id") or execution_run_id(trigger, contracts.execution_policy)
                ),
                comments=comments,
                contracts=contracts,
                trusted_bot_id=args.trusted_bot_id,
            )
            _emit({"ok": True, **result})
            return 0
        if command_name == "build-implementation-packet":
            trigger = _load(args.trigger, "GitHub trigger")
            issue = _load(args.issue, "GitHub issue")
            result = build_implementation_packet(
                trigger=trigger,
                issue=issue,
                contract_root=contracts.contract_root,
                output_dir=args.output_dir,
                run_id=str(
                    trigger.get("run_id") or execution_run_id(trigger, contracts.execution_policy)
                ),
                change_name=args.change_name,
                planning_pr_merged=args.planning_pr_merged,
                approval_actor_id=args.approval_actor_id,
            )
            _emit({"ok": True, **result})
            return 0
        if command_name == "materialize-plan":
            result = _load(args.result, "planning result")
            validate_planning_result(result, contract_root=contracts.contract_root)
            _emit(
                {
                    "ok": True,
                    **materialize_plan(
                        result,
                        publication_root=args.publication_root,
                        issue_number=args.issue_number,
                        run_id=args.run_id,
                    ),
                }
            )
            return 0
        if command_name == "validate-implementation-result":
            result = _load(args.result, "implementation result")
            task_plan = _load(args.task_plan, "implementation task plan")
            _validate_contract(
                result,
                contracts=contracts,
                schema_name="countyforge-implementation-result.schema.json",
                kind="implementation result",
            )
            _validate_contract(
                task_plan,
                contracts=contracts,
                schema_name="countyforge-implementation-task-plan.schema.json",
                kind="implementation task plan",
            )
            events = _load_command_events(
                args.command_events,
                contracts.contract_root
                / ".ai"
                / "schemas"
                / "countyforge-implementation-command-event.schema.json",
            )
            validate_implementation_result(
                result,
                workspace_root=args.workspace,
                expected_revision=args.expected_revision,
            )
            changed_paths = [
                str(path)
                for field in ("files_created", "files_modified", "files_deleted")
                for path in result.get(field, [])
            ]
            validate_implementation_tasks(
                result,
                task_plan,
                trusted_command_events=events,
                changed_paths=changed_paths,
            )
            _emit({"ok": True, "publication_eligibility": "trusted_validation_required"})
            return 0
        if command_name == "validate-implementation-context":
            packet = _load(args.packet, "implementation packet")
            manifest = _load(args.manifest, "implementation context manifest")
            task_plan = _load(args.task_plan, "implementation task plan")
            for document, schema_name, kind in (
                (
                    packet,
                    "countyforge-implementation-packet.schema.json",
                    "implementation packet",
                ),
                (
                    manifest,
                    "countyforge-implementation-context-manifest.schema.json",
                    "implementation context manifest",
                ),
                (
                    task_plan,
                    "countyforge-implementation-task-plan.schema.json",
                    "implementation task plan",
                ),
            ):
                _validate_contract(
                    document, contracts=contracts, schema_name=schema_name, kind=kind
                )
            _emit({"ok": True, "validated": ["packet", "manifest", "task_plan"]})
            return 0
        if command_name == "validate-implementation-artifact":
            result = _load(args.result, "implementation result")
            manifest = _load(args.manifest, "implementation workspace manifest")
            _validate_contract(
                result,
                contracts=contracts,
                schema_name="countyforge-implementation-result.schema.json",
                kind="implementation result",
            )
            _validate_contract(
                manifest,
                contracts=contracts,
                schema_name="countyforge-implementation-workspace-manifest.schema.json",
                kind="implementation workspace manifest",
            )
            validate_implementation_artifact(
                result,
                manifest,
                workspace_root=args.workspace,
                policy_root=args.policy_root,
                expected_run_id=args.run_id,
                expected_issue_number=args.issue_number,
                expected_change_name=args.change_name,
                expected_base_sha=args.base_sha,
            )
            _emit({"ok": True, "publication_eligibility": "trusted_validation_required"})
            return 0
        if command_name == "freeze-implementation-artifact":
            result = _load(args.result, "implementation result")
            _validate_contract(
                result,
                contracts=contracts,
                schema_name="countyforge-implementation-result.schema.json",
                kind="implementation result",
            )
            manifest = freeze_implementation_artifact(
                result,
                workspace_root=args.workspace,
                policy_root=args.policy_root,
                output_root=args.output,
                expected_run_id=args.run_id,
                expected_issue_number=args.issue_number,
                expected_change_name=args.change_name,
                expected_base_sha=args.base_sha,
            )
            _emit({"ok": True, "manifest": manifest})
            return 0
        if command_name == "publish-implementation":
            github = _github_client()
            implementation_result = _load(args.implementation_result, "implementation result")
            manifest_path = args.workspace / "countyforge-workspace-manifest.json"
            manifest = _load(manifest_path, "implementation workspace manifest")
            report = _load(args.validation_report, "implementation validation report")
            _validate_contract(
                implementation_result,
                contracts=contracts,
                schema_name="countyforge-implementation-result.schema.json",
                kind="implementation result",
            )
            _validate_contract(
                manifest,
                contracts=contracts,
                schema_name="countyforge-implementation-workspace-manifest.schema.json",
                kind="implementation workspace manifest",
            )
            _validate_contract(
                report,
                contracts=contracts,
                schema_name="countyforge-implementation-validation-report.schema.json",
                kind="implementation validation report",
            )
            if (
                report.get("run_id") != args.run_id
                or report.get("issue_number") != args.issue_number
                or report.get("change_name") != args.change_name
                or report.get("base_sha") != args.base_sha
                or report.get("artifact_sha256") != file_sha256(args.implementation_result)
                or report.get("workspace_manifest_sha256") != file_sha256(manifest_path)
                or report.get("valid") is not True
                or report.get("publication_eligible") is not True
            ):
                raise ControlPlaneError(
                    "implementation_validation_failed",
                    "Trusted implementation validation is not publication-eligible.",
                )
            result = publish_implementation(
                github,
                repository=args.repository,
                issue_number=args.issue_number,
                change_name=args.change_name,
                revision=args.revision,
                base_sha=args.base_sha,
                run_id=args.run_id,
                workspace=args.workspace,
                evidence_url=args.evidence_url,
                implementation_result=implementation_result,
                policy_root=args.policy_root,
                publication_preflight=lambda: verify_publication_lease(
                    github,
                    repository=args.repository,
                    status_comment_id=args.status_comment_id,
                    trusted_bot_id=args.trusted_bot_id,
                    idempotency_key=args.idempotency_key,
                    run_id=args.run_id,
                    workflow_run_id=args.workflow_run_id,
                    nonce=args.nonce,
                    at=args.at,
                ),
            )
            publication_manifest = {
                "contract_version": 1,
                "run_id": args.run_id,
                "issue_number": args.issue_number,
                "change_name": args.change_name,
                "revision": args.revision,
                "base_sha": args.base_sha,
                "branch": result["branch"],
                "commit_sha": result["commit_sha"],
                "draft_pr_number": result["pr_number"],
                "validation_report_sha256": file_sha256(args.validation_report),
            }
            _validate_contract(
                publication_manifest,
                contracts=contracts,
                schema_name="countyforge-implementation-publication-manifest.schema.json",
                kind="implementation publication manifest",
            )
            _emit({"ok": True, **result, "publication_manifest": publication_manifest})
            return 0
        if command_name == "validate-implementation-report":
            report = _load(args.report, "implementation validation report")
            _validate_contract(
                report,
                contracts=contracts,
                schema_name="countyforge-implementation-validation-report.schema.json",
                kind="implementation validation report",
            )
            _emit({"ok": True, "report": report})
            return 0
        if command_name == "run-implementation-command":
            broker = CommandBroker(args.registry, args.schema)
            evidence = broker.run(
                args.command_id,
                workspace=args.workspace,
                contract_root=args.contract_root,
                run_id=args.run_id,
                workspace_revision=args.workspace_revision,
            )
            _emit({"ok": int(evidence["exit_code"]) == 0, "evidence": evidence})
            return 0 if int(evidence["exit_code"]) == 0 else 5
        if command_name == "publish-plan":
            result = _load(args.result, "planning result")
            _emit(
                publish_plan(
                    _github_client(),
                    repository=args.repository,
                    default_branch=args.default_branch,
                    target_sha=args.target_sha,
                    issue_number=args.issue_number,
                    run_id=args.run_id,
                    result=result,
                    publication_root=args.publication_root,
                    planning_packet_path=args.planning_packet,
                    context_manifest_path=args.context_manifest,
                    evidence_url=args.evidence_url,
                    already_materialized=args.already_materialized,
                )
            )
            return 0
        if command_name == "reconcile":
            _emit(
                reconcile_workflow(
                    _load(args.state, "GitHub state"),
                    _load(args.workflow, "GitHub workflow"),
                    args.at,
                )
            )
            return 0
        if command_name == "resolve-terminal-result":
            _emit(
                resolve_terminal_result(
                    command=args.command,
                    result_path=args.result,
                    exit_code_path=args.exit_code,
                )
            )
            return 0
        if command_name == "intake":
            github = _github_client()
            result = process_intake(
                _load(args.event, "GitHub event"),
                github,
                trusted_tool_sha=args.trusted_tool_sha,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
                default_branch=args.default_branch,
                trusted_bot_id=args.trusted_bot_id,
                delivery_id=args.delivery_id,
                at=args.at,
                contracts=contracts,
            )
            _emit(result)
            return 0 if result["ok"] else 3
        if command_name == "claim-run":
            state = claim_run(
                _github_client(),
                repository=args.repository,
                status_comment_id=args.status_comment_id,
                trusted_bot_id=args.trusted_bot_id,
                idempotency_key=args.idempotency_key,
                run_id=args.run_id,
                workflow_run_id=args.workflow_run_id,
                workflow_run_attempt=args.workflow_run_attempt,
                at=args.at,
            )
            event = state_event(
                state,
                event_type="lease_acquired",
                authorization_outcome="not_applicable",
                outcome="pending",
                disposition="lease_acquired",
                timestamp=args.at,
            )
            _emit(
                with_audit(
                    {"ok": True, "state": state, "nonce": state["lease"]["nonce"]},
                    [event],
                )
            )
            return 0
        if command_name == "advance-run":
            state = advance_run(
                _github_client(),
                repository=args.repository,
                status_comment_id=args.status_comment_id,
                trusted_bot_id=args.trusted_bot_id,
                idempotency_key=args.idempotency_key,
                run_id=args.run_id,
                workflow_run_id=args.workflow_run_id,
                nonce=args.nonce,
                target_state=args.target_state,
                at=args.at,
                disposition=args.disposition,
                evidence_url=args.evidence_url,
                planning_change_name=args.planning_change_name,
                planning_branch=args.planning_branch,
                planning_pr_number=args.planning_pr_number,
                planning_context_sha256=args.planning_context_sha256,
                planning_result_sha256=args.planning_result_sha256,
                implementation_change_name=args.implementation_change_name,
                implementation_revision=args.implementation_revision,
                implementation_branch=args.implementation_branch,
                implementation_pr_number=args.implementation_pr_number,
                implementation_completed_task_count=args.implementation_completed_task_count,
                implementation_incomplete_task_count=args.implementation_incomplete_task_count,
                implementation_blocked_task_count=args.implementation_blocked_task_count,
                implementation_eligible=(
                    args.implementation_eligible == "true"
                    if args.implementation_eligible is not None
                    else None
                ),
            )
            terminal = state["lifecycle_state"] in {
                "succeeded",
                "failed",
                "cancelled",
                "timed_out",
                "stale",
                "not_implemented",
            }
            events = [
                state_event(
                    state,
                    event_type="terminal_outcome" if terminal else "state_reconciled",
                    authorization_outcome="not_applicable",
                    outcome=outcome_for_state(str(state["lifecycle_state"])),
                    disposition=str(state["disposition"] or args.disposition),
                    timestamp=args.at,
                )
            ]
            if terminal:
                events.append(
                    state_event(
                        state,
                        event_type="lease_released",
                        authorization_outcome="not_applicable",
                        outcome=outcome_for_state(str(state["lifecycle_state"])),
                        disposition="lease_released",
                        timestamp=args.at,
                    )
                )
            _emit(with_audit({"ok": True, "state": state}, events))
            return 0
        if command_name == "maintain":
            _emit(
                audit_expired_leases(
                    _github_client(),
                    repository=args.repository,
                    trusted_bot_id=args.trusted_bot_id,
                    at=args.at,
                )
            )
            return 0
        if command_name == "fail-unclaimed-run":
            state = fail_unclaimed_run(
                _github_client(),
                repository=args.repository,
                status_comment_id=args.status_comment_id,
                trusted_bot_id=args.trusted_bot_id,
                idempotency_key=args.idempotency_key,
                run_id=args.run_id,
                at=args.at,
            )
            event = state_event(
                state,
                event_type=(
                    "terminal_outcome"
                    if state["lifecycle_state"] == "failed"
                    else "state_reconciled"
                ),
                authorization_outcome="not_applicable",
                outcome=outcome_for_state(str(state["lifecycle_state"])),
                disposition=str(state["disposition"] or "workflow_claim_failed"),
                timestamp=args.at,
            )
            _emit(with_audit({"ok": True, "state": state}, [event]))
            return 0
        if command_name == "verify-publication":
            state = verify_publication_lease(
                _github_client(),
                repository=args.repository,
                status_comment_id=args.status_comment_id,
                trusted_bot_id=args.trusted_bot_id,
                idempotency_key=args.idempotency_key,
                run_id=args.run_id,
                workflow_run_id=args.workflow_run_id,
                nonce=args.nonce,
                at=args.at,
            )
            _emit({"ok": True, "state": state})
            return 0
        raise ControlPlaneError("unknown_command", "Unknown CountyForge adapter command.")
    except (ControlPlaneError, KernelError) as error:
        _emit(error.as_document())
        return error.exit_code
    except Exception:  # noqa: BLE001 - sanitize every workflow boundary failure
        unexpected_error = ControlPlaneError(
            "internal_error",
            "CountyForge GitHub control failed unexpectedly.",
            exit_code=5,
        )
        _emit(unexpected_error.as_document())
        return unexpected_error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
