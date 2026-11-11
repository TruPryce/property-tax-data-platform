# agent-runner-kernel Specification

## Purpose
Define CountyForge run requests, immutable capability profiles, provider and budget binding, isolated execution, and sanitized evidence for review, planning, and implementation.

## Requirements

### Requirement: Strict versioned run requests
The CountyForge kernel SHALL accept a strict versioned JSON run request containing immutable trigger facts, repository base and head SHAs, mode, profile identity, prompt/template identity, provider/model selection, reasoning effort, optional tightening budgets, input context, expected output schema, and requested artifacts. It MUST reject unknown properties, unsupported contract versions, unknown modes, ambiguous refs, undeclared schemas, undeclared artifacts, and mode-specific missing facts before provider execution.

The kernel SHALL retain all accepted request-schema, immutable-reference, profile-compatibility, budget, capability-expansion, output-schema, artifact, and provenance rejection guarantees. For `implement`, the request MUST additionally bind a frozen implementation packet, context manifest, task plan, and isolated workspace to the repository, issue, accepted OpenSpec change, trusted base SHA, and run identity before credentials or an executor are selected. Missing or partial implementation inputs MUST fail closed.

#### Scenario: Reject incomplete implementation context
- **WHEN** an implementation request omits any packet, manifest, task plan, or workspace binding
- **THEN** request resolution fails before provider credential loading or workspace execution

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
The executable profiles SHALL remain independently isolated: `plan.read-only.v1` remains executable under its accepted planning contract, while `fix.targeted-write.v1` and `validate.deterministic.v1` remain fully validatable but not executable in this change and SHALL return structured `profile_not_implemented` evidence without loading credentials or mounts. The `implement.workspace-write.v1` profile is the sole newly executable write-capable profile and MUST validate its packet, manifest, task plan, workspace, path policy, command policy, and repository binding before loading the selected provider credential. It MUST never grant implementation publication authority to the model.

#### Scenario: Execute implementation only with trusted context
- **WHEN** a complete, hash-bound implementation request resolves to the executable implementation profile
- **THEN** the kernel invokes only its declared adapter with the isolated workspace and selected provider credential

#### Scenario: Reject future write profiles
- **WHEN** a fix or validate request is executed
- **THEN** the kernel emits `profile_not_implemented` and performs no provider, mount, or repository mutation

#### Scenario: Execute the bounded planning profile
- **WHEN** a valid plan request supplies a bound planning packet and context manifest and resolves the implemented `plan.read-only.v1` profile
- **THEN** the kernel may invoke only the profile-specific read-only adapter and reports success only for a schema-valid, policy-safe planning result

#### Scenario: Explain an unimplemented mode
- **WHEN** an operator explains a valid future-mode request
- **THEN** the command returns its profile, provider/model when applicable, budgets, output schema, capabilities, and `execution_eligible: false` without creating run evidence or starting execution

### Requirement: Separate mode-result contracts
The repository SHALL maintain distinct strict schemas for review, plan, implementation, fix, and validation results. Each non-review schema MUST encode meaningful mode-specific status, work, decisions, validation, and eligibility fields rather than reusing the review verdict contract.

The repository SHALL maintain distinct strict review, plan, implementation, fix, and validation result schemas. The implementation result MUST report task IDs, changed paths, command evidence, validation claims, deviations, risks, artifact hashes, and a non-authoritative publication-eligibility field; trusted validation remains the only authority to publish.

#### Scenario: Model cannot authorize publication
- **WHEN** an implementation result declares itself publication eligible
- **THEN** trusted result validation rejects the claim and publication remains ineligible

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

### Requirement: Separate trusted contract and immutable target roots
The CountyForge kernel SHALL resolve profiles, schemas, provider catalogs, prompts, adapters, container policy, and run evidence only from an explicit trusted `contract_root`, while validating repository identity, immutable `HEAD`, base ancestry, and packet provenance against an explicit `target_root`. The roots MAY be equal for a local developer invocation, but a GitHub-dispatched run MUST keep them distinct. An executable review MUST revalidate the target and packet binding immediately before selecting a provider credential, and neither a target file nor target configuration may replace a contract-root resource.

#### Scenario: Preserve local single-root compatibility
- **WHEN** a developer invokes the existing local pre-PR path without separate root options
- **THEN** the kernel treats the current repository as both roots and preserves the existing request, security posture, and evidence contract

#### Scenario: Resolve trusted resources separately
- **WHEN** a GitHub run supplies a trusted default-branch tooling checkout as `contract_root` and an immutable target repository as `target_root`
- **THEN** the kernel loads all executable policy from the contract root and validates repository/packet facts against only the target root

#### Scenario: Reject target-root replacement of policy
- **WHEN** the target revision contains modified profiles, schemas, prompts, provider catalogs, adapters, workflow files, package hooks, or runner source
- **THEN** no target version of those files is loaded or executed and the trusted contract-root versions remain authoritative

#### Scenario: Validate a bare immutable target repository
- **WHEN** the provider-execution phase supplies a bare Git repository containing the bound base and head commits without a checked-out worktree
- **THEN** repository identity, exact head, base existence, ancestry, and packet provenance validation succeeds without executing or checking out target content

#### Scenario: Fail closed on root or binding drift
- **WHEN** either root is absent, the trusted resource hash differs, the target repository identity or head differs, the base commit is invalid, or packet provenance disagrees with the target facts
- **THEN** the kernel returns a sanitized structured failure before provider credential selection or executor dispatch

### Requirement: Planning provider and model binding

The runner SHALL execute `plan.read-only.v1` only after validating a strict planning packet and context manifest against the trusted contract root. The adapter MUST receive the resolved logical model reference, configured model identifier, reasoning effort, and provider-generation schema selected by the profile/provider catalog; image labels and runtime configuration MUST agree with those facts. The generation schema MUST use only the provider-compatible structured-output subset and MUST be distinct from the authoritative strict planning-result schema when provider compatibility requires it. The runner MUST bind both schema identities and MUST validate every generated document against the authoritative result schema and planning policy before reporting success.

#### Scenario: Model and effort are bound to the image

- **WHEN** a planning request resolves `sakana.fugu` with `high` effort
- **THEN** the trusted image build and invocation use that exact model reference and effort, and a mismatch fails before provider credentials are loaded.

#### Scenario: Provider generation cannot weaken trusted validation

- **WHEN** the provider returns a document accepted by the generation schema but rejected by the authoritative planning-result schema or planning policy
- **THEN** the runner reports a sanitized validation failure and no materialization or publication begins.

#### Scenario: Provider generation sentinel is distinct

- **WHEN** the provider adapter exits successfully but writes the exact bounded `Error generating response` sentinel instead of JSON
- **THEN** the runner reports `provider_generation_failed`, preserves sanitized evidence, and does not classify the provider failure as malformed planning intent.

### Requirement: Planning read-only profile isolation

The executable planning profile SHALL mount no repository, writable workspace, Git credential, GitHub token, production credential, or model-invokable tool. It MAY write only bounded run evidence and the structured planning result to its claimed output directory.

#### Scenario: Planning output cannot mutate a repository

- **WHEN** the planning model attempts to request a source, workflow, policy, or infrastructure path
- **THEN** strict result validation rejects it and the runner reports a sanitized validation failure without repository mutation.
