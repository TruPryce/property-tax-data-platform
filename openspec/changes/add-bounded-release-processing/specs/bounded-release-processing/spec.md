## ADDED Requirements

### Requirement: Provide a single-pass reader and a caller-supplied atomic stage

The production release boundary SHALL be a single-pass, context-managed county reader plus a caller-supplied atomic release stage, provided as `typing.Protocol` classes in `property_tax_adapters.release` so a county supplies a reader without inheriting a base class.

A prepared reader SHALL validate its complete layout or schema and expose the resulting layout fingerprint, parser contract version, and jurisdiction before iteration begins, and SHALL then yield one validated `AppraisalSourceRecord` at a time. It SHALL NOT materialize the whole member.

The processor SHALL stage records and SHALL NOT return or yield accepted production records to its caller.

A whole-release `bytes | str -> tuple` API SHALL NOT be a production input.

The processor SHALL NOT create a disk spool, implicitly or otherwise. Any future spool requires separately approved bounded volume, byte limit, cleanup contract, and retry behaviour.

The release package SHALL import no county module, and no county module SHALL import the release package.

#### Scenario: A reader that materializes its member fails conformance
- **GIVEN** a reader whose source cannot be consumed eagerly without exhausting memory
- **WHEN** the conformance suite drives it
- **THEN** a reader that reads its member into memory before yielding fails
- **THEN** a reader that yields one record at a time passes

#### Scenario: Layout provenance is available before the first record
- **GIVEN** a prepared reader
- **WHEN** preparation completes and before iteration begins
- **THEN** the layout fingerprint, parser contract version, and jurisdiction are readable
- **THEN** no record has been read to obtain them

#### Scenario: The boundary depends on no county
- **GIVEN** each module in `property_tax_adapters.release` parsed with `ast` and its docstrings removed
- **WHEN** its imports are collected
- **THEN** no import resolves to a county module or a third-party package
- **THEN** no county module imports the release package

### Requirement: Validate, stage, and commit in one fixed order

The processor SHALL follow exactly this order for one logical release:

1. open the immutable source through the county reader;
2. validate the complete required layout or schema and capture its fingerprint;
3. open one atomic stage for the logical release;
4. decode and validate each physical row, writing its adapter records only to the invisible stage;
5. finalize release-wide checks after end-of-input;
6. commit exactly once, only after parsing and every blocking check succeed.

No accepted record SHALL be consumer-visible during steps 1 through 5.

A layout failure SHALL occur before the first stage write, and SHALL NOT open a stage at all.

A row failure after any number of internal writes SHALL abort the complete stage.

#### Scenario: A layout failure never opens a stage
- **GIVEN** a member whose layout fails validation
- **WHEN** the processor runs with a stage that records whether it was opened
- **THEN** the outcome reports `layout_rejected`
- **THEN** the stage was never opened
- **THEN** no record was written

#### Scenario: A row failure after staged writes aborts everything
- **GIVEN** a member whose first row is valid and whose second row fails validation
- **WHEN** the processor runs with a stage that records whether `abort` ran
- **THEN** the first row was written to the stage
- **THEN** `abort` ran and `commit` did not
- **THEN** the outcome reports zero accepted records, including for the row that was valid

#### Scenario: Commit happens exactly once
- **GIVEN** a member whose rows and release-wide checks all pass
- **WHEN** the processor runs
- **THEN** `commit` is called exactly once
- **THEN** it is called after finalization, not before

### Requirement: Reject the logical release on any boundary failure

A reader, parser, row-validation, duplicate, resource-limit, progress-callback, stage-write, finalize, or commit failure SHALL reject the logical release.

Rejection SHALL invoke stage abort and return a bounded rejected outcome. It SHALL NOT return staged records.

An aborted stage, and a commit that fails, SHALL expose zero accepted records.

#### Scenario: Rejection before staging
- **GIVEN** a failure that occurs before the first record is written
- **WHEN** the processor runs
- **THEN** the outcome disposition is rejected
- **THEN** zero accepted records are exposed

#### Scenario: Rejection after the first staged record
- **GIVEN** a failure that occurs after at least one record has been written to the stage
- **WHEN** the processor runs
- **THEN** the stage is aborted
- **THEN** zero accepted records are exposed

#### Scenario: Rejection during finalize or commit
- **GIVEN** a stage whose `finalize` raises, and separately one whose `commit` raises
- **WHEN** the processor runs against each
- **THEN** the outcome reports `stage_finalize_failed` and `stage_commit_failed` respectively
- **THEN** zero accepted records are exposed in both cases

#### Scenario: A rejected outcome carries no records
- **GIVEN** any rejected release
- **WHEN** the outcome is inspected
- **THEN** it carries counts, codes, and contract metadata
- **THEN** it exposes no record, row, or per-row payload field

### Requirement: Enforce cross-row constraints in the stage, not in the processor

The processor SHALL NOT retain the complete key set for a release.

Duplicate and other release-wide constraints SHALL be enforced by the atomic stage through a bounded external unique or index contract, and a duplicate SHALL be reported as `duplicate_record_key`.

This change SHALL provide a stage conformance suite, and a file-backed standard-library test stage or equivalent deterministic fixture, proving duplicate rejection and rollback without introducing production persistence or a new dependency.

A scratch-backed test implementation SHALL use a caller-supplied directory, an explicit page or byte ceiling, and cleanup on success, on failure, and on retry.

#### Scenario: The duplicate is caught by the stage
- **GIVEN** a member containing two records with the same key
- **WHEN** the processor runs against a conforming stage
- **THEN** the stage reports the duplicate and the release is rejected with `duplicate_record_key`
- **THEN** the processor retained no key set of its own

#### Scenario: Rollback leaves nothing behind
- **GIVEN** a stage that has written records and is then aborted
- **WHEN** its backing store is inspected
- **THEN** no accepted record remains
- **THEN** scratch resources are cleaned up

#### Scenario: The test stage adds no dependency
- **GIVEN** the test stage implementation
- **WHEN** its imports are collected
- **THEN** every import resolves to the standard library
- **THEN** it is not presented as a production stage

### Requirement: Bound the diagnostics and close their vocabulary

The boundary SHALL declare a closed diagnostic vocabulary including at least `layout_rejected`, `record_rejected`, `duplicate_record_key`, `stage_write_failed`, `stage_finalize_failed`, `stage_commit_failed`, `progress_callback_failed`, and `resource_limit_exceeded`. Every declared code SHALL be reachable, proved by driving inputs through the boundary rather than by comparing the vocabulary with itself.

`resource_limit_exceeded` SHALL be reachable in this change through a caller-supplied bound, even though the measured resource target belongs to a later change. A declared code no input can produce is a promise nothing keeps.

At most 100 diagnostics SHALL be retained per release, the total count SHALL be preserved, and truncation SHALL be marked deterministically: the retained entries SHALL be the first 100 in encounter order, so two runs over one member agree.

A diagnostic SHALL carry only its stable code and, where applicable, an approved field name, the one-based physical row number, and the layout fingerprint. Those SHALL be the whole type, so there is nowhere to put a complete row, an arbitrary source value, exception text, a credential, an identity, an address, or a host-local path.

Exception text SHALL NOT be retained, including from a reader, a stage, or a progress callback.

#### Scenario: Every declared code is produced by some input
- **GIVEN** the closed boundary vocabulary
- **WHEN** inputs are driven through the processor to provoke each condition
- **THEN** every declared code is observed at least once
- **THEN** `resource_limit_exceeded` is among them, provoked by the caller-supplied bound

#### Scenario: Truncation is deterministic
- **GIVEN** a release producing more than 100 diagnostics
- **WHEN** the processor runs twice over the same member
- **THEN** exactly 100 are retained in both runs, and they are the same 100 in the same order
- **THEN** the preserved total exceeds 100 and truncation is marked

#### Scenario: An exception message never reaches the outcome
- **GIVEN** a reader and a stage that raise with identifiable text in their messages
- **WHEN** the processor runs
- **THEN** the outcome reports the stable code for the failure
- **THEN** that text appears in no diagnostic, outcome field, or progress event

### Requirement: Emit a bounded, deterministic progress contract

`ReleaseProgressEvent` SHALL be immutable and SHALL carry exactly the progress contract version, jurisdiction, bounded release identity, parser contract version, layout fingerprint, physical rows processed, staged adapter record count, a deterministic sequence number, and a `final` indicator, and no other field.

The callback protocol SHALL be synchronous.

A non-final event SHALL be emitted after every 100,000 physical rows, and exactly one final event SHALL be emitted at end-of-input, including when the row count is an exact multiple of 100,000 and when the release is empty.

Sequence numbers SHALL be deterministic and gapless within a release.

A callback that raises SHALL reject and abort the release with `progress_callback_failed`, and its exception text SHALL NOT be retained.

#### Scenario: An exact multiple still emits one final event
- **GIVEN** a release of exactly 200,000 physical rows
- **WHEN** the processor runs
- **THEN** two non-final events are emitted
- **THEN** exactly one final event is emitted, and it is the last

#### Scenario: An empty release still emits one final event
- **GIVEN** a release containing no physical rows
- **WHEN** the processor runs
- **THEN** no non-final event is emitted
- **THEN** exactly one final event is emitted, reporting zero rows and zero staged records

#### Scenario: A failing callback rejects the release
- **GIVEN** a progress callback that raises on its first invocation
- **WHEN** the processor runs
- **THEN** the release is rejected with `progress_callback_failed`
- **THEN** the stage is aborted and zero accepted records are exposed
- **THEN** the callback's exception text is not retained

### Requirement: Keep the Dallas whole-member helper out of the production path

`parse_dallas_appraisal_csv` SHALL remain a synthetic fixture and contract helper. It SHALL NOT be wrapped and presented as the production streaming boundary, and no production DAG or release processor SHALL import or invoke it.

All 52 existing Dallas contract cases SHALL remain collected unchanged, or migrate case-for-case with no scenario lost.

A future Dallas production reader SHALL implement the prepared-reader protocol directly and emit only the shared adapter output its caller selected.

#### Scenario: The boundary does not reach for the helper
- **GIVEN** each module in `property_tax_adapters.release` parsed with `ast`
- **WHEN** its imports and calls are collected
- **THEN** `parse_dallas_appraisal_csv` is neither imported nor invoked

#### Scenario: The Dallas cases are undisturbed
- **GIVEN** the Dallas contract test module
- **WHEN** the suite is collected
- **THEN** all 52 cases are present and unchanged by this work

### Requirement: State the boundary this change does not cross

Documentation SHALL state that this change implements issue #43 decisions D1, D2, D3, D4, D6, D8, and the diagnostic portion of D5, and that the remainder of D5 — the 900 MiB peak-RSS target, the requirement that memory not grow linearly with row count, the cgroup `memory.peak` and `ru_maxrss` measurement method, and the reproducible 1,000,000-row, 90-column benchmark — belongs to a second change that depends on this one.

It SHALL state that the 900 MiB target supersedes the issue body's earlier 1 GiB wording, because the scheduler's measured 400 MiB peak shares the same 4 GiB container.

It SHALL state that durable quarantine persistence and the production unique index remain owned by bootstrap tasks 3.4 and 3.5, and that the SQLite stage is a test fixture proving the conformance suite has a passing implementation rather than a production stage.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, or archive locations.

#### Scenario: The excluded scope is named
- **GIVEN** the boundary document
- **WHEN** it is read
- **THEN** the resource target, its measurement method, and the benchmark are each named as the second change
- **THEN** the 900 MiB figure is stated as superseding the issue body's 1 GiB

#### Scenario: The test stage is not mistaken for a production one
- **GIVEN** the boundary document
- **WHEN** its stage section is read
- **THEN** the SQLite stage is described as a test fixture
- **THEN** durable quarantine and the production index are attributed to bootstrap tasks 3.4 and 3.5
