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
mkdir -p \
  "$TEST_REPO/docs/engineering" \
  "$TEST_REPO/.ai/prompts" \
  "$TEST_REPO/libs" \
  "$TEST_REPO/openspec/changes/active-change/specs/example" \
  "$TEST_REPO/openspec/changes/archive/old-change" \
  "$TEST_REPO/openspec/specs/example"
git -C "$TEST_REPO" init -q -b main
git -C "$TEST_REPO" config user.email packet-test@example.invalid
git -C "$TEST_REPO" config user.name "Packet Test"
printf 'ROOT-GUIDANCE\n' > "$TEST_REPO/AGENTS.md"
printf 'DOCS-GUIDANCE\n' > "$TEST_REPO/docs/AGENTS.md"
printf 'LIBS-GUIDANCE-SHOULD-NOT-APPEAR\n' > "$TEST_REPO/libs/AGENTS.md"
printf 'OPENSPEC-GUIDANCE\n' > "$TEST_REPO/openspec/AGENTS.md"
printf 'ACTIVE-PROPOSAL\n' > "$TEST_REPO/openspec/changes/active-change/proposal.md"
printf 'ACTIVE-DESIGN\n' > "$TEST_REPO/openspec/changes/active-change/design.md"
printf 'ACTIVE-TASKS\n' > "$TEST_REPO/openspec/changes/active-change/tasks.md"
printf 'ACTIVE-DELTA-SPEC\n' > "$TEST_REPO/openspec/changes/active-change/specs/example/spec.md"
printf 'ARCHIVED-SHOULD-NOT-APPEAR\n' > "$TEST_REPO/openspec/changes/archive/old-change/proposal.md"
printf 'ACCEPTED-SPEC\n' > "$TEST_REPO/openspec/specs/example/spec.md"
printf '# Test contract\n' > "$TEST_REPO/docs/engineering/pre-pr-review-contract.md"
printf '# Test prompt\n' > "$TEST_REPO/.ai/prompts/codex-prepr-review.md"
printf 'baseline\n' > "$TEST_REPO/tracked.txt"
git -C "$TEST_REPO" add .
git -C "$TEST_REPO" commit -q -m baseline
git -C "$TEST_REPO" switch -q -c feature/packet-contract
printf 'branch change\n' >> "$TEST_REPO/tracked.txt"
printf 'docs branch change\n' >> "$TEST_REPO/docs/engineering/pre-pr-review-contract.md"
cat > "$TEST_REPO/notes.txt" <<'EOF'
api_key=packet-test-secret
client_secret: "quoted-packet-secret" # pragma: allowlist secret
Authorization: Bearer header-packet-secret
AWS_ACCESS_KEY_ID=cloud-access-literal
AWS_SECRET_ACCESS_KEY="cloud-secret-literal" # pragma: allowlist secret
access_key=short-access-literal
secret_access_key: "short-secret-access-literal" # pragma: allowlist secret
headers={"Authorization": "Bearer json-header-secret"}
call(api_key=paren-packet-secret)
authorization_assert='Authorization: Bearer [REDACTED]'
assignment_assert='api_key=[REDACTED]'
shell_default=${SAKANA_API_KEY:-}
shell_assign=${SAKANA_API_KEY:=fallback}
SAKANA_API_KEY="${SAKANA_API_KEY:-}"
Authorization: Bearer ${SAKANA_API_KEY:-}
VERIFICATION_TOKEN: CANARY-DO-NOT-REDACT
EOF

OUT_ONE="$WORK/packet-one.md"
OUT_TWO="$WORK/packet-two.md"
OUT_LIMITED="$WORK/packet-limited.md"
(
  cd "$TEST_REPO"
  "$BUILDER" main > "$OUT_ONE"
  "$BUILDER" main > "$OUT_TWO"
  MAX_CONTEXT_BYTES=32 MAX_CONTEXT_FILE_BYTES=16 \
    "$BUILDER" main > "$OUT_LIMITED"
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
grep -Fq 'client_secret: "[REDACTED]"' "$OUT_ONE" \
  || fail "packet did not preserve quotes around a redacted assignment"
grep -Fq 'Authorization: Bearer [REDACTED]' "$OUT_ONE" \
  || fail "packet did not redact a literal authorization header"
grep -Fq 'AWS_ACCESS_KEY_ID=[REDACTED]' "$OUT_ONE" \
  || fail "packet did not redact an AWS access-key identifier"
grep -Fq 'AWS_SECRET_ACCESS_KEY="[REDACTED]"' "$OUT_ONE" \
  || fail "packet did not redact an AWS secret access key"
grep -Fq 'access_key=[REDACTED]' "$OUT_ONE" \
  || fail "packet did not redact a generic access key"
grep -Fq 'secret_access_key: "[REDACTED]"' "$OUT_ONE" \
  || fail "packet did not redact a generic secret access key"
grep -Fq 'headers={"Authorization": "Bearer [REDACTED]"}' "$OUT_ONE" \
  || fail "packet did not preserve JSON authorization delimiters"
grep -Fq 'call(api_key=[REDACTED])' "$OUT_ONE" \
  || fail "packet did not preserve an assignment closing parenthesis"
grep -Fq "authorization_assert='Authorization: Bearer [REDACTED]'" "$OUT_ONE" \
  || fail "packet corrupted an already-redacted authorization assertion"
grep -Fq "assignment_assert='api_key=[REDACTED]'" "$OUT_ONE" \
  || fail "packet corrupted an already-redacted assignment assertion"
grep -Fq 'shell_default=${SAKANA_API_KEY:-}' "$OUT_ONE" \
  || fail "packet corrupted a shell default expansion"
grep -Fq 'shell_assign=${SAKANA_API_KEY:=fallback}' "$OUT_ONE" \
  || fail "packet corrupted a shell assignment expansion"
grep -Fq 'SAKANA_API_KEY="${SAKANA_API_KEY:-}"' "$OUT_ONE" \
  || fail "packet corrupted a dynamic API-key assignment"
grep -Fq 'Authorization: Bearer ${SAKANA_API_KEY:-}' "$OUT_ONE" \
  || fail "packet corrupted a dynamic authorization header"
grep -Fq 'VERIFICATION_TOKEN: CANARY-DO-NOT-REDACT' "$OUT_ONE" \
  || fail "packet redacted the non-secret verification canary"
if grep -Eq 'packet-test-secret|quoted-packet-secret|header-packet-secret|cloud-access-literal|cloud-secret-literal|short-access-literal|short-secret-access-literal|json-header-secret|paren-packet-secret' "$OUT_ONE"; then
  fail "packet retained a redacted secret value"
fi

grep -Fq 'ROOT-GUIDANCE' "$OUT_ONE" \
  || fail "packet omitted the root agent guide"
grep -Fq 'DOCS-GUIDANCE' "$OUT_ONE" \
  || fail "packet omitted the path-scoped docs agent guide"
grep -Fq 'OPENSPEC-GUIDANCE' "$OUT_ONE" \
  || fail "packet omitted the OpenSpec agent guide"
grep -Fq 'ACTIVE-PROPOSAL' "$OUT_ONE" \
  || fail "packet omitted an active OpenSpec proposal"
grep -Fq 'ACTIVE-DESIGN' "$OUT_ONE" \
  || fail "packet omitted an active OpenSpec design"
grep -Fq 'ACTIVE-TASKS' "$OUT_ONE" \
  || fail "packet omitted active OpenSpec tasks"
grep -Fq 'ACTIVE-DELTA-SPEC' "$OUT_ONE" \
  || fail "packet omitted an active OpenSpec delta spec"
grep -Fq 'ACCEPTED-SPEC' "$OUT_ONE" \
  || fail "packet omitted an accepted OpenSpec spec"
if grep -Eq 'LIBS-GUIDANCE-SHOULD-NOT-APPEAR|ARCHIVED-SHOULD-NOT-APPEAR' "$OUT_ONE"; then
  fail "packet included irrelevant or archived repository context"
fi
grep -Fq 'Total context limit: 32 bytes. Per-file limit: 16 bytes.' "$OUT_LIMITED" \
  || fail "packet omitted configured repository-context limits"
grep -Fq '_Omitted: total repository-context byte limit reached._' "$OUT_LIMITED" \
  || fail "packet did not enforce its total repository-context byte limit"

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
