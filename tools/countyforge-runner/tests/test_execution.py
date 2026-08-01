"""Fail-closed execution, evidence, credentials, and legacy adapter dispatch."""

from __future__ import annotations

import copy
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from countyforge_runner.cli import main
from countyforge_runner.contracts import JsonObject, validate_document
from countyforge_runner.errors import KernelError
from countyforge_runner.executor import Runner, _output_bytes, _safe_branch
from countyforge_runner.resolver import Kernel


def _valid_plan_document() -> JsonObject:
    return {
        "contract_version": 1,
        "status": "planned",
        "originating_issue": 1,
        "proposed_change_name": "safe-plan",
        "issue_classification": "feature_work",
        "problem_statement": "A bounded problem.",
        "desired_outcome": "A plan.",
        "assumptions": ["Trusted contracts"],
        "unresolved_decisions": [],
        "affected_capabilities": ["runner"],
        "files_to_create": ["openspec/changes/safe-plan/proposal.md"],
        "files_to_modify": [],
        "proposed_files": ["openspec/changes/safe-plan/proposal.md"],
        "task_slices": ["Write contracts"],
        "acceptance_criteria": ["It validates"],
        "risks": ["Injection"],
        "security_privacy_considerations": ["Read-only"],
        "migration_compatibility_concerns": ["None"],
        "validation_commands": ["openspec validate"],
        "non_goals": ["Implementation"],
        "implementation_eligibility": False,
        "blocked_reasons": [],
        "evidence_citations": [{"source_id": "s", "excerpt": "evidence"}],
    }


def _write_plan_adapter(path: Path, result: JsonObject | str) -> Path:
    body = result if isinstance(result, str) else json.dumps(result, sort_keys=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'mkdir -p "$OUT_DIR"\n'
        "cat > \"$OUT_DIR/countyforge-plan-result.json\" <<'EOF'\n"
        f"{body}\n"
        "EOF\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _json_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    raise AssertionError(f"unsupported JSON value type: {type(value).__name__}")


def _resolve_schema_reference(schema: JsonObject, root: JsonObject) -> JsonObject:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    assert isinstance(reference, str) and reference.startswith("#/$defs/")
    resolved: object = root
    for component in reference.removeprefix("#/").split("/"):
        assert isinstance(resolved, dict)
        resolved = resolved[component]
    assert isinstance(resolved, dict)
    return resolved


def _effective_schema_type(schema: JsonObject) -> str:
    declared_type = schema.get("type")
    if declared_type is not None:
        assert isinstance(declared_type, str)
        return declared_type
    if "const" in schema:
        return _json_type(schema["const"])
    enum = schema.get("enum")
    assert isinstance(enum, list) and enum
    enum_types = {_json_type(value) for value in enum}
    assert len(enum_types) == 1
    return enum_types.pop()


def _assert_generation_structure(
    generation: JsonObject,
    authoritative: JsonObject,
    *,
    authoritative_root: JsonObject,
    path: str = "$",
) -> None:
    authoritative = _resolve_schema_reference(authoritative, authoritative_root)
    expected_type = _effective_schema_type(authoritative)
    assert generation.get("type") == expected_type, f"{path}: type drift"
    if "enum" in authoritative:
        assert generation.get("enum") == authoritative["enum"], f"{path}: enum drift"
    else:
        assert "enum" not in generation, f"{path}: unexpected enum"

    if expected_type == "object":
        assert generation.get("additionalProperties") == authoritative.get(
            "additionalProperties"
        ), f"{path}: closed-object posture drift"
        generation_properties = generation.get("properties")
        authoritative_properties = authoritative.get("properties")
        assert isinstance(generation_properties, dict)
        assert isinstance(authoritative_properties, dict)
        assert set(generation_properties) == set(authoritative_properties), (
            f"{path}: property drift"
        )
        assert set(generation.get("required", [])) == set(authoritative.get("required", [])), (
            f"{path}: required-field drift"
        )
        for name in sorted(authoritative_properties):
            generation_child = generation_properties[name]
            authoritative_child = authoritative_properties[name]
            assert isinstance(generation_child, dict)
            assert isinstance(authoritative_child, dict)
            _assert_generation_structure(
                generation_child,
                authoritative_child,
                authoritative_root=authoritative_root,
                path=f"{path}.{name}",
            )
    elif expected_type == "array":
        generation_items = generation.get("items")
        authoritative_items = authoritative.get("items")
        assert isinstance(generation_items, dict)
        assert isinstance(authoritative_items, dict)
        _assert_generation_structure(
            generation_items,
            authoritative_items,
            authoritative_root=authoritative_root,
            path=f"{path}[]",
        )


@pytest.mark.parametrize("mode", ["fix", "validate"])
def test_unimplemented_profiles_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
    mode: str,
) -> None:
    sentinel = "provider-sentinel-value-that-must-never-leak"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("SAKANA_API_KEY", sentinel)
    kernel = Kernel()
    resolved = kernel.resolve(request_factory(mode))
    document, exit_code = Runner(kernel, evidence_root=tmp_path / "evidence").run(resolved)
    assert exit_code == 4
    assert document["disposition"] == "profile_not_implemented"
    assert document["summary"]["outcome"] == "not_executed"
    run_dir = tmp_path / "evidence" / mode / f"fixture-{mode}"
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    assert sentinel not in all_text


def test_implemented_profile_requires_frozen_context_before_provider_execution(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    kernel = Kernel()
    request = request_factory("implement")
    request["input"].pop("implementation_packet_path")
    with pytest.raises(KernelError, match="schema_validation_failed"):
        kernel.resolve(request)


def test_implementation_dispatches_isolated_adapter_with_structured_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    adapter = tmp_path / "implementation-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test -n "${OPENAI_API_KEY:-}"\n'
        'test -z "${SAKANA_API_KEY:-}"\n'
        'mkdir -p "$OUT_DIR"\n'
        "cat > \"$OUT_DIR/countyforge-implementation-result.json\" <<'JSON'\n"
        '{"contract_version":1,"status":"partial","repository":"TruPryce/property-tax-data-platform",'
        '"issue_number":1,"openspec_change":"build-mode-aware-runner-kernel",'
        '"run_id":"fixture-implement","implementation_revision":1,"base_sha":"'
        + subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        + '","profile":{"id":"implement.workspace-write.v1","version":1,"provider":"openai",'
        '"model_ref":"openai.gpt-5.6","reasoning_effort":"high"},"completed_task_ids":[],'
        '"incomplete_task_ids":["1.1"],"blocked_task_ids":[],"files_created":[],"files_modified":[],"file_bundle":[],'
        '"files_deleted":[],"diff":{"files":0,"bytes_added":0,"bytes_deleted":0},"tests_run":[],'
        '"command_evidence":[],"validation_results":[],"deviations":[],"residual_risks":[],'
        '"dependency_changes":[],"migration_changes":[],"security_sensitive_changes":[],'
        '"publication_eligibility":"trusted_validation_required","blocked_reasons":[],"output_artifact_hashes":{}}\n'
        "JSON\n",
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    monkeypatch.setenv("OPENAI_API_KEY", "implementation-fixture-secret")
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("implement"))
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", implementation_adapter=adapter
    ).run(resolved)
    assert exit_code == 0
    assert document["ok"] is True
    assert document["mode"] == "implement"
    assert document["implementation"]["incomplete_task_ids"] == ["1.1"]


def test_implementation_evidence_removes_provider_bearing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    adapter = tmp_path / "leaking-implementation-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'mkdir -p "$OUT_DIR"\n'
        'printf "%s" "$OPENAI_API_KEY" > "$OUT_DIR/leaked-output.log"\n'
        "exit 1\n",
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    secret = "implementation-output-fixture-secret"  # pragma: allowlist secret
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", implementation_adapter=adapter
    ).run(kernel.resolve(request_factory("implement")))
    assert exit_code == 5
    run_dir = Path(document["run_dir"])
    all_text = "\n".join(
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
    )
    assert secret not in all_text
    assert not (run_dir / "leaked-output.log").exists()


def test_unimplemented_execution_has_no_global_credential_lookup() -> None:
    evidence_source = Path("tools/countyforge-runner/src/countyforge_runner/evidence.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("OPENAI_API_KEY"' not in evidence_source
    assert 'os.environ.get("SAKANA_API_KEY"' not in evidence_source


def _fake_adapter(path: Path, expected_provider: str) -> Path:
    credential_check = (
        'test -n "${SAKANA_API_KEY:-}" && test -z "${OPENAI_API_KEY:-}"'
        if expected_provider == "sakana"
        else 'test -n "${OPENAI_API_KEY:-}" && test -z "${SAKANA_API_KEY:-}"'
    )
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{credential_check}\n"
        'mkdir -p "$OUT_DIR"\n'
        'cp "$PACKET_PATH" "$OUT_DIR/review-packet.md"\n'
        'printf \'%s\\n\' \'{"verdict":"pass"}\' > "$OUT_DIR/codex-prepr-review.md"\n'
        "printf '%s\\n' "
        '\'{"image_id":"sha256:fixture","codex_cli_version":"0.144.6"}\' '
        '> "$OUT_DIR/container.provenance.json"\n'
        'printf \'%s\\n\' \'{"status":"succeeded","exit_code":0}\' > "$OUT_DIR/run.summary.json"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    ("provider", "model_ref"),
    [("sakana", "sakana.fugu-ultra"), ("openai", "openai.gpt-5.6")],
)
def test_review_dispatches_existing_adapter_with_one_provider_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
    provider: str,
    model_ref: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fixture-secret-value")
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-fixture-secret-value")
    request = request_factory("review")
    request["run_id"] = f"review-{provider}"
    request["provider"] = {
        "id": provider,
        "model_ref": model_ref,
        "codex_cli_version": "0.144.6",
    }
    kernel = Kernel()
    adapter = _fake_adapter(tmp_path / f"adapter-{provider}.sh", provider)
    document, exit_code = Runner(
        kernel,
        evidence_root=tmp_path / "evidence",
        review_adapter=adapter,
    ).run(kernel.resolve(request))
    assert exit_code == 0
    assert document["disposition"] == "completed"
    run_dir = Path(document["run_dir"])
    assert (run_dir / "codex-prepr-review.md").is_file()
    assert (run_dir / "countyforge-run-event.ndjson").is_file()
    legacy = json.loads((run_dir / "run.summary.json").read_text(encoding="utf-8"))
    generic = json.loads((run_dir / "countyforge-run-summary.json").read_text(encoding="utf-8"))
    assert legacy["status"] == "succeeded"
    assert generic["outcome"] == "succeeded"
    assert generic["run_id"] == request["run_id"]
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir())
    assert "openai-fixture-secret-value" not in all_text
    assert "sakana-fixture-secret-value" not in all_text


def test_plan_dispatches_read_only_adapter_with_one_provider_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-plan-secret-value")
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-unused-plan-secret")
    adapter = tmp_path / "plan-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'test -n "${OPENAI_API_KEY:-}" && test -z "${SAKANA_API_KEY:-}"\n'
        'test "$(basename "$GENERATION_SCHEMA_PATH")" = "countyforge-plan-generation.schema.json"\n'
        'test "$RESULT_SCHEMA_NAME" = "countyforge-plan-result.schema.json"\n'
        'test "$(sha256sum "$GENERATION_SCHEMA_PATH" | cut -d" " -f1)" = '
        '"$EXPECTED_GENERATION_SCHEMA_SHA256"\n'
        'test "$EXPECTED_GENERATION_SCHEMA_SHA256" != "$EXPECTED_OUTPUT_SCHEMA_SHA256"\n'
        'mkdir -p "$OUT_DIR"\n'
        "cat > \"$OUT_DIR/countyforge-plan-result.json\" <<'JSON'\n"
        '{"contract_version":1,"status":"planned","originating_issue":1,"proposed_change_name":"safe-plan",'
        '"issue_classification":"feature_work","problem_statement":"A bounded problem.",'
        '"desired_outcome":"A plan.","assumptions":["Trusted contracts"],'
        '"unresolved_decisions":[],"affected_capabilities":["runner"],'
        '"files_to_create":["openspec/changes/safe-plan/proposal.md"],'
        '"files_to_modify":[],"proposed_files":["openspec/changes/safe-plan/proposal.md"],'
        '"task_slices":["Write contracts"],"acceptance_criteria":["It validates"],'
        '"risks":["Injection"],'
        '"security_privacy_considerations":["Read-only"],'
        '"migration_compatibility_concerns":["None"],"validation_commands":["openspec validate"],'
        '"non_goals":["Implementation"],"implementation_eligibility":false,"blocked_reasons":[],"evidence_citations":[{"source_id":"s","excerpt":"evidence"}]}\n'
        "JSON",
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("plan"))
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", plan_adapter=adapter
    ).run(resolved)
    assert exit_code == 0
    assert document["disposition"] == "completed"
    assert document["plan"]["implementation_eligibility"] is False
    snapshot = json.loads(
        (
            tmp_path / "evidence" / "plan" / resolved.run_id / "countyforge-profile.snapshot.json"
        ).read_text(encoding="utf-8")
    )
    assert snapshot["generation_schema_sha256"] == resolved.generation_schema_sha256
    assert snapshot["output_schema_sha256"] == resolved.output_schema_sha256


def test_plan_generation_schema_uses_provider_compatible_subset() -> None:
    generation = json.loads(
        Path(".ai/schemas/countyforge-plan-generation.schema.json").read_text(encoding="utf-8")
    )
    authoritative = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    keywords: set[str] = set()

    def collect(schema: object) -> None:
        if not isinstance(schema, dict):
            return
        for keyword, value in schema.items():
            keywords.add(keyword)
            if keyword == "properties":
                for property_schema in value.values():
                    collect(property_schema)
            elif keyword == "items":
                collect(value)

    collect(generation)
    assert keywords <= {
        "type",
        "enum",
        "properties",
        "required",
        "additionalProperties",
        "items",
    }
    assert generation["required"] == authoritative["required"]
    assert set(generation["properties"]) == set(authoritative["properties"])
    _assert_generation_structure(
        generation,
        authoritative,
        authoritative_root=authoritative,
    )
    validate_document(_valid_plan_document(), generation, kind="planning generation fixture")
    validate_document(_valid_plan_document(), authoritative, kind="planning result fixture")


@pytest.mark.parametrize("drift", ["nested", "type", "enum"])
def test_plan_generation_schema_structure_drift_fails(drift: str) -> None:
    generation = json.loads(
        Path(".ai/schemas/countyforge-plan-generation.schema.json").read_text(encoding="utf-8")
    )
    authoritative = json.loads(
        Path(".ai/schemas/countyforge-plan-result.schema.json").read_text(encoding="utf-8")
    )
    changed = copy.deepcopy(generation)
    if drift == "nested":
        del changed["properties"]["evidence_citations"]["items"]["properties"]["excerpt"]
    elif drift == "type":
        changed["properties"]["problem_statement"]["type"] = "integer"
    else:
        changed["properties"]["status"]["enum"] = ["planned", "blocked"]
    with pytest.raises(AssertionError):
        _assert_generation_structure(
            changed,
            authoritative,
            authoritative_root=authoritative,
        )


def test_plan_generation_output_still_requires_authoritative_validation(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    document = _valid_plan_document()
    document["proposed_change_name"] = "INVALID CHANGE NAME"
    generation = json.loads(
        Path(".ai/schemas/countyforge-plan-generation.schema.json").read_text(encoding="utf-8")
    )
    validate_document(document, generation, kind="planning generation fixture")
    adapter = _write_plan_adapter(tmp_path / "plan-adapter.sh", document)
    kernel = Kernel()
    result, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", plan_adapter=adapter
    ).run(kernel.resolve(request_factory("plan")))
    assert exit_code == 5
    assert result["disposition"] == "validation_failed"
    assert "plan" not in result


def test_plan_provider_generation_sentinel_has_specific_disposition(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    adapter = _write_plan_adapter(tmp_path / "plan-adapter.sh", "Error generating response")
    kernel = Kernel()
    result, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", plan_adapter=adapter
    ).run(kernel.resolve(request_factory("plan")))
    assert exit_code == 5
    assert result["disposition"] == "provider_generation_failed"
    assert result["summary"]["error_code"] == "provider_generation_failed"
    assert "plan" not in result


def test_plan_provider_generation_sentinel_must_match_exactly(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    adapter = _write_plan_adapter(tmp_path / "plan-adapter.sh", " Error generating response")
    kernel = Kernel()
    result, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", plan_adapter=adapter
    ).run(kernel.resolve(request_factory("plan")))
    assert exit_code == 5
    assert result["disposition"] == "validation_failed"


def test_plan_profile_mounts_match_adapter_and_provenance_contract() -> None:
    profile = json.loads(Path(".ai/profiles/plan.read-only.v1.json").read_text(encoding="utf-8"))
    mounts = {
        (mount["source"], mount["target"], mount["access"])
        for mount in profile["filesystem_mounts"]
    }
    assert ("schema_directory", "/workspace/.ai/schemas", "read_only") in mounts
    assert ("frozen_planning_packet", "/workspace/packet.json", "read_only") in mounts
    assert ("frozen_context_manifest", "/workspace/manifest.json", "read_only") in mounts
    assert ("claimed_output_directory", "/out", "read_write") in mounts
    adapter = Path(".ai/codex/08-run-countyforge-plan-docker.sh").read_text(encoding="utf-8")
    assert '-v "$PACKET_PATH:/workspace/packet.json:ro"' in adapter
    assert '-v "$MANIFEST_PATH:/workspace/manifest.json:ro"' in adapter
    assert '"frozen_planning_packet:/workspace/packet.json:read_only"' in adapter
    assert '"frozen_context_manifest:/workspace/manifest.json:read_only"' in adapter
    assert '--output-schema "$CONTAINER_GENERATION_SCHEMA"' in adapter
    assert '"$EXPECTED_GENERATION_SCHEMA_SHA256"' in adapter
    assert '"$EXPECTED_OUTPUT_SCHEMA_SHA256"' in adapter
    assert '"generation_schema_sha256": generation_schema_sha' in adapter
    assert '"result_schema_sha256": result_schema_sha' in adapter


def test_implementation_profile_mounts_match_adapter_and_provenance_contract() -> None:
    profile = json.loads(
        Path(".ai/profiles/implement.workspace-write.v1.json").read_text(encoding="utf-8")
    )
    mounts = {
        (mount["source"], mount["target"], mount["access"])
        for mount in profile["filesystem_mounts"]
    }
    expected = {
        ("frozen_implementation_packet", "/workspace/implementation-packet.json", "read_only"),
        ("frozen_implementation_manifest", "/workspace/implementation-manifest.json", "read_only"),
        (
            "frozen_implementation_task_plan",
            "/workspace/implementation-task-plan.json",
            "read_only",
        ),
        (
            "frozen_implementation_result_schema",
            "/workspace/implementation-result.schema.json",
            "read_only",
        ),
        (
            "frozen_implementation_command_policy",
            "/workspace/implementation-commands.json",
            "read_only",
        ),
        ("implementation_model_workspace", "/workspace", "read_write"),
        ("claimed_output_directory", "/out", "read_write"),
    }
    assert mounts == expected
    adapter = Path(".ai/codex/09-run-countyforge-implement-docker.sh").read_text(encoding="utf-8")
    for source, target, access in expected:
        assert f'"{source}:{target}:{access}"' in adapter
    assert '"python:3.12-alpine@sha256:' in adapter
    assert 'MODEL_PROMPT="$OUT_DIR/implementation-prompt.md"' in adapter
    assert "pathlib.Path(prompt_path).read_text" in adapter
    assert ' < "$MODEL_PROMPT"' in adapter
    # Prompt assembly moved into the tested builder; the mandatory sections and
    # snapshot exclusions are asserted there, where they can be exercised.
    builder = Path(
        "tools/countyforge-runner/src/countyforge_runner/implementation_prompt.py"
    ).read_text(encoding="utf-8")
    assert '"IMPLEMENTATION RESULT SCHEMA"' in builder
    assert '"IMPLEMENTATION COMMAND POLICY"' in builder
    for excluded in (".git", ".env", ".ai/policies", ".github/workflows"):
        assert f'"{excluded}"' in builder
    assert profile["model_input"] == {
        "mode": "bounded_stdin",
        "prompt_path": ".ai/prompts/countyforge-implement.v1.md",
        "maximum_model_input_chars": 950_000,
        "workspace_snapshot_max_bytes": 4 * 1024 * 1024,
        "contract_inputs": [
            "packet",
            "manifest",
            "task_plan",
            "result_schema",
            "command_policy",
            "source_snapshot",
        ],
    }


def test_generic_metrics_are_low_cardinality(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("validate"))
    document, _ = Runner(kernel, evidence_root=tmp_path).run(resolved)
    run_dir = tmp_path / "validate" / resolved.run_id
    metrics = (run_dir / "countyforge-run-metrics.prom").read_text(encoding="utf-8")
    forbidden = ["run_id=", "branch=", "sha=", "issue=", "path=", "error="]
    assert not any(label in metrics for label in forbidden)
    assert document["summary"]["disposition"] == "profile_not_implemented"


def test_generic_run_directory_collision_preserves_evidence(
    tmp_path: Path,
    request_factory: Callable[[str], JsonObject],
) -> None:
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("validate"))
    runner = Runner(kernel, evidence_root=tmp_path)
    runner.run(resolved)
    run_dir = tmp_path / "validate" / resolved.run_id
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    with pytest.raises(KernelError, match="run directory"):
        runner.run(resolved)
    after = {path.name: path.read_bytes() for path in run_dir.iterdir()}
    assert after == before


def test_review_profile_declares_no_repository_mount() -> None:
    profile = json.loads(
        Path(".ai/profiles/review.packet-only.v1.json").read_text(encoding="utf-8")
    )
    assert profile["repository_access"] == "none"
    assert profile["expected_security_posture"]["repository_mounted"] is False
    assert all(mount["source"] != "repository" for mount in profile["filesystem_mounts"])
    runner = Path(".ai/codex/02-run-prepr-review-docker.sh").read_text(encoding="utf-8")
    assert '-v "$SCHEMA_DIR:/workspace/.ai/schemas:ro"' in runner
    assert '-v "$RUN_DIR:/out:rw"' in runner
    assert '-v "$REPO_ROOT' not in runner


def test_kernel_preserves_declared_host_docker_environment_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("DOCKER_HOST", "ssh://docker.example.test")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/fixture")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-must-not-be-selected")
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-selected-fixture")
    kernel = Kernel()
    resolved = kernel.resolve(request_factory("review"))
    environment = Runner(kernel)._scoped_environment(resolved, tmp_path / "run")
    assert environment["DOCKER_HOST"] == "ssh://docker.example.test"
    assert environment["XDG_RUNTIME_DIR"] == "/run/user/fixture"
    assert environment["SAKANA_API_KEY"] == "sakana-selected-fixture"  # pragma: allowlist secret
    assert "OPENAI_API_KEY" not in environment


def test_packet_binding_is_revalidated_before_credential_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("review")
    kernel = Kernel()
    resolved = kernel.resolve(request)
    packet = Path(str(request["input"]["packet_path"]))
    packet.write_text("changed after resolution\n", encoding="utf-8")
    runner = Runner(kernel, evidence_root=tmp_path / "evidence")

    def fail_if_credentials_are_selected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("provider credentials were selected before packet revalidation")

    monkeypatch.setattr(runner, "_scoped_environment", fail_if_credentials_are_selected)
    with pytest.raises(KernelError) as raised:
        runner.run(resolved)
    assert raised.value.code == "packet_hash_mismatch"


def test_output_budget_counts_only_model_provider_artifacts(tmp_path: Path) -> None:
    (tmp_path / "codex-prepr-review.md").write_bytes(b"r" * 100)
    (tmp_path / "codex-prepr-review.stderr").write_bytes(b"e" * 20)
    (tmp_path / "container.provenance.json").write_bytes(b"p" * 5000)
    (tmp_path / "countyforge-run-event.ndjson").write_bytes(b"o" * 5000)
    assert _output_bytes(tmp_path) == 120


def test_safe_branch_uses_documented_ascii_character_class(
    request_factory: Callable[[str], JsonObject],
) -> None:
    request = request_factory("review")
    request["display_metadata"]["branch"] = "feature/café"
    resolved = Kernel().resolve(request)
    assert _safe_branch(resolved) == "feature__caf__"


def test_review_wall_clock_timeout_never_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-timeout-fixture-secret")
    adapter = tmp_path / "timeout-adapter.sh"
    adapter.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nmkdir -p "$OUT_DIR"\nsleep 5\n',
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    request = request_factory("review")
    request["run_id"] = "review-timeout"
    request["budget_overrides"]["wall_clock_seconds"] = 1
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", review_adapter=adapter
    ).run(kernel.resolve(request))
    assert exit_code == 5
    assert document["disposition"] == "timed_out"
    assert document["summary"]["outcome"] == "failed"


def test_review_output_budget_never_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    monkeypatch.setenv("SAKANA_API_KEY", "sakana-output-fixture-secret")
    adapter = tmp_path / "output-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'mkdir -p "$OUT_DIR"\n'
        'head -c 4096 /dev/zero > "$OUT_DIR/codex-prepr-review.md"\n',
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    request = request_factory("review")
    request["run_id"] = "review-output-budget"
    request["budget_overrides"]["max_output_bytes"] = 1024
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", review_adapter=adapter
    ).run(kernel.resolve(request))
    assert exit_code == 5
    assert document["disposition"] == "budget_exceeded"
    assert document["summary"]["outcome"] == "failed"


def test_signal_failure_is_normalized_and_diagnostic_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_factory: Callable[[str], JsonObject],
) -> None:
    secret = "sakana-signal-fixture-secret"  # pragma: allowlist secret
    monkeypatch.setenv("SAKANA_API_KEY", secret)
    adapter = tmp_path / "signal-adapter.sh"
    adapter.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'mkdir -p "$OUT_DIR"\n'
        "printf 'adapter failed near %s\\n' \"$SAKANA_API_KEY\" >&2\n"
        "kill -TERM $$\n",
        encoding="utf-8",
    )
    adapter.chmod(0o755)
    request = request_factory("review")
    request["run_id"] = "review-signal"
    kernel = Kernel()
    document, exit_code = Runner(
        kernel, evidence_root=tmp_path / "evidence", review_adapter=adapter
    ).run(kernel.resolve(request))
    assert exit_code == 143
    assert document["disposition"] == "adapter_failed"
    assert secret not in document["adapter_stderr_tail"]
    assert "***REDACTED-CREDENTIAL***" in document["adapter_stderr_tail"]


def test_unexpected_cli_failure_is_sanitized_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    request_factory: Callable[[str], JsonObject],
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_factory("validate")), encoding="utf-8")

    def fail_unexpectedly(*_args: object, **_kwargs: object) -> None:
        raise OSError("/private/host/path")

    monkeypatch.setattr("countyforge_runner.cli.Runner.run", fail_unexpectedly)
    assert main(["run", "--request", str(request_path), "--json"]) == 5
    result = json.loads(capsys.readouterr().out)
    assert result["disposition"] == "internal_error"
    assert "/private/host/path" not in json.dumps(result)
