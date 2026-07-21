## ADDED Requirements

### Requirement: Planning provider and model binding

The runner SHALL execute `plan.read-only.v1` only after validating a strict planning packet and context manifest against the trusted contract root. The adapter MUST receive the resolved logical model reference, configured model identifier, and reasoning effort selected by the profile/provider catalog; image labels and runtime configuration MUST agree with those facts.

#### Scenario: Model and effort are bound to the image

- **WHEN** a planning request resolves `sakana.fugu` with `high` effort
- **THEN** the trusted image build and invocation use that exact model reference and effort, and a mismatch fails before provider credentials are loaded.

### Requirement: Planning read-only profile isolation

The executable planning profile SHALL mount no repository, writable workspace, Git credential, GitHub token, production credential, or model-invokable tool. It MAY write only bounded run evidence and the structured planning result to its claimed output directory.

#### Scenario: Planning output cannot mutate a repository

- **WHEN** the planning model attempts to request a source, workflow, policy, or infrastructure path
- **THEN** strict result validation rejects it and the runner reports a sanitized validation failure without repository mutation.

## MODIFIED Requirements

### Requirement: Fail-closed future profile execution

The `implement`, `fix`, and `validate` profiles SHALL be fully validatable but SHALL have `not_implemented` execution state in this change. The `plan.read-only.v1` profile is the sole exception: it is executable only after strict planning packet and context-manifest validation, provider/model/effort compatibility resolution, and planning-result policy validation. Every attempted unimplemented profile MUST validate and resolve first, emit sanitized request and profile provenance, return a structured `profile_not_implemented` disposition with a non-zero exit status, and stop before loading provider credentials, creating mounts, running containers, or starting deterministic commands.

#### Scenario: Execute the bounded planning profile
- **WHEN** a valid plan request supplies a bound planning packet and context manifest and resolves the implemented `plan.read-only.v1` profile
- **THEN** the kernel may invoke only the profile-specific read-only adapter and reports success only for a schema-valid, policy-safe planning result

#### Scenario: Attempt an unimplemented mode
- **WHEN** a valid request attempts to run the implement, fix, or validate profile
- **THEN** the run emits generic failed summary/event evidence with disposition `profile_not_implemented`, invokes no executor or credential loader, and cannot report success

#### Scenario: Explain an unimplemented mode
- **WHEN** an operator explains a valid future-mode request
- **THEN** the command returns its profile, provider/model when applicable, budgets, output schema, capabilities, and `execution_eligible: false` without creating run evidence or starting execution
