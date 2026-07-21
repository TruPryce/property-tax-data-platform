## ADDED Requirements

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
Every command and execution workflow SHALL run trusted default-branch workflow and package code at one immutable trusted tool SHA. Review packet preparation MUST use trusted tooling against a separate immutable target checkout in a job with no provider credential and MUST NOT run target scripts, hooks, tests, Make targets, package installation, workflows, or binaries. Provider execution MUST consume a bounded frozen packet, validated provenance, and non-worktree target identity; MUST load profiles, schemas, catalogs, prompts, adapters, and kernel code from the trusted contract root; and MUST NOT check out or execute the target worktree.

#### Scenario: Prepare an untrusted pull request without secrets
- **WHEN** an authorized review targets a fork or branch pull request
- **THEN** the preparation job fetches immutable base/head objects, builds the packet with trusted code, validates its provenance, uploads a bounded artifact, and receives no provider credential

#### Scenario: Ignore target-controlled executable files
- **WHEN** the target changes workflow files, packet scripts, package hooks, tests, Make targets, profiles, schemas, prompts, or runner adapters
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

#### Scenario: Execute packet-only review
- **WHEN** an authorized review command resolves an eligible immutable target and declared provider/model
- **THEN** the control plane dispatches only `review.packet-only.v1` through the trusted kernel and preserves its no-repository-mount posture

#### Scenario: Fail closed for future modes
- **WHEN** an authorized plan, implement, fix, or validate command reaches the kernel
- **THEN** the kernel returns `profile_not_implemented`, no provider credential or privileged mount is loaded, no repository change occurs, and status/check publication records neutral `not_implemented`

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
`/countyforge retry` SHALL require authorization, select the latest retry-eligible terminal run, preserve its trigger provenance and evidence, increment attempt, create a new run ID and retry-derived semantic key, and require the current target head SHA to equal the original head. It MUST reject active, successful, or stale-head retry unless a later accepted policy explicitly permits it, and it MUST never mutate or overwrite the original run.

#### Scenario: Retry a failed unchanged target
- **WHEN** an authorized retry targets the latest failed, cancelled, timed-out, stale, or not-implemented run and the immutable head is unchanged
- **THEN** a new attempt with a new run ID/key may be queued while the original state/evidence remains preserved

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
Each workflow job MUST declare least-privilege `GITHUB_TOKEN` permissions and MUST NOT receive `contents: write`, `packages: write`, `deployments: write`, `id-token: write`, `security-events: write`, a code-push credential, or a production credential. Intake/control may receive only the issue/PR/check/Actions access required to authorize, dispatch, reconcile, or cancel; packet preparation MUST receive no provider credential; execution MUST receive exactly the selected provider credential at the invocation step; and publication MUST receive no provider credential.

#### Scenario: Deny secret-bearing preparation
- **WHEN** workflow policy checks inspect packet-preparation jobs
- **THEN** no OpenAI, Sakana, production, or code-push secret is declared or referenced and target content cannot execute

#### Scenario: Select provider secret scope
- **WHEN** a review chooses one provider
- **THEN** workflow policy and execution evidence prove the other provider credential is absent from the invocation environment

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
