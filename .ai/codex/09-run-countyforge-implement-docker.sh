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
docker run --rm \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --network=none \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --user "$(id -u):$(id -g)" \
  -v "$WORKSPACE_PATH:/workspace:rw" \
  -v "$IMPLEMENTATION_PACKET_PATH:/workspace/implementation-packet.json:ro" \
  -v "$IMPLEMENTATION_MANIFEST_PATH:/workspace/implementation-manifest.json:ro" \
  -v "$IMPLEMENTATION_TASK_PLAN_PATH:/workspace/implementation-task-plan.json:ro" \
  -v "$IMPLEMENTATION_SCHEMA_PATH:/workspace/implementation-result.schema.json:ro" \
  -v "$IMPLEMENTATION_COMMAND_POLICY_PATH:/workspace/implementation-commands.json:ro" \
  -v "$OUT_DIR:/out:rw" \
  -e CODEX_PROVIDER -e CODEX_MODEL -e CODEX_MODEL_REF -e CODEX_REASONING_EFFORT \
  -e OPENAI_API_KEY \
  "$CODEX_IMAGE" \
  codex exec --json --sandbox workspace-write \
    --output-schema /workspace/implementation-result.schema.json \
    --output-last-message /out/countyforge-implementation-result.json \
    "$(cat "$PROMPT_PATH")" \
  > "$OUT_DIR/countyforge-implementation-command-events.ndjson"
