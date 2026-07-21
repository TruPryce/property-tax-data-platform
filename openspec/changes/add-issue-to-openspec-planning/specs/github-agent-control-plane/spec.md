## MODIFIED Requirements

### Requirement: Minimal permissions and secrets

The control plane SHALL keep provider and target-preparation jobs read-only. The trusted planning publication job MAY receive `contents: write`, `issues: write`, `pull-requests: write`, and `checks: write` solely to materialize the bounded OpenSpec files on the deterministic planning ref and create or update a draft PR. It MUST receive no provider credential and no untrusted target execution.

#### Scenario: Permission policy remains narrow

- **WHEN** workflow policy validation examines CountyForge jobs
- **THEN** only the trusted planning `publish` job has `contents: write`, and all other jobs reject write permissions.

### Requirement: Two-root trusted execution pipeline

Before any Git data API mutation, the publication job SHALL reread trusted canonical state in the per-target state lane and require the expected run, workflow owner, nonce, `running` lifecycle, and unexpired lease. Cancellation, terminal, stale, ownership, or lease failures MUST prevent branch and PR mutation.

#### Scenario: Cancellation wins before publication

- **WHEN** canonical state is `cancel_requested` or terminal before the publication preflight
- **THEN** publication fails closed without creating a branch, commit, or draft PR and the finalizer records a sanitized failure.

### Requirement: Canonical bot-owned GitHub state

Planning-specific canonical fields SHALL remain optional for legacy review and control-plane state. Readers MUST apply bounded defaults when those fields are absent, and writers MAY add them only for planning runs.

#### Scenario: Legacy state remains readable

- **WHEN** status or reconciliation reads a pre-planning canonical marker without planning metadata
- **THEN** schema validation and status rendering succeed without inventing a branch or PR.

### Requirement: Target concurrency and renewable leases

The publication workflow SHALL run its sanitized canonical finalizer even when materialization, trusted validation, or Git publication fails. It MUST preserve the runner's original terminal disposition when no publication was required and use a publication-failure disposition only when a successful planning result required publication but that path did not complete.

#### Scenario: Validation failure is visible

- **WHEN** trusted OpenSpec validation rejects a generated plan
- **THEN** no Git mutation occurs and canonical state reaches a sanitized terminal failure.
