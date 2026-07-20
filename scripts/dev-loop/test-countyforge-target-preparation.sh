#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(git rev-parse --show-toplevel)"
FIXTURE_ROOT="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_ROOT"' EXIT

BASE_ROOT="$FIXTURE_ROOT/base-reference"
TARGET_ROOT="$FIXTURE_ROOT/target"
OUTPUT_ROOT="$FIXTURE_ROOT/prepared"
SENTINEL="$FIXTURE_ROOT/target-code-executed"

git clone --quiet "$REPO_ROOT" "$BASE_ROOT"
git clone --quiet "$REPO_ROOT" "$TARGET_ROOT"
BASE_SHA="$(git -C "$TARGET_ROOT" rev-parse HEAD)"
git -C "$TARGET_ROOT" config user.name "CountyForge fixture"
git -C "$TARGET_ROOT" config user.email "countyforge-fixture@example.invalid"
mkdir -p "$TARGET_ROOT/scripts" "$TARGET_ROOT/.countyforge-hooks"
printf '#!/usr/bin/env bash\ntouch %q\n' "$SENTINEL" > "$TARGET_ROOT/scripts/untrusted-target-command.sh"
printf '#!/usr/bin/env bash\ntouch %q\nprintf "0\\n"\n' "$SENTINEL" > \
  "$TARGET_ROOT/scripts/untrusted-fsmonitor.sh"
printf '#!/usr/bin/env bash\ntouch %q\n' "$SENTINEL" > "$TARGET_ROOT/.countyforge-hooks/post-checkout"
chmod +x \
  "$TARGET_ROOT/scripts/untrusted-target-command.sh" \
  "$TARGET_ROOT/scripts/untrusted-fsmonitor.sh" \
  "$TARGET_ROOT/.countyforge-hooks/post-checkout"
git -C "$TARGET_ROOT" add scripts/untrusted-target-command.sh scripts/untrusted-fsmonitor.sh
git -C "$TARGET_ROOT" commit --quiet -m "synthetic untrusted target"
git -C "$TARGET_ROOT" config core.hooksPath .countyforge-hooks
git -C "$TARGET_ROOT" config core.fsmonitor scripts/untrusted-fsmonitor.sh
HEAD_SHA="$(git -C "$TARGET_ROOT" rev-parse HEAD)"

"$REPO_ROOT/scripts/dev-loop/prepare-countyforge-target.sh" \
  "$TARGET_ROOT" \
  "$BASE_ROOT" \
  "$OUTPUT_ROOT" \
  "$BASE_SHA" \
  "$HEAD_SHA" \
  "TruPryce/property-tax-data-platform" \
  review

test ! -e "$SENTINEL"
test -s "$OUTPUT_ROOT/review-packet.md"
test -s "$OUTPUT_ROOT/review-packet.provenance.json"
test -s "$OUTPUT_ROOT/checksums.sha256"
test "$(git -C "$OUTPUT_ROOT/target.git" rev-parse HEAD)" = "$HEAD_SHA"
test "$(git -C "$OUTPUT_ROOT/target.git" remote get-url origin)" = \
  "https://github.com/TruPryce/property-tax-data-platform.git"
grep -Fq 'scripts/untrusted-target-command.sh' "$OUTPUT_ROOT/review-packet.md"
(
  cd "$OUTPUT_ROOT"
  sha256sum --check checksums.sha256 >/dev/null
)
python3 - "$OUTPUT_ROOT/review-packet.provenance.json" "$BASE_SHA" "$HEAD_SHA" <<'PY'
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert document["repository_full_name"] == "TruPryce/property-tax-data-platform"
assert document["base_sha"] == sys.argv[2]
assert document["head_sha"] == sys.argv[3]
assert document["packet_bytes"] > 0
PY

echo "==> COUNTYFORGE TARGET PREPARATION TESTS PASSED"
