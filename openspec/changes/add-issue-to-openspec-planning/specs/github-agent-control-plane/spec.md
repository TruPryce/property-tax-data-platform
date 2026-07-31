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

### Requirement: Live default-branch freshness in canonical status

Whenever canonical state is rendered or reconciled, the control plane SHALL resolve the repository's default branch and its current head SHA through the trusted GitHub port, and SHALL display the target SHA, the default branch name, the current default-branch SHA, retry eligibility, and the instant the default branch was checked. Retry eligibility MUST be true only when the lifecycle state is retryable and the current default-branch SHA exactly equals the recorded target head SHA; a target whose retry comparand is not the default branch, and an unresolved lookup, MUST report unknown rather than guessing. The resolved value is display and reconciliation metadata only: it MUST NOT be persisted into canonical state, MUST NOT participate in semantic run identity or the canonical marker, and MUST NOT authorize execution. `/countyforge retry` SHALL continue to resolve the live target independently and compare it itself. Freshness SHALL be refreshed only by writers inside the target's canonical concurrency lane, using the ordinary expected-state write path, and the displayed observation instant MUST come from the current operation rather than from persisted lifecycle state. Guidance offered when a retry is ineligible MUST name a command that can be issued as written, including the recorded OpenSpec change for an implementation run. A canonical write MUST publish a corrected display even when canonical state is unchanged, so `/countyforge status` on a settled run reports a currently observed verdict; it MUST NOT write when the branch, its SHA, and eligibility are all unchanged. Repository-wide scheduled maintenance MUST NOT patch canonical comments, because it cannot join a target's lane and GitHub offers no conditional comment write, so any such patch could revert a newly claimed run to an older marker.

#### Scenario: Report a retryable run whose default branch has not moved
- **WHEN** canonical status is rendered for a retryable issue-target run and the default-branch head still equals its target SHA
- **THEN** the comment reports the default branch, its current SHA, a checked timestamp, and retry eligibility true

#### Scenario: Report a run the default branch has outrun
- **WHEN** the default-branch head no longer equals the recorded target SHA
- **THEN** retry eligibility is false and the guidance directs the maintainer to a new execution command instead of a retry

#### Scenario: Degrade an unavailable lookup
- **WHEN** the default branch or its head SHA cannot be resolved through the trusted port
- **THEN** canonical status still publishes, the fields render as unavailable, and retry eligibility reports unknown rather than a stale value

#### Scenario: Refuse a retry the display appears to permit
- **WHEN** a displayed default-branch SHA is stale and a retry is issued against a target whose live head has since changed
- **THEN** retry resolves the live target itself and is refused, because the rendered value never authorizes execution

#### Scenario: Correct a stale display on an unchanged run
- **WHEN** `/countyforge status` reconciles a settled run to the same canonical state and the default branch has moved since it ran
- **THEN** the in-lane writer publishes the corrected eligibility against the expected predecessor, the marker still encodes the unchanged state, and no second status comment is created

#### Scenario: Stamp the observation with the operation that made it
- **WHEN** a settled run whose recorded update time is old is rendered during a later operation
- **THEN** the displayed observation instant is that operation's, so a freshly resolved SHA is never labelled with when the run finished

#### Scenario: Offer only a command that can be issued as written
- **WHEN** guidance replaces an ineligible retry for an implementation run
- **THEN** it names the recorded OpenSpec change, or describes the command generically, and never emits a bare `/countyforge implement`

#### Scenario: Refuse a write that would only restamp the observation
- **WHEN** an in-lane writer re-renders a display whose branch, SHA, and eligibility are all unchanged
- **THEN** no comment update is sent

#### Scenario: Keep repository-wide maintenance out of canonical comments
- **WHEN** the scheduled sweep encounters a canonical comment whose display is stale
- **THEN** it records discovery only and sends no comment update, because an out-of-lane patch could revert a run claimed between its read and its write

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
