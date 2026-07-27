# Claude Fix From Review Prompt

Apply only the `BLOCKER` and `MUST_FIX` findings from the Codex pre-PR review file provided by the caller.

## Source and Scope

* The repository is `TruPryce/property-tax-data-platform`. The current issue-linked OpenSpec change
  defines branch scope; `openspec/specs/` and active delta specs define accepted behavior.
* Confirm each finding still applies to the current file and line before editing. Do not edit the
  generated review to suppress a finding or apply stale advice blindly.
* Fix root causes with the smallest coherent patch. Do not expand scope beyond the current branch
  objective and its referenced GitHub Issue / OpenSpec change.
* Do not implement `NICE_TO_FIX` or `QUESTION` items unless a minimal part is required to resolve a
  blocker or must-fix. Preserve unresolved product or architecture decisions for a human.

## Repository Rules

* Preserve the dependency direction `dags/services -> adapters -> application -> domain`; never move county parsing, mapping, or SQL into `dags/`, or vendor (PACS) vocabulary into the domain.
* Keep CountyForge runner and GitHub-control-plane behavior under `tools/` and `.ai/`; do not couple
  developer tooling to property-tax domain, application, adapters, services, or DAG runtime.
* Keep Dallas, Collin, Tarrant, Denton, Rockwall, and Ellis behind one application port while
  preserving county-specific contracts. Rockwall GIS is partial enrichment, not a full roll.
* Preserve immutable SHA-256 Bronze identity, source-grain Silver lineage, explicit Gold
  `latest_available` / `latest_certified` / `history` products, and prior Gold state when a blocking
  quality rule fails.
* Do not collapse `(prop_id, owner_sequence)` owner rows, invent canonical value semantics for
  unresolved source fields (including Dallas `TOT_VAL` and Tarrant `Total_Value`), or enable
  owner/mailing-address publication as part of a fix.
* Never present appraisal values as authoritative bills, payments, delinquency, penalties, or
  interest.
* Never introduce secrets, county source records, or oversized artifacts; fixtures stay small, synthetic or redistribution-safe.
* Keep OpenSpec artifacts valid; check off tasks only for work actually completed and verified.

## Validation

* Run the smallest relevant free deterministic checks after editing: `make lint`, `make typecheck`,
  and `make test`, plus `make docs`, `make spec`, `make secrets`, `make artifacts`, or the focused
  `make countyforge-*-check` / fixture targets for changed areas.
* Before handoff, prefer `make prepr-no-ai` or `make check` when their scope is warranted. Never run
  paid `make prepr`, `make codex-smoke`, `make codex-smoke-openai`, a
  `RUN_LIVE_PROVIDER_SMOKE=1` command, or a paid `/countyforge review` path.
* Summarize findings resolved, files changed, checks actually run, and any remaining risks or
  findings. Never claim a check passed unless its command completed successfully.
