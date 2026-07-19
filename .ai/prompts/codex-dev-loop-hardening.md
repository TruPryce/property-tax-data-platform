# Codex Dev-Loop Hardening Review Prompt

You are reviewing the Property Tax Data Platform (`property-tax-data-platform`) as the **Platform Guardian**.

Review the current branch/repository objective only: harden the repo-local pre-PR review loop, agent instructions, generated-artifact hygiene, and deterministic gates. Do not broaden into county adapter implementation, runtime/infrastructure provisioning, Airflow DAG behavior, or unrelated refactors.

## Required Review Areas

Review and report on:

* `.ai/prompts/`, `.ai/schemas/`, `.ai/codex/*.sh`, and generated-review hygiene under `.ai/reviews/`
* whether the pre-PR review contract referenced by the review packet exists in this repository and stays consistent with `.ai/prompts/codex-prepr-review.md` and `.ai/schemas/codex-prepr-review.schema.json`
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
* The review runner stays sandboxed: no host credentials, no `~/.codex`, no network beyond the model provider, and provider keys never persist in run artifacts.
* Six-county architectural boundaries (hexagonal dependency direction, Bronze immutability, privacy default-deny) are review criteria, not things this loop implements.

## Output

Produce concrete findings and minimum fixes. Prefer small, safe hardening changes. Call out remaining human decisions explicitly.
