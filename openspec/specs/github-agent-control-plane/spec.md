# github-agent-control-plane Specification

## Purpose
Define authorized GitHub command intake, immutable run identity, trusted execution and publication, concurrency, cancellation, retry, and bounded status evidence for CountyForge.

## Requirements

### Requirement: Strict top-level CountyForge commands
The control plane SHALL accept exactly one bounded top-level ASCII command line in the form `/countyforge <command> [declared arguments]`, where command is one of `plan`, `implement`, `validate`, `review`, `fix`, `status`, `cancel`, or `retry`. It MUST ignore commands inside fenced or inline code, blockquotes, HTML comments, quoted prior comments, and generated status sections; ignore bot-authored comments; reject unknown arguments, Unicode lookalikes, multiple top-level commands, and oversized input; and subscribe only to newly created comments.

#### Scenario: Parse one executable command
- **WHEN** a human-authored created comment contains exactly one standalone `/countyforge review` line outside excluded Markdown regions
- **THEN** the parser emits one schema-valid normalized `review` command without interpreting surrounding prose as instructions

#### Scenario: Ignore inert Markdown and bot comments
- **WHEN** command text appears only in a fence, inline code, blockquote, HTML comment, quoted prior text, canonical status section, or a bot-authored comment
- **THEN** the parser emits an ignored disposition and no authorization, request, or dispatch occurs

#### Scenario: Reject ambiguity and lookalikes
- **WHEN** a comment contains multiple top-level commands, an unknown token, undeclared arguments, an oversized body, or non-ASCII lookalike characters in the command prefix
- **THEN** the parser returns a stable sanitized rejection and executes nothing

#### Scenario: Ignore edited and deleted comments
- **WHEN** GitHub delivers an edited or deleted comment event
- **THEN** no CountyForge workflow path parses or executes it

### Requirement: Permission-based authorization
The control plane MUST resolve the actor's effective repository permission through GitHub before target preparation, runner-request creation, workflow dispatch, cancellation, or provider-secret access. It SHALL allow `admin`, `maintain`, and `write`; deny `triage`, `read`, and `none`; and permit named bot identities or teams only through an exact versioned allow-policy entry. It MUST record actor login, immutable actor ID, actor type, resolved permission, policy version, outcome, and reason code without recording a token.

#### Scenario: Allow a write-capable maintainer
- **WHEN** GitHub resolves a human actor to `write`, `maintain`, or `admin`
- **THEN** authorization succeeds under the versioned policy and immutable actor facts are recorded in sanitized control-plane evidence

#### Scenario: Deny a non-maintainer
- **WHEN** GitHub resolves a human actor to `triage`, `read`, or `none`
- **THEN** authorization returns a concise refusal, creates no runner request or execution check, and starts no target-preparation or secret-bearing job

#### Scenario: Reject self-asserted authority
- **WHEN** an issue author, label, body, comment, linked page, or forged status marker claims a higher permission or bot identity
- **THEN** the claim has no authorization effect

### Requirement: Immutable GitHub trigger envelope
The adapter SHALL construct and strictly validate a versioned trigger envelope containing base-repository ID/full name, target source-repository ID/full name, target type and number, comment ID, created action, delivery identifier when available, actor immutable facts, resolved permission, normalized command and arguments, trusted tool SHA, immutable ancestor merge-base/head SHAs, workflow run ID/attempt, authorization policy version, and timestamp, with display metadata separated from immutable facts. An explicit retry envelope SHALL carry the original semantic key/run ID and incremented attempt. Unknown properties MUST fail validation. The envelope MUST NOT contain tokens, provider keys, environment dumps, complete issue/comment bodies, or target file content.

#### Scenario: Build a pull-request trigger
- **WHEN** an authorized command targets a branch or fork pull request and GitHub resolves its source repository, head, ancestor merge base, and the current trusted default-branch SHA
- **THEN** the adapter emits a schema-valid immutable envelope bound to those exact facts while retaining the base repository as the reviewed repository identity

#### Scenario: Reject mutable trigger facts
- **WHEN** an envelope uses branch names where commit SHAs are required, omits immutable actor/repository identity, or adds undeclared data
- **THEN** validation fails before request creation or dispatch

### Requirement: Two-root trusted execution pipeline
Every command and execution workflow SHALL run trusted default-branch workflow and package code at one immutable trusted tool SHA. Review packet preparation MUST use trusted tooling against a separate immutable target checkout in a job with no provider credential and MUST NOT run target scripts, hooks, tests, Make targets, package installation, workflows, or binaries. Review provider execution MUST consume a bounded frozen packet, validated provenance, and non-worktree target identity; MUST load profiles, schemas, catalogs, prompts, adapters, and kernel code from the trusted contract root; and MUST NOT check out or execute the target worktree.

The control plane SHALL retain the trusted default-branch/tooling root and immutable source-root separation. Implementation additionally creates an ephemeral writable workspace copied from the trusted base; the model may write only there and to a claimed output directory. Trusted profiles, schemas, prompts, policies, adapters, and publication code remain read-only and are never replaced by target or model files.

#### Scenario: Isolate model writes
- **WHEN** an implementation job executes
- **THEN** no GitHub token, Git credential, Docker socket, host home, Tailscale socket, production credential, or writable contract-root mount is available to the model

#### Scenario: Prepare an untrusted pull request without secrets
- **WHEN** an authorized review targets a fork or branch pull request
- **THEN** the preparation job fetches immutable base/head objects, builds the packet with trusted code, validates its provenance, uploads a bounded artifact, and receives no provider credential

#### Scenario: Ignore target-controlled executable files
- **WHEN** a review target changes workflow files, packet scripts, package hooks, tests, Make targets, profiles, schemas, prompts, or runner adapters
- **THEN** those target files are treated only as packet data and none controls or executes in the preparation or provider jobs

#### Scenario: Expose exactly one provider credential
- **WHEN** an eligible review selects OpenAI or Sakana
- **THEN** only the selected `OPENAI_API_KEY` or `SAKANA_API_KEY` is available to the provider invocation step and neither value appears in artifacts, logs, comments, checks, state, metrics, or errors

### Requirement: Semantic idempotency
Execution commands SHALL derive a deterministic SHA-256 idempotency key from canonical versioned facts including repository ID, target type/number, normalized command/arguments, profile ID/version, immutable head SHA, optional OpenSpec change, and control-plane contract version. Comment IDs and delivery IDs SHALL remain provenance only. An identical semantic command on the same head MUST deduplicate; a changed head MUST produce a distinct eligible key; retry MUST derive a new key from the original key and incremented attempt.

#### Scenario: Deduplicate webhook and comment retries
- **WHEN** the same semantic execution command is delivered again with a different delivery ID or comment ID while target head and declared arguments are unchanged
- **THEN** the control plane records a duplicate disposition and dispatches no new run

#### Scenario: Permit a command after head changes
- **WHEN** the same normalized execution command is issued after the immutable target head changes
- **THEN** the new semantic key differs and the command may become eligible subject to authorization and lease policy

### Requirement: Canonical bot-owned GitHub state
The control plane SHALL maintain at most one canonical CountyForge status comment per issue or pull request. Its bounded hidden marker MUST contain canonical, schema-valid, sanitized state and MUST be trusted only when the immutable comment author identity matches the configured trusted bot. State MUST include current run ID, semantic key, command/profile, target SHA, workflow run/attempt, monotonic revision, lifecycle, timestamps, lease, disposition, sanitized evidence link, and check-run ID when present. A new state starts at revision 1; every successful state mutation increments revision exactly once, and every transition MUST supply the expected revision and produce expected revision + 1. The revision is application-level stale-state detection, not an atomic API guarantee. Updates MUST edit the canonical comment rather than create status spam, and terminal evidence MUST remain immutable.

#### Scenario: Update existing canonical status
- **WHEN** a bot-owned schema-valid canonical comment exists for the target
- **THEN** the control plane updates that comment and creates no second status comment

#### Scenario: Ignore a forged marker
- **WHEN** a user-authored comment contains a byte-for-byte valid hidden CountyForge marker
- **THEN** the adapter treats it as untrusted content and neither loads nor mutates its state

#### Scenario: Reject malformed or oversized hidden state
- **WHEN** a bot-owned marker is malformed, contains unknown fields, or exceeds the documented bound
- **THEN** state loading fails closed with a sanitized audit outcome and never executes embedded content

#### Scenario: Reject canonical state for another target
- **WHEN** otherwise valid bot-owned state embeds another repository ID, target type, or issue/pull-request number
- **THEN** state loading fails closed and no duplicate, status, cancellation, retry, check, or dispatch decision uses that state

#### Scenario: Reject a stale state revision
- **WHEN** a writer attempts a transition with a missing, repeated, skipped, or older expected revision
- **THEN** the transition fails closed and the newer canonical state remains unchanged

#### Scenario: Serialize canonical comment updates without conditional writes
- **WHEN** a writer mutates canonical state
- **THEN** it rereads the canonical comment inside the shared per-target state concurrency lane, requires its persisted state to equal the expected predecessor, sends a plain comment update without depending on `If-Match`/`412`, and updates the check only after the comment update succeeds

#### Scenario: Fail closed when a serialized predecessor is stale
- **WHEN** another writer commits a newer canonical state before this writer's reread completes
- **THEN** the reread no longer equals the expected predecessor, the writer fails closed with `state_write_conflict`, and the newer state is never overwritten

### Requirement: Explicit lifecycle state machine
The adapter SHALL enforce versioned legal transitions among `received`, `authorized`, `deduplicated`, `queued`, `preparing`, `running`, `succeeded`, `failed`, `cancel_requested`, `cancelled`, `timed_out`, `stale`, and `not_implemented`. It MUST reject illegal transitions, MUST NOT report success for a failed or unavailable executor, and MUST treat a completed run as immutable except for display reconciliation.

#### Scenario: Advance a normal review lifecycle
- **WHEN** an authorized review is dispatched, prepared, executed, and published successfully
- **THEN** each state transition is legal, timestamped, auditable, and terminates at `succeeded`

#### Scenario: Reject terminal mutation
- **WHEN** an operation attempts to transition a completed `succeeded`, `failed`, `cancelled`, `timed_out`, `stale`, or `not_implemented` run back to an active state
- **THEN** the transition fails and prior evidence remains unchanged

### Requirement: Target concurrency and renewable leases
The workflows SHALL serialize short control decisions and target execution separately using repository/target-keyed concurrency groups with ordinary automatic cancellation disabled. Because GitHub does not honor conditional (`If-Match`/`412`) writes on the issue-comment update endpoint, canonical state mutations SHALL be serialized by a shared per-target `countyforge-state-<repository-id>-<target-type>-<target-number>` job concurrency lane that contains only the state transaction; target preparation, image build, provider execution, and artifact upload MUST run outside that lane so cancellation and status stay responsive. A monotonic revision advanced exactly once per successful mutation SHALL provide application-level stale-state detection, and a reread whose predecessor no longer matches MUST fail closed rather than overwrite newer state. State SHALL include a lease with owner workflow run/attempt, semantic key, command, target SHA, acquisition/heartbeat/expiry timestamps, and ownership nonce. Stage transitions SHALL refresh the heartbeat. Only one contender may acquire or reclaim a lease, an unexpired lease MUST block another execution, and expiry recovery MUST mark abandoned work stale without overwriting completed evidence. A queued state that has neither a workflow owner nor a lease MUST have a bounded preclaim deadline and become a retryable terminal failure when that deadline passes.

Any canonical publication, including a terminal one, SHALL require a live lease: once the lease has expired the owning workflow MUST fail closed rather than publish. An expired lease therefore means no owner writer remains, and recovery of an expired run is performed by the `stale` reclamation path inside the per-target state lane. Scheduled maintenance MAY discover and report expired candidates, but MUST NOT mutate canonical comments from its repository-wide lane. This preserves the completed-evidence invariant while canonical writes use plain reread/compare/PATCH without an atomic comment primitive.

#### Scenario: Elect one lease winner
- **WHEN** two authorized execution commands race for the same repository target
- **THEN** control serialization and compare-before-transition rules allow exactly one active lease and at most one execution dispatch

#### Scenario: Reclaim expired work
- **WHEN** an active run's lease is expired and no terminal state exists
- **THEN** an authorized command or `/countyforge status` atomically marks it stale inside the target state lane and preserves all prior evidence; scheduled maintenance may only report the candidate

#### Scenario: Refuse a post-expiry owner publication
- **WHEN** an owning execution workflow attempts to publish a stage or terminal result after its lease has expired
- **THEN** the publication fails closed on the expired lease and cannot overwrite a concurrent stale reclamation or any completed evidence

#### Scenario: Recover failure before lease claim
- **WHEN** the dispatched execution workflow fails before it can acquire the queued run's lease
- **THEN** a no-secret recovery job marks that exact bot-owned queued run failed so it is visible and retryable rather than permanently active

#### Scenario: Recover an accepted dispatch that never starts
- **WHEN** a queued run still has no workflow owner or lease after its preclaim deadline
- **THEN** status or a later authorized command atomically marks it failed with a stable timeout disposition and concludes its existing check; scheduled maintenance only reports the candidate

#### Scenario: Preserve completed evidence
- **WHEN** maintenance encounters a terminal run whose former lease time is expired
- **THEN** it does not reclaim, mutate, or overwrite the completed run or artifacts

### Requirement: Eligible profile dispatch
The control plane SHALL map `review` to `review.packet-only.v1`, `plan` to `plan.read-only.v1`, `implement` to `implement.workspace-write.v1`, `fix` to `fix.targeted-write.v1`, and `validate` to `validate.deterministic.v1`. It MUST construct the strict mode-specific runner request and invoke the kernel without adding capabilities or bypassing implementation state. `status`, `cancel`, and `retry` are control operations and MUST NOT be sent as runner modes.

The control plane SHALL preserve the existing authorization, immutable trigger, semantic idempotency, lease, state-lane, cancellation, retry, and sanitized-publication guarantees while mapping `implement` to `implement.workspace-write.v1`. An implementation command MUST target only its originating issue, name an exact accepted OpenSpec change, and pass the trusted merged-planning-PR eligibility gate before dispatch. The model job receives no GitHub write permission; only the short trusted publication job may create an implementation branch or draft PR.

#### Scenario: Dispatch an eligible implementation
- **WHEN** an authorized maintainer requests an exact accepted change whose planning PR is merged by an authorized maintainer and whose trusted OpenSpec facts validate
- **THEN** the control plane dispatches the implementation profile with no publication capability and records the immutable eligibility evidence

#### Scenario: Refuse an unapproved implementation
- **WHEN** the change is absent from trusted main, planning approval is only a draft/label/reaction, traceability is missing, or blocking decisions remain
- **THEN** the command returns a sanitized ineligible disposition before provider access or workspace creation

#### Scenario: Execute packet-only review
- **WHEN** an authorized review command resolves an eligible immutable target and declared provider/model
- **THEN** the control plane dispatches only `review.packet-only.v1` through the trusted kernel and preserves its no-repository-mount posture

### Requirement: Safe status reconciliation
`/countyforge status` SHALL require authorization, load only canonical bot-owned state for the same repository target, reconcile it with bounded workflow/check facts, update the canonical comment, and start no runner or model call. If no valid state exists, it MUST safely report that no CountyForge run was found without disclosing internal paths, permissions, topology, logs, or secrets.

#### Scenario: Reconcile an active run
- **WHEN** an authorized status command finds a valid active run and matching workflow/check facts
- **THEN** the control plane updates display state and heartbeat conclusions without dispatching agent work

#### Scenario: Preserve cancellation while GitHub is still stopping work
- **WHEN** canonical state is `cancel_requested` and the owned workflow remains queued or in progress
- **THEN** status preserves `cancel_requested` until a terminal workflow fact justifies a legal terminal transition

#### Scenario: Report no run safely
- **WHEN** no valid bot-owned state exists for the target
- **THEN** status returns a concise no-run response and performs no model, cancellation, or artifact operation

#### Scenario: Recover when mutable pull-request facts are unavailable
- **WHEN** an authorized status or cancel operation targets an existing canonical run after its fork branch or compare facts become unavailable
- **THEN** the operation uses stable repository/target identity plus canonical workflow ownership and does not require mutable PR head resolution

### Requirement: Target-bound idempotent cancellation
`/countyforge cancel` SHALL require authorization, identify an active run from canonical state, verify repository and target ownership plus the exact CountyForge workflow run identity, transition to `cancel_requested`, and call the GitHub Actions cancellation API. Repeated cancellation MUST be idempotent and MUST NOT cancel an unrelated target or workflow. Reconciliation SHALL later resolve the run to `cancelled`, `failed`, or `succeeded`; kernel wall-clock budgets remain independently enforced.

#### Scenario: Cancel the active target run
- **WHEN** an authorized cancel command references a canonical active run whose workflow belongs to the same repository and target
- **THEN** the adapter records `cancel_requested` and requests cancellation of only that workflow run

#### Scenario: Reject cross-target cancellation
- **WHEN** canonical or supplied workflow facts identify another repository, issue, pull request, semantic key, or non-CountyForge workflow
- **THEN** cancellation fails closed and no Actions cancellation request is sent

#### Scenario: Repeat cancellation
- **WHEN** an authorized actor repeats cancel after `cancel_requested` or `cancelled`
- **THEN** the operation returns the existing disposition without issuing an unrelated or duplicate destructive action

### Requirement: Immutable retry attempts
`/countyforge retry` SHALL require authorization, select the latest retry-eligible terminal run, preserve its trigger provenance and evidence, increment attempt, create a new run ID and retry-derived semantic key, and require the current target head SHA to equal the original head. Initial planning intake and packet construction MUST bound the discussion fingerprint at the immutable plan-command comment ID. The retry envelope MUST retain that original trigger-comment ID in addition to the original semantic key, run ID, and incremented attempt. It MUST reject active, successful, or stale-head retry unless a later accepted policy explicitly permits it, and it MUST never mutate or overwrite the original run. A current planning retry SHALL restore the stored planning-context fingerprint and rebuild the same selected bounded discussion from comments whose immutable IDs are at or before the original trigger-comment ID; the retry command, later comments, and older pre-cutoff comments outside the selected window MUST NOT alter that frozen context. Edits or deletion within the issue evidence or selected original comment window MUST still fail closed with `planning_context_mismatch`. A schema-valid legacy planning run without a context fingerprint SHALL retain its legacy identity and remain retryable. Every new implementation run SHALL store the accepted-change hash and a SHA-256 fingerprint of exactly `planning_pr_number`, `planning_pr_merge_sha`, `approval_actor_id`, `approval_actor_type`, `approval_actor_login`, and `approval_permission`. Before dispatching an implementation retry, the control plane MUST re-resolve those approval facts from GitHub, rerun implementation eligibility, require the current accepted-change hash and complete approval fingerprint to equal the stored values, and attach the freshly resolved bounded approval envelope to the retry trigger.

#### Scenario: Retry a failed unchanged target
- **WHEN** an authorized retry targets the latest failed, cancelled, timed-out, stale, or not-implemented run and the immutable head is unchanged
- **THEN** a new attempt with a new run ID/key may be queued while the original state/evidence remains preserved

#### Scenario: Preserve current and legacy planning identity
- **WHEN** an authorized planning retry targets an unchanged head
- **THEN** the retry restores the stored planning-context fingerprint and original trigger-comment cutoff when present, excludes the retry command and later discussion from packet reconstruction, or reconstructs the original legacy semantic identity when that optional fingerprint is absent

#### Scenario: Freeze original planning discussion
- **WHEN** a higher-ID comment is visible while an original plan command is accepted or its packet is prepared
- **THEN** both stages exclude that post-command comment and derive the same planning-context fingerprint used by a later retry

#### Scenario: Refuse mutation inside frozen planning context
- **WHEN** issue evidence or a comment selected into the original bounded window changes or disappears before retry packet construction
- **THEN** packet construction fails closed with `planning_context_mismatch` before provider access

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

### Requirement: Sanitized status comments and checks
The canonical status comment SHALL display only command, profile, abbreviated target SHA, current state, bounded timestamps, sanitized workflow/check/evidence links, outcome, and applicable retry/cancel guidance. For pull-request executable commands, the control plane SHALL create one `CountyForge / <command>` check using the semantic key as external identity and map queued/running to in-progress, succeeded to success, failed to failure, cancelled to cancelled, timed out to timed_out, and not implemented to neutral. A review MUST NOT reach succeeded unless result evidence is valid JSON and its separately captured runner exit code is present and zero. Unauthorized or ignored commands MUST create no execution check. Raw model output, logs, secrets, internal paths, and untrusted HTML MUST NOT appear.

#### Scenario: Publish a successful review check
- **WHEN** a pull-request review succeeds with sanitized GitHub evidence
- **THEN** its single check concludes success and links only to that evidence while the canonical comment reports the same outcome

#### Scenario: Reject inconsistent runner result evidence
- **WHEN** review result JSON is missing or malformed, its captured exit code is absent or nonzero, or a completed disposition conflicts with that exit code
- **THEN** publication records a stable sanitized failure and never reports the run or check as successful

#### Scenario: Publish an unavailable future mode
- **WHEN** a future profile returns `profile_not_implemented`
- **THEN** the check concludes neutral and the comment states not implemented without reporting success

### Requirement: Minimal permissions and secrets

Each workflow job MUST declare least-privilege `GITHUB_TOKEN` permissions and MUST NOT receive `packages: write`, `deployments: write`, `id-token: write`, `security-events: write`, a code-push credential, or a production credential. Intake/control may receive only the issue/PR/check/Actions access required to authorize, dispatch, reconcile, or cancel; packet preparation MUST receive no provider credential; execution MUST receive exactly the selected provider credential at the invocation step; and publication MUST receive no provider credential. The trusted planning `plan-publish` job MAY receive `contents: write`, `issues: write`, `pull-requests: write`, and `checks: write` solely to materialize the bounded OpenSpec files on the deterministic planning ref and create or update a draft PR. The read-only `publish` and `plan-validation` jobs MUST NOT receive `contents: write`.

Every workflow job SHALL retain least-privilege permissions. Packet preparation and validation receive no provider credential; the implementation model job receives only the selected provider credential and read-only GitHub/Actions access; within implementation jobs, only the trusted implementation publication job may receive `contents: write`, pull-request/issue/check writes, and Actions read access. No provider credential reaches validation or publication.

#### Scenario: Keep code publication trusted
- **WHEN** workflow policy inspects implementation jobs
- **THEN** only the dedicated publication job has code-write permission and the model job cannot publish a branch, commit, or PR

#### Scenario: Deny secret-bearing preparation
- **WHEN** workflow policy checks inspect packet-preparation jobs
- **THEN** no OpenAI, Sakana, production, or code-push secret is declared or referenced and target content cannot execute

#### Scenario: Select provider secret scope
- **WHEN** a review chooses one provider
- **THEN** workflow policy and execution evidence prove the other provider credential is absent from the invocation environment

#### Scenario: Restrict planning contents write
- **WHEN** workflow policy checks inspect CountyForge jobs
- **THEN** only the trusted planning and implementation publication jobs may receive `contents: write`, and all other jobs reject that permission

#### Scenario: Reject broad workflow permissions
- **WHEN** a workflow adds an undeclared write permission, OIDC, package/deployment/security publication, or a target-derived shell expression
- **THEN** deterministic workflow policy tests fail

### Requirement: Sanitized control-plane observability
The adapter SHALL emit bounded structured events for command received, authorization allowed/denied, duplicate detected, lease acquired/reclaimed/released, workflow dispatched, cancellation requested, retry started, state reconciled, invalid maintenance state detected, and terminal outcome. Metrics MAY label command, target type, authorization outcome, state, outcome, and disposition, but MUST NOT label actor, target number, comment/workflow ID, SHA, idempotency key, error text, repository path, or another high-cardinality value.

#### Scenario: Emit an authorization denial
- **WHEN** a command is denied
- **THEN** a sanitized event records the closed outcome and reason code without a token, permission topology, actor metric label, request artifact, or provider job

#### Scenario: Reject high-cardinality metrics
- **WHEN** a metric includes a run-specific identifier, SHA, actor, target number, key, error text, or path as a label
- **THEN** the deterministic observability validator fails

### Requirement: Machine-readable adapter commands and fakeable API ports
The `countyforge-github` package SHALL expose stable JSON CLI commands for command parsing, authorization, trigger construction, idempotency calculation, state transition, status rendering, runner-request construction, and reconciliation. Errors MUST use stable non-zero exit codes and sanitized JSON. GitHub API access MUST be behind typed ports so deterministic tests use fakes and ordinary CI makes no live mutation or paid provider call.

#### Scenario: Build a request locally
- **WHEN** a valid authorized trigger is supplied to the request builder
- **THEN** it emits the exact profile-specific strict CountyForge request without contacting GitHub or a provider

#### Scenario: Exercise control operations with fakes
- **WHEN** tests simulate comments, permissions, workflow runs, checks, cancellation, retries, and races through an in-memory GitHub port
- **THEN** all policy and state decisions execute deterministically without a live GitHub mutation or secret

### Requirement: Deterministic control-plane acceptance suite
The repository SHALL run no-cost CI and Make targets covering schemas, malicious Markdown, all permissions, bot recursion, created-only events, duplicate delivery and semantic deduplication, head changes, forged markers, two-root trust, target non-execution, provider-secret scoping, job permissions, cancel ownership, stale-head retry, lease and no-lease recovery, check-initialization failure, malformed/nonzero runner evidence, terminal evidence immutability, comment reuse, hidden-state bounds, sanitization, low-cardinality metrics, future-mode failure, and legacy runner compatibility. Paid provider execution MUST remain explicitly opt-in.

#### Scenario: Run pull-request CI
- **WHEN** ordinary pull-request CI runs the CountyForge control-plane targets
- **THEN** the entire deterministic suite completes without provider credentials, target code execution, GitHub mutations, Docker, or paid model calls

#### Scenario: Opt into a live review
- **WHEN** an authorized operator explicitly invokes a configured review command after the workflows exist on the default branch
- **THEN** the trusted workflow may use the selected provider credential under the review profile and records whether the live probe ran

### Requirement: Planning publication permission boundary

The control plane SHALL keep provider and target-preparation jobs read-only. The trusted planning publication job MAY receive `contents: write`, `issues: write`, `pull-requests: write`, and `checks: write` solely to materialize the bounded OpenSpec files on the deterministic planning ref and create or update a draft PR. It MUST receive no provider credential and no untrusted target execution.

#### Scenario: Permission policy remains narrow

- **WHEN** workflow policy validation examines CountyForge planning jobs
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

### Requirement: Live default-branch freshness in canonical status

Whenever canonical state is rendered or reconciled, the control plane SHALL resolve the repository's default branch and its current head SHA through the trusted GitHub port, and SHALL display the target SHA, the default branch name, the current default-branch SHA, retry eligibility, and the instant the default branch was checked. Retry eligibility MUST be true only when the lifecycle state is retryable and the current default-branch SHA exactly equals the recorded target head SHA; a target whose retry comparand is not the default branch, and an unresolved lookup, MUST report unknown rather than guessing. The resolved value is display and reconciliation metadata only: it MUST NOT be persisted into canonical state, MUST NOT participate in semantic run identity or the canonical marker, and MUST NOT authorize execution. `/countyforge retry` SHALL continue to resolve the live target independently and compare it itself. Freshness SHALL be refreshed only by writers inside the target's canonical concurrency lane, using the ordinary expected-state write path, and the displayed observation instant MUST come from the current operation rather than from persisted lifecycle state. Guidance offered when a retry is ineligible MUST name a command that can be issued as written, including the recorded OpenSpec change for an implementation run. A canonical write MUST publish the rendered display whenever it differs from the published one, including when canonical state is unchanged, so `/countyforge status` on a settled run renews the observation as well as the verdict. Repository-wide scheduled maintenance MUST NOT patch canonical comments, because it cannot join a target's lane and GitHub offers no conditional comment write, so any such patch could revert a newly claimed run to an older marker.

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

#### Scenario: Renew the observation on demand
- **WHEN** `/countyforge status` runs again against an unchanged terminal run whose default branch has not moved
- **THEN** only the displayed observation instant changes, and the hidden marker stays byte-identical

#### Scenario: Keep repository-wide maintenance out of canonical comments
- **WHEN** the scheduled sweep encounters a canonical comment whose display is stale
- **THEN** it records discovery only and sends no comment update, because an out-of-lane patch could revert a run claimed between its read and its write
