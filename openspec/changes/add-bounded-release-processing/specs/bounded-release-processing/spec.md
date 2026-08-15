## ADDED Requirements

### Requirement: Provide a single-pass reader carrying release metadata and row envelopes

The production release boundary SHALL be a single-pass, context-managed county reader plus a caller-supplied atomic release stage, provided as `typing.Protocol` classes in `property_tax_adapters.release` so a county supplies a reader without inheriting a base class.

A prepared reader SHALL validate its complete layout or schema before iteration begins and SHALL then expose `PreparedRelease` metadata carrying the jurisdiction code, the release identifier, the source member name, the layout fingerprint, and the parser contract version. That metadata SHALL be readable without reading any record, so an empty release still has a complete identity.

Iteration SHALL yield one `SourceRowEnvelope` per **physical row**, carrying the one-based physical row number and the zero or more `AppraisalSourceRecord` values that row produced. A physical row producing no record and a physical row producing several are both ordinary: one accepted Collin row already produces one record per observed family. The envelope is what makes row completion explicit, so physical rows and staged records are counted from the same traversal rather than inferred from one another.

The processor SHALL stage records and SHALL NOT return or yield accepted production records to its caller.

A whole-release `bytes | str -> tuple` API SHALL NOT be a production input.

The processor SHALL NOT create a disk spool, implicitly or otherwise. Any future spool requires separately approved bounded volume, byte limit, cleanup contract, and retry behaviour.

The release package SHALL import no county module, and no county module SHALL import the release package.

#### Scenario: Release identity is complete before the first record
- **GIVEN** a prepared reader over a release containing no physical rows
- **WHEN** preparation completes
- **THEN** the jurisdiction, release identifier, source member name, layout fingerprint, and parser contract version are all readable
- **THEN** no record was read to obtain them

#### Scenario: A physical row may produce zero, one, or several records
- **GIVEN** a reader yielding one envelope with no record, one with a single record, and one with two records
- **WHEN** the processor runs
- **THEN** the physical row count is three
- **THEN** the staged record count is three
- **THEN** neither count is derived from the other

#### Scenario: The boundary depends on no county
- **GIVEN** each module in `property_tax_adapters.release` parsed with `ast` and its docstrings removed
- **WHEN** its imports are collected
- **THEN** no import resolves to a county module or a third-party package
- **THEN** no county module imports the release package

### Requirement: Bound the release identity so a host path is unrepresentable

`release_identifier` and `source_member_name` SHALL each be a `str` of 1 through 128 characters, containing only ASCII letters, digits, `.`, `_`, and `-`, and SHALL NOT begin with `.` or `-`. A value outside that shape SHALL be rejected before the release is processed, and SHALL NOT be coerced.

This is the bound the accepted Tarrant contract already sets for the same two fields, adopted here rather than a second one invented. That alphabet admits no `/`, `\`, `:`, whitespace, or control character, so an absolute path, a UNC path, a drive-qualified path, and a parent-directory traversal are unrepresentable in a progress event rather than merely discouraged.

`jurisdiction_code` SHALL be the shape the shared contracts already require: a lowercase state prefix, a hyphen, and a county slug.

#### Scenario: A host path cannot reach a progress event
- **GIVEN** a release identifier of `/var/tmp/dallas-2026` or `../../etc/passwd`
- **WHEN** the processor is invoked
- **THEN** the release is rejected before any row is read
- **THEN** the value is not coerced into an acceptable one

#### Scenario: The accepted bound is reused rather than redefined
- **GIVEN** the boundary's identity rule and the accepted Tarrant contract's rule
- **WHEN** the two are compared
- **THEN** the permitted length, alphabet, and leading-character restriction are identical

### Requirement: Validate, stage, and commit in one fixed order

The processor SHALL follow exactly this order for one logical release:

1. open the immutable source through the county reader;
2. validate the complete required layout or schema and capture its fingerprint;
3. open one atomic stage for the logical release;
4. for each physical row envelope, write its records only to the invisible stage;
5. at end-of-input, emit the final progress event;
6. finalize release-wide checks;
7. commit exactly once, only after every blocking check succeeds.

No accepted record SHALL be consumer-visible during steps 1 through 6.

A layout failure SHALL occur before the first stage write, and SHALL NOT open a stage at all.

A row failure after any number of internal writes SHALL abort the complete stage.

The final progress event SHALL be emitted **before** finalization and commit. A final callback that raises must be able to reject the release while zero records are still visible, which is impossible if the event follows the commit it is meant to be able to prevent.

#### Scenario: A layout failure never opens a stage
- **GIVEN** a member whose layout fails validation
- **WHEN** the processor runs with a stage that records whether it was opened
- **THEN** the outcome reports `layout_rejected`
- **THEN** the stage was never opened, and `abort` was never called
- **THEN** no record was written

#### Scenario: A row failure after staged writes aborts everything
- **GIVEN** a member whose first row is valid and whose second row fails validation
- **WHEN** the processor runs with a stage that records whether `abort` ran
- **THEN** the first row was written to the stage
- **THEN** `abort` ran and `commit` did not
- **THEN** the outcome reports zero accepted records, including for the row that was valid

#### Scenario: Commit happens exactly once and last
- **GIVEN** a member whose rows and release-wide checks all pass
- **WHEN** the processor runs
- **THEN** the observed call order is write, final progress event, finalize, commit
- **THEN** `commit` is called exactly once

### Requirement: Reject the logical release on any boundary failure

A reader, parser, row-validation, duplicate, resource-guard, progress-callback, stage-write, finalize, or commit failure SHALL reject the logical release.

Rejection SHALL abort the stage **if and only if the stage was entered**. A failure before the stage is opened SHALL NOT call `abort`, because there is nothing to abort and calling it would require a stage the contract says was never created.

Rejection SHALL return a bounded rejected outcome and SHALL NOT return staged records.

An aborted stage, and a commit that fails, SHALL expose zero accepted records.

#### Scenario: Rejection before the stage exists calls no abort
- **GIVEN** a failure that occurs before the stage is opened
- **WHEN** the processor runs
- **THEN** the outcome disposition is rejected
- **THEN** `abort` is not called
- **THEN** zero accepted records are exposed

#### Scenario: Rejection after the first staged record aborts
- **GIVEN** a failure that occurs after at least one record has been written to the stage
- **WHEN** the processor runs
- **THEN** `abort` is called exactly once
- **THEN** zero accepted records are exposed

#### Scenario: Rejection during finalize or commit
- **GIVEN** a stage whose `finalize` raises, and separately one whose `commit` raises
- **WHEN** the processor runs against each
- **THEN** the outcome reports `stage_finalize_failed` and `stage_commit_failed` respectively
- **THEN** `abort` is called in both cases
- **THEN** zero accepted records are exposed

#### Scenario: A rejected outcome carries no records
- **GIVEN** any rejected release
- **WHEN** the outcome is inspected
- **THEN** it carries counts, codes, and contract metadata
- **THEN** it exposes no record, row, or per-row payload field

### Requirement: Enforce cross-row constraints in the stage, not in the processor

The processor SHALL NOT retain the complete key set for a release.

Duplicate and other release-wide constraints SHALL be enforced by the atomic stage through a bounded external unique or index contract.

The stage SHALL signal a duplicate by raising `DuplicateRecordKey`, a typed exception the release package declares. Any other exception from `write` is an ordinary write failure. Without a typed signal the processor would have to inspect exception text to tell the two apart, which the privacy rules forbid and which no stage implementation could be relied on to phrase consistently.

This change SHALL provide a stage conformance suite, and a file-backed standard-library test stage or equivalent deterministic fixture, proving duplicate rejection and rollback without introducing production persistence or a new dependency.

A scratch-backed test implementation SHALL use a caller-supplied directory, an explicit page or byte ceiling, and cleanup on success, on failure, and on retry.

#### Scenario: A duplicate is distinguished from a write failure
- **GIVEN** a stage that raises `DuplicateRecordKey` for a repeated key and a different exception for a disk failure
- **WHEN** the processor runs against each
- **THEN** the first is reported as `duplicate_record_key`
- **THEN** the second is reported as `stage_write_failed`
- **THEN** neither decision inspects exception text

#### Scenario: The duplicate is caught by the stage
- **GIVEN** a member containing two records with the same key
- **WHEN** the processor runs against a conforming stage
- **THEN** the release is rejected with `duplicate_record_key`
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

### Requirement: Check a caller-supplied resource guard at deterministic checkpoints

The boundary SHALL declare a `ResourceGuard` protocol with one synchronous method taking the physical rows processed and the staged record count and returning nothing. A guard that raises SHALL reject the release with `resource_limit_exceeded`.

The processor SHALL call the guard at exactly these checkpoints, and at no others: once immediately after the stage is opened and before the first write, once at every 100,000-physical-row boundary alongside the progress event, and once at end-of-input before finalization. Those checkpoints are a function of the row count alone, so two runs over one member call the guard the same number of times in the same places.

The boundary SHALL define **what** it calls and **when**, and SHALL NOT define what the guard measures, in what units, or by what probe. A guard that measures nothing and never raises is a conforming guard, and is the default when a caller supplies none. The measured resource target, the probe, and the acceptance benchmark belong to the second change; this change fixes the contract that change plugs into.

The guard's exception text SHALL NOT be retained.

#### Scenario: The guard is called at the specified checkpoints only
- **GIVEN** a recording guard and a release of exactly 250,000 physical rows
- **WHEN** the processor runs
- **THEN** the guard is called after the stage opens, at 100,000, at 200,000, and once at end-of-input
- **THEN** it is called at no other point
- **THEN** two runs over the same member produce the same call sequence

#### Scenario: A raising guard rejects the release
- **GIVEN** a guard that raises on its second call
- **WHEN** the processor runs
- **THEN** the release is rejected with `resource_limit_exceeded`
- **THEN** the stage is aborted and zero accepted records are exposed
- **THEN** the guard's exception text is not retained

#### Scenario: The default guard changes nothing
- **GIVEN** a caller supplying no guard
- **WHEN** the processor runs an otherwise valid release
- **THEN** the release is accepted
- **THEN** no `resource_limit_exceeded` diagnostic is produced

### Requirement: Close the failure vocabulary and fix the phase-to-code mapping

The boundary vocabulary SHALL be **exactly** these eight codes and no others: `layout_rejected`, `record_rejected`, `duplicate_record_key`, `stage_write_failed`, `stage_finalize_failed`, `stage_commit_failed`, `progress_callback_failed`, and `resource_limit_exceeded`.

The mapping from failure to code SHALL be deterministic and exhaustive:

| failure | code |
| --- | --- |
| reader preparation or layout validation | `layout_rejected` |
| reader iteration, decode, or row validation | `record_rejected` |
| `DuplicateRecordKey` from `write` | `duplicate_record_key` |
| any other exception from `write` | `stage_write_failed` |
| any exception from `finalize` | `stage_finalize_failed` |
| any exception from `commit` | `stage_commit_failed` |
| any exception from a progress callback | `progress_callback_failed` |
| any exception from the resource guard | `resource_limit_exceeded` |

Every declared code SHALL be reachable, proved by driving inputs through the boundary rather than by comparing the vocabulary with itself.

At most 100 diagnostics SHALL be retained per release, the total count SHALL be preserved, and truncation SHALL be marked deterministically: the retained entries SHALL be the first 100 in encounter order, so two runs over one member agree.

A diagnostic SHALL carry only its stable code and, where applicable, an approved field name, the one-based physical row number, and the layout fingerprint. Those SHALL be the whole type, so there is nowhere to put a complete row, an arbitrary source value, exception text, a credential, an identity, an address, or a host-local path.

Exception text SHALL NOT be retained, from any source.

#### Scenario: The vocabulary is exactly eight codes
- **GIVEN** the declared boundary vocabulary
- **WHEN** its members are enumerated
- **THEN** there are exactly eight
- **THEN** each is produced by some input driven through the processor

#### Scenario: Each failure phase maps to one code
- **GIVEN** a failure injected at each phase in the mapping table
- **WHEN** the processor runs against each
- **THEN** the code observed is the one the table names
- **THEN** no phase produces a code belonging to another phase

#### Scenario: Truncation is deterministic
- **GIVEN** a release producing more than 100 diagnostics
- **WHEN** the processor runs twice over the same member
- **THEN** exactly 100 are retained in both runs, and they are the same 100 in the same order
- **THEN** the preserved total exceeds 100 and truncation is marked

#### Scenario: An exception message never reaches the outcome
- **GIVEN** a reader, a stage, a callback, and a guard that each raise with identifiable text
- **WHEN** the processor runs against each
- **THEN** the outcome reports the stable code from the mapping table
- **THEN** that text appears in no diagnostic, outcome field, or progress event

### Requirement: Emit a bounded, deterministic progress contract

`ReleaseProgressEvent` SHALL be immutable and SHALL carry exactly the progress contract version, jurisdiction, release identifier, source member name, parser contract version, layout fingerprint, physical rows processed, staged adapter record count, a deterministic sequence number, and a `final` indicator, and no other field.

Identity fields SHALL come from the reader's `PreparedRelease` metadata, so an empty release emits a complete event.

The callback protocol SHALL be synchronous.

A non-final event SHALL be emitted after every 100,000 physical rows, and exactly one final event SHALL be emitted at end-of-input, including when the row count is an exact multiple of 100,000 and when the release is empty. The final event SHALL precede finalization and commit.

Sequence numbers SHALL be deterministic and gapless within a release, starting at zero.

A callback that raises SHALL reject and abort the release with `progress_callback_failed`, and its exception text SHALL NOT be retained.

#### Scenario: An exact multiple still emits one final event
- **GIVEN** a release of exactly 200,000 physical rows
- **WHEN** the processor runs
- **THEN** two non-final events are emitted, at 100,000 and 200,000
- **THEN** exactly one final event is emitted, and it is the last
- **THEN** the sequence numbers are 0, 1, 2 with no gap

#### Scenario: An empty release still emits one complete final event
- **GIVEN** a release containing no physical rows
- **WHEN** the processor runs
- **THEN** no non-final event is emitted
- **THEN** exactly one final event is emitted, reporting zero rows and zero staged records
- **THEN** its jurisdiction, release identifier, source member name, and layout fingerprint are all populated from the prepared release

#### Scenario: A failing final callback prevents the commit
- **GIVEN** a small release whose rows all pass, and a callback that raises on the final event
- **WHEN** the processor runs
- **THEN** the release is rejected with `progress_callback_failed`
- **THEN** `finalize` and `commit` are never called
- **THEN** the stage is aborted and zero accepted records are exposed

#### Scenario: A failing non-final callback rejects mid-release
- **GIVEN** a callback that raises on its first non-final event
- **WHEN** the processor runs
- **THEN** the release is rejected with `progress_callback_failed`
- **THEN** the stage is aborted and zero accepted records are exposed
- **THEN** the callback's exception text is not retained

### Requirement: Detect read-ahead deterministically rather than by resource behaviour

The conformance suite SHALL detect a reader that reads ahead by construction, not by observing memory.

It SHALL drive a candidate reader from a **guarded pull source** that records the order of pulls and writes. A reader conforms only if, at the moment the processor writes the records of physical row *n*, the guarded source has been pulled at most *n* times. A reader that materializes its member pulls the source to exhaustion before the first write and fails that check on any release of two or more rows.

A county enters the suite through a **reader factory** taking the guarded source, so a real county reader is exercised by the same harness as a synthetic one, and conformance is a property the county can be tested for rather than asserted about.

This requirement SHALL NOT depend on measured memory. The peak-RSS target, its probe, and the benchmark belong to the second change; read-ahead is a structural property observable without them.

#### Scenario: An eager reader fails on a two-row release
- **GIVEN** a reader that consumes the guarded source fully before yielding
- **WHEN** the conformance suite drives it over two physical rows
- **THEN** the pull count exceeds one before the first write
- **THEN** the reader fails conformance

#### Scenario: A single-pass reader passes
- **GIVEN** a reader that pulls one row, yields its envelope, and repeats
- **WHEN** the suite drives it over the same release
- **THEN** the pull count never exceeds the number of rows written
- **THEN** the reader passes conformance

#### Scenario: The check needs no memory measurement
- **GIVEN** the conformance suite
- **WHEN** its implementation is inspected
- **THEN** it observes pull and write order only
- **THEN** it reads no resident set size, cgroup file, or allocation counter

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

It SHALL state that the `ResourceGuard` protocol defines when the boundary asks, and that what is measured is the second change's to supply.

It SHALL state that durable quarantine persistence and the production unique index remain owned by bootstrap tasks 3.4 and 3.5, and that the SQLite stage is a test fixture proving the conformance suite has a passing implementation rather than a production stage.

Documentation SHALL contain no county bytes, production rows, owner values, addresses, layouts, credentials, or archive locations.

#### Scenario: The excluded scope is named
- **GIVEN** the boundary document
- **WHEN** it is read
- **THEN** the resource target, its measurement method, and the benchmark are each named as the second change
- **THEN** the 900 MiB figure is stated as superseding the issue body's 1 GiB
- **THEN** the guard is described as fixing when the boundary asks, not what is measured

#### Scenario: The test stage is not mistaken for a production one
- **GIVEN** the boundary document
- **WHEN** its stage section is read
- **THEN** the SQLite stage is described as a test fixture
- **THEN** durable quarantine and the production index are attributed to bootstrap tasks 3.4 and 3.5
