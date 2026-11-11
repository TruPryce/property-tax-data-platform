## ADDED Requirements

### Requirement: Strict versioned run requests
The CountyForge kernel SHALL accept a strict versioned JSON run request containing immutable trigger facts, repository base and head SHAs, mode, profile identity, prompt/template identity, provider/model selection, reasoning effort, optional tightening budgets, input context, expected output schema, and requested artifacts. It MUST reject unknown properties, unsupported contract versions, unknown modes, ambiguous refs, undeclared schemas, undeclared artifacts, and mode-specific missing facts before provider execution.

#### Scenario: Validate an immutable review request
- **WHEN** a review request supplies supported contract versions, a 40-character base SHA and head SHA, the matching review profile, a declared packet input, compatible provider/model/effort, declared output schema, and allowed artifacts
- **THEN** validation succeeds and returns a machine-readable normalized request without starting a model call

#### Scenario: Reject mutable or extended request data
- **WHEN** a request supplies a branch name instead of an immutable SHA or adds a property for a tool, mount, network destination, credential, or other unknown value
- **THEN** validation fails before profile execution or credential loading

#### Scenario: Require mode-specific facts
- **WHEN** a fix request omits selected finding identifiers or its expected head SHA
- **THEN** request validation fails with a structured non-secret error

### Requirement: Immutable capability profiles
The repository SHALL store strict, versioned, immutable profiles for `review.packet-only.v1`, `plan.read-only.v1`, `implement.workspace-write.v1`, `fix.targeted-write.v1`, and `validate.deterministic.v1`. Every profile MUST declare its mode, enabled and implementation state, provider/model/effort policy, output schema, artifacts, budget defaults and ceilings, mounts, repository and writable-path access, tools, deterministic commands, network, credential names, environment allowlist, image/configuration identity, and expected security posture.

#### Scenario: Resolve each mode profile
- **WHEN** an operator lists or resolves the version-controlled profiles
- **THEN** each requested mode maps to its own exact profile version and mode-result schema and exposes its execution implementation state

#### Scenario: Detect capability posture drift
- **WHEN** any declared tool, mount, network rule, credential name, writable path, image identity, or other capability field changes
- **THEN** the canonical profile SHA-256 changes and historical evidence continues to identify the earlier hash

#### Scenario: Reject an unknown profile version
- **WHEN** a request names an existing profile ID with an unrecognized version
- **THEN** resolution fails closed and does not substitute a newer or older profile

### Requirement: Mode and capability isolation
The kernel MUST reject a request whose mode differs from its selected profile and MUST NOT allow request fields or runtime flags to add tools, mounts, paths, network destinations, credentials, schemas, artifacts, efforts, or execution implementation. A profile selection SHALL be immutable for the duration of a run.

#### Scenario: Attempt to change mode after selection
- **WHEN** a request selects the review profile but asks to run in implement mode
- **THEN** compatibility validation rejects the request before an executor is selected

#### Scenario: Attempt to expand a capability
- **WHEN** a request tries to add a model shell, repository mount, external network destination, provider credential, or undeclared artifact
- **THEN** strict schema or profile compatibility validation rejects it before provider execution

### Requirement: Packet-only review execution
The `review.packet-only.v1` profile SHALL execute through the existing `.ai/codex/` review adapter and MUST preserve its frozen packet, atomic run-directory claim, no-repository-mount boundary, read-only schema-directory mount, claimed-output-directory write mount, disabled model tools, disabled browser/apps/MCP/image generation/web search, provider-request-only network path, secret scans, structured review result, and v1 evidence guarantees.

#### Scenario: Dispatch a valid review
- **WHEN** a valid eligible review request is run
- **THEN** the kernel invokes the existing packet-only adapter with only resolved declared values and never mounts the repository into the container

#### Scenario: Detect executable posture drift
- **WHEN** the build or run adapter introduces a mount, credential, tool, network behavior, schema, image label, or Codex version not declared by the review profile
- **THEN** a no-cost compatibility contract test fails

#### Scenario: Enforce runtime limits
- **WHEN** a review exceeds its resolved wall-clock or output-byte limit
- **THEN** the kernel terminates or rejects the run, records the budget disposition, and never reports success

### Requirement: Executable input and repository binding
Every profile SHALL declare repository-relative approved input roots and repository identity/base policy. Before an executable review is eligible, the kernel MUST resolve symlinks, require packet and packet-provenance inputs to be regular files under a profile-approved root, verify the configured repository identity, require current `HEAD` to equal the request head SHA, require the request base SHA to exist as a commit and be an ancestor of that head, verify request-declared packet and provenance hashes, and require the strict packet-provenance document to agree with the request repository, base, head, packet hash, and packet byte count. The same binding MUST be revalidated immediately before provider credential selection. Ordinary run requests MUST NOT override approved input roots or repository policy.

#### Scenario: Accept a bound canonical review packet
- **WHEN** a review packet and strict provenance sidecar are regular files beneath `.ai/reviews/`, their hashes and byte count agree, the packet's embedded metadata and sidecar match the request repository/base/head facts, origin identifies the declared repository, current `HEAD` equals the request head, and base is an ancestor commit
- **THEN** the review becomes execution-eligible without loading a provider credential during validation

#### Scenario: Reject an input-root escape
- **WHEN** a review request names an absolute outside-root file, a `..` escape, a symlink resolving outside an approved root, a directory, device, or other non-regular input
- **THEN** resolution fails with a sanitized structured error before provider credential selection

#### Scenario: Reject repository or packet provenance drift
- **WHEN** repository identity is wrong, current `HEAD` is stale, the base commit does not exist or is not an ancestor, either input hash differs, or the embedded packet metadata or sidecar disagrees with the request repository/base/head/hash/byte facts
- **THEN** resolution fails closed and the review adapter is not invoked

### Requirement: Fail-closed future profile execution
The plan, implement, fix, and validate profiles SHALL be fully validatable but SHALL have `not_implemented` execution state in this change. Attempted execution MUST validate and resolve first, emit sanitized request and profile provenance, return a structured `profile_not_implemented` disposition with a non-zero exit status, and stop before loading provider credentials, creating mounts, running containers, or starting deterministic commands.

#### Scenario: Attempt an unimplemented mode
- **WHEN** a valid request attempts to run the plan, implement, fix, or validate profile
- **THEN** the run emits generic failed summary/event evidence with disposition `profile_not_implemented`, invokes no executor or credential loader, and cannot report success

#### Scenario: Explain an unimplemented mode
- **WHEN** an operator explains a valid future-mode request
- **THEN** the command returns its profile, provider/model when applicable, budgets, output schema, capabilities, and `execution_eligible: false` without creating run evidence or starting execution

### Requirement: Separate mode-result contracts
The repository SHALL maintain distinct strict schemas for review, plan, implementation, fix, and validation results. Each non-review schema MUST encode meaningful mode-specific status, work, decisions, validation, and eligibility fields rather than reusing the review verdict contract.

#### Scenario: Resolve result schemas
- **WHEN** each of the five profiles is resolved
- **THEN** review maps to the existing review result schema and every other mode maps to its own mode-specific result schema

#### Scenario: Reject a cross-mode result schema
- **WHEN** a request asks the plan profile to emit the review or implementation schema
- **THEN** compatibility validation rejects the undeclared schema before execution

### Requirement: Provider and model catalog compatibility
The kernel SHALL resolve provider configuration independently from profile policy through a strict version-controlled catalog supporting `openai` and `sakana`. Every model entry MUST declare a logical reference, provider, concrete configured identifier, supported reasoning efforts, minimum Codex CLI version, structured-output support, expected tool capabilities, credential name, and availability/live-validation state. The kernel MUST reject unsupported provider/model combinations, unsupported efforts, and Codex versions below either the profile or model minimum.

#### Scenario: Resolve a supported model
- **WHEN** the review profile selects a permitted OpenAI GPT-5.6 or Sakana Fugu logical model reference at a supported effort and compatible Codex version
- **THEN** resolution returns the catalog's exact configured identifier and compatibility facts without a provider call

#### Scenario: Reject catalog incompatibility
- **WHEN** a request pairs a Sakana logical model with OpenAI, requests an unsupported effort, or supplies a Codex version below the declared minimum
- **THEN** resolution fails before provider credential loading

#### Scenario: Change a provider identifier
- **WHEN** a concrete remote model identifier or compatibility floor changes
- **THEN** the version-controlled catalog and associated deterministic/live-validation state must change explicitly rather than silently assuming the identifier

### Requirement: Bounded execution budgets
Every profile SHALL declare defaults and hard ceilings for wall-clock duration, attempts, output bytes, input/context bytes, reasoning effort, token use when reported, and estimated or actual cost when reported. A request MAY tighten these values but MUST NOT raise them above profile ceilings or select an undeclared effort. Missing provider token or cost reporting MUST remain explicitly unavailable or null.

#### Scenario: Tighten a budget
- **WHEN** a request supplies wall time, attempts, byte limits, tokens, or cost that keeps or tightens the effective profile defaults and remains no greater than the hard ceilings
- **THEN** the resolved effective budget uses the tighter request values

#### Scenario: Expand a budget
- **WHEN** a request exceeds a ceiling for wall time, attempts, input/output bytes, tokens, cost, or effort
- **THEN** resolution rejects the request before execution

#### Scenario: Provider omits usage
- **WHEN** a provider supplies no token or cost usage
- **THEN** the generic event and summary record the corresponding typed unavailable state and never fabricate a number

### Requirement: Credential minimization and secret-safe evidence
The selected profile/provider combination SHALL receive only its declared provider credential name and any explicitly declared host credential-broker names. Credential values MUST NOT appear in requests, resolved profiles, profile snapshots, events, summaries, metrics, logs, paths, or exception messages, and no rejection path may load unnecessary credentials.

#### Scenario: Select one provider
- **WHEN** an eligible review selects OpenAI or Sakana
- **THEN** the container receives only `OPENAI_API_KEY` or `SAKANA_API_KEY` respectively and never receives the other provider's credential

#### Scenario: Protect credential values
- **WHEN** sentinel provider and broker credential values exist in the process environment during validation, explanation, unimplemented execution, or failed compatibility resolution
- **THEN** no generated artifact or command output contains any sentinel value

### Requirement: Generic provenance and low-cardinality observability
The kernel SHALL emit strict generic run event and summary artifacts containing version, run, mode, profile/hash, provider/model, execution/lifecycle/outcome/disposition, timestamps, duration, budget usage, immutable SHAs, image/CLI identity, output/prompt/capability hashes, secret-leak status, and artifact-export status without hard-coding review-only event types, stages, or verdicts. Metrics MUST exclude run IDs, branch names, SHAs, issue/PR numbers, hashes, error text, and filesystem paths from labels.

#### Scenario: Emit generic review evidence
- **WHEN** a review run completes or fails after the kernel claims execution
- **THEN** one schema-valid generic event and summary describe its provider-neutral state and capability provenance

#### Scenario: Validate metric labels
- **WHEN** deterministic observability fixtures inspect generic metrics
- **THEN** only the documented low-cardinality label set is accepted and any run-specific or free-text label fails validation

### Requirement: PR #1 artifact compatibility
The kernel SHALL keep `make prepr` working and SHALL preserve the existing review directory, review result, legacy runner event/metrics, summary, latest pointer, compatibility mirrors, secret-leak behavior, and evidence readability. Generic CountyForge artifacts SHALL be additive during the migration period.

#### Scenario: Run the legacy contributor command
- **WHEN** a contributor invokes `make prepr`
- **THEN** the command builds the deterministic packet, enters the kernel, dispatches the existing review adapter, and leaves the canonical v1 review evidence readable at its documented paths

#### Scenario: Read historical evidence
- **WHEN** an operator reads a PR #1 review directory that predates the kernel
- **THEN** existing validation and documentation continue to interpret it without requiring generic artifacts

### Requirement: Machine-readable operator CLI
The package SHALL expose `countyforge-runner run`, `validate-request`, `resolve-profile`, `list-profiles`, and `explain` commands with machine-readable JSON output. `explain` MUST report the selected profile, provider, configured model, effective budgets, output schema, allowed capabilities, and execution eligibility without starting a provider call.

#### Scenario: Inspect resolution without execution
- **WHEN** an operator invokes `explain --request <path>` in JSON mode
- **THEN** the command returns the complete resolution and creates no model call, privileged mount, or run evidence

#### Scenario: Receive a structured error
- **WHEN** any command encounters invalid JSON, schema, profile, provider, model, version, effort, budget, schema, or artifact input
- **THEN** it returns non-zero with a stable disposition and sanitized JSON error document

### Requirement: Deterministic acceptance suite
The repository SHALL provide free deterministic Make and CI checks for request/profile/catalog schemas, all five mode resolutions, review adapter dispatch and posture, unimplemented-mode failure, budget and capability expansion rejection, version gates, profile hashing, secret non-disclosure, approved input roots, repository/commit/packet-provenance binding, low-cardinality metrics, legacy compatibility, and unknown JSON property rejection. Paid Sakana and OpenAI provider probes MUST remain explicitly opt-in and outside ordinary CI.

#### Scenario: Validate the kernel in CI
- **WHEN** pull-request CI runs the runner contract suite
- **THEN** all deterministic CountyForge request, profile, catalog, execution, observability, compatibility, and version-gate tests run without Docker, provider credentials, or a paid model call

#### Scenario: Run a live provider probe
- **WHEN** an operator explicitly sets the documented paid-smoke opt-in for a selected provider
- **THEN** the provider-specific smoke path runs under the review profile posture and records that live validation without making paid probes a merge prerequisite
