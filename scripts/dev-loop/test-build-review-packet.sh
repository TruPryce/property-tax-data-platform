#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BUILDER="$REPO_ROOT/scripts/dev-loop/build-review-packet.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "PACKET TEST FAILED: $1" >&2
  exit 1
}

TEST_REPO="$WORK/repo"
mkdir -p "$TEST_REPO/docs/engineering" "$TEST_REPO/.ai/prompts"
git -C "$TEST_REPO" init -q -b main
git -C "$TEST_REPO" config user.email packet-test@example.invalid
git -C "$TEST_REPO" config user.name "Packet Test"
printf '# Test contract\n' > "$TEST_REPO/docs/engineering/pre-pr-review-contract.md"
printf '# Test prompt\n' > "$TEST_REPO/.ai/prompts/codex-prepr-review.md"
printf 'baseline\n' > "$TEST_REPO/tracked.txt"
git -C "$TEST_REPO" add .
git -C "$TEST_REPO" commit -q -m baseline
git -C "$TEST_REPO" switch -q -c feature/packet-contract
printf 'branch change\n' >> "$TEST_REPO/tracked.txt"
printf 'api_key=packet-test-secret\n' > "$TEST_REPO/notes.txt"

OUT_ONE="$WORK/packet-one.md"
OUT_TWO="$WORK/packet-two.md"
(
  cd "$TEST_REPO"
  "$BUILDER" main > "$OUT_ONE"
  "$BUILDER" main > "$OUT_TWO"
)

cmp -s "$OUT_ONE" "$OUT_TWO" || fail "unchanged repository produced different packets"
grep -Fq '| Branch | `feature/packet-contract` |' "$OUT_ONE" \
  || fail "packet metadata omitted the branch"
grep -Fq '## Raw Diff: Unstaged Changes' "$OUT_ONE" \
  || fail "packet omitted the unstaged diff"
grep -Fq '### `notes.txt`' "$OUT_ONE" \
  || fail "packet omitted safe untracked content"
grep -Fq 'api_key=[REDACTED]' "$OUT_ONE" \
  || fail "packet did not redact an API-key assignment"
if grep -Fq 'packet-test-secret' "$OUT_ONE"; then
  fail "packet retained a redacted secret value"
fi

printf 'do-not-emit\n' > "$TEST_REPO/.env"
git -C "$TEST_REPO" add -f .env
if (
  cd "$TEST_REPO"
  "$BUILDER" main > "$WORK/sensitive.md" 2> "$WORK/sensitive.err"
); then
  fail "packet builder accepted a raw diff containing .env"
fi
grep -Fq 'refusing to emit raw diff' "$WORK/sensitive.err" \
  || fail "sensitive-path refusal was not actionable"
if grep -Fq 'do-not-emit' "$WORK/sensitive.md"; then
  fail "packet emitted content from a sensitive path"
fi

echo "==> REVIEW PACKET CONTRACT TESTS PASSED"
