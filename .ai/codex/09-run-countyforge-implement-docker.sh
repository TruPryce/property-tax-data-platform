#!/usr/bin/env bash
set -euo pipefail

# The implementation adapter is the only profile allowed a writable mount.  The model sees
# an ephemeral workspace plus frozen packet/manifest inputs; trusted contract files and Git
# credentials are never mounted writable or passed through the environment.
: "${WORKSPACE_PATH:?WORKSPACE_PATH is required}"
: "${IMPLEMENTATION_PACKET_PATH:?IMPLEMENTATION_PACKET_PATH is required}"
: "${IMPLEMENTATION_MANIFEST_PATH:?IMPLEMENTATION_MANIFEST_PATH is required}"
: "${IMPLEMENTATION_TASK_PLAN_PATH:?IMPLEMENTATION_TASK_PLAN_PATH is required}"
: "${IMPLEMENTATION_SCHEMA_PATH:?IMPLEMENTATION_SCHEMA_PATH is required}"
: "${IMPLEMENTATION_COMMAND_POLICY_PATH:?IMPLEMENTATION_COMMAND_POLICY_PATH is required}"
: "${OUT_DIR:?OUT_DIR is required}"
: "${CODEX_IMAGE:?CODEX_IMAGE is required}"

mkdir -p "$OUT_DIR"
EXPECTED_PROFILE_SHA="${COUNTYFORGE_PROFILE_SHA256:?COUNTYFORGE_PROFILE_SHA256 is required}"
EXPECTED_CODEX_VERSION="${MIN_CODEX_CLI_VERSION:?MIN_CODEX_CLI_VERSION is required}"
if ! docker image inspect "$CODEX_IMAGE" >/dev/null 2>&1; then
  echo "error: implementation image is unavailable: $CODEX_IMAGE" >&2
  exit 2
fi
IMAGE_PROFILE_ID="$(docker image inspect "$CODEX_IMAGE" --format '{{ index .Config.Labels "org.countyforge.profile" }}' 2>/dev/null || true)"
IMAGE_PROFILE_SHA="$(docker image inspect "$CODEX_IMAGE" --format '{{ index .Config.Labels "org.countyforge.profile-sha256" }}' 2>/dev/null || true)"
IMAGE_PROVIDER="$(docker image inspect "$CODEX_IMAGE" --format '{{ index .Config.Labels "org.countyforge.provider" }}' 2>/dev/null || true)"
IMAGE_MODEL_REF="$(docker image inspect "$CODEX_IMAGE" --format '{{ index .Config.Labels "org.countyforge.model-ref" }}' 2>/dev/null || true)"
IMAGE_REASONING_EFFORT="$(docker image inspect "$CODEX_IMAGE" --format '{{ index .Config.Labels "org.countyforge.reasoning-effort" }}' 2>/dev/null || true)"
IMAGE_CODEX_VERSION="$(docker image inspect "$CODEX_IMAGE" --format '{{ index .Config.Labels "org.countyforge.codex-cli" }}' 2>/dev/null || true)"
if [ "$IMAGE_PROFILE_ID" != "implement.workspace-write.v1" ] || [ "$IMAGE_PROFILE_SHA" != "$EXPECTED_PROFILE_SHA" ] || \
   [ "$IMAGE_PROVIDER" != "${CODEX_PROVIDER:?CODEX_PROVIDER is required}" ] || \
   [ "$IMAGE_MODEL_REF" != "${CODEX_MODEL_REF:?CODEX_MODEL_REF is required}" ] || \
   [ "$IMAGE_REASONING_EFFORT" != "${CODEX_REASONING_EFFORT:?CODEX_REASONING_EFFORT is required}" ] || \
   [ "$IMAGE_CODEX_VERSION" != "$EXPECTED_CODEX_VERSION" ]; then
  echo "error: image capability profile identity does not match the resolved implementation profile" >&2
  exit 2
fi
IMAGE_ID="$(docker image inspect "$CODEX_IMAGE" --format '{{.Id}}')"
python3 - "$OUT_DIR/container.provenance.json" "$CODEX_IMAGE" "$IMAGE_ID" "$CODEX_PROVIDER" "$EXPECTED_PROFILE_SHA" "$EXPECTED_CODEX_VERSION" "$CODEX_MODEL_REF" "$CODEX_REASONING_EFFORT" <<'PY'
import json
import pathlib
import sys

path, image, image_id, provider, profile_sha, codex_version, model_ref, reasoning_effort = sys.argv[1:]
document = {
    "contract_version": 1,
    "profile_id": "implement.workspace-write.v1",
    "profile_sha256": profile_sha,
    "image": image,
    "image_id": image_id,
    "provider": provider,
    "model_ref": model_ref,
    "reasoning_effort": reasoning_effort,
    "codex_cli_version": codex_version,
    "credential_names": ["OPENAI_API_KEY"],
    "enabled_tools": ["structured_file_bundle"],
    "disabled_tools": [
        "shell_tool", "unified_exec", "browser_use", "computer_use", "apps",
        "image_generation", "web_search",
    ],
    "mounts": [
        "implementation_workspace:/workspace:read_write",
        "frozen_implementation_packet:/workspace/implementation-packet.json:read_only",
        "frozen_implementation_manifest:/workspace/implementation-manifest.json:read_only",
        "claimed_output_directory:/out:read_write",
    ],
    "network_policy": "provider_only",
    "repository_mounted": True,
}
pathlib.Path(path).write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
PY
NETWORK_NAME="countyforge-implement-${RANDOM}-$$"
PROXY_NAME="${NETWORK_NAME}-proxy"
cleanup_network() {
  docker rm -f "$PROXY_NAME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
}
trap cleanup_network EXIT
docker network create --driver bridge --internal "$NETWORK_NAME" >/dev/null

# The model is attached only to the internal network.  The proxy sidecar is the sole
# container attached to both the internal network and Docker's ordinary egress network;
# direct provider or arbitrary internet connections from the model are therefore impossible.
docker run -d --name "$PROXY_NAME" \
  --network "$NETWORK_NAME" \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --user 65532:65532 \
  -v "$(pwd)/tools/countyforge-runner/src/countyforge_runner/provider_proxy.py:/provider_proxy.py:ro" \
  python:3.12-alpine \
  python /provider_proxy.py --host 0.0.0.0 --port 45000 --allowed-host api.openai.com \
  >/dev/null
docker network connect bridge "$PROXY_NAME"
sleep 1
docker inspect "$PROXY_NAME" --format '{{.State.Running}}' | grep -qx true || {
  echo "provider proxy failed" >&2
  exit 2
}
docker run --rm \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --network "$NETWORK_NAME" \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --tmpfs /tmp/codex-home:rw,nosuid,nodev,size=256m \
  --user "$(id -u):$(id -g)" \
  -v "$WORKSPACE_PATH:/workspace:rw" \
  --tmpfs /workspace/.git:rw,noexec,nosuid,nodev,size=16m \
  --tmpfs /workspace/.github/workflows:ro,noexec,nosuid,nodev,size=16m \
  --tmpfs /workspace/.ai/policies:ro,noexec,nosuid,nodev,size=16m \
  --tmpfs /workspace/.env:ro,noexec,nosuid,nodev,size=16m \
  -v "$IMPLEMENTATION_PACKET_PATH:/workspace/implementation-packet.json:ro" \
  -v "$IMPLEMENTATION_MANIFEST_PATH:/workspace/implementation-manifest.json:ro" \
  -v "$IMPLEMENTATION_TASK_PLAN_PATH:/workspace/implementation-task-plan.json:ro" \
  -v "$IMPLEMENTATION_SCHEMA_PATH:/workspace/implementation-result.schema.json:ro" \
  -v "$IMPLEMENTATION_COMMAND_POLICY_PATH:/workspace/implementation-commands.json:ro" \
  -v "$OUT_DIR:/out:rw" \
  -e CODEX_PROVIDER -e CODEX_MODEL -e CODEX_MODEL_REF -e CODEX_REASONING_EFFORT \
  -e HOME=/tmp/codex-home -e CODEX_HOME=/tmp/codex-home \
  -e OPENAI_API_KEY \
  -e "HTTPS_PROXY=http://${PROXY_NAME}:45000" \
  -e "HTTP_PROXY=http://${PROXY_NAME}:45000" \
  -e NO_PROXY= \
  "$CODEX_IMAGE" \
  exec --ephemeral --ignore-rules --skip-git-repo-check --json --sandbox read-only \
    --disable shell_tool --disable unified_exec \
    --model "$CODEX_MODEL" -c "model_reasoning_effort=$CODEX_REASONING_EFFORT" \
    --output-schema /workspace/implementation-result.schema.json \
    --output-last-message /out/countyforge-implementation-result.json \
    "$(cat "$PROMPT_PATH")" \
  > "$OUT_DIR/countyforge-implementation-model-events.ndjson"

# The model emits a bounded structured file bundle because no process-execution tool is
# available inside the container. Trusted host-side materialization is limited to relative
# paths and the mounted workspace; the full path/secret policy is enforced before upload.
python3 - "$OUT_DIR/countyforge-implementation-result.json" "$WORKSPACE_PATH" <<'PY'
import json
import pathlib
import sys

result_path, workspace = sys.argv[1:]
root = pathlib.Path(workspace).resolve(strict=True)
document = json.loads(pathlib.Path(result_path).read_text(encoding="utf-8"))
bundle = document.get("file_bundle", [])
if not isinstance(bundle, list):
    raise SystemExit("implementation file bundle is invalid")
for item in bundle:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("content"), str):
        raise SystemExit("implementation file bundle entry is invalid")
    relative = pathlib.PurePosixPath(item["path"])
    if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
        raise SystemExit("implementation file bundle path is prohibited")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target.is_symlink():
        raise SystemExit("implementation file bundle escaped workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(item["content"], encoding="utf-8")
for relative in document.get("files_deleted", []):
    target = (root / pathlib.PurePosixPath(str(relative))).resolve()
    if target.is_relative_to(root) and target.is_file() and not target.is_symlink():
        target.unlink()
PY

# Never upload provider-bearing model output or command logs.  The workspace itself is
# frozen by trusted tooling after this process exits; this scan covers the separate output
# directory that is uploaded as workflow evidence.  A hit removes the offending file and
# fails the adapter, so no provider value can cross the artifact boundary.
if [ -n "${OPENAI_API_KEY:-}" ]; then
  PROVIDER_SECRET="$OPENAI_API_KEY" python3 - "$OUT_DIR" <<'PY'
import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
secret = os.environ.get("PROVIDER_SECRET", "")
if not secret:
    raise SystemExit(0)
leaked = False
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue
    try:
        data = path.read_bytes()
    except OSError:
        continue
    if secret.encode() in data:
        leaked = True
        path.unlink(missing_ok=True)
if leaked:
    raise SystemExit("provider credential detected in implementation evidence")
PY
fi
