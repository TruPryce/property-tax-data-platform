#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

DEFAULT_BASE="origin/main"
REQUESTED_BASE="${1:-${BASE:-$DEFAULT_BASE}}"
MAX_DIFF_BYTES="${MAX_DIFF_BYTES:-600000}"
MAX_DOC_BYTES="${MAX_DOC_BYTES:-160000}"
MAX_UNTRACKED_FILE_BYTES="${MAX_UNTRACKED_FILE_BYTES:-100000}"
INCLUDE_UNTRACKED_CONTENT="${INCLUDE_UNTRACKED_CONTENT:-1}"
REDACT_REVIEW_PACKET="${REDACT_REVIEW_PACKET:-1}"

err() { printf 'ERROR: %s\n' "$*" >&2; }
warn() { printf 'WARN: %s\n' "$*" >&2; }

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  err "not inside a git repository"
  exit 2
}
cd "$REPO_ROOT"

have_ref() { git rev-parse --verify "$1" >/dev/null 2>&1; }

resolve_base() {
  local requested="$1"
  if have_ref "$requested"; then
    printf '%s\n' "$requested"
    return 0
  fi

  if [[ "$requested" == "$DEFAULT_BASE" ]]; then
    local candidate
    for candidate in origin/main main origin/master master; do
      if have_ref "$candidate"; then
        warn "base ref '$requested' not found; using '$candidate'"
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  fi

  err "base ref '$requested' not found. Fetch it or pass BASE=<ref>."
  exit 2
}

BASE="$(resolve_base "$REQUESTED_BASE")"
MERGE_BASE="$(git merge-base "$BASE" HEAD)"
BRANCH="$(git branch --show-current 2>/dev/null || echo 'unknown')"
HEAD_SHA="$(git rev-parse --short HEAD)"
BASE_SHA="$(git rev-parse --short "$BASE")"
MERGE_BASE_SHA="$(git rev-parse --short "$MERGE_BASE")"

redact_stream() {
  if [[ "$REDACT_REVIEW_PACKET" == "0" ]]; then
    cat
    return 0
  fi
  python3 -c '
import re, sys
patterns = [
    (re.compile(r"(?i)(authorization:\s*)(bearer|basic)\s+[^\s,;]+"), r"\1\2 [REDACTED]"),
    (re.compile(r"(?i)((?:token|secret|password|passwd|api[_-]?key|client[_-]?secret|private[_-]?key|signing[_-]?key)\s*[=:]\s*)([^\s\"\x27,}]+)"), r"\1[REDACTED]"),
]
for line in sys.stdin:
    for pat, repl in patterns:
        line = pat.sub(repl, line)
    sys.stdout.write(line)
'
}

emit_bytes_redacted() {
  local path="$1"
  local max_bytes="$2"
  local bytes
  bytes="$(wc -c < "$path" | tr -d ' ')"
  if (( bytes == 0 )); then
    echo "[no output]"
  elif (( bytes > max_bytes )); then
    head -c "$max_bytes" "$path" | redact_stream
    echo
    echo
    echo "[TRUNCATED: output was $bytes bytes; emitted first $max_bytes bytes]"
  else
    redact_stream < "$path"
  fi
}

emit_truncated_file() {
  local path="$1"
  local max_bytes="$2"
  [[ -f "$path" ]] || return 0

  echo
  echo "### \`$path\`"
  echo
  echo '```markdown'
  emit_bytes_redacted "$path" "$max_bytes"
  echo '```'
}

emit_truncated_command() {
  local title="$1"
  local language="$2"
  local max_bytes="$3"
  shift 3

  local tmp status
  tmp="$(mktemp)"
  if "$@" > "$tmp" 2>&1; then
    status=0
  else
    status=$?
  fi

  echo
  echo "## $title"
  echo
  if (( status != 0 )); then
    echo "Command failed with exit code $status:"
    echo
    echo '```text'
    printf '%q ' "$@"
    echo
    echo '```'
    emit_bytes_redacted "$tmp" "$max_bytes"
    rm -f "$tmp"
    return "$status"
  fi

  echo "\`\`\`$language"
  emit_bytes_redacted "$tmp" "$max_bytes"
  echo '```'
  rm -f "$tmp"
}

is_sensitive_path() {
  local path_lc
  path_lc="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$path_lc" in
    .env.example | .env.sample | .env.template) return 1 ;;
    .env | .env.* | *credential* | *secret* | *token* | *.pem | *.key | *.p12 | *.pfx | *.license | *.lic) return 0 ;;
    *) return 1 ;;
  esac
}

emit_truncated_diff() {
  local title="$1"
  local max_bytes="$2"
  shift 2

  local sensitive_paths=()
  local status path second_path
  while IFS= read -r -d '' status; do
    if [[ "$status" == R* || "$status" == C* ]]; then
      IFS= read -r -d '' path || true
      IFS= read -r -d '' second_path || true
      is_sensitive_path "$path" && sensitive_paths+=("$path")
      is_sensitive_path "$second_path" && sensitive_paths+=("$second_path")
    else
      IFS= read -r -d '' path || true
      is_sensitive_path "$path" && sensitive_paths+=("$path")
    fi
  done < <("$@" --name-status -z)

  if (( ${#sensitive_paths[@]} > 0 )); then
    echo
    echo "## $title"
    echo
    echo "ERROR: refusing to emit raw diff because sensitive path(s) are present:"
    printf '%s\n' "${sensitive_paths[@]}" | sed 's/^/- /'
    echo
    echo "Remove the sensitive file from the diff or rename it before building a review packet."
    err "refusing to emit raw diff because sensitive path(s) are present"
    return 3
  fi

  emit_truncated_command "$title" "diff" "$max_bytes" "$@"
}

emit_untracked_files() {
  local files=()
  while IFS= read -r -d '' file; do
    files+=("$file")
  done < <(git ls-files --others --exclude-standard -z)

  echo
  echo "## Untracked Files"
  echo

  if (( ${#files[@]} == 0 )); then
    echo "_No untracked files._"
    return 0
  fi

  printf '%s\n' "${files[@]}" | sed 's/^/- /'

  if [[ "$INCLUDE_UNTRACKED_CONTENT" != "1" ]]; then
    echo
    echo "_Untracked file content omitted because INCLUDE_UNTRACKED_CONTENT=$INCLUDE_UNTRACKED_CONTENT._"
    return 0
  fi

  echo
  echo "## Untracked File Contents"

  local file bytes tmp
  for file in "${files[@]}"; do
    echo
    echo "### \`$file\`"
    echo

    if [[ -L "$file" ]]; then
      echo "_Skipped: symlink content is not included in review packets._"
      continue
    fi
    if [[ ! -f "$file" ]]; then
      echo "_Skipped: not a regular file._"
      continue
    fi
    if is_sensitive_path "$file"; then
      echo "_Skipped content: path looks secret-bearing._"
      continue
    fi

    bytes="$(wc -c < "$file" | tr -d ' ')"
    if (( bytes > MAX_UNTRACKED_FILE_BYTES )); then
      echo "_Skipped content: file is $bytes bytes; limit is $MAX_UNTRACKED_FILE_BYTES bytes._"
      continue
    fi
    if ! LC_ALL=C grep -Iq . "$file" && (( bytes > 0 )); then
      echo "_Skipped content: file appears to be binary._"
      continue
    fi

    tmp="$(mktemp)"
    {
      echo "diff --git a/$file b/$file"
      echo "new file mode 100644"
      echo "--- /dev/null"
      echo "+++ b/$file"
      sed 's/^/+/' "$file"
    } > "$tmp"
    echo '```diff'
    emit_bytes_redacted "$tmp" "$MAX_UNTRACKED_FILE_BYTES"
    echo '```'
    rm -f "$tmp"
  done
}

cat <<EOF
# Pre-PR Review Packet

## Metadata

| Field | Value |
|---|---|
| Requested base ref | \`$REQUESTED_BASE\` |
| Resolved base ref | \`$BASE\` |
| Base SHA | \`$BASE_SHA\` |
| Merge base | \`$MERGE_BASE_SHA\` |
| Branch | \`$BRANCH\` |
| Head SHA | \`$HEAD_SHA\` |

## Reviewer Task

Review the current branch diff against \`$BASE\`.

Use the repository's pre-PR review contract if present. Do not expand the scope beyond this branch's changes.
EOF

if [[ -f "docs/engineering/pre-pr-review-contract.md" ]]; then
  echo
  echo "## Review Contract"
  emit_truncated_file "docs/engineering/pre-pr-review-contract.md" "$MAX_DOC_BYTES"
fi

if [[ -f ".ai/prompts/codex-prepr-review.md" ]]; then
  echo
  echo "## Codex Review Prompt"
  emit_truncated_file ".ai/prompts/codex-prepr-review.md" "$MAX_DOC_BYTES"
fi

emit_truncated_command "Git Status" "text" 80000 git status --short --branch
emit_truncated_command "Changed Files: Branch Diff" "text" 120000 git diff --name-status "$MERGE_BASE"...HEAD
emit_truncated_command "Changed Files: Staged Diff" "text" 80000 git diff --cached --name-status
emit_truncated_command "Changed Files: Unstaged Diff" "text" 80000 git diff --name-status
emit_truncated_command "Diff Stat: Branch Diff" "text" 120000 git diff --stat "$MERGE_BASE"...HEAD
emit_truncated_command "Diff Stat: Staged Diff" "text" 80000 git diff --cached --stat
emit_truncated_command "Diff Stat: Unstaged Diff" "text" 80000 git diff --stat
emit_truncated_diff "Raw Diff: Branch Commits" "$MAX_DIFF_BYTES" git diff --find-renames --find-copies "$MERGE_BASE"...HEAD
emit_truncated_diff "Raw Diff: Staged Changes" "$MAX_DIFF_BYTES" git diff --cached --find-renames --find-copies
emit_truncated_diff "Raw Diff: Unstaged Changes" "$MAX_DIFF_BYTES" git diff --find-renames --find-copies

emit_untracked_files

cat <<'EOF'

## Review Output Requirement

Return the review using `.ai/schemas/codex-prepr-review.schema.json`.
EOF
