# Contributing

## Development Setup

Requirements:

- Git
- uv
- OpenSpec CLI 1.6 or compatible
- Python 3.12, installed automatically by uv when permitted

```bash
git clone <repository-url>
cd property-tax-data-platform
make sync
make hooks
make check
```

Use `.env.example` only as a list of configuration names. Store real secrets in local untracked configuration, Airflow Connections, or an approved secrets backend.

The pre-commit hook scans staged text files with `detect-secrets` and formats and lints Python files with Ruff. Run `make secrets` to scan all tracked and untracked, non-ignored repository files. Treat a finding as a credential incident until it is disproven; remove and rotate real secrets before continuing. Baseline changes require explicit review and must contain only documented false positives.

The artifact hook rejects county archives, databases, spatial files, tabular source extracts, prohibited data directories, disguised binary formats, and files larger than 5 MiB. Run `make artifacts` to scan all tracked and untracked, non-ignored files. Add an exact path to `.artifact-allowlist` only for a reviewed synthetic or redistribution-safe fixture and justify the exception in the pull request.

`pre-commit install` refuses to replace a centrally configured Git `core.hooksPath`. In that environment, configure the existing hook manager to run `uv run pre-commit run --hook-stage pre-commit`; do not unset or replace the shared hook path solely for this repository.

## Delivery Workflow

1. Open the appropriate structured GitHub Issue form.
2. Triage and accept the issue before implementation begins.
3. Create or update an OpenSpec change that references the issue.
4. Validate the change with `openspec validate <change-name>`.
5. Implement tasks in dependency order and update their checkboxes as they complete.
6. Run `make prepr` and address `BLOCKER` and `MUST_FIX` findings.
7. Open a pull request that references the issue and OpenSpec change.
8. Archive the OpenSpec change only after implementation and checks are complete.

The repository bootstrap change predates the GitHub remote and is the only issue-reference exception.

## Validation

```bash
make format       # apply Ruff formatting
make lint         # formatting and lint checks
make typecheck    # strict mypy
make test         # unit and architecture tests
make docs         # local Markdown links
make spec         # active OpenSpec change and repository health
make secrets      # all non-ignored files against the reviewed baseline
make artifacts    # source-artifact, content-signature, path, and size policy
make precommit    # every pre-commit hook against tracked files
make check        # all checks
make review-packet               # deterministic packet only; no model call
make prepr-no-ai                 # checks plus packet; no model call
make prepr                       # complete packet-only Docker review loop
make runner-contract-tests       # free packet and observability fixtures
make countyforge-runner-check    # free kernel, profile, provider, and compatibility suite
make countyforge-profile-tests   # immutable profile and execution-boundary fixtures
make countyforge-request-fixtures # request, budget, provider, and version fixtures
make countyforge-github-check     # GitHub adapter contracts, state, API-port, and request tests
make countyforge-plan-check       # bounded planning contracts and materializer checks
make countyforge-plan-fixtures    # no-cost planning and runner fixtures
make countyforge-plan-policy-tests # planning workflow/request policy checks
make countyforge-command-fixtures # malicious Markdown, auth, duplicate, cancel, retry, and lease fixtures
make countyforge-workflow-policy-tests # workflow triggers, pins, permissions, target isolation, and secret scope
make codex-observability-qa      # free fixture/latest-run export validation
```

The live adversarial smoke test makes a paid provider call and is never part of CI. Run it only
after building the image and opting in explicitly:

```bash
make codex-image
RUN_LIVE_PROVIDER_SMOKE=1 make codex-smoke

make codex-image-openai
RUN_LIVE_PROVIDER_SMOKE=1 make codex-smoke-openai
```

`make prepr` builds a versioned request and enters through `countyforge-runner`; the kernel then
dispatches the unchanged packet-only Docker adapter. Select `COUNTYFORGE_PROVIDER=openai` only
after building the OpenAI-specific review image. Both live smoke paths are paid and opt-in.

After the GitHub control workflows exist on the default branch, authorized repository maintainers may use `/countyforge plan` on a structured issue and `/countyforge review`, `/countyforge status`, `/countyforge cancel`, and `/countyforge retry` on issues or pull requests. Planning publishes only a validated draft OpenSpec PR and remains ineligible for implementation until human approval; implement, fix, and validate still publish `profile_not_implemented`. See the [planning-agent guide](docs/engineering/countyforge-planning-agent.md), [control-plane guide](docs/engineering/countyforge-github-control-plane.md), and [operations runbook](docs/operations/countyforge-github-operations.md).

## Pull Requests

- Keep changes scoped to one accepted issue and OpenSpec change.
- Add fixtures and contract tests for source behavior; never commit full county releases.
- Preserve original source evidence in runtime Bronze storage, not Git.
- Call out schema changes, backfill needs, migration order, and rollback behavior.
- Do not mark an adapter `production_ready` until its OpenSpec tasks and required checks pass.

## Related

- [Repository overview](README.md)
- [Documentation hub](docs/README.md)
- [OpenSpec workflow](openspec/README.md)
- [Pre-PR review contract](docs/engineering/pre-pr-review-contract.md)
- [CountyForge runner guide](docs/engineering/countyforge-runner-kernel.md)
- [CountyForge GitHub control plane](docs/engineering/countyforge-github-control-plane.md)
- [CountyForge GitHub operations](docs/operations/countyforge-github-operations.md)
- [CountyForge planning agent](docs/engineering/countyforge-planning-agent.md)
