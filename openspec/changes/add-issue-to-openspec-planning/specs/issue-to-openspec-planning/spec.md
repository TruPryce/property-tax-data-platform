## ADDED Requirements

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

Publication SHALL record the last entered stage from a closed vocabulary, starting before its first fallible preflight so no failure and no persisted snapshot can report a stage outside that vocabulary, and MUST attach it to every sanitized failure. The trusted workflow MUST preserve and upload the publisher's structured result on both success and failure, and MUST reduce that result and the captured return code to one consistent document: a missing, malformed, non-object, or exit-code-inconsistent result becomes sanitized evidence with a nonzero effective exit code, a surviving closed-vocabulary progress stage is carried into that evidence, and step outputs are produced only for a zero exit that also reports complete, well-typed publication facts. Before creating the deterministic planning ref, publication MUST inspect it: an absent ref is created, a ref whose commit carries this plan's tree and trusted parent is resumed, and any other ref fails closed as a branch conflict without being moved.

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

### Requirement: Deterministic planning revisions
The control plane SHALL deduplicate identical semantic planning requests. Changed context SHALL create a revision and a linked superseding draft without overwriting human edits; an exact same-run publication may be reused idempotently. Blocking unresolved decisions SHALL keep implementation ineligible.

#### Scenario: Preserve human edits
- **WHEN** an existing planning PR is manually adopted or materially edited
- **THEN** a new superseding draft is created and the predecessor remains intact

### Requirement: Recent discussion selection
The planning adapter SHALL deduplicate issue comments and select a deterministic newest-first window of at most 16 comments using immutable comment identity and timestamps. When the triggering command comment is available, it MUST be retained in the selected window even if it falls outside the newest window. The selected comments, including their bounded redacted bodies and identities, MUST participate in the planning context fingerprint and packet provenance.

#### Scenario: Late discussion changes planning identity
- **WHEN** an issue has more than 16 comments and a later comment changes an accepted decision
- **THEN** the newest window and context fingerprint include that late comment, causing a changed planning identity rather than silently reusing stale context

#### Scenario: Trigger comment is retained
- **WHEN** the triggering command comment is older than the newest 16 comments
- **THEN** the bounded packet retains that comment alongside the newest discussion and remains deterministically hashable

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
The planning agent MUST NOT approve its own result. Implementation eligibility SHALL remain false until an authorized maintainer merges the planning PR under the documented approval contract; reactions and labels alone MUST NOT count as approval.

#### Scenario: Unresolved decisions block implementation
- **WHEN** the result contains a blocking unresolved decision
- **THEN** the draft remains blocked and no implementation command becomes eligible

### Requirement: Publication finalization is cancellation-aware

The trusted workflow SHALL verify the live canonical planning lease in the per-target state lane immediately before any branch, commit, or draft PR mutation. Every materialization, validation, and publication failure SHALL reach a sanitized terminal state update.

#### Scenario: Cancelled planning run creates no publication
- **WHEN** cancellation wins before the publication preflight
- **THEN** no planning branch or draft PR is created and the canonical issue status reports the failure or cancellation without claiming publication succeeded
