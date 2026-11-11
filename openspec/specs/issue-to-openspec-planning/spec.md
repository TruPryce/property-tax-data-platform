# issue-to-openspec-planning Specification

## Purpose
Define bounded issue-to-OpenSpec planning, deterministic discussion selection, trusted draft publication, and the human approval boundary before implementation.

## Requirements

### Requirement: Bounded planning context
The planning adapter SHALL classify structured issues and construct a strict packet and context manifest from approved repository material and bounded issue discussion. It MUST confine paths after symlink resolution, require regular files, enforce file/byte limits, record hashes and truncation, and label all issue/comment text as untrusted evidence. Trusted bot-owned CountyForge status and feedback comments MUST be excluded using immutable bot identity plus their canonical markers; user-authored marker text remains untrusted evidence. Packet preparation MUST recompute the bounded context fingerprint from the selected issue/comment window and fail closed if it differs from the intake fingerprint.

#### Scenario: Reject unsafe context
- **WHEN** a candidate path escapes an approved root, is a symlink to outside material, is non-regular, or exceeds a configured bound
- **THEN** the candidate is excluded with a reason code and no provider call is started

#### Scenario: Reject context fingerprint drift
- **WHEN** issue or discussion evidence changes between intake and packet preparation
- **THEN** packet construction fails with a sanitized context-mismatch disposition before provider execution

#### Scenario: Ignore mutable CountyForge output
- **WHEN** a trusted CountyForge status comment is inserted or updated between intake and packet preparation
- **THEN** the comment is excluded from both fingerprints and the packet, while an identical marker authored by a user remains selected as untrusted evidence

### Requirement: Strict planning result
The planning result SHALL use a versioned authoritative schema with bounded strings and arrays, kebab-case change names, safe repository-relative OpenSpec paths, packet citations, assumptions, unresolved decisions, blocked reasons, and explicit implementation eligibility. A separate provider-generation schema MAY omit unsupported constraint keywords only to shape structured generation; it MUST preserve the complete required field and object structure and MUST NOT replace authoritative trusted validation. Unknown properties, absolute/traversal paths, shell payloads, secrets, workflow/policy paths, and production-code paths MUST fail trusted validation. Shell-payload scanning SHALL be scoped by field purpose. Command fields MUST reject any shell builtin invoked in command position with an argument, and detection MUST NOT depend on whether that argument resembles a filename. Task fields MUST apply that same rule to their Markdown inline-code spans while remaining prose-compatible, and MUST still reject substitution, chaining, separators, interpreters, and destructive commands anywhere in the slice. Every other planning field MUST be checked only for command/parameter substitution and interpreter piping. Markdown inline code MUST be unwrapped rather than rejected, and no field MAY be rejected for domain vocabulary that reuses a shell builtin name outside command position.

#### Scenario: Materialize only OpenSpec files
- **WHEN** a schema-valid plan is published
- **THEN** trusted code renders only the OpenSpec change files and leaves source, workflow, policy, provider, and infrastructure paths untouched

#### Scenario: Reject generation-only validity
- **WHEN** provider output satisfies the generation schema but violates a bound, path rule, constant, or policy in the authoritative result contract
- **THEN** trusted validation fails closed before materialization and publication

#### Scenario: Accept planning prose that names identifiers and county sources
- **WHEN** a schema-valid plan quotes identifiers such as `ACCOUNT_NUM` in Markdown inline code, or describes county source records, source members, and source onboarding
- **THEN** trusted payload validation accepts the result, while command and task fields still fail closed on substitution, chaining, interpreters, and destructive commands

#### Scenario: Reject a sourced script whatever its argument looks like
- **WHEN** a command field or a task field's inline-code span invokes `source` or `eval` in command position, whether the argument is a bare relative script, a quoted path, a variable, or a dotted path
- **THEN** trusted payload validation fails closed, and no filename-shape exception is granted

### Requirement: Trusted planning publication
The planning model MUST run without a writable repository, GitHub write token, Git credentials, production credentials, arbitrary tools, or ungoverned network access. A no-secret trusted job SHALL validate packet/result provenance and deterministic repository gates before any branch or draft PR mutation.

Publication SHALL record the last entered stage from a closed vocabulary, opening that evidence boundary before its inputs are read and before any provider client is constructed, so no failure and no persisted snapshot can report a stage outside that vocabulary. Every failure leaving publication MUST be sanitized and MUST carry its stage, including a contract-check failure and an unexpected exception from untrusted API responses or the filesystem; no raw exception value MAY cross that boundary. Recorded stages SHALL advance only to the next stage in the vocabulary, so completed stages are always its exact ordered prefix. The trusted workflow MUST preserve and upload the publisher's structured result on both success and failure, and MUST reduce that result and the captured return code to one consistent document: a missing, malformed, non-object, or exit-code-inconsistent result becomes sanitized evidence with a nonzero effective exit code, and step outputs are produced only for a zero exit that also reports complete, well-typed publication facts. Stage and completed stages are reserved normalized fields validated as an exact ordered prefix; persisted progress is authoritative over the reported document, contradiction between two valid records fails closed, and only bounded allow-listed auxiliary detail is carried forward.

Before creating the deterministic planning ref, publication MUST inspect it: an absent ref is created, a ref whose commit carries this plan's tree and trusted parent is resumed, and any other ref fails closed as a branch conflict without being moved. A pull-request body marker is mutable evidence and MUST NOT by itself deduplicate a publication: a deduplicated success SHALL be reported only after the candidate tree is built, the deterministic ref passes that equivalence check, and the draft's head matches the verified ref; otherwise publication fails closed as a draft conflict.

#### Scenario: Validation fails closed
- **WHEN** result hashes, issue/repository/SHA/run bindings, schema, path policy, or deterministic validation fail
- **THEN** no commit or PR update is made and canonical status records a sanitized failure

#### Scenario: Name the failing publication mutation
- **WHEN** a GitHub Git-data or pull-request mutation fails during publication
- **THEN** the sanitized result records the failing stage and the stages already completed, the workflow preserves and uploads that document, and canonical state records `planning_publication_failed`

#### Scenario: Refuse to finalize on unreadable publisher evidence
- **WHEN** the publisher's result is missing, malformed, not a single JSON object, reports failure, or reports success alongside a nonzero exit code or incomplete publication facts
- **THEN** normalization replaces it with sanitized evidence carrying a nonzero effective exit code and any surviving progress stage, and no publication step output is written

#### Scenario: Resume an interrupted publication
- **WHEN** the deterministic planning ref already exists and its commit carries this plan's tree and trusted parent
- **THEN** publication reuses that ref and its existing draft if one was created, instead of creating a second branch or draft

#### Scenario: Refuse a divergent planning ref
- **WHEN** the deterministic planning ref exists and holds any other commit
- **THEN** publication fails closed as a branch conflict and never moves the ref

#### Scenario: Refuse a marker whose branch no longer backs it
- **WHEN** an existing draft's body marker claims this plan but its branch is absent, divergent, or force-pushed away from the verified ref
- **THEN** publication fails closed as a draft conflict instead of reporting a deduplicated success, and creates no second draft

#### Scenario: Attribute a preflight or unexpected publication failure
- **WHEN** the planning result artifact is unreadable or invalid, the provider client cannot be constructed, or an unexpected exception escapes a publication stage
- **THEN** the failure is reported as a sanitized publication failure carrying its stage, the progress document exists, and no raw exception value appears in the output

#### Scenario: Refuse contradictory publication evidence
- **WHEN** the reported result and the persisted progress both carry a valid stage and they disagree
- **THEN** normalization reports inconsistent evidence with a nonzero effective exit code and the persisted stage, and writes no publication step output

### Requirement: Deterministic planning revisions
The control plane SHALL deduplicate identical semantic planning requests. Changed context SHALL create a revision and a linked superseding draft without overwriting human edits; an exact same-run publication may be reused idempotently. Blocking unresolved decisions SHALL keep implementation ineligible.

#### Scenario: Preserve human edits
- **WHEN** an existing planning PR is manually adopted or materially edited
- **THEN** a new superseding draft is created and the predecessor remains intact

### Requirement: Recent discussion selection
The planning adapter SHALL deduplicate issue comments whose immutable comment IDs are at or before the original plan-command comment ID and select a deterministic newest-first window of at most 16 comments using immutable comment identity and timestamps. Initial intake, initial packet preparation, and retry packet reconstruction MUST apply the same candidate cutoff and selected window. When the original triggering command comment is available, it MUST be retained in the selected window. The selected comments, including their bounded redacted bodies and identities, MUST participate in the planning context fingerprint and packet provenance; post-cutoff comments and older pre-cutoff comments outside the selected window MUST NOT participate.

#### Scenario: Freeze discussion at the plan command
- **WHEN** initial intake, initial packet preparation, or retry reconstruction observes comments whose IDs are greater than the original plan-command comment ID
- **THEN** those post-cutoff comments are excluded and every stage derives the same bounded planning-context fingerprint

#### Scenario: Selected discussion mutation changes identity
- **WHEN** an issue has more than 16 eligible pre-cutoff comments and a comment selected into the newest bounded window changes or disappears
- **THEN** packet reconstruction detects a changed planning-context fingerprint and fails closed before provider execution

#### Scenario: Unselected discussion preserves frozen identity
- **WHEN** an older pre-cutoff comment outside the selected 16-comment window or any post-cutoff comment changes
- **THEN** the frozen planning-context fingerprint remains unchanged

### Requirement: Issue-only planning intake
The control plane SHALL accept `/countyforge plan` only for structured issue targets. Pull-request-backed issue comments MUST be refused before target preparation, provider credential access, workflow dispatch, or runner execution.

#### Scenario: Pull-request plan is refused
- **WHEN** an authorized maintainer posts `/countyforge plan` on a pull request
- **THEN** the control plane emits a sanitized `plan_requires_issue` refusal and creates no runner request, check, or execution workflow

### Requirement: Canonical recent-run history
The canonical bot-owned status comment SHALL remain a single comment. Its primary table SHALL show the current active/latest run, and it SHALL render up to five prior completed runs from canonical history in a bounded newest-first `Recent runs` table. Each newly archived run MUST preserve immutable display facts including run ID, command, profile and version, target head SHA, idempotency key, attempt, revision, lifecycle state, completion/update time, and sanitized evidence reference. History entries MUST reject unknown properties; readers MAY render legacy entries that lack newer display fields with bounded fallback values without invalidating the canonical state. Only the current run may display `Pending`; a historical entry without an evidence URL MUST display its bounded disposition instead.

#### Scenario: Completed validation remains visible after review
- **WHEN** a completed validation run is followed by a review run on the same target
- **THEN** the canonical comment shows the review as current and the validation in the bounded recent-run table without creating a second status comment

#### Scenario: History remains bounded
- **WHEN** more than the configured number of runs are archived
- **THEN** only the newest five prior entries are rendered and older entries remain excluded from the visible table without overwriting the current state

#### Scenario: Historical evidence is sanitized
- **WHEN** a prior run has an approved GitHub evidence URL or no evidence URL
- **THEN** the visible table renders the approved link safely or a bounded disposition, never an internal path, idempotency key, or unescaped display value

### Requirement: Human approval
The planning agent MUST NOT approve its own result. Implementation eligibility SHALL remain false until the planning change exists on the trusted default branch as the result of a planning PR merged by an authorized human maintainer. The eligibility evidence MUST bind the merged PR's merge commit SHA and immutable approving actor ID; reactions, labels, draft PRs, bot output, and issue prose alone MUST NOT count as approval.

#### Scenario: Accept only merged human planning work
- **WHEN** trusted GitHub facts show the exact planning change on the captured default-branch SHA and a merged planning PR whose actor has `admin`, `maintain`, or `write`
- **THEN** implementation eligibility may be granted

#### Scenario: Reject draft or self-approval
- **WHEN** the planning PR is open/draft, the actor is unauthorized, or approval facts are missing
- **THEN** implementation eligibility is denied before workspace or provider execution

#### Scenario: Unresolved decisions block implementation
- **WHEN** the result contains a blocking unresolved decision
- **THEN** the draft remains blocked and no implementation command becomes eligible

### Requirement: Publication finalization is cancellation-aware

The trusted workflow SHALL verify the live canonical planning lease in the per-target state lane immediately before any branch, commit, or draft PR mutation. Every materialization, validation, and publication failure SHALL reach a sanitized terminal state update.

#### Scenario: Cancelled planning run creates no publication
- **WHEN** cancellation wins before the publication preflight
- **THEN** no planning branch or draft PR is created and the canonical issue status reports the failure or cancellation without claiming publication succeeded
