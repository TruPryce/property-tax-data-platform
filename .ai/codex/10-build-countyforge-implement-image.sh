#!/usr/bin/env bash
set -euo pipefail

# Both implementation images are built from a public, pinned base and install the
# pinned Codex CLI here, matching the planning image strategy.  The previous
# OpenAI image inherited FROM ghcr.io/openai/codex, which GitHub-hosted runners
# cannot pull anonymously: run 30691544362 failed with a GHCR 403 while fetching
# a pull token, before the model was ever invoked.  Pulling it would have
# required package credentials this job must never hold.

PROVIDER="${CODEX_PROVIDER:-openai}"
REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
CODEX_VERSION="${CODEX_VERSION:-0.144.6}"
MODEL_REF="${CODEX_MODEL_REF:-}"
case "$PROVIDER" in
  openai)
    IMAGE="${CODEX_IMAGE:-countyforge-implement-agent:openai-v1}"
    MODEL_REF="${MODEL_REF:-openai.gpt-5.6}"
    PROVIDER_URL=""
    ;;
  sakana)
    IMAGE="${CODEX_IMAGE:-countyforge-implement-agent:sakana-v1}"
    MODEL_REF="${MODEL_REF:-sakana.fugu-ultra}"
    PROVIDER_URL="https://api.sakana.ai/v1"
    ;;
  *) echo "error: CODEX_PROVIDER must be openai or sakana" >&2; exit 2 ;;
esac
case "$PROVIDER:$MODEL_REF" in
  openai:openai.gpt-5.6) MODEL="gpt-5.6" ;;
  sakana:sakana.fugu) MODEL="fugu" ;;
  sakana:sakana.fugu-ultra) MODEL="fugu-ultra" ;;
  *) echo "error: model reference is not compatible with the implementation provider" >&2; exit 2 ;;
esac
case "$REASONING_EFFORT" in
  high|xhigh) ;;
  *) echo "error: unsupported implementation reasoning effort" >&2; exit 2 ;;
esac
: "${COUNTYFORGE_PROFILE_SHA256:?COUNTYFORGE_PROFILE_SHA256 is required}"

ROOT="$(git rev-parse --show-toplevel)"
CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT
cp "$ROOT/.ai/codex/fugu/fugu.json" "$CTX/fugu.json"
cat > "$CTX/config.toml" <<EOF
model = "$MODEL"
model_reasoning_effort = "$REASONING_EFFORT"
EOF
if [ "$PROVIDER" = "sakana" ]; then
cat >> "$CTX/config.toml" <<'EOF'
model_provider = "sakana"
model_catalog_json = "/opt/countyforge/fugu.json"
EOF
fi
# The implementation model has no shell, unified exec, browser, or search tool;
# `structured_file_bundle` output is its only write mechanism, for both providers.
cat >> "$CTX/config.toml" <<'EOF'
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
stream_idle_timeout_ms = 7200000
stream_max_retries = 5
request_max_retries = 4
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
  --label "org.opencontainers.image.title=CountyForge implement workspace-write" \
  --label "org.countyforge.profile=implement.workspace-write.v1" \
  --label "org.countyforge.profile-sha256=$COUNTYFORGE_PROFILE_SHA256" \
  --label "org.countyforge.provider=$PROVIDER" \
  --label "org.countyforge.model-ref=$MODEL_REF" \
  --label "org.countyforge.reasoning-effort=$REASONING_EFFORT" \
  --label "org.countyforge.codex-cli=$CODEX_VERSION" \
  --build-arg "CODEX_VERSION=$CODEX_VERSION" \
  --tag "$IMAGE" -f - "$CTX" <<'DOCKERFILE'
FROM node:22-bookworm-slim
ARG CODEX_VERSION
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*
RUN npm install -g "@openai/codex@${CODEX_VERSION}"
COPY fugu.json /opt/countyforge/fugu.json
COPY config.toml /opt/countyforge/config.toml
COPY entrypoint.sh /usr/local/bin/codex-entrypoint.sh
RUN chmod +x /usr/local/bin/codex-entrypoint.sh
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT ["codex-entrypoint.sh"]
DOCKERFILE
