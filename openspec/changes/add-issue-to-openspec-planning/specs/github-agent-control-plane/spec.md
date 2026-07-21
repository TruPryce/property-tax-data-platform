## ADDED Requirements

### Requirement: Planning publication permission boundary

The control plane SHALL keep provider and target-preparation jobs read-only. The trusted planning publication job MAY receive `contents: write`, `issues: write`, `pull-requests: write`, and `checks: write` solely to materialize the bounded OpenSpec files on the deterministic planning ref and create or update a draft PR. It MUST receive no provider credential and no untrusted target execution.

#### Scenario: Permission policy remains narrow

- **WHEN** workflow policy validation examines CountyForge jobs
- **THEN** only the trusted planning `plan-publish` job has `contents: write`, and all other jobs reject write permissions.

### Requirement: Planning publication lease preflight

Before any Git data API mutation, the publication job SHALL reread trusted canonical state in the per-target state lane and require the expected run, workflow owner, nonce, `running` lifecycle, and unexpired lease. Cancellation, terminal, stale, ownership, or lease failures MUST prevent branch and PR mutation.

#### Scenario: Cancellation wins before publication

- **WHEN** canonical state is `cancel_requested` or terminal before the publication preflight
- **THEN** publication fails closed without creating a branch, commit, or draft PR and the finalizer records a sanitized failure.

### Requirement: Planning metadata compatibility

Planning-specific canonical fields SHALL remain optional for legacy review and control-plane state. Readers MUST apply bounded defaults when those fields are absent, and writers MAY add them only for planning runs.

#### Scenario: Legacy state remains readable

- **WHEN** status or reconciliation reads a pre-planning canonical marker without planning metadata
- **THEN** schema validation and status rendering succeed without inventing a branch or PR.

### Requirement: Planning publication finalization

The publication workflow SHALL run its sanitized canonical finalizer even when materialization, trusted validation, or Git publication fails. It MUST preserve the runner's original terminal disposition when no publication was required and use a publication-failure disposition only when a successful planning result required publication but that path did not complete.

#### Scenario: Validation failure is visible

- **WHEN** trusted OpenSpec validation rejects a generated plan
- **THEN** no Git mutation occurs and canonical state reaches a sanitized terminal failure.

## MODIFIED Requirements

### Requirement: Minimal permissions and secrets

Each workflow job MUST declare least-privilege `GITHUB_TOKEN` permissions and MUST NOT receive `packages: write`, `deployments: write`, `id-token: write`, `security-events: write`, a code-push credential, or a production credential. Intake/control may receive only the issue/PR/check/Actions access required to authorize, dispatch, reconcile, or cancel; packet preparation MUST receive no provider credential; execution MUST receive exactly the selected provider credential at the invocation step; and publication MUST receive no provider credential. The trusted planning `plan-publish` job MAY receive `contents: write`, `issues: write`, `pull-requests: write`, and `checks: write` solely to materialize the bounded OpenSpec files on the deterministic planning ref and create or update a draft PR. The read-only `publish` and `plan-validation` jobs MUST NOT receive `contents: write`.

#### Scenario: Deny secret-bearing preparation
- **WHEN** workflow policy checks inspect packet-preparation jobs
- **THEN** no OpenAI, Sakana, production, or code-push secret is declared or referenced and target content cannot execute

#### Scenario: Select provider secret scope
- **WHEN** a review chooses one provider
- **THEN** workflow policy and execution evidence prove the other provider credential is absent from the invocation environment

#### Scenario: Restrict planning contents write
- **WHEN** workflow policy checks inspect CountyForge jobs
- **THEN** only the trusted planning `plan-publish` job has `contents: write`, and all other jobs reject that permission

#### Scenario: Reject broad workflow permissions
- **WHEN** a workflow adds an undeclared write permission, OIDC, package/deployment/security publication, or a target-derived shell expression
- **THEN** deterministic workflow policy tests fail
