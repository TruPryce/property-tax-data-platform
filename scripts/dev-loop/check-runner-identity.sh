#!/usr/bin/env bash
set -euo pipefail

SEARCH_BIN="${RUNNER_IDENTITY_SEARCH_BIN:-grep}"
TARGET="${1:-.ai}"
PATTERN='platform[-]edge|pulse[-]ops[-]ai|forproperty[-]tax|dev[.]platform[-]edge'

if ! command -v "$SEARCH_BIN" >/dev/null 2>&1; then
  echo "error: required runner identity search tool is unavailable: $SEARCH_BIN" >&2
  exit 2
fi

if [[ ! -e "$TARGET" ]]; then
  echo "error: runner identity scan target does not exist: $TARGET" >&2
  exit 2
fi

set +e
OUTPUT="$($SEARCH_BIN -rEn --exclude-dir=reviews -- "$PATTERN" "$TARGET" 2>&1)"
STATUS=$?
set -e

case "$STATUS" in
  0)
    printf '%s\n' "$OUTPUT"
    echo "error: inherited runner identity remains in the runtime contract" >&2
    exit 1
    ;;
  1)
    exit 0
    ;;
  *)
    printf '%s\n' "$OUTPUT" >&2
    echo "error: runner identity scan failed with status $STATUS" >&2
    exit 2
    ;;
esac
