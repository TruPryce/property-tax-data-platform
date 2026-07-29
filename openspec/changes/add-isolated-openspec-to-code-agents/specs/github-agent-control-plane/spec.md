## MODIFIED Requirements

### Requirement: Eligible profile dispatch
The control plane SHALL preserve the existing authorization, immutable trigger, semantic idempotency, lease, state-lane, cancellation, retry, and sanitized-publication guarantees while mapping `implement` to `implement.workspace-write.v1`. An implementation command MUST target only its originating issue, name an exact accepted OpenSpec change, and pass the trusted merged-planning-PR eligibility gate before dispatch. The model job receives no GitHub write permission; only the short trusted publication job may create an implementation branch or draft PR.

#### Scenario: Dispatch an eligible implementation
- **WHEN** an authorized maintainer requests an exact accepted change whose planning PR is merged by an authorized maintainer and whose trusted OpenSpec facts validate
- **THEN** the control plane dispatches the implementation profile with no publication capability and records the immutable eligibility evidence

#### Scenario: Refuse an unapproved implementation
- **WHEN** the change is absent from trusted main, planning approval is only a draft/label/reaction, traceability is missing, or blocking decisions remain
- **THEN** the command returns a sanitized ineligible disposition before provider access or workspace creation

### Requirement: Two-root trusted execution pipeline
The control plane SHALL retain the trusted default-branch/tooling root and immutable source-root separation. Implementation additionally creates an ephemeral writable workspace copied from the trusted base; the model may write only there and to a claimed output directory. Trusted profiles, schemas, prompts, policies, adapters, and publication code remain read-only and are never replaced by target or model files.

#### Scenario: Isolate model writes
- **WHEN** an implementation job executes
- **THEN** no GitHub token, Git credential, Docker socket, host home, Tailscale socket, production credential, or writable contract-root mount is available to the model

### Requirement: Minimal permissions and secrets
Every workflow job SHALL retain least-privilege permissions. Packet preparation and validation receive no provider credential; the implementation model job receives only the selected provider credential and read-only GitHub/Actions access; the trusted implementation publication job alone may receive `contents: write`, pull-request/issue/check writes, and Actions read access. No provider credential reaches validation or publication.

#### Scenario: Keep code publication trusted
- **WHEN** workflow policy inspects implementation jobs
- **THEN** only the dedicated publication job has code-write permission and the model job cannot publish a branch, commit, or PR

### Requirement: Immutable retry attempts
`/countyforge retry` SHALL require authorization, select the latest retry-eligible terminal run, preserve its trigger provenance and evidence, increment attempt, create a new run ID and retry-derived semantic key, and require the current target head SHA to equal the original head. It MUST reject active, successful, or stale-head retry unless a later accepted policy explicitly permits it, and it MUST never mutate or overwrite the original run. A current planning retry SHALL restore the stored planning-context fingerprint before reconstructing the original semantic identity; a schema-valid legacy planning run without that fingerprint SHALL retain its legacy identity and remain retryable. Every new implementation run SHALL store the accepted-change hash and a SHA-256 fingerprint of exactly `planning_pr_number`, `planning_pr_merge_sha`, `approval_actor_id`, `approval_actor_type`, `approval_actor_login`, and `approval_permission`. Before dispatching an implementation retry, the control plane MUST re-resolve those approval facts from GitHub, rerun implementation eligibility, require the current accepted-change hash and complete approval fingerprint to equal the stored values, and attach the freshly resolved bounded approval envelope to the retry trigger.

#### Scenario: Retry a failed unchanged target
- **WHEN** an authorized retry targets the latest failed, cancelled, timed-out, stale, or not-implemented run and the immutable head is unchanged
- **THEN** a new attempt with a new run ID/key may be queued while the original state/evidence remains preserved

#### Scenario: Preserve current and legacy planning identity
- **WHEN** an authorized planning retry targets an unchanged head
- **THEN** the retry restores the stored planning-context fingerprint when present, or reconstructs the original legacy semantic identity when that optional fingerprint is absent

#### Scenario: Revalidate an implementation retry
- **WHEN** an authorized implementation retry has complete stored change and approval fingerprints and the freshly resolved approval remains eligible and byte-equivalent across all six bounded facts
- **THEN** the retry trigger carries the fresh approval envelope and the original accepted-change hash before implementation-packet construction

#### Scenario: Refuse missing implementation retry provenance
- **WHEN** a legacy implementation state lacks the accepted-change hash, change name, or approval fingerprint
- **THEN** retry is refused with `implementation_retry_provenance_missing`, no run is dispatched, and the operator is instructed to issue a new implement command

#### Scenario: Refuse changed implementation provenance
- **WHEN** the accepted-change hash differs, any one of the six approval facts differs, the merged approval disappears, or current implementation eligibility fails
- **THEN** retry is refused before dispatch with `implementation_change_changed`, `implementation_approval_changed`, `planning_pr_approval_not_found`, or `implementation_ineligible` as applicable

#### Scenario: Refuse stale-head retry
- **WHEN** the target head differs from the original run's head
- **THEN** retry is refused with an instruction to issue a new execution command and no run is dispatched

#### Scenario: Refuse active or successful retry
- **WHEN** the latest run is active or succeeded
- **THEN** retry fails closed and does not create a new attempt
