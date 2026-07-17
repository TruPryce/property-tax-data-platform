#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${CODEX_IMAGE_NAME:-platform-edge-codex-agent}"
IMAGE_TAG="${CODEX_IMAGE_TAG:-local}"
IMAGE="${CODEX_IMAGE:-${IMAGE_NAME}:${IMAGE_TAG}}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
FUGU_SRC="$REPO_ROOT/.ai/codex/fugu"

BUILD_CTX="$(mktemp -d)"
trap 'rm -rf "$BUILD_CTX"' EXIT

# --- Stage Sakana Fugu defaults into the build context ---------------------
# Reuse the committed Fugu model catalog; write a consolidated config.toml that
# makes Fugu the default model/provider, plus an entrypoint that seeds the
# (tmpfs) CODEX_HOME at container start so the review runner can stay read-only.
cp "$FUGU_SRC/fugu.json" "$BUILD_CTX/fugu.json"

cat > "$BUILD_CTX/config.toml" <<'TOML'
model = "fugu-ultra"
model_reasoning_effort = "xhigh"
model_provider = "sakana"
model_catalog_json = "/opt/fugu/fugu.json"

# Packet-only review runner: web search disabled. It is also off by default,
# but pinning it here ensures an image rebuild cannot silently enable the
# Responses `web_search` tool.
[tools]
web_search = false

# Remove every model-invokable execution/network capability. This runner only
# reviews a self-contained packet delivered on stdin; the model must never run
# shell commands, drive a browser, invoke MCP apps, generate images, or reach
# the network. The Docker container is the isolation boundary (see
# 02-run-prepr-review-docker.sh), and these toggles remove the tools the model
# could otherwise use to act inside it. All keys verified accepted under
# `codex exec --strict-config` for codex-cli 0.142.2.
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

[model_providers.sakana]
name = "Sakana API"
base_url = "https://api.sakana.ai/v1"
env_key = "SAKANA_API_KEY"
wire_api = "responses"
stream_idle_timeout_ms = 7200000
stream_max_retries = 5
request_max_retries = 4
TOML

cat > "$BUILD_CTX/codex-entrypoint.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
# Seed the Fugu default config into CODEX_HOME (a writable tmpfs at runtime)
# so the rest of the container filesystem can stay read-only.
: "${CODEX_HOME:=${HOME:-/root}/.codex}"
mkdir -p "$CODEX_HOME"
if [ ! -f "$CODEX_HOME/config.toml" ]; then
  cp /opt/fugu/config.toml "$CODEX_HOME/config.toml"
fi
exec codex "$@"
EOS

echo "==> Building Codex Docker image: $IMAGE (default model: Sakana Fugu)"

docker build \
  --pull \
  --label "org.opencontainers.image.title=platform-edge-codex-agent" \
  --label "org.opencontainers.image.description=Ephemeral Codex CLI runner (Sakana Fugu default) forproperty-tax review packets" \
  -t "$IMAGE" \
  -f - "$BUILD_CTX" <<'DOCKERFILE'
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    jq \
    openssh-client \
  && rm -rf /var/lib/apt/lists/*

# Pin the Codex CLI to the version this harness was tested against so image
# rebuilds stay reproducible. The packet-only tool/sandbox posture below
# (config.toml feature toggles + runner flags) is validated against this
# version; bump deliberately and re-run .ai/codex/03-smoke-test.sh when updating.
ARG CODEX_VERSION=0.142.2
RUN npm install -g "@openai/codex@${CODEX_VERSION}"

# Bake the pinned CLI version into an image label so the review runner can
# record it in container.provenance.json without launching an extra container.
LABEL dev.platform-edge.codex-cli-version="${CODEX_VERSION}"

COPY fugu.json /opt/fugu/fugu.json
COPY config.toml /opt/fugu/config.toml
COPY codex-entrypoint.sh /usr/local/bin/codex-entrypoint.sh

RUN chmod +x /usr/local/bin/codex-entrypoint.sh \
  && mkdir -p /workspace/.ai/schemas /out \
  && chmod 0777 /workspace /workspace/.ai /workspace/.ai/schemas /out

WORKDIR /workspace

# Default to Sakana Fugu via the seeded config.
# To revert to plain Codex/OpenAI: change ENTRYPOINT back to ["codex"], drop the
# COPY/seed lines above, and use OPENAI_API_KEY instead of SAKANA_API_KEY.
ENTRYPOINT ["codex-entrypoint.sh"]
DOCKERFILE

echo "==> Built image:"
docker image inspect "$IMAGE" --format '    {{.RepoTags}} {{.Id}} {{.Created}}'
