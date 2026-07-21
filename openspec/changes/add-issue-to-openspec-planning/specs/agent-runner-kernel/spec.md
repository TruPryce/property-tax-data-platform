## MODIFIED Requirements

### Requirement: Provider and model catalog compatibility

The runner SHALL execute `plan.read-only.v1` only after validating a strict planning packet and context manifest against the trusted contract root. The adapter MUST receive the resolved logical model reference, configured model identifier, and reasoning effort selected by the profile/provider catalog; image labels and runtime configuration MUST agree with those facts.

#### Scenario: Model and effort are bound to the image

- **WHEN** a planning request resolves `sakana.fugu` with `high` effort
- **THEN** the trusted image build and invocation use that exact model reference and effort, and a mismatch fails before provider credentials are loaded.

### Requirement: Mode and capability isolation

The executable planning profile SHALL mount no repository, writable workspace, Git credential, GitHub token, production credential, or model-invokable tool. It MAY write only bounded run evidence and the structured planning result to its claimed output directory.

#### Scenario: Planning output cannot mutate a repository

- **WHEN** the planning model attempts to request a source, workflow, policy, or infrastructure path
- **THEN** strict result validation rejects it and the runner reports a sanitized validation failure without repository mutation.
