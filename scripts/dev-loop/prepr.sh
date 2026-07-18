#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

BASE="${BASE:-origin/main}"
REVIEWS_ROOT="${REVIEWS_ROOT:-.ai/reviews}"
ALLOW_EXTERNAL_OUT_DIR="${ALLOW_EXTERNAL_OUT_DIR:-0}"
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
  python3 - "$REPO_ROOT" "$1" "$ALLOW_EXTERNAL_OUT_DIR" <<'PY'
import os
import sys

root = os.path.realpath(sys.argv[1])
requested = sys.argv[2]
allow_external = sys.argv[3] == "1"
candidate = requested if os.path.isabs(requested) else os.path.join(root, requested)
path = os.path.realpath(candidate)

try:
    inside_repo = os.path.commonpath([root, path]) == root
except ValueError:
    inside_repo = False

if not inside_repo and not allow_external:
    sys.stderr.write(
        f"REVIEWS_ROOT resolves outside repo root: {requested} -> {path}\n"
        "Use a repo-contained path, or set ALLOW_EXTERNAL_OUT_DIR=1 intentionally.\n"
    )
    sys.exit(2)

print(path)
PY
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
python3 -m json.tool .ai/schemas/codex-prepr-review.schema.json >/dev/null
python3 -m json.tool .ai/schemas/codex-runner-event.schema.json >/dev/null

PACKET_SOURCE="$(mktemp "${TMPDIR:-/tmp}/property-tax-prepr-packet.XXXXXX")"
SHARED_PACKET_TMP="$(mktemp "$REVIEWS_ROOT/.review-packet.XXXXXX")"
cleanup() {
  rm -f "$PACKET_SOURCE" "$SHARED_PACKET_TMP"
}
trap cleanup EXIT

info "Building deterministic review packet"
scripts/dev-loop/build-review-packet.sh "$BASE" > "$PACKET_SOURCE"
cp "$PACKET_SOURCE" "$SHARED_PACKET_TMP"
mv "$SHARED_PACKET_TMP" "$REVIEWS_ROOT/review-packet.md"

if [[ "$RUN_CODEX_REVIEW" != "1" ]]; then
  info "RUN_CODEX_REVIEW=$RUN_CODEX_REVIEW: skipping paid Codex review"
  info "Review packet: $REVIEWS_ROOT/review-packet.md"
  exit 0
fi

BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
SAFE_BRANCH="$(printf '%s' "$BRANCH" | sed 's#[^A-Za-z0-9._-]#__#g')"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%d-%H%M%S)-$$}"
RUN_DIR="$REVIEWS_ROOT/codex-prepr/$SAFE_BRANCH/$RUN_ID"
FINAL_REVIEW="$RUN_DIR/codex-prepr-review.md"

info "Running the packet-only Docker review profile"
PACKET_PATH="$PACKET_SOURCE" \
OUT_DIR="$RUN_DIR" \
RUN_ID="$RUN_ID" \
COMPAT_DIR="$REVIEWS_ROOT" \
REVIEW_BASE="$BASE" \
ALLOW_EXTERNAL_OUT_DIR="$ALLOW_EXTERNAL_OUT_DIR" \
  .ai/codex/02-run-prepr-review-docker.sh

if [[ ! -s "$FINAL_REVIEW" ]]; then
  err "runner exited successfully without the canonical review: $FINAL_REVIEW"
  exit 2
fi

info "Review complete: $FINAL_REVIEW"
cat "$FINAL_REVIEW"
