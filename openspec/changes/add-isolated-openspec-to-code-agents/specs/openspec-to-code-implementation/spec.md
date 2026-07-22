## ADDED Requirements

### Requirement: Accepted-plan implementation eligibility
The control plane SHALL allow `implement <change>` only when the exact change exists and validates on the trusted default branch, identifies the originating issue, has no unresolved blocking decisions, and its planning PR was merged by an authorized maintainer. The request MUST bind an immutable trusted base SHA and semantic implementation revision. Reactions, labels, draft branches, bot output, and issue prose MUST NOT establish approval.

#### Scenario: Draft planning change is refused
- **WHEN** an authorized maintainer requests implementation for a planning change that exists only on an unmerged or draft branch
- **THEN** intake returns a sanitized ineligible disposition before provider credentials, target preparation, or workflow dispatch

### Requirement: Isolated implementation workspace
The executable profile SHALL provide the model only an ephemeral writable workspace derived from the immutable trusted base. Contract tooling, profiles, schemas, policies, source credentials, GitHub tokens, Git credentials, Docker, Tailscale, production services, and protected branches MUST remain inaccessible.

#### Scenario: Workspace escape is blocked
- **WHEN** the model attempts to write outside the workspace or access `.git`, credentials, workflows, policies, production data, or host sockets
- **THEN** the broker or artifact validator rejects the operation and records a sanitized policy violation

### Requirement: Governed command execution
Implementation commands SHALL come from a versioned repository registry with exact executable/argument definitions, phase eligibility, bounded time/output, allowed environment, expected artifacts, and default-deny network. Arbitrary shell, interpreters, privilege escalation, Docker, SSH, and unapproved package/network access MUST fail closed.

#### Scenario: Unregistered command is denied
- **WHEN** an implementation request asks to execute a command not present in the active registry
- **THEN** no process starts and a bounded command-policy event is emitted

### Requirement: Trusted implementation handoff
The model SHALL produce a strict result, task evidence, workspace manifest, declared file bundle, and checksums bound to the run, issue, change hash, base SHA, profile, packet, and context manifest. Trusted validation SHALL reconstruct a clean worktree, apply only declared files, enforce path/size/secret policy, and determine publication eligibility.

#### Scenario: Undeclared artifact is rejected
- **WHEN** the handoff contains a file not in the declared manifest or a checksum/provenance mismatch
- **THEN** validation fails without creating a branch, commit, or draft PR

### Requirement: Deterministic task reconciliation
Trusted code SHALL derive task slices from accepted OpenSpec tasks and require bounded diff and required-check evidence for completion. Model prose alone MUST NOT mark a task complete, and accepted OpenSpec task checkboxes MUST NOT be rewritten automatically.

#### Scenario: Missing required check blocks publication
- **WHEN** a claimed completed task lacks its required trusted check or changes an undeclared path
- **THEN** the result is blocked and publication eligibility is false

### Requirement: Trusted draft publication
Only a no-provider-secret trusted publisher with a live per-target lease MAY create or update the deterministic implementation branch and draft PR. It MUST derive the branch from issue/change/revision facts, never write the default branch, preserve human edits, and update canonical state after successful Git mutation.

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
