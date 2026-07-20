## 1. Contracts and package foundation

- [x] 1.1 Add strict command, trigger, authorization-policy, state, lease, and transition JSON Schemas with valid and invalid fixtures.
- [x] 1.2 Add the version-controlled deny-by-default GitHub authorization policy and its policy-version contract.
- [x] 1.3 Create the Python 3.12 `tools/countyforge-github` src-layout package, one-way runner dependency, CLI entry point, README, and uv-workspace registration.

## 2. Pure control-plane policy

- [x] 2.1 Implement the bounded line-oriented Markdown command parser and malicious Markdown/bot/event fixtures.
- [x] 2.2 Implement permission and explicit bot/team authorization decisions with sanitized audit facts for every permission class.
- [x] 2.3 Implement immutable trigger construction, semantic idempotency, profile mapping, and strict runner-request construction.
- [x] 2.4 Implement the legal lifecycle table, terminal immutability, canonical comment marker ownership/validation, bounded rendering, and sanitized check mapping.
- [x] 2.5 Implement lease acquisition, heartbeat, release, expiry reclamation, single-winner race behavior, status reconciliation, cancellation ownership, and immutable retry policy.
- [x] 2.6 Add typed GitHub API ports, a minimal REST adapter, fake-port orchestration, stable JSON CLI commands, and sanitized exit/error behavior.

## 3. Runner two-root integration

- [x] 3.1 Add backward-compatible `contract_root` and `target_root` kernel/CLI options and load all executable policy only from the contract root.
- [x] 3.2 Bind repository identity, exact head, base ancestry, packet metadata, and provenance to the target root, including a bare Git repository, and revalidate before credential selection.
- [x] 3.3 Add positive and negative two-root tests proving target profiles/scripts/hooks/workflows cannot replace or execute trusted tooling and local `make prepr` remains compatible.

## 4. GitHub Actions control plane

- [x] 4.1 Add pinned-action `countyforge-command.yml` for created-comment intake, bot suppression, authorization, immutable resolution, canonical state/check updates, deduplication, and dispatch.
- [x] 4.2 Add pinned-action `countyforge-run.yml` with separate no-secret packet/identity preparation, fail-closed future-mode execution, selected-secret review execution, sanitized publication, and target execution concurrency.
- [x] 4.3 Add pinned-action `countyforge-maintenance.yml` for manual/scheduled expired-lease reconciliation without automatic agent dispatch.
- [x] 4.4 Add workflow-policy tests for triggers, permissions, action pins, two-root checkout isolation, target non-execution, provider-secret scoping, concurrency, cancellation ownership, and forbidden privileges.

## 5. Acceptance and observability

- [x] 5.1 Add control-plane event and low-cardinality metric rendering/validation for all required command, authorization, lease, dispatch, cancellation, retry, reconciliation, and terminal events.
- [x] 5.2 Add deterministic tests for unauthorized, duplicate, changed-head, forged-marker, status, cancel, retry, stale lease, evidence immutability, comment reuse, check conclusions, and credential non-disclosure.
- [x] 5.3 Add `countyforge-github-check`, command-fixture, and workflow-policy Make targets and include all free deterministic checks in `runner-contract-tests` and CI.
- [x] 5.4 Exercise authorized/unauthorized, duplicate/cancel/retry/stale-lease, future-mode, and synthetic safe review workflow fixtures without a paid call.

## 6. Architecture and operations documentation

- [x] 6.1 Add the accepted GitHub-native CountyForge control-plane ADR covering the two-root trust model, GitHub-native state, idempotency, permissions/secrets, leases/recovery, and rejected infrastructure alternatives.
- [x] 6.2 Add the engineering control-plane and GitHub operations references, schema/CLI docs, architecture diagram updates, and reciprocal documentation links.
- [x] 6.3 Update root/tool READMEs, contributor workflow, runner/review documentation, and scoped `AGENTS.md` guidance without duplicating normative contracts.

## 7. Verification and delivery

- [x] 7.1 Run strict OpenSpec validation and complete every implemented task in this change without modifying the completed bootstrap change.
- [x] 7.2 Run `make check`, `make runner-contract-tests`, `make countyforge-runner-check`, `make countyforge-github-check`, `make countyforge-command-fixtures`, `make countyforge-workflow-policy-tests`, and `make prepr-no-ai` successfully.
- [x] 7.3 Verify all six initial counties remain explicit, generated state/evidence stays ignored, no source/owner PII or credential is committed, and no target code executes in provider-secret fixtures.
- [ ] 7.4 Run the repo-native pre-PR review when a provider credential is available, resolve all BLOCKER/MUST_FIX findings, and record any intentionally skipped paid smoke.
- [ ] 7.5 Commit and push the implementation, open a draft PR referencing Issue #5, parent program #2, and `add-github-run-control-plane`, then verify CI and review threads.
