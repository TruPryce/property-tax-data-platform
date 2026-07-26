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
