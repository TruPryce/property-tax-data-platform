#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

BASE="${BASE:-origin/main}"
REVIEWS_ROOT="${REVIEWS_ROOT:-.ai/reviews}"
ALLOW_NONSTANDARD_REVIEW_DIR="${ALLOW_NONSTANDARD_REVIEW_DIR:-0}"
RUN_CHECKS="${RUN_CHECKS:-1}"
if [[ -n "${CI:-}" ]]; then
  RUN_CODEX_REVIEW="${RUN_CODEX_REVIEW:-0}"
else
  RUN_CODEX_REVIEW="${RUN_CODEX_REVIEW:-1}"
fi

err() { printf 'ERROR: %s\n' "$*" >&2; }
info() { printf '==> %s\n' "$*" >&2; }

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  err "not inside a git repository"
  exit 2
}
cd "$REPO_ROOT"
REPO_ROOT="$(pwd -P)"

resolve_reviews_root() {
  python3 "$REPO_ROOT/scripts/dev-loop/resolve-review-path.py" \
    "$REPO_ROOT" "$1" "$ALLOW_NONSTANDARD_REVIEW_DIR" REVIEWS_ROOT
}

REVIEWS_ROOT="$(resolve_reviews_root "$REVIEWS_ROOT")"
mkdir -p "$REVIEWS_ROOT"

if [[ "$RUN_CHECKS" == "1" ]]; then
  info "Running deterministic repository gates"
  make check
else
  info "RUN_CHECKS=$RUN_CHECKS: skipping deterministic repository gates"
fi

info "Validating runner JSON schemas"
for contract in .ai/schemas/*.json .ai/profiles/*.json .ai/providers/*.json; do
  python3 -m json.tool "$contract" >/dev/null
done

PACKET_TMP="$(mktemp "$REVIEWS_ROOT/.review-packet.XXXXXX")"
PACKET_PROVENANCE_TMP="$(mktemp "$REVIEWS_ROOT/.review-packet-provenance.XXXXXX")"
REQUEST_PATH="$(mktemp "${TMPDIR:-/tmp}/countyforge-review-request.XXXXXX")"
RUN_RESULT="$(mktemp "${TMPDIR:-/tmp}/countyforge-review-result.XXXXXX")"
cleanup() {
  rm -f "$PACKET_TMP" "$PACKET_PROVENANCE_TMP" "$REQUEST_PATH" "$RUN_RESULT"
}
trap cleanup EXIT

info "Building deterministic review packet"
scripts/dev-loop/build-review-packet.sh "$BASE" > "$PACKET_TMP"
python3 scripts/dev-loop/build-review-packet-provenance.py \
  --repo-root "$REPO_ROOT" \
  --packet "$PACKET_TMP" \
  --repository "TruPryce/property-tax-data-platform" \
  > "$PACKET_PROVENANCE_TMP"
PACKET_PATH="$REVIEWS_ROOT/review-packet.md"
PACKET_PROVENANCE_PATH="$REVIEWS_ROOT/review-packet.provenance.json"
mv "$PACKET_TMP" "$PACKET_PATH"
mv "$PACKET_PROVENANCE_TMP" "$PACKET_PROVENANCE_PATH"

if [[ "$RUN_CODEX_REVIEW" != "1" ]]; then
  info "RUN_CODEX_REVIEW=$RUN_CODEX_REVIEW: skipping paid Codex review"
  info "Review packet: $REVIEWS_ROOT/review-packet.md"
  info "Packet provenance: $REVIEWS_ROOT/review-packet.provenance.json"
  exit 0
fi

BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%d-%H%M%S)-$$}"

BASE_SHA="$(jq -r '.base_sha' "$PACKET_PROVENANCE_PATH")"
HEAD_SHA="$(jq -r '.head_sha' "$PACKET_PROVENANCE_PATH")"
ACTOR="$(id -un 2>/dev/null || printf 'local-operator')"
COUNTYFORGE_PROVIDER="${COUNTYFORGE_PROVIDER:-${CODEX_PROVIDER:-sakana}}"
COUNTYFORGE_REASONING_EFFORT="${COUNTYFORGE_REASONING_EFFORT:-${CODEX_REASONING_EFFORT:-xhigh}}"
if [[ "$COUNTYFORGE_REASONING_EFFORT" == "max" ]]; then
  COUNTYFORGE_REASONING_EFFORT="xhigh"
fi
if [[ -z "${COUNTYFORGE_MODEL_REF:-}" && -n "${CODEX_MODEL:-}" ]]; then
  case "$COUNTYFORGE_PROVIDER:$CODEX_MODEL" in
    sakana:fugu) COUNTYFORGE_MODEL_REF="sakana.fugu" ;;
    sakana:fugu-ultra) COUNTYFORGE_MODEL_REF="sakana.fugu-ultra" ;;
    openai:gpt-5.6) COUNTYFORGE_MODEL_REF="openai.gpt-5.6" ;;
    *) err "CODEX_MODEL does not map to a declared CountyForge provider/model"; exit 2 ;;
  esac
fi

REQUEST_ARGS=(
  --repo-root "$REPO_ROOT"
  --packet "$PACKET_PATH"
  --packet-provenance "$PACKET_PROVENANCE_PATH"
  --run-id "$RUN_ID"
  --base-sha "$BASE_SHA"
  --head-sha "$HEAD_SHA"
  --branch "$BRANCH"
  --actor "$ACTOR"
  --provider "$COUNTYFORGE_PROVIDER"
  --reasoning-effort "$COUNTYFORGE_REASONING_EFFORT"
)
if [[ -n "${COUNTYFORGE_MODEL_REF:-}" ]]; then
  REQUEST_ARGS+=(--model-ref "$COUNTYFORGE_MODEL_REF")
fi
if [[ -n "${OPENSPEC_CHANGE:-}" ]]; then
  REQUEST_ARGS+=(--openspec-change "$OPENSPEC_CHANGE")
fi
python3 scripts/dev-loop/build-countyforge-review-request.py \
  "${REQUEST_ARGS[@]}" \
  > "$REQUEST_PATH"

info "Running review.packet-only.v1 through the CountyForge kernel"
set +e
UV_CACHE_DIR="${UV_CACHE_DIR:-.cache/uv}" uv run --package countyforge-runner \
  countyforge-runner run --request "$REQUEST_PATH" --json > "$RUN_RESULT"
RUNNER_STATUS=$?
set -e
if [[ "$RUNNER_STATUS" -ne 0 ]]; then
  cat "$RUN_RESULT" >&2
  exit "$RUNNER_STATUS"
fi

RUN_DIR_VALUE="$(jq -er '.run_dir | strings | select(length > 0)' "$RUN_RESULT")" || {
  err "runner exited successfully without a run_dir in its JSON result"
  exit 2
}
RUN_DIR="$(resolve_reviews_root "$RUN_DIR_VALUE")"
FINAL_REVIEW="$RUN_DIR/codex-prepr-review.md"

if [[ ! -s "$FINAL_REVIEW" ]]; then
  err "runner exited successfully without the canonical review: $FINAL_REVIEW"
  exit 2
fi

info "Review complete: $FINAL_REVIEW"
cat "$FINAL_REVIEW"
