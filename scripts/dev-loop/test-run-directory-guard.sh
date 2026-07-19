#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
RUNNER="$REPO_ROOT/.ai/codex/02-run-prepr-review-docker.sh"
BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
SAFE_BRANCH="$(printf '%s' "$BRANCH" | sed 's#[^A-Za-z0-9._-]#__#g')"
CANONICAL_PARENT="$REPO_ROOT/.ai/reviews/codex-prepr/$SAFE_BRANCH"

mkdir -p "$CANONICAL_PARENT"
TEST_ROOT="$(mktemp -d "$CANONICAL_PARENT/.runner-guard-test.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "RUN DIRECTORY GUARD TEST FAILED: $1" >&2
  exit 1
}

snapshot() {
  local directory="$1"
  (
    cd "$directory"
    find . -mindepth 1 -printf '%P %y %s\n' | LC_ALL=C sort
    find . -type f -exec sha256sum {} + | LC_ALL=C sort
  )
}

run_rejected_case() {
  local label="$1"
  local run_dir="$2"
  local expected_error="$3"
  local before after status

  before="$(snapshot "$run_dir")"
  set +e
  PACKET_PATH="$TEST_ROOT/review-packet.md" \
    OUT_DIR="$run_dir" \
    RUN_ID="guard-$label" \
    "$RUNNER" >"$TEST_ROOT/$label.out" 2>"$TEST_ROOT/$label.err"
  status=$?
  set -e

  [[ "$status" -eq 2 ]] || fail "$label returned $status instead of 2"
  grep -Fq "$expected_error" "$TEST_ROOT/$label.err" \
    || fail "$label rejection did not explain the collision"
  after="$(snapshot "$run_dir")"
  [[ "$after" == "$before" ]] || fail "$label modified prior run evidence"
}

printf '# run-directory guard fixture\n' > "$TEST_ROOT/review-packet.md"

CLAIMED_RUN="$TEST_ROOT/claimed"
mkdir -p "$CLAIMED_RUN/.claim"
printf 'claimed evidence must survive\n' > "$CLAIMED_RUN/prior-evidence.txt"
run_rejected_case claimed "$CLAIMED_RUN" 'run directory is already claimed'

NONEMPTY_RUN="$TEST_ROOT/nonempty"
mkdir -p "$NONEMPTY_RUN"
printf 'completed evidence must survive\n' > "$NONEMPTY_RUN/prior-evidence.txt"
run_rejected_case nonempty "$NONEMPTY_RUN" 'run directory already exists and is not empty'

echo "==> RUN DIRECTORY GUARD TESTS PASSED"
