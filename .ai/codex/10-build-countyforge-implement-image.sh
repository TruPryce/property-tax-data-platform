#!/usr/bin/env bash
set -euo pipefail

: "${CODEX_PROVIDER:=openai}"
: "${CODEX_MODEL_REF:=openai.gpt-5.6}"
: "${CODEX_REASONING_EFFORT:=xhigh}"
: "${CODEX_VERSION:=0.144.6}"
: "${CODEX_IMAGE:=countyforge-implement-agent:openai-v1}"
: "${COUNTYFORGE_PROFILE_SHA256:?COUNTYFORGE_PROFILE_SHA256 is required}"

docker build \
  --label "org.countyforge.profile=implement.workspace-write.v1" \
  --label "org.countyforge.profile-sha256=$COUNTYFORGE_PROFILE_SHA256" \
  --label "org.countyforge.provider=$CODEX_PROVIDER" \
  --label "org.countyforge.model-ref=$CODEX_MODEL_REF" \
  --label "org.countyforge.reasoning-effort=$CODEX_REASONING_EFFORT" \
  --label "org.countyforge.codex-cli=$CODEX_VERSION" \
  --tag "$CODEX_IMAGE" \
  -f .ai/codex/implement.Dockerfile .
