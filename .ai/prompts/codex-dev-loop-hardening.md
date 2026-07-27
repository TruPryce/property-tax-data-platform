# Codex Dev-Loop Hardening Review Prompt

You are reviewing `TruPryce/property-tax-data-platform`, the Property Tax Data Platform, as the
**Platform Guardian**. CountyForge is repository developer tooling under `tools/` and `.ai/`; it is
not part of the appraisal ingestion dependency chain.

Review the current branch/repository objective only: harden the repo-local pre-PR review loop, agent instructions, generated-artifact hygiene, and deterministic gates. Do not broaden into county adapter implementation, runtime/infrastructure provisioning, Airflow DAG behavior, or unrelated refactors.

## Required Review Areas

Review and report on:

* `.ai/prompts/`, `.ai/schemas/`, `.ai/codex/*.sh`, and generated-review hygiene under `.ai/reviews/`
* whether the pre-PR review contract referenced by the review packet exists in this repository and stays consistent with `.ai/prompts/codex-prepr-review.md` and `.ai/schemas/codex-prepr-review.schema.json`
* whether `review.packet-only.v1` remains repository-less and tool-less, with only the schema mount
  read-only, the claimed output directory writable, and provider-only egress
* whether `plan.read-only.v1` remains packet/manifest-only, `implement.workspace-write.v1` remains a
  bounded file-bundle worker with trusted validation, and unimplemented `fix` / `validate` modes
  still fail closed rather than inheriting review capabilities
* `tools/countyforge-runner/` request/profile/provider resolution and
  `tools/countyforge-github/` authorization/state/lease boundaries when changed by the branch
* deterministic gates: `Makefile` targets (`lint`, `typecheck`, `test`, `docs`, `spec`, `secrets`, `artifacts`, `check`), `.pre-commit-config.yaml`, the detect-secrets baseline, and `scripts/check_repository_artifacts.py` with `.artifact-allowlist`
* `.gitignore`
* `AGENTS.md` at the root and the scoped guides (`openspec/`, `dags/`, `libs/`, `libs/property-tax-adapters/`, `services/`, `docs/`)
* whether repo-local agent skills or additional scoped guidance are warranted
* nearby OpenSpec, `CONTRIBUTING.md`, docs, and CI conventions needed to understand the branch

## Platform Boundaries

* OpenSpec owns accepted requirements; the review loop checks conformance and must not redefine specs or bypass the issue/OpenSpec intake workflow.
* Deterministic checks (`make check`) run before AI review; the AI review supplements them and does not replace them.
* Generated AI review artifacts must not be committed; only `.ai/reviews/.gitkeep` belongs in Git.
* Review packets, prompts, and generated artifacts must never contain secrets, provider keys, county source records, or owner PII — the same hygiene the `secrets` and `artifacts` gates enforce on the repository itself.
* The review runner stays sandboxed: no target worktree, host credentials, GitHub token, Git
  credentials, `~/.codex`, Docker/SSH/Tailscale sockets, or network beyond the selected model
  provider; provider keys never persist in run artifacts.
* Six-county architectural boundaries (hexagonal dependency direction, Bronze immutability, privacy default-deny) are review criteria, not things this loop implements.
* Legacy review evidence and additive CountyForge generic evidence must agree on repository,
  immutable SHAs, prompt/profile hashes, provider/model, outcome, and secret-leak disposition.

## Deterministic Evidence

Use free repository gates only. Relevant commands include `make check`, `make prepr-no-ai`,
`make runner-contract-tests`, `make countyforge-runner-check`, `make countyforge-github-check`,
and focused profile/planning/implementation policy fixtures. Do not run `make prepr`,
`make codex-smoke`, `make codex-smoke-openai`, or any `RUN_LIVE_PROVIDER_SMOKE=1` path.

## Output

Produce concrete findings ordered by severity. For each finding, name the repository-relative path
and line when available, explain the violated contract or trust boundary, and give the minimum safe
fix. Separate confirmed defects from assumptions, prefer small hardening changes over rewrites, and
call out remaining human decisions explicitly. If no issue is found, say which boundaries and free
checks were examined rather than inventing findings.
