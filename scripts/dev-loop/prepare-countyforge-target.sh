#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

if [[ "$#" -ne 7 ]]; then
  echo "usage: $0 <target-root> <base-root> <output-root> <base-sha> <head-sha> <repository> <command>" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRUSTED_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TARGET_ROOT="$(realpath "$1")"
BASE_ROOT="$(realpath "$2")"
OUTPUT_ROOT="$3"
BASE_SHA="$4"
HEAD_SHA="$5"
REPOSITORY="$6"
COMMAND="$7"
MAX_PREPARED_BYTES="${MAX_PREPARED_BYTES:-100000000}"

# These command-scope settings also apply to trusted packet-builder Git subprocesses.
# They prevent target-local hooks, fsmonitor commands, helpers, or ext transports from
# turning fixed read-only Git queries into an execution path.
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_COUNT=6
export GIT_CONFIG_KEY_0=core.hooksPath
export GIT_CONFIG_VALUE_0=/dev/null
export GIT_CONFIG_KEY_1=core.fsmonitor
export GIT_CONFIG_VALUE_1=false
export GIT_CONFIG_KEY_2=credential.helper
export GIT_CONFIG_VALUE_2=
export GIT_CONFIG_KEY_3=protocol.ext.allow
export GIT_CONFIG_VALUE_3=never
export GIT_CONFIG_KEY_4=protocol.file.allow
export GIT_CONFIG_VALUE_4=always
export GIT_CONFIG_KEY_5=core.sshCommand
export GIT_CONFIG_VALUE_5=false
export GIT_TERMINAL_PROMPT=0

if [[ ! "$BASE_SHA" =~ ^[0-9a-f]{40}$ || ! "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "error: target preparation requires immutable commit SHAs" >&2
  exit 2
fi
if [[ ! "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "error: target preparation repository identity is invalid" >&2
  exit 2
fi
case "$COMMAND" in
  review | plan | implement | fix | validate) ;;
  *)
    echo "error: target preparation command is invalid" >&2
    exit 2
    ;;
esac
if [[ ! "$MAX_PREPARED_BYTES" =~ ^[1-9][0-9]*$ ]]; then
  echo "error: target preparation byte limit is invalid" >&2
  exit 2
fi
if [[ -e "$OUTPUT_ROOT" && -n "$(find "$OUTPUT_ROOT" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
  echo "error: target preparation output directory is not empty" >&2
  exit 2
fi

mkdir -p "$OUTPUT_ROOT"
git -C "$TARGET_ROOT" fetch --quiet --no-tags "$BASE_ROOT" "$BASE_SHA"
git -C "$TARGET_ROOT" cat-file -e "${BASE_SHA}^{commit}"
test "$(git -C "$TARGET_ROOT" rev-parse HEAD)" = "$HEAD_SHA"

if [[ "$COMMAND" == "review" ]]; then
  (
    cd "$TARGET_ROOT"
    bash "$TRUSTED_ROOT/scripts/dev-loop/build-review-packet.sh" "$BASE_SHA"
  ) > "$OUTPUT_ROOT/review-packet.md"
  python3 "$TRUSTED_ROOT/scripts/dev-loop/build-review-packet-provenance.py" \
    --repo-root "$TARGET_ROOT" \
    --packet "$OUTPUT_ROOT/review-packet.md" \
    --repository "$REPOSITORY" \
    > "$OUTPUT_ROOT/review-packet.provenance.json"
fi

git init --quiet --bare --initial-branch=countyforge-target "$OUTPUT_ROOT/target.git"
git -C "$OUTPUT_ROOT/target.git" remote add origin "https://github.com/${REPOSITORY}.git"
git -C "$OUTPUT_ROOT/target.git" fetch --quiet --no-tags "$TARGET_ROOT" \
  "$BASE_SHA" "$HEAD_SHA"
git -C "$OUTPUT_ROOT/target.git" update-ref refs/heads/countyforge-target "$HEAD_SHA"
git -C "$OUTPUT_ROOT/target.git" symbolic-ref HEAD refs/heads/countyforge-target

(
  cd "$OUTPUT_ROOT"
  LC_ALL=C find . -type f ! -name checksums.sha256 -print0 | LC_ALL=C sort -z | \
    xargs -0 sha256sum > checksums.sha256
)
prepared_bytes="$(du -sb "$OUTPUT_ROOT" | cut -f1)"
if (( prepared_bytes > MAX_PREPARED_BYTES )); then
  echo "error: target preparation exceeds its byte limit" >&2
  exit 2
fi
