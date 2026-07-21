#!/usr/bin/env bash
set -euo pipefail

PROVIDER="${CODEX_PROVIDER:-sakana}"
MODEL_REF="${CODEX_MODEL_REF:-}"
REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
case "$PROVIDER" in
  sakana)
    IMAGE="${CODEX_IMAGE:-countyforge-plan-agent-sakana:v1}"
    MODEL_REF="${MODEL_REF:-sakana.fugu-ultra}"
    PROVIDER_URL="https://api.sakana.ai/v1"
    ;;
  openai)
    IMAGE="${CODEX_IMAGE:-countyforge-plan-agent-openai:v1}"
    MODEL_REF="${MODEL_REF:-openai.gpt-5.6}"
    PROVIDER_URL=""
    ;;
  *) echo "error: CODEX_PROVIDER must be openai or sakana" >&2; exit 2 ;;
esac
case "$PROVIDER:$MODEL_REF" in
  sakana:sakana.fugu) MODEL="fugu" ;;
  sakana:sakana.fugu-ultra) MODEL="fugu-ultra" ;;
  openai:openai.gpt-5.6) MODEL="gpt-5.6" ;;
  *) echo "error: model reference is not compatible with the planning provider" >&2; exit 2 ;;
esac
case "$REASONING_EFFORT" in
  medium|high|xhigh) ;;
  *) echo "error: unsupported planning reasoning effort" >&2; exit 2 ;;
esac
ROOT="$(git rev-parse --show-toplevel)"
PROFILE_SHA="$(python3 - "$ROOT/.ai/profiles/plan.read-only.v1.json" <<'PY'
import hashlib, json, sys
print(hashlib.sha256(json.dumps(json.load(open(sys.argv[1])), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
PY
)"
CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT
cat > "$CTX/config.toml" <<EOF
model = "$MODEL"
model_reasoning_effort = "$REASONING_EFFORT"
[tools]
web_search = false
[features]
image_generation = false
apps = false
shell_tool = false
unified_exec = false
browser_use = false
browser_use_external = false
browser_use_full_cdp_access = false
computer_use = false
in_app_browser = false
EOF
if [ -n "$PROVIDER_URL" ]; then
cat >> "$CTX/config.toml" <<EOF
[model_providers.sakana]
name = "Sakana API"
base_url = "$PROVIDER_URL"
env_key = "SAKANA_API_KEY"
wire_api = "responses"
EOF
fi
cat > "$CTX/entrypoint.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$CODEX_HOME"
cp /opt/countyforge/config.toml "$CODEX_HOME/config.toml"
exec codex "$@"
EOF
chmod +x "$CTX/entrypoint.sh"
docker build --pull \
  --label "org.opencontainers.image.title=CountyForge plan read-only" \
  --label "dev.trupryce.property-tax-data-platform.profile-id=plan.read-only.v1" \
  --label "dev.trupryce.property-tax-data-platform.profile-sha256=$PROFILE_SHA" \
  --label "dev.trupryce.property-tax-data-platform.provider=$PROVIDER" \
  --label "dev.trupryce.property-tax-data-platform.model-ref=$MODEL_REF" \
  --label "dev.trupryce.property-tax-data-platform.reasoning-effort=$REASONING_EFFORT" \
  --build-arg CODEX_VERSION=0.144.6 \
  -t "$IMAGE" -f - "$CTX" <<'DOCKERFILE'
FROM node:22-bookworm-slim
ARG CODEX_VERSION
RUN npm install -g "@openai/codex@${CODEX_VERSION}"
LABEL dev.trupryce.property-tax-data-platform.codex-cli-version="${CODEX_VERSION}"
COPY config.toml /opt/countyforge/config.toml
COPY entrypoint.sh /usr/local/bin/codex-entrypoint.sh
RUN chmod +x /usr/local/bin/codex-entrypoint.sh
ENTRYPOINT ["codex-entrypoint.sh"]
DOCKERFILE
