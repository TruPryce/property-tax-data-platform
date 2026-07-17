#!/usr/bin/env bash
set -uo pipefail

# QA entry point for the local observability export. Free + deterministic — runs
# NO paid model call and NO Docker. Runs:
#   - fixture QA (always)
#   - latest-run validation (only if a run exists for the current branch)
# Exits non-zero if any tier fails.

REPO_ROOT="$(git rev-parse --show-toplevel)"
rc=0

echo "==> Codex runner observability QA (free, deterministic — no model call)"

echo
echo "--- Fixture QA (always) ---"
if ! "$REPO_ROOT/.ai/codex/05-test-observability-export-fixtures.sh"; then
  rc=1
fi

echo
echo "--- Latest-run validation (only if a run exists for this branch) ---"
branch="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
safe="$(printf '%s' "$branch" | sed 's#[^A-Za-z0-9._-]#__#g')"
latest="$REPO_ROOT/.ai/reviews/codex-prepr/$safe/latest.json"
if [ -f "$latest" ]; then
  if ! "$REPO_ROOT/.ai/codex/04-validate-observability-export.sh"; then
    rc=1
  fi
else
  echo "WARN: no latest run for branch '$branch'; skipping latest-run validation."
  echo "      Produce a run with 'make prepr', or pass RUN_DIR=/path/to/run to"
  echo "      ./.ai/codex/04-validate-observability-export.sh."
fi

echo
if [ "$rc" -eq 0 ]; then
  echo "==> OBSERVABILITY QA PASSED"
else
  echo "==> OBSERVABILITY QA FAILED"
fi
exit "$rc"
