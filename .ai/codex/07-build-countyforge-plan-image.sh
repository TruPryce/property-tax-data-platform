#!/usr/bin/env bash
set -euo pipefail

PROVIDER="${CODEX_PROVIDER:-sakana}"
case "$PROVIDER" in
  sakana) IMAGE="${CODEX_IMAGE:-countyforge-plan-agent-sakana:v1}"; MODEL="fugu-ultra"; PROVIDER_URL="https://api.sakana.ai/v1" ;;
  openai) IMAGE="${CODEX_IMAGE:-countyforge-plan-agent-openai:v1}"; MODEL="gpt-5.6"; PROVIDER_URL="" ;;
  *) echo "error: CODEX_PROVIDER must be openai or sakana" >&2; exit 2 ;;
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
