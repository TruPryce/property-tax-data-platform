#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CHECKER="$REPO_ROOT/scripts/dev-loop/check-runner-identity.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "RUNNER IDENTITY TEST FAILED: $1" >&2
  exit 1
}

mkdir -p "$WORK/clean" "$WORK/inherited"
printf 'property-tax-codex-reviewer\n' > "$WORK/clean/image.txt"
printf 'platform-edge-codex-agent\n' > "$WORK/inherited/image.txt"

"$CHECKER" "$WORK/clean" || fail "clean identity fixture was rejected"

if "$CHECKER" "$WORK/inherited" >"$WORK/inherited.out" 2>"$WORK/inherited.err"; then
  fail "inherited identity fixture was accepted"
fi
grep -Fq 'inherited runner identity remains' "$WORK/inherited.err" \
  || fail "identity rejection was not actionable"

if RUNNER_IDENTITY_SEARCH_BIN=missing-runner-identity-search-tool \
  "$CHECKER" "$WORK/clean" >"$WORK/missing.out" 2>"$WORK/missing.err"; then
  fail "missing search dependency was accepted"
fi
grep -Fq 'search tool is unavailable' "$WORK/missing.err" \
  || fail "missing-tool failure was not actionable"

echo "==> RUNNER IDENTITY TESTS PASSED"
