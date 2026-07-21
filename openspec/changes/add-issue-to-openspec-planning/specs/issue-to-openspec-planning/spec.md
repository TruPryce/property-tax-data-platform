## ADDED Requirements

### Requirement: Bounded planning context
The planning adapter SHALL classify structured issues and construct a strict packet and context manifest from approved repository material and bounded issue discussion. It MUST confine paths after symlink resolution, require regular files, enforce file/byte limits, record hashes and truncation, and label all issue/comment text as untrusted evidence.

#### Scenario: Reject unsafe context
- **WHEN** a candidate path escapes an approved root, is a symlink to outside material, is non-regular, or exceeds a configured bound
- **THEN** the candidate is excluded with a reason code and no provider call is started

### Requirement: Strict planning result
The planning result SHALL use a versioned schema with bounded strings and arrays, kebab-case change names, safe repository-relative OpenSpec paths, packet citations, assumptions, unresolved decisions, blocked reasons, and explicit implementation eligibility. Unknown properties, absolute/traversal paths, shell payloads, secrets, workflow/policy paths, and production-code paths MUST fail validation.

#### Scenario: Materialize only OpenSpec files
- **WHEN** a schema-valid plan is published
- **THEN** trusted code renders only the OpenSpec change files and leaves source, workflow, policy, provider, and infrastructure paths untouched

### Requirement: Trusted planning publication
The planning model MUST run without a writable repository, GitHub write token, Git credentials, production credentials, arbitrary tools, or ungoverned network access. A no-secret trusted job SHALL validate packet/result provenance and deterministic repository gates before any branch or draft PR mutation.

#### Scenario: Validation fails closed
- **WHEN** result hashes, issue/repository/SHA/run bindings, schema, path policy, or deterministic validation fail
- **THEN** no commit or PR update is made and canonical status records a sanitized failure

### Requirement: Deterministic planning revisions
The control plane SHALL deduplicate identical semantic planning requests. Changed context SHALL create a revision and a linked superseding draft without overwriting human edits; an exact same-run publication may be reused idempotently. Blocking unresolved decisions SHALL keep implementation ineligible.

#### Scenario: Preserve human edits
- **WHEN** an existing planning PR is manually adopted or materially edited
- **THEN** a new superseding draft is created and the predecessor remains intact

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
