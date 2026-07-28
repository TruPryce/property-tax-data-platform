#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

ROOT="$(git rev-parse --show-toplevel)"
SAKANA_IMAGE="countyforge-plan-agent-sakana:compatibility-$$"
OPENAI_IMAGE="countyforge-plan-agent-openai:compatibility-$$"

cleanup() {
  docker image rm -f "$SAKANA_IMAGE" "$OPENAI_IMAGE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

CODEX_PROVIDER=sakana CODEX_IMAGE="$SAKANA_IMAGE" \
  "$ROOT/.ai/codex/07-build-countyforge-plan-image.sh"
CODEX_PROVIDER=openai CODEX_IMAGE="$OPENAI_IMAGE" \
  "$ROOT/.ai/codex/07-build-countyforge-plan-image.sh"

for image in "$SAKANA_IMAGE" "$OPENAI_IMAGE"; do
  test "$(docker run --rm --entrypoint codex "$image" --version)" = "codex-cli 0.144.6"
  docker run --rm --network none --entrypoint /bin/sh "$image" \
    -c 'test -s /etc/ssl/certs/ca-certificates.crt'
  test "$(
    docker image inspect "$image" \
      --format '{{ index .Config.Labels "dev.trupryce.property-tax-data-platform.codex-cli-version" }}'
  )" = "0.144.6"
done

check_config() {
  local image="$1"
  local resolved_model="${2:-}"
  local output
  local status

  set +e
  output="$(
    docker run --rm --network none --read-only \
      --tmpfs '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777' \
      --tmpfs '/tmp/codex-home:rw,nosuid,nodev,size=64m,mode=1777' \
      -e HOME=/tmp/codex-home \
      -e CODEX_HOME=/tmp/codex-home \
      "$image" \
      exec --strict-config --skip-git-repo-check --json \
      -c 'model_provider="countyforge-offline"' \
      -c 'model_providers.countyforge-offline.name="CountyForge Offline"' \
      -c 'model_providers.countyforge-offline.base_url="http://127.0.0.1:9/v1"' \
      -c 'model_providers.countyforge-offline.env_key="COUNTYFORGE_OFFLINE_KEY"' \
      -c 'model_providers.countyforge-offline.wire_api="responses"' \
      'configuration validation only' </dev/null 2>&1
  )"
  status=$?
  set -e

  test "$status" -eq 1
  grep -Fq '"type":"thread.started"' <<<"$output"
  grep -Fq 'Missing environment variable: `COUNTYFORGE_OFFLINE_KEY`.' <<<"$output"
  ! grep -Fq 'Error loading config.toml' <<<"$output"
  if [ -n "$resolved_model" ]; then
    ! grep -Fq "Model metadata for \`$resolved_model\` not found" <<<"$output"
  fi
}

check_config "$SAKANA_IMAGE" "fugu-ultra"
check_config "$OPENAI_IMAGE"

echo "==> COUNTYFORGE PLAN IMAGE COMPATIBILITY PASSED"
