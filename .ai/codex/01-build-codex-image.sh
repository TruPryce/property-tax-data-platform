#!/usr/bin/env bash
set -euo pipefail

PROVIDER="${CODEX_PROVIDER:-sakana}"
case "$PROVIDER" in
  sakana) DEFAULT_IMAGE_NAME="property-tax-codex-reviewer"; DEFAULT_MODEL="fugu-ultra" ;;
  openai) DEFAULT_IMAGE_NAME="property-tax-codex-reviewer-openai"; DEFAULT_MODEL="gpt-5.6" ;;
  *) echo "error: CODEX_PROVIDER must be 'openai' or 'sakana'" >&2; exit 2 ;;
esac
IMAGE_NAME="${CODEX_IMAGE_NAME:-$DEFAULT_IMAGE_NAME}"
IMAGE_TAG="${CODEX_IMAGE_TAG:-local}"
IMAGE="${CODEX_IMAGE:-${IMAGE_NAME}:${IMAGE_TAG}}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
FUGU_SRC="$REPO_ROOT/.ai/codex/fugu"
PROFILE_SHA256="$(python3 -c 'import hashlib,json,sys; p=json.load(open(sys.argv[1])); b=json.dumps(p,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); print(hashlib.sha256(b).hexdigest())' "$REPO_ROOT/.ai/profiles/review.packet-only.v1.json")"

BUILD_CTX="$(mktemp -d)"
trap 'rm -rf "$BUILD_CTX"' EXIT

# --- Stage immutable provider-specific defaults into the build context ------
cp "$FUGU_SRC/fugu.json" "$BUILD_CTX/fugu.json"

if [[ "$PROVIDER" == "sakana" ]]; then
cat > "$BUILD_CTX/config.toml" <<'TOML'
model = "fugu-ultra"
model_reasoning_effort = "xhigh"
model_provider = "sakana"
model_catalog_json = "/opt/countyforge/fugu.json"

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
# `codex exec --strict-config` for codex-cli 0.144.6.
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
else
cat > "$BUILD_CTX/config.toml" <<'TOML'
model = "gpt-5.6"
model_reasoning_effort = "xhigh"

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
TOML
fi

cat > "$BUILD_CTX/codex-entrypoint.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
# Seed the provider-specific config into CODEX_HOME (a writable tmpfs at runtime)
# so the rest of the container filesystem can stay read-only.
: "${CODEX_HOME:=${HOME:-/root}/.codex}"
mkdir -p "$CODEX_HOME"
if [ ! -f "$CODEX_HOME/config.toml" ]; then
  cp /opt/countyforge/config.toml "$CODEX_HOME/config.toml"
fi
exec codex "$@"
EOS

echo "==> Building Codex Docker image: $IMAGE (provider: $PROVIDER; model: $DEFAULT_MODEL)"

docker build \
  --pull \
  --label "org.opencontainers.image.title=property-tax-codex-reviewer" \
  --label "org.opencontainers.image.description=Ephemeral packet-only CountyForge review profile" \
  --label "dev.trupryce.property-tax-data-platform.profile-id=review.packet-only.v1" \
  --label "dev.trupryce.property-tax-data-platform.profile-sha256=$PROFILE_SHA256" \
  --label "dev.trupryce.property-tax-data-platform.provider=$PROVIDER" \
  --build-arg "RUNNER_PROVIDER=$PROVIDER" \
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
ARG CODEX_VERSION=0.144.6
ARG RUNNER_PROVIDER
RUN npm install -g "@openai/codex@${CODEX_VERSION}"

# Bake the pinned CLI version into an image label so the review runner can
# record it in container.provenance.json without launching an extra container.
LABEL dev.trupryce.property-tax-data-platform.codex-cli-version="${CODEX_VERSION}"
LABEL dev.trupryce.property-tax-data-platform.provider="${RUNNER_PROVIDER}"

COPY fugu.json /opt/countyforge/fugu.json
COPY config.toml /opt/countyforge/config.toml
COPY codex-entrypoint.sh /usr/local/bin/codex-entrypoint.sh

RUN chmod +x /usr/local/bin/codex-entrypoint.sh \
  && mkdir -p /workspace/.ai/schemas /out \
  && chmod 0777 /workspace /workspace/.ai /workspace/.ai/schemas /out

WORKDIR /workspace

# The build chooses one immutable provider-specific configuration bundle.
ENTRYPOINT ["codex-entrypoint.sh"]
DOCKERFILE

echo "==> Built image:"
docker image inspect "$IMAGE" --format '    {{.RepoTags}} {{.Id}} {{.Created}}'
