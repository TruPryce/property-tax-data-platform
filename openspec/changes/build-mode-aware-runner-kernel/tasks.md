## 1. Contracts and Declarative Policy

- [x] 1.1 Add strict schemas for CountyForge run requests, capability profiles, and provider/model catalogs
- [x] 1.2 Add separate strict plan, implementation, fix, and validation result schemas while retaining the review schema
- [x] 1.3 Add provider-neutral generic run-event and run-summary schemas with typed budget-usage states
- [x] 1.4 Define and schema-validate the OpenAI and Sakana provider/model catalog with explicit credential names and Codex version floors
- [x] 1.5 Define and schema-validate all five immutable capability profiles with distinct mode schemas, budgets, images/configs, tools, mounts, network, credentials, and posture

## 2. Runner Kernel Package

- [x] 2.1 Add `tools/*` to the uv workspace and scaffold the typed Python 3.12 `countyforge-runner` package and CLI entry point
- [x] 2.2 Implement strict request/profile/catalog loading and deterministic canonical document hashing
- [x] 2.3 Implement mode/profile, provider/model, Codex-version, effort, schema, artifact, and mode-specific compatibility validation
- [x] 2.4 Implement budget resolution that permits tightening and rejects every ceiling expansion without fabricating unavailable usage
- [x] 2.5 Implement `validate-request`, `resolve-profile`, `list-profiles`, and non-executing `explain` JSON commands
- [x] 2.6 Implement sanitized structured CLI errors and verify credential values never enter validation, resolution, or explanation output

## 3. Execution and Evidence

- [x] 3.1 Implement fail-closed `profile_not_implemented` execution for plan, implement, fix, and validate before credential or executor access
- [x] 3.2 Implement additive generic request/profile/event/summary/metrics evidence with low-cardinality labels and atomic run-directory claims
- [x] 3.3 Implement review dispatch through the existing packet-only adapter with scoped configuration and provider credentials
- [x] 3.4 Enforce resolved review wall-clock, attempt, input-byte, and output-byte budgets and record typed usage/dispositions
- [x] 3.5 Emit generic review evidence alongside legacy artifact-contract v1 evidence and keep historical evidence readable

## 4. Provider and Image Compatibility

- [x] 4.1 Upgrade the Codex CLI image pin to published version 0.144.6 and update labels, provenance, catalog, and compatibility documentation deliberately
- [x] 4.2 Make the review adapter select only catalog-declared OpenAI or Sakana models and inject only the selected provider credential into the container
- [x] 4.3 Add deterministic Codex version and executable-posture gates that detect undeclared tools, mounts, credentials, schemas, images, or network changes
- [x] 4.4 Preserve the opt-in Sakana live smoke and add an equivalent explicitly opt-in OpenAI review smoke path without paid CI calls

## 5. Compatibility and Developer Workflow

- [x] 5.1 Route `make prepr` through a generated versioned review request and the CountyForge kernel while preserving `make prepr-no-ai` and legacy evidence paths
- [x] 5.2 Add `countyforge-runner-check`, `countyforge-profile-tests`, and `countyforge-request-fixtures` Make targets and include all deterministic gates in `runner-contract-tests`
- [x] 5.3 Add the no-cost CountyForge runner checks to CI and keep all live-provider probes opt-in
- [x] 5.4 Verify generated CountyForge/review evidence remains ignored and repository artifact/secret checks reject unsafe committed content

## 6. Acceptance Tests

- [x] 6.1 Test valid review resolution, adapter dispatch, and the no-repository-mount review boundary
- [x] 6.2 Test all five modes resolve their own schemas and all four future modes return `profile_not_implemented` without credential/executor access
- [x] 6.3 Test mode immutability and rejection of added tools, mounts, network destinations, credentials, artifacts, schemas, and unknown JSON properties
- [x] 6.4 Test rejection of wall-time, attempt, input/output, effort, token, and cost expansion above profile ceilings
- [x] 6.5 Test unknown profile versions, unsupported provider/model combinations, unsupported effort, and below-minimum Codex versions
- [x] 6.6 Test capability hashes change on posture changes, sentinel credentials never enter artifacts, and generic metrics remain low cardinality
- [x] 6.7 Test legacy `make prepr` command and artifact compatibility plus cross-agreement between generic and legacy review evidence

## 7. Architecture and Documentation

- [x] 7.1 Add accepted ADR-0005 for the mode-aware kernel, immutable profiles, provider separation, review isolation, and PR #1 compatibility
- [x] 7.2 Add scoped `tools/AGENTS.md`, package README, engineering runner guide, and schema/profile/provider documentation with layered cross-links
- [x] 7.3 Update the root README, documentation hub, contributor workflow, review artifact/observability contracts, and architecture navigation without duplicating OpenSpec requirements

## 8. Final Validation and Delivery

- [x] 8.1 Validate the OpenSpec change strictly and run `make check`, `make runner-contract-tests`, `make countyforge-runner-check`, and `make prepr-no-ai`
- [x] 8.2 Run the existing review profile through the new kernel without posture change and record whether paid provider smoke tests were run or intentionally skipped
- [x] 8.3 Inspect tracked/untracked content for source records, owner PII, credentials, and generated run artifacts and address all BLOCKER/MUST_FIX review findings
- [x] 8.4 Commit and push the scoped branch and open a draft PR referencing Issue #4, parent program #2, and OpenSpec change `build-mode-aware-runner-kernel`

## 9. PR Review Trust-Boundary Remediation

- [x] 9.1 Add strict profile input-root/repository policies plus packet-provenance and request hash contracts
- [x] 9.2 Enforce canonical regular inputs, repository identity, actual HEAD, valid ancestor base, and packet/request/provenance agreement before credentials
- [x] 9.3 Generate canonical packet provenance in `make prepr`, document the binding, and preserve the direct operator-only smoke path
- [x] 9.4 Add negative path/SHA/repository/provenance tests, rerun all deterministic gates, push, and resolve the two addressed PR threads
