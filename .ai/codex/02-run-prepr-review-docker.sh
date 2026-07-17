#!/usr/bin/env bash
set -euo pipefail

# Artifact contract version for the per-run review directory. Bump when the set
# of files written under .ai/reviews/codex-prepr/<branch>/<run-id>/ or their
# field shapes change. Documented in docs/engineering/review-artifact-contract.md.
ARTIFACT_CONTRACT_VERSION="1"
# Schema version for the local observability event (codex-runner-event.ndjson).
# Documented in docs/engineering/codex-runner-observability.md.
EVENT_SCHEMA_VERSION="1"

REPO_ROOT="$(git rev-parse --show-toplevel)"
# Low-cardinality repo identifier for the observability event/metrics labels.
REPO="$(basename "$REPO_ROOT")"
IMAGE="${CODEX_IMAGE:-platform-edge-codex-agent:local}"

# Redact the live provider key from any text streamed to the terminal. Failure
# paths below tail captured stdout/stderr for debugging; this guarantees the
# SAKANA_API_KEY value is never echoed even if the model or CLI ever surfaced
# it. Literal (not regex) replacement so key characters can't break the match.
redact_secret() {
  if [ -n "${SAKANA_API_KEY:-}" ]; then
    SAKANA_API_KEY="$SAKANA_API_KEY" python3 -c 'import os,sys; k=os.environ["SAKANA_API_KEY"]; sys.stdout.write(sys.stdin.read().replace(k, "***REDACTED-SAKANA_API_KEY***") if k else sys.stdin.read())'
  else
    cat
  fi
}

PACKET_PATH="${PACKET_PATH:-$REPO_ROOT/.ai/reviews/review-packet.md}"
SCHEMA_PATH="${SCHEMA_PATH:-$REPO_ROOT/.ai/schemas/codex-prepr-review.schema.json}"

BRANCH_NAME="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
SAFE_BRANCH="$(printf '%s' "$BRANCH_NAME" | sed 's#[^A-Za-z0-9._-]#__#g')"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%d-%H%M%S)}"
HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
HEAD_SHORT="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"

# Source of truth: every run writes a self-contained, auditable directory at
# .ai/reviews/codex-prepr/<safe-branch>/<run-id>/. An explicit OUT_DIR override
# (direct callers, smoke test) names that run directory; otherwise default to
# the per-branch/per-run path. The historical root .ai/reviews/ files are a
# compatibility MIRROR only (see COMPAT_DIR), never the source of truth.
OUT_DIR="${OUT_DIR:-$REPO_ROOT/.ai/reviews/codex-prepr/$SAFE_BRANCH/$RUN_ID}"

# Keep generated review artifacts (review, logs, provenance) inside the repo
# unless a human intentionally opts out, matching the AGENTS.md contract and the
# native scripts/dev-loop/prepr.sh guard. An inherited OUT_DIR=/tmp/... from a
# shell or CI job would otherwise silently write outside .ai/reviews/.
ALLOW_EXTERNAL_OUT_DIR="${ALLOW_EXTERNAL_OUT_DIR:-0}"
resolve_out_dir() {
  local requested="$1"
  python3 - "$REPO_ROOT" "$requested" "$ALLOW_EXTERNAL_OUT_DIR" <<'PYINNER'
import os
import sys

root = os.path.realpath(sys.argv[1])
requested = sys.argv[2]
allow_external = sys.argv[3] == "1"

candidate = requested if os.path.isabs(requested) else os.path.join(root, requested)
path = os.path.realpath(candidate)

try:
    inside_repo = os.path.commonpath([root, path]) == root
except ValueError:
    inside_repo = False

if not inside_repo and not allow_external:
    sys.stderr.write(
        f"OUT_DIR resolves outside repo root: {requested} -> {path}\n"
        "Use a repo-contained OUT_DIR, or set ALLOW_EXTERNAL_OUT_DIR=1 intentionally.\n"
    )
    sys.exit(2)

print(path)
PYINNER
}
OUT_DIR="$(resolve_out_dir "$OUT_DIR")" || exit $?
RUN_DIR="$OUT_DIR"
BRANCH_DIR="$(dirname "$RUN_DIR")"

# The per-branch latest.json pointer is meaningful ONLY when RUN_DIR sits in the
# documented .../codex-prepr/<safe-branch>/<run-id> layout (default path or a
# custom reviews root). For an arbitrary OUT_DIR override (e.g. the smoke test's
# temp dir) there is no per-branch namespace, so skip the pointer rather than
# scatter a latest.json into an unrelated parent directory.
case "$RUN_DIR" in
  */codex-prepr/"$SAFE_BRANCH"/*) WRITE_LATEST=1 ;;
  *) WRITE_LATEST=0 ;;
esac

# Optional backward-compatibility mirror. prepr.sh passes COMPAT_DIR=.ai/reviews
# so the historical root-level files (review, logs, packet provenance) keep
# working for existing tooling. It is a copy target, not the source of truth.
COMPAT_DIR="${COMPAT_DIR:-}"
if [ -n "$COMPAT_DIR" ]; then
  COMPAT_DIR="$(resolve_out_dir "$COMPAT_DIR")" || exit $?
fi

STDOUT_LOG="$RUN_DIR/codex-prepr-review.stdout"
STDERR_LOG="$RUN_DIR/codex-prepr-review.stderr"
EVENTS_LOG="$RUN_DIR/codex-events.ndjson"
FINAL_REVIEW="$RUN_DIR/codex-prepr-review.md"
PACKET_PROVENANCE="$RUN_DIR/packet.provenance.json"
CONTAINER_PROVENANCE="$RUN_DIR/container.provenance.json"
RUN_PROVENANCE="$RUN_DIR/run.provenance.json"
RUN_SUMMARY="$RUN_DIR/run.summary.json"
LATEST_POINTER="$BRANCH_DIR/latest.json"
CLAIM_MARKER="$RUN_DIR/.claim"
# Local observability export (contract/export only — no live collector). The
# event is a single normalized JSON line; the metrics are Prometheus textfile
# format. Both are derived only from non-secret provenance/summary values.
RUNNER_EVENT="$RUN_DIR/codex-runner-event.ndjson"
RUNNER_METRICS="$RUN_DIR/codex-runner-metrics.prom"
LATEST_METRICS="$BRANCH_DIR/latest-codex-runner-metrics.prom"

SCHEMA_DIR="$(dirname "$SCHEMA_PATH")"
SCHEMA_FILE="$(basename "$SCHEMA_PATH")"
CONTAINER_SCHEMA_PATH="/workspace/.ai/schemas/$SCHEMA_FILE"
CONTAINER_NAME="platform-edge-codex-prepr-${SAFE_BRANCH}-${RUN_ID}"
USER_SPEC="$(id -u):$(id -g)"

# Single source of truth for the writable tmpfs specs: used verbatim both in the
# `docker run --tmpfs` flags and in container.provenance.json, so the recorded
# posture is byte-exact to what ran and cannot drift.
TMPFS_TMP_SPEC="/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777"
TMPFS_CODEX_HOME_SPEC="/tmp/codex-home:rw,nosuid,nodev,size=256m,mode=1777"

# Single source of truth for the model-invokable tools we strip at the CLI. Used
# both to build EXEC_ARGS below and to record the posture in
# container.provenance.json, so the two can never drift.
DISABLED_TOOLS=(
  shell_tool
  unified_exec
  browser_use
  browser_use_external
  browser_use_full_cdp_access
  computer_use
  in_app_browser
  apps
  image_generation
)

# Collision guard, in two parts, BOTH before the EXIT trap is installed so a
# refused run never touches (or summarizes into) a directory that isn't ours:
#
#   1) Refuse a directory that already holds a prior run's evidence. An
#      already-existing but EMPTY directory is fine (callers/tests may pre-create
#      the mount point). The `[ -d ]` guard short-circuits the `ls` so an absent
#      default run directory does not trip `set -e` before the trap is installed.
#      The run dir is empty here in every supported path: this run's input packet
#      is staged into it only AFTER the claim below, so there is nothing to
#      special-case.
#   2) Take an ATOMIC claim. `mkdir` of the claim marker is atomic and fails if a
#      concurrent run with the same RUN_ID (the default is a one-second-
#      resolution stamp) already claimed this directory. A plain "is it empty?"
#      check followed by a write is a race: two same-RUN_ID runs could both see
#      it empty and then interleave evidence. The claim makes the reservation
#      single-winner. finalize() removes the marker on exit.
# An existing .claim means another same-RUN_ID run is in flight (or one was
# interrupted before its EXIT trap removed the marker). Report that specifically,
# since the `.claim` marker is itself a non-empty entry that would otherwise hit
# the generic "prior evidence" branch below.
if [ -e "$CLAIM_MARKER" ]; then
  cat >&2 <<EOF
error: run directory is already claimed:

  $RUN_DIR

Another review with the same RUN_ID is in progress, or a prior run was
interrupted before releasing its claim. Use a distinct RUN_ID, or remove that
directory if you are sure no run is active.
EOF
  exit 2
fi

if [ -d "$RUN_DIR" ] && [ -n "$(ls -A "$RUN_DIR" 2>/dev/null)" ]; then
  cat >&2 <<EOF
error: run directory already exists and is not empty:

  $RUN_DIR

Refusing to overwrite a prior run's evidence. Use a fresh RUN_ID (the default is
a UTC YYYYMMDD-HHMMSS stamp) or remove that directory if it is stale.
EOF
  exit 2
fi

if ! mkdir -p "$RUN_DIR" 2>/dev/null; then
  echo "error: could not create run directory: $RUN_DIR" >&2
  exit 2
fi

if ! mkdir "$CLAIM_MARKER" 2>/dev/null; then
  cat >&2 <<EOF
error: run directory is already claimed by a concurrent run:

  $RUN_DIR

Another review with the same RUN_ID is in progress. Use a distinct RUN_ID.
EOF
  exit 2
fi

# --- Run lifecycle bookkeeping ---------------------------------------------
# STAGE/ERROR_MSG track where we are so the EXIT trap can always emit an
# accurate run.summary.json on any path AFTER this point (the run directory is
# now resolved and created). Failures earlier than this — bad OUT_DIR
# resolution, the collision guard above, or mkdir itself — exit before the trap
# and intentionally leave no summary in a directory that isn't ours.
STAGE="preflight"
ERROR_MSG=""
# Set true only if the live provider key is found in a generated artifact by the
# post-run secret-leak gate below; recorded in run.summary.json on every path.
LEAK_FOUND="false"
START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_TS="$(date -u +%s)"

# Identity fields the summary/pointer need are exported early so the EXIT trap
# produces a valid summary even if we fail before the provenance files are
# written. The rest of the PV_* values are exported just before the run.
export PV_ACV="$ARTIFACT_CONTRACT_VERSION"
export PV_RUN_ID="$RUN_ID"
export PV_BRANCH="$BRANCH_NAME"
export PV_SAFE="$SAFE_BRANCH"
export PV_RUN_DIR="$RUN_DIR"
PV_RUN_DIRNAME="$(basename "$RUN_DIR")"
export PV_RUN_DIRNAME
export PV_COMPAT_DIR="$COMPAT_DIR"
export PV_PACKET_PATH="$PACKET_PATH"
export PV_START="$START_ISO"
# Observability identity/posture available on every path (incl. early failures):
# repo, the event schema version, and the constant tool-disable posture.
export PV_REPO="$REPO"
export PV_MODE="docker"
export EV_SCHEMA_VERSION="$EVENT_SCHEMA_VERSION"
export PV_DISABLED="${DISABLED_TOOLS[*]}"

mirror_to_compat() {
  # Mirror the historical root-level artifact subset into COMPAT_DIR for backward
  # compatibility. The run directory remains the source of truth.
  #
  # The mirror is kept COHERENT with this run only: for each compat file, copy it
  # when this run produced it, otherwise REMOVE any stale copy. Without the
  # removal, a failed run (fresh logs + packet.provenance.json, but no
  # codex-prepr-review.md) would leave a PREVIOUS run's review.md in the root,
  # pairing a stale verdict with current-run evidence.
  [ -n "$COMPAT_DIR" ] || return 0
  [ "$COMPAT_DIR" = "$RUN_DIR" ] && return 0
  # A pure preflight failure (bad effort, missing key/packet/schema/image)
  # produced NO this-run artifacts, so refreshing the mirror would only delete
  # the last good root-level copies. Leave them untouched. A detected leak is the
  # exception: it always purges (below), and any run that reached execution
  # refreshes the mirror coherently.
  if [ "$LEAK_FOUND" != "true" ] && [ "$STAGE" = "preflight" ]; then
    return 0
  fi
  mkdir -p "$COMPAT_DIR" 2>/dev/null || return 0
  local f
  for f in \
    codex-prepr-review.md \
    codex-prepr-review.stdout \
    codex-prepr-review.stderr \
    packet.provenance.json; do
    if [ "$LEAK_FOUND" = "true" ]; then
      # Leak detected: never propagate the leaked artifacts to the compat mirror;
      # purge any copies instead.
      rm -f "$COMPAT_DIR/$f" 2>/dev/null || true
    elif [ -f "$RUN_DIR/$f" ]; then
      cp -f "$RUN_DIR/$f" "$COMPAT_DIR/$f" 2>/dev/null || true
    else
      rm -f "$COMPAT_DIR/$f" 2>/dev/null || true
    fi
  done
}

finalize() {
  local code=$?
  set +e
  local finish_iso finish_ts duration status verdict schema_valid obs_ok obs_rc obs_failed obs_f
  finish_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  finish_ts="$(date -u +%s)"
  duration=$(( finish_ts - START_TS ))
  if [ "$code" -eq 0 ]; then status="succeeded"; else status="failed"; fi
  verdict=""
  if [ -s "$FINAL_REVIEW" ]; then
    verdict="$(jq -r '.verdict // empty' "$FINAL_REVIEW" 2>/dev/null)" || verdict=""
  fi
  if [ -n "$verdict" ]; then schema_valid="true"; else schema_valid="false"; fi

  # --- Local observability export (event + metrics) -------------------------
  # Contract/export only — NO live collector. Derived solely from non-secret
  # provenance/summary values (never raw review/stdout/stderr/event payloads,
  # keys, tokens, or env dumps). Written BEFORE run.summary.json so its artifact
  # map reflects them. This is part of the local observability contract, so a
  # write failure fails the run loudly (below) rather than being best-effort.
  obs_ok=1
  RS_STATUS="$status" RS_CODE="$code" RS_STAGE="$STAGE" RS_FINISH="$finish_iso" \
  RS_DURATION="$duration" RS_VERDICT="$verdict" RS_SECRET_LEAK="$LEAK_FOUND" \
  RS_SCHEMA_VALID="$schema_valid" \
  python3 - "$RUNNER_EVENT" "$RUNNER_METRICS" <<'PY'
import json, os, sys

event_path, metrics_path = sys.argv[1], sys.argv[2]


def s(name):
    v = os.environ.get(name)
    return v if v not in (None, "") else None


def i(name):
    v = os.environ.get(name)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except ValueError:
        return None


disabled = os.environ.get("PV_DISABLED", "").split()

event = {
    "schema_version": int(os.environ.get("EV_SCHEMA_VERSION", "1")),
    "artifact_contract_version": i("PV_ACV"),
    "event_type": "codex_prepr_review_run",
    "repo": s("PV_REPO"),
    "run_id": s("PV_RUN_ID"),
    "branch": s("PV_BRANCH"),
    "safe_branch": s("PV_SAFE"),
    "review_mode": s("PV_MODE"),
    "run_dir": s("PV_RUN_DIR"),
    "started_at": s("PV_START"),
    "finished_at": s("RS_FINISH"),
    "duration_seconds": i("RS_DURATION"),
    "status": s("RS_STATUS"),
    "exit_code": i("RS_CODE"),
    "stage": s("RS_STAGE"),
    "verdict": s("RS_VERDICT"),
    "secret_leak_detected": os.environ.get("RS_SECRET_LEAK") == "true",
    "packet_bytes": i("PV_PACKET_BYTES"),
    "packet_sha256": s("PV_PACKET_SHA"),
    "max_packet_bytes": i("PV_MAX_BYTES"),
    "schema_sha256": s("PV_SCHEMA_SHA"),
    "head_sha": s("PV_HEAD_SHA"),
    "head_short_sha": s("PV_HEAD_SHORT"),
    "review_base": s("PV_REVIEW_BASE"),
    "image": s("PV_IMAGE"),
    "image_id": s("PV_IMAGE_ID"),
    "codex_cli_version": s("PV_CODEX_VER"),
    "model": s("PV_MODEL"),
    "model_source": s("PV_MODEL_SOURCE"),
    "model_provider": s("PV_PROVIDER"),
    "reasoning_effort": s("PV_REASONING_EFFORT"),
    "reasoning_effort_source": s("PV_REASONING_SOURCE"),
    "sandbox": "danger-full-access",
    "web_search": False,
    "disabled_tools": disabled,
    "output_schema_sha256": s("PV_SCHEMA_SHA"),
}
with open(event_path, "w") as f:
    f.write(json.dumps(event) + "\n")

# Prometheus textfile metrics — low cardinality, only the allowed label set.
def lv(v):
    if v in (None, ""):
        return "unknown"
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

labels = {
    "repo": lv(event["repo"]),
    "run_type": "prepr_review",
    "runner": lv(event["review_mode"]),
    "provider": lv(event["model_provider"]),
    "model": lv(event["model"]),
    "reasoning_effort": lv(event["reasoning_effort"]),
    "outcome": lv(event["status"]),
    "stage": lv(event["stage"]),
    "verdict": lv(event["verdict"] if event["verdict"] is not None else "none"),
}


def lbls(d):
    return "{" + ",".join('%s="%s"' % (k, v) for k, v in d.items()) + "}"


L = lbls(labels)
lines = []


def metric(name, help_text, value, lblstr=L):
    lines.append("# HELP %s %s" % (name, help_text))
    lines.append("# TYPE %s gauge" % name)
    lines.append("%s%s %s" % (name, lblstr, value))


dur = event["duration_seconds"] if event["duration_seconds"] is not None else 0
exit_code = event["exit_code"] if event["exit_code"] is not None else 0
secret_leak = 1 if event["secret_leak_detected"] else 0
schema_valid = 1 if os.environ.get("RS_SCHEMA_VALID") == "true" else 0

metric("codex_runner_run_duration_seconds",
       "Wall-clock duration of the Codex/Fugu pre-PR review run.", dur)
if event["packet_bytes"] is not None:
    metric("codex_runner_packet_bytes",
           "Size in bytes of the reviewed packet.", event["packet_bytes"])
metric("codex_runner_exit_code", "Runner process exit code.", exit_code)
metric("codex_runner_secret_leak_detected",
       "1 if a provider key leaked into a generated artifact, else 0.", secret_leak)
metric("codex_runner_schema_valid",
       "1 if the review output is present with a parseable verdict, else 0. The CLI "
       "enforces the output schema at generation; this is not a re-validation.",
       schema_valid)
metric("codex_runner_artifact_contract_version_info",
       "Artifact contract and event schema versions (value always 1).", 1,
       lbls({"repo": labels["repo"],
             "artifact_contract_version": str(event["artifact_contract_version"]),
             "event_schema_version": str(event["schema_version"])}))
metric("codex_runner_run_info",
       "Identity and configuration of the run (value always 1).", 1)

with open(metrics_path, "w") as f:
    f.write("\n".join(lines) + "\n")
PY
  obs_rc=$?
  [ "$obs_rc" -eq 0 ] || obs_ok=0

  # Safety net: the event/metrics are built only from non-secret values, but scan
  # them for the live key anyway. A hit (should be impossible) is treated as a
  # leak — delete them and flag it.
  for obs_f in "$RUNNER_EVENT" "$RUNNER_METRICS"; do
    [ -f "$obs_f" ] || continue
    if [ -n "${SAKANA_API_KEY:-}" ] && grep -Fq -- "$SAKANA_API_KEY" "$obs_f"; then
      LEAK_FOUND="true"
      obs_ok=0
      rm -f "$RUNNER_EVENT" "$RUNNER_METRICS" 2>/dev/null || true
      echo "error: provider key found in observability export; deleted it" >&2
      break
    fi
  done

  # Branch-latest metrics mirror (canonical layout only). This is a MIRROR ONLY —
  # the per-run codex-runner-metrics.prom is the source of truth — so a copy
  # failure WARNS but does NOT set obs_ok=0 or change the run's outcome. Failing
  # here would flip an otherwise-successful run to failed while the per-run event
  # and metrics still say succeeded, desyncing them from run.summary.json.
  if [ "$WRITE_LATEST" = "1" ] && [ -f "$RUNNER_METRICS" ]; then
    cp -f "$RUNNER_METRICS" "$LATEST_METRICS" 2>/dev/null \
      || echo "warning: could not update latest metrics mirror (per-run metrics are authoritative): $LATEST_METRICS" >&2
  fi

  # Fail loud if the local observability export failed on an otherwise-successful
  # run — it is part of the contract, not best-effort.
  obs_failed=0
  if [ "$obs_ok" != "1" ] && [ "$code" -eq 0 ]; then
    obs_failed=1
    code=3
    status="failed"
    STAGE="observability_export"
    ERROR_MSG="local observability export failed (event/metrics)"
    echo "error: $ERROR_MSG; failing the run" >&2
  fi

  # run.summary.json — always written, including failure paths.
  RS_STATUS="$status" RS_CODE="$code" RS_STAGE="$STAGE" RS_ERROR="$ERROR_MSG" \
  RS_FINISH="$finish_iso" RS_DURATION="$duration" RS_VERDICT="$verdict" \
  RS_SECRET_LEAK="$LEAK_FOUND" \
  python3 - "$RUN_SUMMARY" "$RUN_DIR" <<'PY'
import json, os, sys

out, run_dir = sys.argv[1], sys.argv[2]
names = [
    "review-packet.md",
    "codex-prepr-review.md",
    "codex-events.ndjson",
    "codex-prepr-review.stdout",
    "codex-prepr-review.stderr",
    "packet.provenance.json",
    "container.provenance.json",
    "run.provenance.json",
    "codex-runner-event.ndjson",
    "codex-runner-metrics.prom",
]
artifacts = {n: os.path.exists(os.path.join(run_dir, n)) for n in names}
# This summary file is being written now, so it is always present.
artifacts["run.summary.json"] = True
doc = {
    "artifact_contract_version": int(os.environ.get("PV_ACV", "1")),
    "run_id": os.environ.get("PV_RUN_ID", ""),
    "branch": os.environ.get("PV_BRANCH", ""),
    "safe_branch": os.environ.get("PV_SAFE", ""),
    "status": os.environ.get("RS_STATUS", ""),
    "exit_code": int(os.environ.get("RS_CODE", "0") or "0"),
    "stage": os.environ.get("RS_STAGE", ""),
    "verdict": os.environ.get("RS_VERDICT") or None,
    "error": os.environ.get("RS_ERROR") or None,
    "secret_leak_detected": os.environ.get("RS_SECRET_LEAK") == "true",
    "started_at": os.environ.get("PV_START", ""),
    "finished_at": os.environ.get("RS_FINISH", ""),
    "duration_seconds": int(os.environ.get("RS_DURATION", "0") or "0"),
    "run_dir": os.environ.get("PV_RUN_DIR", ""),
    "compat_dir": os.environ.get("PV_COMPAT_DIR") or None,
    "packet_path": os.environ.get("PV_PACKET_PATH") or None,
    "artifacts": artifacts,
}
with open(out, "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PY

  # Per-branch latest.json pointer to the most recent run. Only written when
  # RUN_DIR is in the canonical .../codex-prepr/<safe-branch>/<run-id> layout
  # (WRITE_LATEST=1); arbitrary OUT_DIR overrides get no scattered pointer.
  if [ "$WRITE_LATEST" = "1" ]; then
    RS_STATUS="$status" RS_FINISH="$finish_iso" \
    python3 - "$LATEST_POINTER" <<'PY'
import json, os, sys

out = sys.argv[1]
run = os.environ.get("PV_RUN_DIRNAME", "")
doc = {
    "artifact_contract_version": int(os.environ.get("PV_ACV", "1")),
    "run_id": os.environ.get("PV_RUN_ID", ""),
    "branch": os.environ.get("PV_BRANCH", ""),
    "status": os.environ.get("RS_STATUS", ""),
    "finished_at": os.environ.get("RS_FINISH", ""),
    "run_dir": run,
    "run_dir_abs": os.environ.get("PV_RUN_DIR", ""),
    "review": f"{run}/codex-prepr-review.md",
    "summary": f"{run}/run.summary.json",
}
with open(out, "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PY
  fi

  mirror_to_compat

  # Release the atomic claim now that this run's evidence is fully written. A
  # later same-RUN_ID run is then refused by the non-empty guard (the directory
  # now holds this run's artifacts), so reuse-after-completion is still blocked.
  rmdir "$CLAIM_MARKER" 2>/dev/null || true

  # Override the exit code if observability export turned an otherwise-successful
  # run into a failure (the summary above already records status=failed).
  if [ "$obs_failed" -eq 1 ]; then
    exit 3
  fi
}
trap finalize EXIT

fail() {
  # $1 = stage, $2 = exit code. Reads multi-line guidance from stdin.
  STAGE="$1"
  local code="$2"
  local msg
  msg="$(cat)"
  ERROR_MSG="$(printf '%s' "$msg" | head -n1)"
  printf '%s\n' "$msg" >&2
  exit "$code"
}

# Scan the given artifacts for the LITERAL provider key. On the first hit: refuse
# the run, delete ALL leakable run-dir artifacts (the staged packet AND any model
# outputs) so the key cannot persist, record the leak in run.summary.json, and
# exit. The value is never printed (we only name the offending file). Used BEFORE
# the model call on the staged packet — so a key embedded in the packet (e.g.
# redaction was disabled, or it sits outside the packet builder's name-based
# patterns) is caught and never sent to the model — and AFTER it on the model
# outputs plus the packet.
scan_artifacts_for_key() {
  [ -n "${SAKANA_API_KEY:-}" ] || return 0
  local f
  for f in "$@"; do
    [ -f "$f" ] || continue
    if grep -Fq -- "$SAKANA_API_KEY" "$f"; then
      LEAK_FOUND="true"
      STAGE="secret_leak_scan"
      ERROR_MSG="provider key leaked into generated review artifacts"
      echo "error: $ERROR_MSG" >&2
      echo "  offending artifact: $(basename "$f")" >&2
      echo "  run dir:            $RUN_DIR" >&2
      rm -f "$RUN_PACKET" "$FINAL_REVIEW" "$EVENTS_LOG" "$STDOUT_LOG" "$STDERR_LOG" 2>/dev/null || true
      echo "  deleted the leakable artifacts (staged packet + model outputs); compat copies are purged on exit." >&2
      echo "  non-secret provenance and run.summary.json metadata may remain — never the key." >&2
      exit 2
    fi
  done
}

# --- Stage the packet (immediately after the claim, before any slow work) ---
# Capture the packet into the claimed run directory NOW — before reasoning-effort
# parsing and the (potentially slow) Bitwarden key fetch — so the bytes this run
# reviews and audits are frozen at invocation time. A direct caller's default
# PACKET_PATH is the shared .ai/reviews/review-packet.md; staging it here, rather
# than just before the Docker run, closes the window where `make review-packet`
# or a helper could rewrite that shared file mid-preflight. Only the winning run
# (it holds the .claim) writes here, so every run directory is self-contained,
# and all downstream bytes/sha/stdin use THIS copy — the recorded hash always
# matches exactly what is reviewed.
if [ ! -f "$PACKET_PATH" ]; then
  fail preflight 2 <<EOF
error: review packet not found:

  $PACKET_PATH

Run your existing review-packet builder first.
EOF
fi
RUN_PACKET="$RUN_DIR/review-packet.md"
PACKET_SOURCE="$PACKET_PATH"
if [ "$PACKET_PATH" != "$RUN_PACKET" ]; then
  cp -f "$PACKET_PATH" "$RUN_PACKET"
fi
PACKET_PATH="$RUN_PACKET"
# Re-export PV_PACKET_PATH now (the provenance block re-exports it too, later) so
# any failure BETWEEN staging and provenance — bad effort, missing key/schema/
# image, oversized packet, pre-model leak — writes run.summary.json pointing at
# the staged run-dir packet, not the original source (under `make prepr` a
# private temp that prepr.sh deletes on exit). Keeps the failure summary
# self-contained.
export PV_PACKET_PATH="$PACKET_PATH"

# --- Reasoning effort (optional runtime knob) ------------------------------
# The image's baked config.toml defaults model_reasoning_effort to "xhigh", and
# we deliberately keep that default for review quality. Set
# CODEX_REASONING_EFFORT=high for a faster, lower-effort run without rebuilding
# the image. Fugu and fugu-ultra accept only `high` and `xhigh` (`max` is an
# alias of xhigh); any other value is rejected by the API, so fail fast here
# before doing secret work or a paid call.
# EFFECTIVE_EFFORT is the normalized value actually applied and recorded: `max`
# is an alias of `xhigh`, so we collapse it here and record/pass the canonical
# `xhigh`, never the alias. When no override is set, the effective value is the
# image config.toml default (xhigh) and we pass no flag at all.
REASONING_EFFORT="${CODEX_REASONING_EFFORT:-}"
REASONING_EFFORT_SOURCE="image-default"
EFFECTIVE_EFFORT="xhigh"
if [ -n "$REASONING_EFFORT" ]; then
  case "$REASONING_EFFORT" in
    high) EFFECTIVE_EFFORT="high" ;;
    xhigh | max) EFFECTIVE_EFFORT="xhigh" ;;
    *)
      fail preflight 2 <<EOF
error: CODEX_REASONING_EFFORT='$REASONING_EFFORT' is not supported.

Fugu and fugu-ultra accept only: high, xhigh (max is accepted as an alias of xhigh).
EOF
      ;;
  esac
  REASONING_EFFORT_SOURCE="override"
fi

# --- Resolve SAKANA_API_KEY from Bitwarden Secrets Manager (optional) -------
# If SAKANA_API_KEY is not already exported, fetch it with `bws` using a
# Secrets Manager access token, sourced from BWS_ACCESS_TOKEN, BITWARDEN_TOKEN,
# or the BITWARDEN_TOKEN line in .env. The secret value is never printed.
SAKANA_SECRET_NAME="${SAKANA_SECRET_NAME:-SAKANA_API_KEY}"
if [ -z "${SAKANA_API_KEY:-}" ]; then
  bws_token="${BWS_ACCESS_TOKEN:-${BITWARDEN_TOKEN:-}}"
  if [ -z "$bws_token" ] && [ -f "$REPO_ROOT/.env" ]; then
    # Only read the access token from .env if .env is guaranteed git-ignored,
    # so this fallback can never normalise committing a Bitwarden Secrets
    # Manager token. Refuse loudly rather than silently if that guarantee fails.
    if git -C "$REPO_ROOT" check-ignore -q -- .env; then
      bws_token="$(grep -E '^BITWARDEN_TOKEN=' "$REPO_ROOT/.env" | cut -d= -f2- || true)"
    else
      fail preflight 2 <<EOF
error: $REPO_ROOT/.env is NOT git-ignored; refusing to read a secret token from it.
       Add '.env' to .gitignore or supply the token via BWS_ACCESS_TOKEN/BITWARDEN_TOKEN.
EOF
    fi
  fi
  BWS_BIN="$(command -v bws || true)"
  [ -z "$BWS_BIN" ] && [ -x "$HOME/.local/bin/bws" ] && BWS_BIN="$HOME/.local/bin/bws"
  if [ -n "$bws_token" ] && [ -n "$BWS_BIN" ]; then
    echo "==> Fetching $SAKANA_SECRET_NAME from Bitwarden Secrets Manager"
    SAKANA_API_KEY="$(BWS_ACCESS_TOKEN="$bws_token" "$BWS_BIN" secret list -o json 2>/dev/null \
      | jq -r --arg k "$SAKANA_SECRET_NAME" '.[] | select(.key==$k) | .value' \
      | head -n1)"
    export SAKANA_API_KEY
  fi
  unset bws_token
fi

if [ -z "${SAKANA_API_KEY:-}" ]; then
  fail preflight 2 <<'EOF'
error: SAKANA_API_KEY is not set and could not be fetched from Bitwarden.

Provide the Sakana Fugu key one of these ways:

  # A) Export it directly for this invocation
  SAKANA_API_KEY=... ./.ai/codex/02-run-prepr-review-docker.sh

  # B) Let the script pull it from Bitwarden Secrets Manager
  #    (requires `bws` on PATH or ~/.local/bin, plus jq, and a token in
  #     BWS_ACCESS_TOKEN / BITWARDEN_TOKEN / the .env BITWARDEN_TOKEN line)

Do not mount ~/.codex or production secrets into this container.
EOF
fi

# Pre-model leak gate: the provider key is now resolved, so scan the STAGED packet
# (the bytes about to be sent to the model) for it. If a key is embedded in the
# packet — redaction disabled, or it sits outside the packet builder's name-based
# patterns — fail and delete it BEFORE the model call, so the key is never
# transmitted and no paid review is wasted.
scan_artifacts_for_key "$RUN_PACKET"

# Guard: fail loudly if the packet is large enough to risk silent truncation by
# the Fugu catalog's truncation_policy, rather than reviewing a partial diff.
# Default ~3MB (~750k tokens) sits under the catalog's 900k-token limit.
MAX_PACKET_BYTES="${MAX_PACKET_BYTES:-3000000}"
packet_bytes="$(wc -c < "$PACKET_PATH")"
if [ "$packet_bytes" -gt "$MAX_PACKET_BYTES" ]; then
  fail preflight 2 <<EOF
error: review packet is ${packet_bytes} bytes, exceeding MAX_PACKET_BYTES=${MAX_PACKET_BYTES}.

This risks silent truncation during review (a partial diff would be reviewed).
Narrow the diff (smaller BASE range), split the review, or raise MAX_PACKET_BYTES
only after confirming the model context can hold the full packet.
EOF
fi

if [ ! -f "$SCHEMA_PATH" ]; then
  fail preflight 2 <<EOF
error: output schema not found:

  $SCHEMA_PATH
EOF
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  fail preflight 2 <<EOF
error: Codex image does not exist:

  $IMAGE

Build it first:

  ./.ai/codex/01-build-codex-image.sh
EOF
fi

# --- Provenance ------------------------------------------------------------
# Deterministic input/config provenance: record the exact bytes and SHA-256 of
# the packet that is piped to the model, the schema, and the container/runtime
# posture. Truncation protection for THIS run is the MAX_PACKET_BYTES guard
# above plus packet_sha256 recorded here. Separately, the canary in
# `03-smoke-test.sh` proves the prompt+stdin DELIVERY PATH is truncation-safe by
# placing a token at the END of a synthetic packet and requiring it in the model
# output; that validates the harness, it is not a per-run check on this packet.
PACKET_SHA256="$(sha256sum "$PACKET_PATH" | cut -d' ' -f1)"
SCHEMA_SHA256="$(sha256sum "$SCHEMA_PATH" | cut -d' ' -f1)"
IMAGE_ID="$(docker image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || echo unknown)"
CODEX_CLI_VERSION="$(docker image inspect "$IMAGE" --format '{{ index .Config.Labels "dev.platform-edge.codex-cli-version" }}' 2>/dev/null || true)"
[ -n "$CODEX_CLI_VERSION" ] || CODEX_CLI_VERSION="unknown"
# Tie recorded model provenance to how the model is actually selected. When
# CODEX_MODEL is set we pass it via --model (see CODEX_ARGS) and record it as an
# override; otherwise the container uses the image config.toml default
# (model = "fugu-ultra"), which we record as such rather than implying a
# CLI-passed value.
if [ -n "${CODEX_MODEL:-}" ]; then
  MODEL="$CODEX_MODEL"
  MODEL_SOURCE="override"
else
  MODEL="fugu-ultra"
  MODEL_SOURCE="image-default"
fi

# Repoint provenance at the staged run-dir copy that was actually reviewed
# (PV_PACKET_PATH was first exported early, before staging, for early-failure
# summaries). PV_PACKET_SOURCE preserves where the packet came from.
export PV_PACKET_PATH="$PACKET_PATH"
export PV_PACKET_SOURCE="$PACKET_SOURCE"
export PV_PACKET_BYTES="$packet_bytes"
export PV_PACKET_SHA="$PACKET_SHA256"
export PV_MAX_BYTES="$MAX_PACKET_BYTES"
export PV_SCHEMA_PATH="$SCHEMA_PATH"
export PV_SCHEMA_SHA="$SCHEMA_SHA256"
export PV_SCHEMA_DIR="$SCHEMA_DIR"
export PV_CONTAINER_SCHEMA="$CONTAINER_SCHEMA_PATH"
export PV_HEAD_SHA="$HEAD_SHA"
export PV_HEAD_SHORT="$HEAD_SHORT"
export PV_REVIEW_BASE="${REVIEW_BASE:-}"
export PV_IMAGE="$IMAGE"
export PV_IMAGE_ID="$IMAGE_ID"
export PV_CODEX_VER="$CODEX_CLI_VERSION"
export PV_MODEL="$MODEL"
export PV_MODEL_SOURCE="$MODEL_SOURCE"
export PV_PROVIDER="sakana"
export PV_MODE="docker"
# Effective reasoning effort actually applied (normalized; see EFFECTIVE_EFFORT)
# plus whether it was an override or the image default, so the artifact says
# exactly what ran.
export PV_REASONING_EFFORT="$EFFECTIVE_EFFORT"
export PV_REASONING_SOURCE="$REASONING_EFFORT_SOURCE"
export PV_CONTAINER_NAME="$CONTAINER_NAME"
export PV_USER_SPEC="$USER_SPEC"
printf -v PV_TMPFS '%s\n%s' "$TMPFS_TMP_SPEC" "$TMPFS_CODEX_HOME_SPEC"
export PV_TMPFS
export PV_REPO_ROOT="$REPO_ROOT"
export PV_DISABLED="${DISABLED_TOOLS[*]}"
PV_USER="$(id -un 2>/dev/null || echo unknown)"
export PV_USER

python3 - "$PACKET_PROVENANCE" <<'PY'
import json, os, sys
doc = {
    "artifact_contract_version": int(os.environ["PV_ACV"]),
    "run_id": os.environ["PV_RUN_ID"],
    "branch": os.environ["PV_BRANCH"],
    "safe_branch": os.environ["PV_SAFE"],
    "packet_path": os.environ["PV_PACKET_PATH"],
    "packet_source": os.environ.get("PV_PACKET_SOURCE") or None,
    "packet_bytes": int(os.environ["PV_PACKET_BYTES"]),
    "packet_sha256": os.environ["PV_PACKET_SHA"],
    "max_packet_bytes": int(os.environ["PV_MAX_BYTES"]),
    "schema_path": os.environ["PV_SCHEMA_PATH"],
    "schema_sha256": os.environ["PV_SCHEMA_SHA"],
    "head_sha": os.environ["PV_HEAD_SHA"],
    "head_short_sha": os.environ["PV_HEAD_SHORT"],
    "review_base": os.environ.get("PV_REVIEW_BASE") or None,
    "generated_at": os.environ["PV_START"],
}
with open(sys.argv[1], "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PY

python3 - "$CONTAINER_PROVENANCE" <<'PY'
import json, os, sys
disabled = os.environ.get("PV_DISABLED", "").split()
doc = {
    "artifact_contract_version": int(os.environ["PV_ACV"]),
    "run_id": os.environ["PV_RUN_ID"],
    "branch": os.environ["PV_BRANCH"],
    "review_mode": os.environ["PV_MODE"],
    "image": os.environ["PV_IMAGE"],
    "image_id": os.environ["PV_IMAGE_ID"],
    "codex_cli_version": os.environ["PV_CODEX_VER"],
    "model": os.environ["PV_MODEL"],
    "model_source": os.environ["PV_MODEL_SOURCE"],
    "model_provider": os.environ["PV_PROVIDER"],
    "container": {
        "name": os.environ["PV_CONTAINER_NAME"],
        "user": os.environ["PV_USER_SPEC"],
        # NOTE: these constant posture flags mirror the `docker run` invocation
        # below (--cap-drop ALL, --read-only, --security-opt no-new-privileges).
        # If you change the invocation, update these literals (and vice versa).
        "cap_drop": ["ALL"],
        "read_only_rootfs": True,
        "no_new_privileges": True,
        # tmpfs specs come verbatim from the same TMPFS_*_SPEC vars the docker
        # invocation uses, so they cannot drift from what actually ran.
        "tmpfs": os.environ.get("PV_TMPFS", "").split("\n") if os.environ.get("PV_TMPFS") else [],
        "mounts": [
            {"source": os.environ["PV_SCHEMA_DIR"],
             "target": "/workspace/.ai/schemas", "mode": "ro"},
            {"target": "/out", "mode": "rw", "note": "run directory"},
        ],
    },
    "codex_flags": {
        "sandbox": "danger-full-access",
        "json": True,
        "web_search": False,
        "reasoning_effort": os.environ["PV_REASONING_EFFORT"],
        "reasoning_effort_source": os.environ["PV_REASONING_SOURCE"],
        "disabled_tools": disabled,
        "output_schema": os.environ["PV_CONTAINER_SCHEMA"],
    },
    "output_schema_path": os.environ["PV_SCHEMA_PATH"],
    "output_schema_sha256": os.environ["PV_SCHEMA_SHA"],
    "generated_at": os.environ["PV_START"],
}
with open(sys.argv[1], "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PY

python3 - "$RUN_PROVENANCE" <<'PY'
import json, os, sys
doc = {
    "artifact_contract_version": int(os.environ["PV_ACV"]),
    "run_id": os.environ["PV_RUN_ID"],
    "branch": os.environ["PV_BRANCH"],
    "safe_branch": os.environ["PV_SAFE"],
    "review_mode": os.environ["PV_MODE"],
    "invoked_by": os.environ.get("PV_USER", "unknown"),
    "repo_root": os.environ["PV_REPO_ROOT"],
    "run_dir": os.environ["PV_RUN_DIR"],
    "compat_dir": os.environ.get("PV_COMPAT_DIR") or None,
    "head_sha": os.environ["PV_HEAD_SHA"],
    "head_short_sha": os.environ["PV_HEAD_SHORT"],
    "review_base": os.environ.get("PV_REVIEW_BASE") or None,
    "image": os.environ["PV_IMAGE"],
    "image_id": os.environ["PV_IMAGE_ID"],
    "codex_cli_version": os.environ["PV_CODEX_VER"],
    "model": os.environ["PV_MODEL"],
    "model_source": os.environ["PV_MODEL_SOURCE"],
    "model_provider": os.environ["PV_PROVIDER"],
    "packet_provenance": "packet.provenance.json",
    "container_provenance": "container.provenance.json",
    "started_at": os.environ["PV_START"],
}
with open(sys.argv[1], "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PY

PROMPT="$(cat <<'PROMPT'
You are reviewing a self-contained pre-PR review packet.

Hard constraints:
- Use only the packet provided on stdin.
- Do not run shell commands.
- Do not inspect the filesystem.
- Do not access the network or external resources.
- Do not read schema files; the CLI is already enforcing the output schema.
- Return the final review only.
PROMPT
)"

CODEX_ARGS=(
  --ask-for-approval never
)

if [ -n "${CODEX_MODEL:-}" ]; then
  CODEX_ARGS+=(--model "$CODEX_MODEL")
fi

# Prompt delivery uses the documented `codex exec -` contract: `-` reads the
# prompt from stdin, and we feed the guard prompt followed by the full packet as
# a single stdin stream (see the docker invocation below). This does not rely on
# any implicit "append stdin to a positional prompt" behavior, so the model is
# guaranteed to receive the packet/canary, not just the guard text.
# Note: no --ignore-user-config here; the image seeds the Fugu provider config
# into the (isolated tmpfs) CODEX_HOME, and that config is required for Fugu.
#
# --json captures the full event stream as NDJSON (-> codex-events.ndjson),
# giving an auditable, machine-readable trace of the run alongside the final
# review written by --output-last-message.
#
# Tool/sandbox posture for this packet-only runner:
#   --sandbox danger-full-access  -> do NOT build a Codex inner OS sandbox.
#     The gateway cannot rely on Codex's Linux landlock/seccomp/bubblewrap
#     (userns) path; attempting it emits warnings and is not the trust boundary
#     here. The Docker container is the boundary. "full access" is bounded by
#     the container: --read-only rootfs, cap-drop ALL, no-new-privileges,
#     non-root --user, noexec tmpfs, and only /out writable.
#   --disable shell_tool/unified_exec/browser_use/computer_use/in_app_browser/
#     apps/image_generation  -> re-assert at the CLI what the baked config.toml
#     already disables (built from DISABLED_TOOLS above), so the model has no
#     shell/network/tool to invoke even if the seeded config were ever bypassed.
#   -c tools.web_search=false  -> belt-and-suspenders web-search off.
EXEC_ARGS=(
  exec
  --ephemeral
  --ignore-rules
  --skip-git-repo-check
  --sandbox danger-full-access
  --json
)
for tool in "${DISABLED_TOOLS[@]}"; do
  EXEC_ARGS+=(--disable "$tool")
done
EXEC_ARGS+=(-c tools.web_search=false)
# Only override the baked-in reasoning effort when CODEX_REASONING_EFFORT is set;
# otherwise the image config.toml default (xhigh) applies untouched. Passed as a
# quoted TOML string so codex's -c parser accepts it as a string value.
if [ "$REASONING_EFFORT_SOURCE" = "override" ]; then
  EXEC_ARGS+=(-c "model_reasoning_effort=\"$EFFECTIVE_EFFORT\"")
fi
EXEC_ARGS+=(
  --output-schema "$CONTAINER_SCHEMA_PATH"
  --output-last-message /out/codex-prepr-review.md
  -
)

echo "==> Running dockerized Codex pre-PR review"
echo "    branch:  $BRANCH_NAME"
echo "    packet:  $PACKET_PATH"
echo "    schema:  $SCHEMA_PATH"
echo "    run dir: $RUN_DIR"
echo "    image:   $IMAGE"
echo "    effort:  $PV_REASONING_EFFORT ($REASONING_EFFORT_SOURCE)"

STAGE="docker_run"
set +e
# Defense in depth: the "do not run shell / do not access the network" rules in
# $PROMPT are NOT trusted to a prompt alone. They are enforced by (a) removing
# the tools themselves (baked config.toml + EXEC_ARGS --disable flags above:
# no shell_tool/unified_exec/browser/apps/image-gen, web_search off) and (b)
# container posture, and verified by 03-smoke-test.sh (prompt-injection packet):
#   --read-only + cap-drop ALL + no-new-privileges + non-root --user  -> the
#     only writable paths are /out and the noexec/nosuid/nodev tmpfs;
#   --sandbox danger-full-access                                      -> avoids
#     the Codex inner Linux sandbox (bubblewrap/userns) the gateway cannot rely
#     on; "full access" is still bounded by the locked-down container above and
#     the model has no execution tool to use it with;
#   only /out (rw) and the schema dir (ro) are mounted; ~/.codex and production
#   secrets are never mounted, so an injected command has no host blast radius.
#
# stdin = guard prompt + the full packet, delivered to `codex exec -`.
# stdout = the --json event stream, captured to codex-events.ndjson.
{ printf '%s\n\n' "$PROMPT"; cat "$PACKET_PATH"; } | docker run --rm -i \
  --name "$CONTAINER_NAME" \
  --user "$USER_SPEC" \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --read-only \
  --tmpfs "$TMPFS_TMP_SPEC" \
  --tmpfs "$TMPFS_CODEX_HOME_SPEC" \
  -e HOME=/tmp/codex-home \
  -e CODEX_HOME=/tmp/codex-home \
  -e SAKANA_API_KEY \
  -v "$SCHEMA_DIR:/workspace/.ai/schemas:ro" \
  -v "$RUN_DIR:/out:rw" \
  "$IMAGE" \
  "${CODEX_ARGS[@]}" \
  "${EXEC_ARGS[@]}" \
  > "$EVENTS_LOG" \
  2> "$STDERR_LOG"
STATUS=$?
# Back-compat: the historical .stdout path mirrors Codex's raw stdout, which is
# the JSON event stream under --json.
cp -f "$EVENTS_LOG" "$STDOUT_LOG" 2>/dev/null || true
set -e

# Post-model leak gate. Before declaring success (and before the failure paths
# below tail the captured logs), scan the model outputs AND the staged packet for
# the LITERAL provider key. The model never has an execution tool and stderr is
# redacted on display, but this is the last-line guarantee that the key cannot
# survive into a generated artifact. Runs regardless of STATUS so a leak is caught
# even on a failed run. On a hit, every leakable artifact is deleted and only
# run.summary.json metadata (secret_leak_detected=true) is kept.
scan_artifacts_for_key "$FINAL_REVIEW" "$EVENTS_LOG" "$STDOUT_LOG" "$STDERR_LOG" "$RUN_PACKET"

if [ "$STATUS" -ne 0 ]; then
  STAGE="docker_run"
  ERROR_MSG="dockerized Codex review failed with status $STATUS"
  echo "error: $ERROR_MSG" >&2
  echo >&2
  echo "==> stderr tail (SAKANA_API_KEY redacted)" >&2
  redact_secret < "$STDERR_LOG" | tail -120 >&2 || true
  echo >&2
  echo "Logs:" >&2
  echo "  stdout: $STDOUT_LOG" >&2
  echo "  stderr: $STDERR_LOG" >&2
  echo "  events: $EVENTS_LOG" >&2
  exit "$STATUS"
fi

if [ ! -s "$FINAL_REVIEW" ]; then
  STAGE="review_missing"
  ERROR_MSG="Codex completed but final review was not written: $FINAL_REVIEW"
  echo "error: Codex completed but final review was not written:" >&2
  echo "  $FINAL_REVIEW" >&2
  echo >&2
  echo "==> stderr tail (SAKANA_API_KEY redacted)" >&2
  redact_secret < "$STDERR_LOG" | tail -120 >&2 || true
  exit 2
fi

STAGE="completed"
echo "==> Review complete"
echo "    final:   $FINAL_REVIEW"
echo "    events:  $EVENTS_LOG"
echo "    summary: $RUN_SUMMARY"
echo "    stdout:  $STDOUT_LOG"
echo "    stderr:  $STDERR_LOG"
