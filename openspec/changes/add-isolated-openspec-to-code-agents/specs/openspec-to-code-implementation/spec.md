## ADDED Requirements

### Requirement: Accepted-plan implementation eligibility
The control plane SHALL allow `implement <change>` only when the exact change exists and validates on the trusted default branch, identifies the originating issue, has no unresolved blocking decisions, and its planning PR was merged by an authorized human maintainer whose immutable GitHub actor type is `User`. The request MUST bind an immutable trusted base SHA and semantic implementation revision. Reactions, labels, draft branches, bot output, and issue prose MUST NOT establish approval.

#### Scenario: Draft planning change is refused
- **WHEN** an authorized maintainer requests implementation for a planning change that exists only on an unmerged or draft branch
- **THEN** intake returns a sanitized ineligible disposition before provider credentials, target preparation, or workflow dispatch

### Requirement: Provider-routed implementation execution
The implementation profile SHALL declare every permitted provider with its own pinned image and credential. Exactly one provider lane MAY execute per request, selected from the trusted profile and request before either credential is exposed, and a lane MUST receive only its own provider credential and provider endpoint. There MUST be no runtime fallback between providers within a run, so an infrastructure failure remains attributable to the selected provider. Both lanes MUST produce the identical governed outputs under the same isolation, path policy, task plan, workspace binding, and trusted gates. Trusted validation SHALL consume artifacts only from the selected provider lane, MUST fail closed when that lane did not run or published no result, and MUST ignore an unselected lane's artifacts. A lane MUST fail before any provider network activity or model invocation when the selected credential is absent, and MUST NOT read, expand, or pass the unselected provider's credential. Lane outcome SHALL be classified from host-observed execution facts -- the captured runner exit code, runner result, implementation result, freeze outcome, and frozen bundle presence -- never from the wrapper job's conclusion alone, which the workflow deliberately keeps green to capture evidence. A lane MAY be classified complete only when every success condition is independently proven. Implementation images MUST be pullable by the runner without repository or package credentials.

#### Scenario: Route to exactly one provider lane
- **WHEN** the trusted claim resolves an implementation provider
- **THEN** only that provider's lane executes, it receives only that provider's credential and endpoint, and the other lane is skipped

#### Scenario: Refuse an unsupported provider before invocation
- **WHEN** the resolved provider is not a permitted implementation provider
- **THEN** execution fails closed before any credential is exposed or any model is invoked

#### Scenario: Refuse a lane whose credential is absent
- **WHEN** the selected provider's credential is empty or unset
- **THEN** the lane fails before starting the provider proxy or model container, records sanitized evidence naming the missing credential, and never falls back to another provider

#### Scenario: Refuse a green wrapper job that proved nothing
- **WHEN** a provider job concludes successfully but its captured runner exit code is nonzero, its runner result reports failure, its implementation result is absent, or its frozen bundle is missing
- **THEN** the lane is classified as failed and terminal state records that disposition rather than a model outcome or a generic evidence error

#### Scenario: Classify a provider image failure as infrastructure
- **WHEN** the selected lane fails while provisioning its image and publishes no implementation result
- **THEN** the outcome is recorded as a provider infrastructure failure rather than a model failure, and validation refuses to proceed

### Requirement: Bounded implementation model input
The implementation prompt SHALL be assembled under a character budget declared in the trusted profile that leaves margin beneath the selected provider's hard input limit, because providers count characters and a byte ceiling cannot represent that limit. Mandatory contracts -- instructions, packet, context manifest, task plan, result schema, and command policy -- MUST be included byte-identically and MUST NOT be truncated; if they alone exceed the budget, assembly MUST fail before the provider is contacted. Source context SHALL be selected deterministically, prioritized by the trusted task plan's approved paths, added only as complete files, and stopped before the budget is exhausted. Dropping a file under the task's own approved paths MUST be a refusal, not an omission, because a model editing files it was never shown produces work that fails validation for reasons it could not have known. The prompt MUST tell the model which files were elided, so a partial view is visible to the model and not only to a post-hoc auditor. The character unit the budget gates on MUST be defined and MUST be the larger of Unicode code points and UTF-16 code units, so the configured margin holds whichever unit the provider counts. Every included and omitted path MUST be recorded with a bounded omission reason, together with budget utilisation so a run that begins degrading is visible. A provider rejecting an input the configured ceiling accepted MUST be classified distinctly as ceiling drift, and that classification MUST remain reachable when the provider exits nonzero, which is how such a rejection is reported. Any other provider or model failure MUST retain its own exit status and MUST NOT be converted into ceiling drift. Evidence MUST be sanitized on every exit path, including failure paths whose evidence is uploaded. A budget failure MUST be classified as input preparation or provider infrastructure, never as a model failure, and its evidence MUST NOT echo prompt or source content. The assembly boundary MUST report which failure occurred rather than leaving the caller to infer one from a nonzero exit, distinguishing at least a budget failure from a preparation failure. The workspace mounted for the model MUST be exactly the bounded set the prompt describes, so the profile's declared snapshot bound is true and the model cannot read what it was not shown. An adapter disposition MUST be carried into lane evidence and preserved in canonical terminal state; recording it only in the runner's output directory does not make it durable.

#### Scenario: Refuse an oversized prompt before invocation
- **WHEN** the assembled prompt would exceed the configured character budget
- **THEN** assembly fails before the provider network, proxy, or model container exists, and the failure is recorded with the configured ceiling and measured counts only

#### Scenario: Refuse to elide approved implementation context
- **WHEN** a file under the task plan's approved paths cannot fit the budget
- **THEN** assembly fails closed rather than omitting it, and the failure names the path

#### Scenario: Disclose a partial snapshot to the model
- **WHEN** unrelated repository files are elided for budget
- **THEN** the prompt lists them and instructs the model to report a need rather than assume contents

#### Scenario: Distinguish preparation failure from budget failure
- **WHEN** prompt assembly stops for a malformed contract, an unreadable input, or an unexpected exception
- **THEN** it is classified as a preparation failure rather than a budget failure

#### Scenario: Preserve the adapter's reason in terminal state
- **WHEN** the adapter stops before the model for a missing credential, a budget failure, a preparation failure, or ceiling drift
- **THEN** that exact disposition reaches canonical terminal state instead of a generic adapter or infrastructure failure

#### Scenario: Detect a drifted ceiling
- **WHEN** the provider rejects an input that the configured ceiling accepted
- **THEN** the lane records a distinct ceiling-drift disposition rather than a generic adapter failure

#### Scenario: Prioritize approved implementation context
- **WHEN** source context is selected for a task plan naming approved paths
- **THEN** files under those paths are included before unrelated repository files, selection is identical across repeated builds, and no file is included partially

### Requirement: Isolated implementation workspace
The executable profile SHALL provide the model only an ephemeral writable, de-Git workspace snapshot derived from the immutable trusted base. A trusted workspace-binding manifest MUST bind the workspace path, content hash, repository, issue, accepted change, run identity, immutable base/head, and disabled Git settings before provider credentials or the executor are selected. The model mount MUST mask `.git`; contract tooling, profiles, schemas, policies, source credentials, GitHub tokens, Git credentials, Docker, Tailscale, production services, and protected branches MUST remain inaccessible. Trusted code MUST serialize the bounded packet, manifest, task plan, prompt, and size-limited source snapshot into the model input through the declared `bounded_stdin` contract; the model MUST NOT rely on undeclared filesystem-reading capabilities. Git metadata remains available only to trusted host tooling.

#### Scenario: Workspace escape is blocked
- **WHEN** the model attempts to write outside the workspace or access `.git`, credentials, workflows, policies, production data, or host sockets
- **THEN** the broker or artifact validator rejects the operation and records a sanitized policy violation

### Requirement: Governed command execution
Implementation commands SHALL come from a versioned repository registry with exact executable/argument definitions, phase eligibility, bounded time/output, allowed environment, expected artifacts, and default-deny network. The model process SHALL expose no shell or unified-exec tool; it returns a bounded UTF-8 file bundle, while trusted validation starts only registry-defined commands. Arbitrary shell, interpreters, privilege escalation, Docker, SSH, and unapproved package/network access MUST fail closed. Provider HTTPS egress SHALL use a trusted allowlist proxy restricted to the selected provider endpoint.

#### Scenario: Unregistered command is denied
- **WHEN** trusted validation or an implementation request asks to execute a command not present in the active registry
- **THEN** no process starts and a bounded command-policy event is emitted

#### Scenario: Host sockets are unavailable
- **WHEN** a registered validation command probes host home, temporary, Docker, SSH, or Tailscale socket paths
- **THEN** the deny-by-default filesystem sandbox hides those paths and the command cannot establish network egress

### Requirement: Trusted implementation handoff
The model SHALL produce a strict result, task evidence, workspace manifest, declared file bundle, and checksums bound to the run, issue, change hash, base SHA, profile, packet, and context manifest. Trusted validation SHALL reconstruct a clean worktree, apply only declared files, enforce path/size/secret policy, snapshot non-mutating gate execution in a deny-by-default filesystem and PID namespace, and determine publication eligibility from a report bound to the exact implementation-result and workspace-manifest checksums. Candidate files MUST NOT replace the trusted tooling root used to run validators; candidate imports MUST resolve from the candidate worktree and immutable trusted runtime only.

#### Scenario: Undeclared artifact is rejected
- **WHEN** the handoff contains a file not in the declared manifest or a checksum/provenance mismatch
- **THEN** validation fails without creating a branch, commit, or draft PR

#### Scenario: Failure evidence survives bundle rejection
- **WHEN** model execution, schema validation, or safe-bundle freezing fails
- **THEN** generic sanitized runner result and exit evidence are uploaded independently, while no unsafe workspace bundle is uploaded or published

### Requirement: Deterministic task reconciliation
Trusted code SHALL derive task slices from unchecked accepted OpenSpec tasks whose entries carry
explicit path, required-check, risk, and prerequisite metadata. Metadata checks MUST name only
the implementation validation gates. Changes with no unchecked tasks, missing metadata, or
unsupported checks MUST be refused before provider execution. Model prose alone MUST NOT mark a
task complete, and accepted OpenSpec task checkboxes MUST NOT be rewritten automatically.

#### Scenario: Missing required check blocks publication
- **WHEN** a claimed completed task lacks its required trusted check or changes an undeclared path
- **THEN** the result is blocked and publication eligibility is false

### Requirement: Trusted draft publication
Only a no-provider-secret trusted publisher with a live per-target lease MAY create or update the deterministic implementation branch and draft PR. It MUST derive the branch from issue/change/revision facts, never write the default branch, preserve human edits, and update canonical state after successful Git mutation. Reusing an existing CountyForge branch is permitted only when its complete Git tree exactly matches the currently validated manifest applied to the captured base; otherwise publication MUST refuse or supersede without overwriting the branch.

#### Scenario: Cancellation wins before publication
- **WHEN** canonical state is cancelled, stale, terminal, or lease-expired at the final preflight
- **THEN** no Git ref, commit, or draft PR is created and the terminal state records a sanitized cancellation/publication disposition

### Requirement: Resume and supersession
An unchanged semantic request SHALL deduplicate or resume only from validated artifacts. A changed accepted OpenSpec hash or trusted base SHA SHALL create a new revision. Existing human-edited branches or PRs MUST never be overwritten silently; a safe superseding branch/PR or bounded failure is required.

#### Scenario: Human edits cause supersession
- **WHEN** an implementation branch or draft PR diverges from its CountyForge provenance
- **THEN** the publisher preserves the predecessor and creates a linked superseding revision or refuses with recoverable evidence

### Requirement: Implementation security observability
The control plane SHALL emit sanitized low-cardinality events for eligibility, packet, workspace, task, command, policy, artifact, validation, publication, cancellation, and terminal outcomes. Secrets, raw environment data, paths, run IDs, SHAs, issue numbers, branches, and error text MUST NOT be metric labels or public status content.

#### Scenario: Provider secret is absent from publication
- **WHEN** workflow policy and artifact checks inspect the implementation publication job
- **THEN** no provider credential or model workspace is present and only trusted sanitized evidence is published

### Requirement: Finishable implementation requests
The bounded model input SHALL be sized so a single-shot implementation request is one the model can complete inside its declared wall-clock budget. Trusted configuration MUST declare both a hard provider ceiling and a smaller operational source-selection target, and prompt provenance MUST record both. Source selection MUST order the approved package, its sibling packages, and its build configuration ahead of unrelated services, tools, and documentation. Approved-path material MAY exceed the operational target up to the hard ceiling, and that pressure MUST be recorded; approved-path material MUST NOT be silently dropped, and material exceeding the hard ceiling MUST still fail closed before any provider activity. A dedicated timeout disposition SHALL require the full corroborated timeout shape; evidence that contradicts itself MUST fall through to the existing inconsistent-result and failure classification rather than be reported as a clean timeout. The trusted policy SHALL pin exactly one provider, model, and reasoning effort per command; a failed or unfinished run MUST NOT be retried at another effort or routed to another provider.

#### Scenario: A run that exhausts its wall clock is classified as a timeout
- **WHEN** a runner result corroborates a timeout across its envelope, mode, disposition, captured exit code, and summary, and no more specific credential, prompt-budget, preparation, ceiling-drift, provider-infrastructure, freeze, or trusted-validation failure was observed
- **THEN** the lane records `implementation_model_timed_out`, the terminal state is failed, and no lane is retried or re-routed

### Requirement: Preserved model-event evidence
The control plane SHALL locate the provider model-event stream independently of any other artifact, so a run that produced no implementation result still yields evidence of what its budget was spent on. A bounded summary MUST be uploaded on every outcome, and the absence of a stream MUST be recorded as explicit evidence. The summary MUST carry only bounded facts; raw model reasoning, prompt or source content, provider credentials, and arbitrary event payloads MUST NOT be uploaded.

#### Scenario: A timed-out run retains its event evidence
- **WHEN** the implementation lane ends with model events present and no implementation result written
- **THEN** the sanitized evidence contains a bounded event summary, no raw event stream, and no reasoning, source, or credential content
