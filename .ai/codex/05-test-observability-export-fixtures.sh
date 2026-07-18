#!/usr/bin/env bash
set -uo pipefail

# Fixture QA for the observability export validator (04). Free + deterministic:
# builds fake run directories under mktemp and asserts the validator passes on
# safe fixtures and fails on contract violations. Makes NO model call, requires
# NO SAKANA_API_KEY, and never touches Docker or any committed path.

REPO_ROOT="$(git rev-parse --show-toplevel)"
VALIDATOR="$REPO_ROOT/.ai/codex/04-validate-observability-export.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

fails=0

# Generate a fixture run directory for a given mode (consistent summary + event +
# metrics + provenance; specific mutations per mode).
gen_fixture() {
  python3 - "$1" "$2" <<'PY'
import json, os, sys

mode, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)

event = {
    "schema_version": 1,
    "artifact_contract_version": 1,
    "event_type": "codex_prepr_review_run",
    "repo": "property-tax-data-platform",
    "run_id": "fixture-001",
    "branch": "feat/fixture",
    "safe_branch": "feat__fixture",
    "review_mode": "docker",
    "run_dir": out,
    "started_at": "2026-06-30T00:00:00Z",
    "finished_at": "2026-06-30T00:05:00Z",
    "duration_seconds": 300,
    "status": "succeeded",
    "exit_code": 0,
    "stage": "completed",
    "verdict": "pass_with_notes",
    "secret_leak_detected": False,
    "packet_bytes": 12345,
    "packet_sha256": "a" * 64,
    "max_packet_bytes": 3000000,
    "schema_sha256": "b" * 64,
    "head_sha": "c" * 40,
    "head_short_sha": "ccccccc",
    "review_base": "origin/main",
    "image": "property-tax-codex-reviewer:local",
    "image_id": "sha256:" + "d" * 64,
    "codex_cli_version": "0.142.2",
    "model": "fugu-ultra",
    "model_source": "image-default",
    "model_provider": "sakana",
    "reasoning_effort": "xhigh",
    "reasoning_effort_source": "image-default",
    "sandbox": "danger-full-access",
    "web_search": False,
    "disabled_tools": ["shell_tool", "apps"],
    "output_schema_sha256": "b" * 64,
}

write_provenance = True

if mode == "failed_preflight":
    # Legitimate early failure: null packet/model fields, no provenance files.
    event["status"] = "failed"
    event["stage"] = "preflight"
    event["exit_code"] = 2
    event["verdict"] = None
    for k in ["packet_bytes", "packet_sha256", "max_packet_bytes", "schema_sha256",
              "head_sha", "head_short_sha", "review_base", "image", "image_id",
              "codex_cli_version", "model", "model_source", "model_provider",
              "reasoning_effort", "reasoning_effort_source", "output_schema_sha256"]:
        event[k] = None
    write_provenance = False

if mode == "leak":
    event["secret_leak_detected"] = True
    event["status"] = "failed"
    event["stage"] = "secret_leak_scan"
    event["exit_code"] = 2
    event["verdict"] = None

# Schema-shape violations — must be caught by the validator's built-in subset
# validator even when python3-jsonschema is not installed.
if mode == "schema_version_string":
    event["schema_version"] = "1"                  # must be integer
if mode == "event_type_wrong":
    event["event_type"] = "codex_review"           # const mismatch
if mode == "web_search_string":
    event["web_search"] = "false"                  # must be boolean
if mode == "duration_negative":
    event["duration_seconds"] = -5                 # integer minimum 0
if mode == "disabled_tools_nonstring":
    event["disabled_tools"] = ["shell_tool", 42]   # array items must be strings

summary = {
    "artifact_contract_version": 1,
    "run_id": event["run_id"],
    "branch": event["branch"],
    "safe_branch": event["safe_branch"],
    "status": event["status"],
    "exit_code": event["exit_code"],
    "stage": event["stage"],
    "verdict": event["verdict"],
    "error": None,
    "secret_leak_detected": event["secret_leak_detected"],
    "started_at": event["started_at"],
    "finished_at": event["finished_at"],
    "duration_seconds": event["duration_seconds"],
    "run_dir": out,
    "compat_dir": None,
    "packet_path": os.path.join(out, "review-packet.md"),
    "artifacts": {"codex-runner-event.ndjson": True, "codex-runner-metrics.prom": True},
}

if mode == "mismatch":
    # Summary status disagrees with the event.
    summary["status"] = "failed"

with open(os.path.join(out, "run.summary.json"), "w") as f:
    json.dump(summary, f, indent=2)
    f.write("\n")

if write_provenance:
    cprov = {
        "image": event["image"],
        "image_id": event["image_id"],
        "codex_cli_version": event["codex_cli_version"],
        "model": event["model"],
        "model_provider": event["model_provider"],
        "codex_flags": {
            "reasoning_effort": event["reasoning_effort"],
            "reasoning_effort_source": event["reasoning_effort_source"],
            "sandbox": "danger-full-access",
            "web_search": False,
            "disabled_tools": event["disabled_tools"],
        },
    }
    with open(os.path.join(out, "container.provenance.json"), "w") as f:
        json.dump(cprov, f, indent=2)
        f.write("\n")
    pprov = {k: event[k] for k in ["packet_bytes", "packet_sha256", "max_packet_bytes",
                                   "schema_sha256", "head_sha", "head_short_sha", "review_base"]}
    with open(os.path.join(out, "packet.provenance.json"), "w") as f:
        json.dump(pprov, f, indent=2)
        f.write("\n")

# event NDJSON (exactly one line, unless we are testing malformed input)
event_line = json.dumps(event)
if mode == "malformed":
    body = event_line + "\n" + event_line + "\n"  # two lines -> must fail
else:
    body = event_line + "\n"
with open(os.path.join(out, "codex-runner-event.ndjson"), "w") as f:
    f.write(body)

# metrics (allowed low-cardinality labels)
def lv(v):
    return "unknown" if v in (None, "") else str(v)

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
if mode == "highcard":
    labels["run_id"] = event["run_id"]  # forbidden high-cardinality label -> must fail
if mode == "metric_stale_outcome":
    labels["outcome"] = "failed"  # event says succeeded -> label disagreement must fail
L = "{" + ",".join('%s="%s"' % (k, v) for k, v in labels.items()) + "}"
leak = 1 if event["secret_leak_detected"] else 0
lines = []
def metric(name, value, lblstr=L):
    lines.append("# HELP %s fixture metric." % name)
    lines.append("# TYPE %s gauge" % name)
    lines.append("%s%s %s" % (name, lblstr, value))
metric("codex_runner_run_duration_seconds",
       999 if mode == "metric_value_mismatch" else event["duration_seconds"])
if event["packet_bytes"] is not None:
    metric("codex_runner_packet_bytes", event["packet_bytes"])
if mode != "metric_missing":  # drop a required contract metric -> must fail
    metric("codex_runner_exit_code", event["exit_code"])
metric("codex_runner_secret_leak_detected", leak)
metric("codex_runner_schema_valid", 1 if event["verdict"] is not None else 0)
metric("codex_runner_artifact_contract_version_info", 1,
       '{repo="property-tax-data-platform",artifact_contract_version="1",event_schema_version="1"}')
# Label-parsing violations: the whole label block must parse, so unquoted
# values, trailing garbage, and duplicate label names must all be rejected.
if mode == "label_unquoted":
    metric("codex_runner_run_info", 1, '{run_id=r}')
elif mode == "label_trailing_garbage":
    metric("codex_runner_run_info", 1, '{repo="property-tax-data-platform",bad}')
elif mode == "label_duplicate":
    metric("codex_runner_run_info", 1, '{repo="a",repo="b"}')
else:
    metric("codex_runner_run_info", 1)
# Metrics-contract violations: the metric set is closed and its labels/values
# must agree with the event.
if mode == "metric_unexpected":
    metric("wrong_metric", 1, "")           # extra non-contract metric -> must fail
if mode == "metric_only_wrong":
    lines = []                              # ONLY a non-contract metric -> must fail
    metric("wrong_metric", 1, "")
# TYPE-directive violations: contract metrics are gauges, and directives must
# match samples one-to-one.
if mode == "type_not_gauge":
    lines = [l.replace("# TYPE codex_runner_exit_code gauge",
                       "# TYPE codex_runner_exit_code counter") for l in lines]
if mode == "type_missing":
    lines = [l for l in lines if l != "# TYPE codex_runner_exit_code gauge"]
if mode == "type_orphan":
    lines.append("# TYPE stray_metric gauge")  # directive without a sample
# Late directives: HELP/TYPE must precede the metric's sample.
if mode == "help_late":
    h = "# HELP codex_runner_exit_code fixture metric."
    lines.remove(h)
    lines.append(h)  # now after its sample -> must fail
if mode == "type_late":
    t = "# TYPE codex_runner_exit_code gauge"
    lines.remove(t)
    lines.append(t)  # now after its sample -> must fail
with open(os.path.join(out, "codex-runner-metrics.prom"), "w") as f:
    f.write("\n".join(lines) + "\n")

print(out)
PY
}

check() {  # $1 = description, $2 = expected exit code, $3 = run dir, $4 = expected FAIL pattern ("" = none)
  local rc out
  out="$(RUN_DIR="$3" SAKANA_API_KEY="" bash "$VALIDATOR" 2>&1)"
  rc=$?
  if [ "$rc" -ne "$2" ]; then
    echo "FAIL: $1 (expected validator rc $2, got $rc)"
    fails=$((fails + 1))
    return
  fi
  if [ -n "$4" ] && ! printf '%s' "$out" | grep -q "$4"; then
    echo "FAIL: $1 (rc ok, but expected failure reason matching '$4' not in validator output)"
    fails=$((fails + 1))
    return
  fi
  echo "ok: $1 (validator rc=$rc)"
}

run_case() {  # $1 = mode, $2 = expected exit code, $3 = expected FAIL pattern for negatives
  local dir="$WORK/$1"
  gen_fixture "$1" "$dir" >/dev/null
  check "$1 fixture" "$2" "$dir" "${3:-}"
}

echo "==> Observability export fixture QA (no model call, no Docker)"
run_case success 0
run_case failed_preflight 0
run_case leak 0
run_case highcard 1 "forbidden high-cardinality"
run_case mismatch 1 "disagree on"
run_case malformed 1 "exactly one non-empty line"
# Schema-shape negatives (caught by the built-in subset validator).
run_case schema_version_string 1 "event field 'schema_version' has wrong type"
run_case event_type_wrong 1 "event field 'event_type' must be"
run_case web_search_string 1 "event field 'web_search' has wrong type"
run_case duration_negative 1 "event field 'duration_seconds' is below minimum"
run_case disabled_tools_nonstring 1 "wrong item type"
# Label-parsing negatives (the whole label block must parse).
run_case label_unquoted 1 "does not fully parse"
run_case label_trailing_garbage 1 "does not fully parse"
run_case label_duplicate 1 "duplicate metric label 'repo'"
# Metrics-contract negatives (closed metric set + label/value agreement with the event).
run_case metric_only_wrong 1 "missing required contract metric"
run_case metric_missing 1 "missing required contract metric"
run_case metric_unexpected 1 "outside the contract"
run_case metric_stale_outcome 1 "label 'outcome' disagrees with the event"
run_case metric_value_mismatch 1 "value disagrees with the event"
# TYPE-directive negatives (gauge-only; directives match samples one-to-one).
run_case type_not_gauge 1 "must be gauge"
run_case type_missing 1 "no TYPE directive"
run_case type_orphan 1 "TYPE directive for metric with no sample"
# Late-directive negatives (HELP/TYPE must precede the metric's sample).
run_case help_late 1 "HELP directive for metric codex_runner_exit_code appears after its sample"
run_case type_late 1 "TYPE directive for metric codex_runner_exit_code appears after its sample"

if [ "$fails" -eq 0 ]; then
  echo "==> FIXTURE QA PASSED"
  exit 0
fi
echo "==> FIXTURE QA FAILED ($fails check(s))"
exit 1
