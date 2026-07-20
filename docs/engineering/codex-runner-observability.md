# Codex Runner Observability

## Purpose

This contract defines version 1 of the pre-PR review runner's local observability export. It covers
the event and Prometheus textfile artifacts written into each claimed run directory. It does not
deploy a collector or send data to a remote system.

## Event Contract

`codex-runner-event.ndjson` contains exactly one non-empty JSON object line. The object validates
against `.ai/schemas/codex-runner-event.schema.json` and records normalized run identity, timing,
status, packet provenance, image and model provenance, and the enforced tool posture.

The event is derived from `run.summary.json`, `packet.provenance.json`, and
`container.provenance.json`. It never contains review text, Codex event payloads, stdout, stderr,
error text, environment dumps, tokens, or API-key values.

`EVENT_SCHEMA_VERSION` in `.ai/codex/02-run-prepr-review-docker.sh` is the implemented event
version. Change it together with the JSON Schema, fixtures, validator, and this document.

The fields used as lifecycle, posture, or metric-label dimensions are closed values:

| Field | Allowed values |
|---|---|
| `review_mode` | `docker` |
| `status` | `succeeded`, `failed` |
| `stage` | `preflight`, `docker_run`, `review_missing`, `secret_leak_scan`, `output_budget`, `observability_export`, `completed` |
| `verdict` | `pass`, `pass_with_notes`, `block`, or `null` |
| `model_source`, `reasoning_effort_source` | `override`, `image-default`, or `null` |
| `reasoning_effort` | `high`, `xhigh`, or `null` |
| `sandbox` | `danger-full-access` |
| `web_search` | `false` |

The schema and free fixtures reject values outside this set so posture and metric cardinality
cannot drift silently.

## Metrics Contract

`codex-runner-metrics.prom` uses Prometheus textfile syntax. Every metric has one `HELP` directive,
one `TYPE ... gauge` directive, and one sample. The metric set is closed:

| Metric | Value |
|---|---|
| `codex_runner_run_duration_seconds` | Wall-clock run duration |
| `codex_runner_packet_bytes` | Packet size; omitted only when no packet was staged |
| `codex_runner_exit_code` | Runner exit code |
| `codex_runner_secret_leak_detected` | `1` when the live provider key was detected, otherwise `0` |
| `codex_runner_schema_valid` | `1` when a verdict was parsed from schema-constrained output |
| `codex_runner_artifact_contract_version_info` | Constant `1` with artifact and event versions as labels |
| `codex_runner_run_info` | Constant `1` carrying the approved low-cardinality run labels |

Ordinary run metrics use only `repo`, `run_type`, `runner`, `provider`, `model`,
`reasoning_effort`, `outcome`, `stage`, and `verdict`. The version-info metric uses only `repo`,
`artifact_contract_version`, and `event_schema_version`.

High-cardinality or sensitive labels are prohibited, including run IDs, branches, commit hashes,
packet and schema hashes, image IDs, paths, and error text.

## Agreement and Safety

The validator requires exact agreement between:

- event lifecycle fields and `run.summary.json`;
- event packet fields and `packet.provenance.json`, when present;
- event image/model fields and `container.provenance.json`, when present; and
- every metric label/value and the event from which it was derived.

The runner scans both export files for the live provider key before finalizing them. The validator
also rejects secret-token names (`SAKANA_API_KEY`, `BITWARDEN_TOKEN`, `BWS_ACCESS_TOKEN`, and
`OPENAI_API_KEY`) to catch accidental environment dumps.

Per-run event and metrics files are authoritative. The branch-level
`latest-codex-runner-metrics.prom` file is a best-effort mirror and cannot change a completed run's
outcome.

This version-1 contract remains review-specific for compatibility. Kernel-routed reviews also emit
provider-neutral `countyforge-run-event.ndjson`, `countyforge-run-summary.json`, and
`countyforge-run-metrics.prom` according to the CountyForge runner guide. Historical review runs
do not require those generic artifacts.

## Validation

Run fixture-only validation, which makes no provider or Docker call:

```bash
make codex-observability-fixtures
```

Validate a specific existing run:

```bash
RUN_DIR=.ai/reviews/codex-prepr/<safe-branch>/<run-id> make codex-observability-validate
```

Run fixture validation plus validation of the current branch's latest run, when one exists:

```bash
make codex-observability-qa
```

## Related

- [Documentation hub](../README.md) - Repository documentation navigation
- [Pre-PR review contract](pre-pr-review-contract.md) - End-to-end review loop
- [Review artifact contract](review-artifact-contract.md) - Per-run directory and evidence rules
- [Runner event schema](../../.ai/schemas/codex-runner-event.schema.json) - Normalized event shape
- [CountyForge runner kernel](countyforge-runner-kernel.md) - Generic event/summary and migration
- [CountyForge GitHub control plane](countyforge-github-control-plane.md) - Sanitized command/state events and low-cardinality labels
