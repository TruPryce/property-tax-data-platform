#!/usr/bin/env bash
set -euo pipefail

# Local observability QA validator (free, deterministic — no model call, no Docker).
#
# Validates that a per-run directory's local observability artifacts are
# structurally safe and ready for FUTURE shipping to Loki/Prometheus/Grafana.
# This script ships nothing and runs no collector; it only checks the contract
# documented in docs/engineering/codex-runner-observability.md.
#
# Default target: the latest run for the current branch (via latest.json).
# Override:       RUN_DIR=/path/to/run ./.ai/codex/04-validate-observability-export.sh

REPO_ROOT="$(git rev-parse --show-toplevel)"
SCHEMA="$REPO_ROOT/.ai/schemas/codex-runner-event.schema.json"

if [ -n "${RUN_DIR:-}" ]; then
  run_dir="$RUN_DIR"
else
  branch="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
  safe="$(printf '%s' "$branch" | sed 's#[^A-Za-z0-9._-]#__#g')"
  latest="$REPO_ROOT/.ai/reviews/codex-prepr/$safe/latest.json"
  if [ ! -f "$latest" ]; then
    echo "error: no latest.json for branch '$branch':" >&2
    echo "  $latest" >&2
    echo "Run a review first, or set RUN_DIR=/path/to/run to validate a specific run." >&2
    exit 2
  fi
  run_dir="$(jq -r '.run_dir_abs' "$latest")"
fi

if [ ! -d "$run_dir" ]; then
  echo "FAIL: run directory not found: $run_dir" >&2
  exit 2
fi

echo "==> Validating observability export: $run_dir"

# All structural/agreement/secret checks run in Python (clean JSON handling). The
# live provider key is passed via env for the secret scan and is NEVER printed.
SAKANA_API_KEY="${SAKANA_API_KEY:-}" OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
  python3 - "$run_dir" "$SCHEMA" <<'PY'
import json, os, re, sys

run_dir, schema_path = sys.argv[1], sys.argv[2]


def fail(msg):
    print("FAIL: %s" % msg, file=sys.stderr)
    sys.exit(1)


def load_json(path, label):
    if not os.path.isfile(path):
        fail("%s missing: %s" % (label, path))
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        fail("%s is not valid JSON: %s" % (label, e))


# --- run.summary.json ------------------------------------------------------
summary = load_json(os.path.join(run_dir, "run.summary.json"), "run.summary.json")

# --- codex-runner-event.ndjson: exactly one non-empty JSON object line -----
event_path = os.path.join(run_dir, "codex-runner-event.ndjson")
if not os.path.isfile(event_path):
    fail("codex-runner-event.ndjson missing")
lines = [ln for ln in open(event_path).read().splitlines() if ln.strip()]
if len(lines) != 1:
    fail("codex-runner-event.ndjson must contain exactly one non-empty line (found %d)" % len(lines))
try:
    event = json.loads(lines[0])
except Exception as e:  # noqa: BLE001
    fail("codex-runner-event.ndjson line is not valid JSON: %s" % e)
if not isinstance(event, dict):
    fail("codex-runner-event.ndjson line is not a JSON object")

# --- event validates against the schema ------------------------------------
# A built-in subset validator runs ALWAYS, so the QA gate is deterministic with
# no extra setup: required fields, additionalProperties=false, type checks
# (including ["type","null"] unions), enum/const, integer minimum, and array
# item types. python3-jsonschema, when installed, additionally runs afterwards
# for full JSON Schema coverage.
schema = load_json(schema_path, "event schema")


def type_ok(value, t):
    if t == "null":
        return value is None
    if t == "boolean":
        return isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    if t == "array":
        return isinstance(value, list)
    if t == "object":
        return isinstance(value, dict)
    return True  # unknown type keyword: left to full jsonschema when installed


required = set(schema.get("required", []))
props = schema.get("properties", {})
have = set(event.keys())
missing = required - have
if missing:
    fail("event missing required fields: %s" % sorted(missing))
if schema.get("additionalProperties") is False:
    extra = have - set(props.keys())
    if extra:
        fail("event has fields not in the schema: %s" % sorted(extra))
for key, spec in props.items():
    if key not in event:
        continue
    val = event[key]
    types = spec.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        if not any(type_ok(val, t) for t in allowed):
            fail("event field '%s' has wrong type (expected %s, got %s)"
                 % (key, "|".join(allowed), type(val).__name__))
    if "const" in spec and val != spec["const"]:
        fail("event field '%s' must be %r (got %r)" % (key, spec["const"], val))
    if "enum" in spec and val not in spec["enum"]:
        fail("event field '%s' must be one of %r (got %r)" % (key, spec["enum"], val))
    if ("minimum" in spec and isinstance(val, (int, float))
            and not isinstance(val, bool) and val < spec["minimum"]):
        fail("event field '%s' is below minimum %s (got %r)"
             % (key, spec["minimum"], val))
    if isinstance(val, list):
        item_types = (spec.get("items") or {}).get("type")
        if item_types is not None:
            allowed = item_types if isinstance(item_types, list) else [item_types]
            for i, item in enumerate(val):
                if not any(type_ok(item, t) for t in allowed):
                    fail("event field '%s[%d]' has wrong item type (expected %s, got %s)"
                         % (key, i, "|".join(allowed), type(item).__name__))

try:
    import jsonschema
    try:
        jsonschema.validate(event, schema)
    except jsonschema.ValidationError as e:
        fail("event does not validate against codex-runner-event.schema.json: %s" % e.message)
except ImportError:
    pass  # subset validation above already ran; full validation is extra depth

# --- codex-runner-metrics.prom: syntax + label discipline ------------------
metrics_path = os.path.join(run_dir, "codex-runner-metrics.prom")
if not os.path.isfile(metrics_path):
    fail("codex-runner-metrics.prom missing")

ALLOWED_LABELS = {
    "repo", "run_type", "runner", "provider", "model", "reasoning_effort",
    "outcome", "stage", "verdict", "artifact_contract_version", "event_schema_version",
}
FORBIDDEN_LABELS = {
    "run_id", "branch", "safe_branch", "head_sha", "head_short_sha",
    "packet_sha256", "schema_sha256", "image_id", "run_dir", "packet_path", "error",
}
sample_re = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(\{(?P<labels>.*)\})?\s+(?P<value>\S+)\s*$")
label_pair_re = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')
# The ENTIRE label block must be well-formed name="quoted" pairs separated by
# commas (optional trailing comma). Unquoted values and trailing garbage are
# rejected, not skipped.
label_block_re = re.compile(
    r'^[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\]|\\.)*"'
    r'(?:,[a-zA-Z_][a-zA-Z0-9_]*="(?:[^"\\]|\\.)*")*,?$'
)
help_seen, type_seen = set(), set()
samples = {}
for ln in open(metrics_path).read().splitlines():
    if not ln.strip():
        continue
    if ln.startswith("# HELP "):
        name = ln.split(None, 3)[2]
        if name in help_seen:
            fail("duplicate HELP for metric %s in codex-runner-metrics.prom" % name)
        if name in samples:
            fail("HELP directive for metric %s appears after its sample (directives must precede samples)" % name)
        help_seen.add(name)
        continue
    if ln.startswith("# TYPE "):
        parts = ln.split()
        if len(parts) != 4:
            fail("malformed TYPE directive: %r" % ln)
        name, mtype = parts[2], parts[3]
        if name in type_seen:
            fail("duplicate TYPE for metric %s in codex-runner-metrics.prom" % name)
        if mtype != "gauge":
            fail("TYPE for metric %s must be gauge (contract declares every metric a gauge), got %r"
                 % (name, mtype))
        if name in samples:
            fail("TYPE directive for metric %s appears after its sample (directives must precede samples)" % name)
        type_seen.add(name)
        continue
    if ln.startswith("#"):
        continue
    m = sample_re.match(ln)
    if not m:
        fail("metrics line does not parse as a Prometheus sample: %r" % ln)
    try:
        value = float(m.group("value"))
    except ValueError:
        fail("metric value is not numeric: %r" % ln)
    labels_raw = m.group("labels")
    parsed_labels = {}
    if labels_raw:
        if not label_block_re.match(labels_raw):
            fail("metrics label block does not fully parse (unquoted value or trailing garbage): %r" % ln)
        for key, val in label_pair_re.findall(labels_raw):
            if key in parsed_labels:
                fail("duplicate metric label '%s': %r" % (key, ln))
            parsed_labels[key] = val
            if key in FORBIDDEN_LABELS:
                fail("forbidden high-cardinality metric label '%s' in codex-runner-metrics.prom" % key)
            if key not in ALLOWED_LABELS:
                fail("metric label '%s' is not in the allowed low-cardinality set" % key)
    name = m.group("name")
    if name in samples:
        fail("duplicate sample for metric %s (contract is one series per metric per run)" % name)
    samples[name] = (parsed_labels, value)
if not samples:
    fail("codex-runner-metrics.prom has no metric sample lines")

# Directives and samples must match one-to-one: every sample carries HELP+TYPE
# (the runner always emits the triple), and no directive floats without a sample.
for name in sorted(samples):
    if name not in help_seen:
        fail("metric %s has a sample but no HELP directive" % name)
    if name not in type_seen:
        fail("metric %s has a sample but no TYPE directive" % name)
for name in sorted(help_seen - set(samples)):
    fail("HELP directive for metric with no sample: %s" % name)
for name in sorted(type_seen - set(samples)):
    fail("TYPE directive for metric with no sample: %s" % name)

# --- metrics <-> event contract agreement ----------------------------------
# The runner emits a fixed, closed set of metrics whose labels and values are
# derived from the same values as the event (02-run-prepr-review-docker.sh).
# Mirror that derivation exactly and require full agreement, so a metrics file
# that is merely parseable — wrong metric names, stale labels like
# outcome="succeeded" on a failed run, or drifted values — cannot pass the gate.
def lv(v):
    if v in (None, ""):
        return "unknown"
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


expected_labels = {
    "repo": lv(event.get("repo")),
    "run_type": "prepr_review",
    "runner": lv(event.get("review_mode")),
    "provider": lv(event.get("model_provider")),
    "model": lv(event.get("model")),
    "reasoning_effort": lv(event.get("reasoning_effort")),
    "outcome": lv(event.get("status")),
    "stage": lv(event.get("stage")),
    "verdict": lv(event.get("verdict") if event.get("verdict") is not None else "none"),
}
expected_info_labels = {
    "repo": expected_labels["repo"],
    "artifact_contract_version": str(event.get("artifact_contract_version")),
    "event_schema_version": str(event.get("schema_version")),
}
expected_metrics = {
    "codex_runner_run_duration_seconds":
        (expected_labels,
         float(event["duration_seconds"] if event.get("duration_seconds") is not None else 0)),
    "codex_runner_exit_code":
        (expected_labels,
         float(event["exit_code"] if event.get("exit_code") is not None else 0)),
    "codex_runner_secret_leak_detected":
        (expected_labels, 1.0 if event.get("secret_leak_detected") else 0.0),
    # The runner sets schema_valid iff a verdict was parsed from the review,
    # which is exactly when the event's verdict is non-null.
    "codex_runner_schema_valid":
        (expected_labels, 1.0 if event.get("verdict") is not None else 0.0),
    "codex_runner_artifact_contract_version_info": (expected_info_labels, 1.0),
    "codex_runner_run_info": (expected_labels, 1.0),
}
if event.get("packet_bytes") is not None:
    expected_metrics["codex_runner_packet_bytes"] = (expected_labels, float(event["packet_bytes"]))

missing = sorted(set(expected_metrics) - set(samples))
if missing:
    fail("metrics missing required contract metric(s): %s" % missing)
unexpected = sorted(set(samples) - set(expected_metrics))
if unexpected:
    fail("metrics contain metric name(s) outside the contract: %s" % unexpected)
for name, (want_labels, want_value) in sorted(expected_metrics.items()):
    got_labels, got_value = samples[name]
    diff = sorted(k for k in set(want_labels) | set(got_labels)
                  if want_labels.get(k) != got_labels.get(k))
    if diff:
        k = diff[0]
        fail("metric %s label '%s' disagrees with the event (%r != %r)"
             % (name, k, got_labels.get(k), want_labels.get(k)))
    if got_value != want_value:
        fail("metric %s value disagrees with the event (%r != %r)"
             % (name, got_value, want_value))

# --- event <-> summary agreement -------------------------------------------
for k in ["run_id", "status", "exit_code", "stage", "verdict",
          "secret_leak_detected", "duration_seconds"]:
    if event.get(k) != summary.get(k):
        fail("event and run.summary.json disagree on '%s' (%r != %r)"
             % (k, event.get(k), summary.get(k)))

# --- event <-> container.provenance agreement (when present) ---------------
cprov_path = os.path.join(run_dir, "container.provenance.json")
if os.path.isfile(cprov_path):
    cprov = load_json(cprov_path, "container.provenance.json")
    flags = cprov.get("codex_flags", {})
    expected = {
        "image": cprov.get("image"),
        "image_id": cprov.get("image_id"),
        "codex_cli_version": cprov.get("codex_cli_version"),
        "model": cprov.get("model"),
        "model_provider": cprov.get("model_provider"),
        "reasoning_effort": flags.get("reasoning_effort"),
        "reasoning_effort_source": flags.get("reasoning_effort_source"),
    }
    for k, v in expected.items():
        if event.get(k) != v:
            fail("event and container.provenance.json disagree on '%s' (%r != %r)"
                 % (k, event.get(k), v))

# --- event <-> packet.provenance agreement (when present) ------------------
pprov_path = os.path.join(run_dir, "packet.provenance.json")
if os.path.isfile(pprov_path):
    pprov = load_json(pprov_path, "packet.provenance.json")
    for k in ["packet_bytes", "packet_sha256", "max_packet_bytes", "schema_sha256",
              "head_sha", "head_short_sha", "review_base"]:
        if event.get(k) != pprov.get(k):
            fail("event and packet.provenance.json disagree on '%s' (%r != %r)"
                 % (k, event.get(k), pprov.get(k)))

# --- secret posture: no token names, no live key value ---------------------
TOKEN_NAMES = ["SAKANA_API_KEY", "BITWARDEN_TOKEN", "BWS_ACCESS_TOKEN", "OPENAI_API_KEY"]
live_keys = [
    value
    for value in (
        os.environ.get("SAKANA_API_KEY", ""),
        os.environ.get("OPENAI_API_KEY", ""),
    )
    if value
]
for fn in ["codex-runner-event.ndjson", "codex-runner-metrics.prom"]:
    fp = os.path.join(run_dir, fn)
    if not os.path.isfile(fp):
        continue
    text = open(fp).read()
    for name in TOKEN_NAMES:
        if name in text:
            fail("%s contains the secret token name '%s' (possible env dump)" % (fn, name))
    if any(live_key in text for live_key in live_keys):
        # Never print a key value.
        fail("%s contains a live provider key value" % fn)

print("==> OK: observability export is structurally valid and shipping-safe")
PY
