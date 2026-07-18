#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
RESOLVER="$REPO_ROOT/scripts/dev-loop/resolve-review-path.py"
PREPR="$REPO_ROOT/scripts/dev-loop/prepr.sh"
RUNNER="$REPO_ROOT/.ai/codex/02-run-prepr-review-docker.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "REVIEW PATH TEST FAILED: $1" >&2
  exit 1
}

assert_accepts() {
  local requested="$1"
  local allow="${2:-0}"
  python3 "$RESOLVER" "$WORK/repo" "$requested" "$allow" TEST_PATH >/dev/null \
    || fail "expected accepted path: $requested (opt-in=$allow)"
}

assert_rejects() {
  local requested="$1"
  if python3 "$RESOLVER" "$WORK/repo" "$requested" 0 TEST_PATH \
    >"$WORK/rejected.out" 2>"$WORK/rejected.err"; then
    fail "expected rejected path: $requested"
  fi
  grep -Fq 'must resolve under' "$WORK/rejected.err" \
    || fail "rejection did not identify the required review root"
}

mkdir -p "$WORK/repo/.ai/reviews" "$WORK/repo/docs" "$WORK/outside"
assert_accepts ".ai/reviews"
assert_accepts ".ai/reviews/codex-prepr/branch/run"
assert_rejects "docs/reviews"
assert_rejects "$WORK/outside"
assert_accepts "docs/reviews" 1
assert_accepts "$WORK/outside" 1

ln -s "$WORK/outside" "$WORK/repo/.ai/reviews/escape"
assert_rejects ".ai/reviews/escape/run"

mkdir -p "$WORK/root-link-repo/.ai"
ln -s "$WORK/outside" "$WORK/root-link-repo/.ai/reviews"
if python3 "$RESOLVER" "$WORK/root-link-repo" ".ai/reviews/run" 0 TEST_PATH \
  >"$WORK/root-link.out" 2>"$WORK/root-link.err"; then
  fail "expected a redirected standard review root to be rejected"
fi
grep -Fq 'standard review root must not be redirected' "$WORK/root-link.err" \
  || fail "redirected-root rejection was not actionable"

# Verify both public entry points reject tracked-tree destinations before any
# packet, run directory, or compatibility artifact is written.
blocked="$REPO_ROOT/docs/review-output-contract-test"
if REVIEWS_ROOT="$blocked" RUN_CHECKS=0 RUN_CODEX_REVIEW=0 "$PREPR" \
  >"$WORK/prepr.out" 2>"$WORK/prepr.err"; then
  fail "prepr accepted REVIEWS_ROOT outside .ai/reviews"
fi
[ ! -e "$blocked" ] || fail "prepr created the rejected REVIEWS_ROOT"

printf '# path-containment fixture\n' > "$WORK/packet.md"
if PACKET_PATH="$WORK/packet.md" OUT_DIR="$blocked/run" RUN_ID=path-test "$RUNNER" \
  >"$WORK/runner.out" 2>"$WORK/runner.err"; then
  fail "runner accepted OUT_DIR outside .ai/reviews"
fi
[ ! -e "$blocked" ] || fail "runner created the rejected OUT_DIR"

allowed_run="$REPO_ROOT/.ai/reviews/path-contract-test/run"
if PACKET_PATH="$WORK/packet.md" OUT_DIR="$allowed_run" COMPAT_DIR="$blocked/compat" \
  RUN_ID=path-test "$RUNNER" >"$WORK/compat.out" 2>"$WORK/compat.err"; then
  fail "runner accepted COMPAT_DIR outside .ai/reviews"
fi
[ ! -e "$allowed_run" ] || fail "runner wrote before rejecting COMPAT_DIR"
[ ! -e "$blocked" ] || fail "runner created the rejected COMPAT_DIR"

echo "==> REVIEW OUTPUT PATH TESTS PASSED"
