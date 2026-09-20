## MODIFIED Requirements

### Requirement: Strict versioned run requests
The kernel SHALL retain all accepted request-schema, immutable-reference, profile-compatibility, budget, capability-expansion, output-schema, artifact, and provenance rejection guarantees. For `implement`, the request MUST additionally bind a frozen implementation packet, context manifest, task plan, and isolated workspace to the repository, issue, accepted OpenSpec change, trusted base SHA, and run identity before credentials or an executor are selected. Missing or partial implementation inputs MUST fail closed.

#### Scenario: Reject incomplete implementation context
- **WHEN** an implementation request omits any packet, manifest, task plan, or workspace binding
- **THEN** request resolution fails before provider credential loading or workspace execution

### Requirement: Fail-closed future profile execution
The executable profiles SHALL remain independently isolated: `plan.read-only.v1` remains executable under its accepted planning contract, while `fix.targeted-write.v1` and `validate.deterministic.v1` remain fully validatable but not executable in this change and SHALL return structured `profile_not_implemented` evidence without loading credentials or mounts. The `implement.workspace-write.v1` profile is the sole newly executable write-capable profile and MUST validate its packet, manifest, task plan, workspace, path policy, command policy, and repository binding before loading the selected provider credential. It MUST never grant implementation publication authority to the model.

#### Scenario: Execute implementation only with trusted context
- **WHEN** a complete, hash-bound implementation request resolves to the executable implementation profile
- **THEN** the kernel invokes only its declared adapter with the isolated workspace and selected provider credential

#### Scenario: Reject future write profiles
- **WHEN** a fix or validate request is executed
- **THEN** the kernel emits `profile_not_implemented` and performs no provider, mount, or repository mutation

### Requirement: Separate mode-result contracts
The repository SHALL maintain distinct strict review, plan, implementation, fix, and validation result schemas. The implementation result MUST report task IDs, changed paths, command evidence, validation claims, deviations, risks, artifact hashes, and a non-authoritative publication-eligibility field; trusted validation remains the only authority to publish.

#### Scenario: Model cannot authorize publication
- **WHEN** an implementation result declares itself publication eligible
- **THEN** trusted result validation rejects the claim and publication remains ineligible
