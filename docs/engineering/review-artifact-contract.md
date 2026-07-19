# Review Artifact Contract

## Purpose

This contract defines version 1 of the evidence written by the packet-only pre-PR reviewer. A
run's source of truth is its immutable directory:

```text
.ai/reviews/codex-prepr/<safe-branch>/<run-id>/
```

Root-level files under `.ai/reviews/` and branch-level `latest` files are convenience mirrors or
pointers. They are never authoritative run evidence.

## Run Directory Claim

The runner sanitizes branch characters outside `[A-Za-z0-9._-]` to `__`. Before writing evidence,
it refuses a non-empty run directory and atomically claims an empty directory with a transient
`.claim/` marker. A second process cannot reuse the same run ID, and a completed run is never
overwritten.

The runner removes `.claim/` during finalization. A stale marker means a process was interrupted;
operators must verify that no run is active before removing the affected run directory.

The free runner contract suite exercises both collision paths: an existing `.claim/` marker and a
non-empty run directory must return exit code 2 without modifying prior evidence.

## Output Boundary

`REVIEWS_ROOT`, `OUT_DIR`, and `COMPAT_DIR` must resolve beneath the repository's ignored
`.ai/reviews/` directory by default. Resolution follows existing symlinks before applying the
boundary, so a symlink below `.ai/reviews/` cannot redirect generated evidence into tracked source
or outside the repository. The standard `.ai/reviews/` root itself may not be redirected by a
symlink without the same explicit opt-in.

Tests and operators may set `ALLOW_NONSTANDARD_REVIEW_DIR=1` for an intentional nonstandard
location. This is an explicit trust-boundary opt-in: the caller is responsible for choosing an
untracked destination and protecting any evidence written there.

## Version 1 Artifacts

| Artifact | Contract |
|---|---|
| `review-packet.md` | Frozen packet bytes supplied to the model. Staged immediately after the directory claim. |
| `codex-prepr-review.md` | Schema-constrained final review. Present only when the model produces a final response. |
| `codex-events.ndjson` | Raw Codex JSON event stream captured from stdout after execution begins. |
| `codex-prepr-review.stdout` | Compatibility copy of `codex-events.ndjson`. |
| `codex-prepr-review.stderr` | Captured runner stderr after execution begins. |
| `packet.provenance.json` | Packet and output-schema hashes, byte limit, Git head, base ref, and source path. |
| `container.provenance.json` | Image, model, CLI, disabled tools, mounts, user, tmpfs, and container hardening. |
| `run.provenance.json` | Run identity joining Git, packet, container, model, and invocation provenance. |
| `run.summary.json` | Lifecycle result and an explicit presence map for every contract artifact. |
| `codex-runner-event.ndjson` | One normalized observability event defined by the observability contract. |
| `codex-runner-metrics.prom` | Low-cardinality Prometheus textfile metrics defined by the observability contract. |

When the review is entered through CountyForge, five additive migration artifacts sit beside this
version-1 set: `countyforge-request.provenance.json`, `countyforge-profile.snapshot.json`,
`countyforge-run-event.ndjson`, `countyforge-run-summary.json`, and
`countyforge-run-metrics.prom`. Their absence does not invalidate historical PR #1 evidence, and
their presence does not change `ARTIFACT_CONTRACT_VERSION=1`; the legacy files above remain
readable and authoritative for this contract.

`run.summary.json` is written on every path after a run directory is successfully claimed. Early
preflight failures can legitimately omit execution and provenance artifacts; consumers must use
the summary's `artifacts` map instead of assuming every file exists. Failures before a directory is
claimed do not create a summary.

## Packet Integrity

`make prepr` generates one packet, atomically refreshes `.ai/reviews/review-packet.md` and its strict
`review-packet.provenance.json` sidecar, and passes the canonical packet to the runner. The packet
begins with machine-readable repository, merge-base, HEAD, and builder metadata. The request binds
both file hashes; the kernel verifies approved-root containment, repository/commit identity, and
agreement among that embedded metadata, the request, and the sidecar before execution. The runner immediately copies those bytes into the claimed
run directory and rechecks the frozen hash. All packet sizing, hashing, secret scanning, and
model stdin use that staged copy.

The packet builder redacts high-confidence literal credential values while preserving dynamic
source expressions. It rejects secret-looking paths outright. The live provider-key scan remains
a separate runner gate and is not replaced by packet redaction.

`packet.provenance.json` records the staged packet's SHA-256 and byte count. Packets larger than
`MAX_PACKET_BYTES` fail before the provider call so the reviewer never silently reviews a truncated
diff.

## Failure and Secret Handling

The runner records one lifecycle stage in `run.summary.json`: `preflight`, `docker_run`,
`review_missing`, `secret_leak_scan`, `output_budget`, `observability_export`, or `completed`.

The live provider key is scanned before and after the model call without printing the value. If it
appears in the packet or generated output, the runner deletes the staged packet and model-output
artifacts, purges compatibility copies, records `secret_leak_detected: true`, and fails the run.
Non-secret summary and provenance metadata may remain as incident evidence.

## Pointers and Mirrors

For canonical run directories, the runner writes these non-authoritative branch-level files:

- `latest.json` points to the most recently finalized run and its summary and review paths.
- `latest-codex-runner-metrics.prom` mirrors the latest per-run metrics file.

When `COMPAT_DIR` is set, the runner coherently mirrors the review, stdout, stderr, and packet
provenance into that directory. Missing current-run files remove stale mirror files, except that a
pure preflight failure preserves the previous successful compatibility set. The per-run directory
always wins if a pointer or mirror disagrees with it.

## Versioning

`ARTIFACT_CONTRACT_VERSION` in `.ai/codex/02-run-prepr-review-docker.sh` is the implemented version.
Bump it when artifact names, required presence rules, or JSON field shapes change. Update this
contract, runner fixtures, and validators in the same change.

## Validation

Run the free contract checks with:

```bash
make runner-contract-tests
```

Run the paid end-to-end adversarial probe only with explicit consent:

```bash
RUN_LIVE_PROVIDER_SMOKE=1 make codex-smoke

RUN_LIVE_PROVIDER_SMOKE=1 make codex-smoke-openai
```

## Related

- [Documentation hub](../README.md) - Repository documentation navigation
- [Pre-PR review contract](pre-pr-review-contract.md) - Review scope, severity, and verdict rules
- [Runner observability](codex-runner-observability.md) - Event and metrics export contract
- [CountyForge runner kernel](countyforge-runner-kernel.md) - Generic evidence and compatibility
- [Review output schema](../../.ai/schemas/codex-prepr-review.schema.json) - Final review JSON shape
