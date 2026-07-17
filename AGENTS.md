# Agent Guide

## Start Here

This repository is the Property Tax Data Platform. Use `rg --files` to orient, then read the closest scoped `AGENTS.md` before editing an area.

## Source of Truth

1. Accepted behavior: `openspec/specs/` and active delta specs under `openspec/changes/`.
2. Change-specific architecture and work: active `design.md` and `tasks.md`.
3. Stable navigation and operations: `README.md`, `CONTRIBUTING.md`, and `docs/`.
4. Code and tests implement the accepted specs; they do not redefine them.

## Repository Boundaries

- `property_tax_domain` has no infrastructure dependencies.
- `property_tax_application` depends only on the domain and defines ports/use cases.
- `property_tax_adapters` implements outbound ports and may depend on application/domain.
- `property_tax_ingestion` is a composition root and inbound runtime.
- `dags/` declares orchestration only; no parsing, county mapping, or SQL belongs there.

Allowed dependency direction: `dags/services -> adapters -> application -> domain`.

## Workflow

- GitHub Issues are intake. Non-bootstrap implementation must reference an accepted issue.
- OpenSpec artifacts must be complete and valid before implementing non-trivial work.
- Keep all six initial counties visible; do not generalize one county's layout into the domain.
- Appraisal values are not authoritative tax bills, payments, or delinquency records.
- Do not read, log, or commit secrets, local `.env` files, credentials, or full source releases.

## Commands

```bash
make sync
make hooks
make counties
make check
openspec status --change bootstrap-six-county-appraisal-platform
```

## Host Tooling

- Use `scripts/gh` for GitHub CLI commands. It prefers `gh` from `PATH` and otherwise resolves the newest executable at `~/.cache/copilot-desktop-gh-*/gh`.
- The GitHub CLI was found at `/home/mike/.cache/copilot-desktop-gh-2.93.0/gh` on 2026-07-15. Treat that versioned path as host-specific; use the wrapper so upgrades do not require repository changes.

## Scoped Guidance

- [`openspec/AGENTS.md`](openspec/AGENTS.md)
- [`dags/AGENTS.md`](dags/AGENTS.md)
- [`libs/AGENTS.md`](libs/AGENTS.md)
- [`libs/property-tax-adapters/AGENTS.md`](libs/property-tax-adapters/AGENTS.md)
- [`services/AGENTS.md`](services/AGENTS.md)
- [`docs/AGENTS.md`](docs/AGENTS.md)
