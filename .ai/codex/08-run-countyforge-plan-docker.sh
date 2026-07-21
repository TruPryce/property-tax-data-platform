#!/usr/bin/env bash
set -euo pipefail

# Profile-specific adapter for plan.read-only.v1.  Only the frozen packet,
# manifest, prompt, schema, and claimed output directory cross the container
# boundary; no repository, Git credentials, or GitHub token is mounted.
PROVIDER="${CODEX_PROVIDER:-sakana}"
case "$PROVIDER" in
  sakana) CREDENTIAL="SAKANA_API_KEY"; DEFAULT_IMAGE="countyforge-plan-agent-sakana:v1" ;;
  openai) CREDENTIAL="OPENAI_API_KEY"; DEFAULT_IMAGE="countyforge-plan-agent-openai:v1" ;;
  *) echo "error: unsupported planning provider" >&2; exit 2 ;;
esac
PACKET_PATH="${PLANNING_PACKET_PATH:?PLANNING_PACKET_PATH is required}"
MANIFEST_PATH="${CONTEXT_MANIFEST_PATH:?CONTEXT_MANIFEST_PATH is required}"
SCHEMA_PATH="${SCHEMA_PATH:?SCHEMA_PATH is required}"
PROMPT_PATH="${PROMPT_PATH:?PROMPT_PATH is required}"
RUN_DIR="${OUT_DIR:?OUT_DIR is required}"
IMAGE="${CODEX_IMAGE:-$DEFAULT_IMAGE}"
ROOT="$(git rev-parse --show-toplevel)"
PROFILE_PATH="$ROOT/.ai/profiles/plan.read-only.v1.json"
EXPECTED_PROFILE_SHA="${COUNTYFORGE_PROFILE_SHA256:-$(python3 - "$PROFILE_PATH" <<'PY'
import hashlib
import json
import sys

profile = json.load(open(sys.argv[1], encoding="utf-8"))
print(hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
PY
)}"
EXPECTED_CODEX_VERSION="$(python3 - "$PROFILE_PATH" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1], encoding="utf-8"))["container"]["codex_cli_version"])
PY
)"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "error: planning image is unavailable: $IMAGE" >&2
  exit 2
fi
IMAGE_PROFILE_ID="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.profile-id" }}' 2>/dev/null || true)"
IMAGE_PROFILE_SHA="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.profile-sha256" }}' 2>/dev/null || true)"
IMAGE_PROVIDER="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.provider" }}' 2>/dev/null || true)"
IMAGE_MODEL_REF="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.model-ref" }}' 2>/dev/null || true)"
IMAGE_REASONING_EFFORT="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.reasoning-effort" }}' 2>/dev/null || true)"
IMAGE_CODEX_VERSION="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.codex-cli-version" }}' 2>/dev/null || true)"
EXPECTED_MODEL_REF="${CODEX_MODEL_REF:?CODEX_MODEL_REF is required}"
EXPECTED_REASONING_EFFORT="${CODEX_REASONING_EFFORT:?CODEX_REASONING_EFFORT is required}"
if [ "$IMAGE_PROFILE_ID" != "plan.read-only.v1" ] || [ "$IMAGE_PROFILE_SHA" != "$EXPECTED_PROFILE_SHA" ] || \
   [ "$IMAGE_PROVIDER" != "$PROVIDER" ] || [ "$IMAGE_MODEL_REF" != "$EXPECTED_MODEL_REF" ] || \
   [ "$IMAGE_REASONING_EFFORT" != "$EXPECTED_REASONING_EFFORT" ] || \
   [ "$IMAGE_CODEX_VERSION" != "$EXPECTED_CODEX_VERSION" ]; then
  echo "error: image capability profile identity does not match the resolved plan profile" >&2
  exit 2
fi
mkdir -p "$RUN_DIR"
CLAIM="$RUN_DIR/.claim"
if [ -e "$CLAIM" ] || { [ -d "$RUN_DIR" ] && [ -n "$(ls -A "$RUN_DIR" 2>/dev/null)" ]; }; then
  echo "error: planning run directory is already claimed or non-empty" >&2
  exit 2
fi
mkdir "$CLAIM"
trap 'rmdir "$CLAIM" 2>/dev/null || true' EXIT
test -f "$PACKET_PATH" && test -f "$MANIFEST_PATH" && test -f "$SCHEMA_PATH" && test -f "$PROMPT_PATH"
test "$(sha256sum "$PACKET_PATH" | cut -d' ' -f1)" = "${EXPECTED_PLANNING_PACKET_SHA256:?}"
test "$(sha256sum "$MANIFEST_PATH" | cut -d' ' -f1)" = "${EXPECTED_CONTEXT_MANIFEST_SHA256:?}"
IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
python3 - "$RUN_DIR/container.provenance.json" "$IMAGE" "$IMAGE_ID" "$PROVIDER" "$CREDENTIAL" "$EXPECTED_PROFILE_SHA" "$EXPECTED_CODEX_VERSION" "$EXPECTED_MODEL_REF" "$EXPECTED_REASONING_EFFORT" <<'PY'
import json
import pathlib
import sys

path, image, image_id, provider, credential, profile_sha, codex_version, model_ref, reasoning_effort = sys.argv[1:]
document = {
    "contract_version": 1,
    "profile_id": "plan.read-only.v1",
    "profile_sha256": profile_sha,
    "image": image,
    "image_id": image_id,
    "provider": provider,
    "model_ref": model_ref,
    "reasoning_effort": reasoning_effort,
    "codex_cli_version": codex_version,
    "credential_names": [credential],
    "enabled_tools": [],
    "disabled_tools": [
        "shell_tool", "unified_exec", "browser_use", "browser_use_external",
        "computer_use", "in_app_browser", "apps", "image_generation", "web_search",
    ],
    "mounts": [
        "schema_directory:/workspace/.ai/schemas:read_only",
        "frozen_planning_packet:/workspace/packet.json:read_only",
        "frozen_context_manifest:/workspace/manifest.json:read_only",
        "claimed_output_directory:/out:read_write",
    ],
    "network_policy": "provider_only",
    "repository_mounted": False,
}
pathlib.Path(path).write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
PY

SCHEMA_DIR="$(dirname "$SCHEMA_PATH")"
CONTAINER_SCHEMA="/workspace/.ai/schemas/$(basename "$SCHEMA_PATH")"
DISABLED_TOOLS=(shell_tool unified_exec browser_use browser_use_external browser_use_full_cdp_access computer_use in_app_browser apps image_generation)
ARGS=(exec --ephemeral --ignore-rules --skip-git-repo-check --sandbox danger-full-access --json)
for tool in "${DISABLED_TOOLS[@]}"; do ARGS+=(--disable "$tool"); done
ARGS+=(-c tools.web_search=false --output-schema "$CONTAINER_SCHEMA" --output-last-message /out/countyforge-plan-result.json -)
PROMPT="$(cat "$PROMPT_PATH")"
{ printf '%s\n\n' "$PROMPT"; printf 'FROZEN PLANNING PACKET:\n'; cat "$PACKET_PATH"; printf '\nFROZEN CONTEXT MANIFEST:\n'; cat "$MANIFEST_PATH"; } |
  docker run --rm -i \
    --name "countyforge-plan-${RUN_ID:-run}" \
    --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges:true --read-only \
    --tmpfs '/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777' \
    --tmpfs '/tmp/codex-home:rw,nosuid,nodev,size=256m,mode=1777' \
    -e HOME=/tmp/codex-home -e CODEX_HOME=/tmp/codex-home -e "$CREDENTIAL" \
    -v "$SCHEMA_DIR:/workspace/.ai/schemas:ro" -v "$PACKET_PATH:/workspace/packet.json:ro" \
    -v "$MANIFEST_PATH:/workspace/manifest.json:ro" -v "$RUN_DIR:/out:rw" \
    "$IMAGE" "${ARGS[@]}" > "$RUN_DIR/countyforge-plan-events.ndjson" 2> "$RUN_DIR/countyforge-plan.stderr"
test -s "$RUN_DIR/countyforge-plan-result.json"
