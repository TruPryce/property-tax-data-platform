## ADDED Requirements

### Requirement: Provide a single-pass reader carrying release metadata, row envelopes, and row rejections

The production release boundary SHALL be a single-pass, context-managed county reader plus a caller-supplied atomic release stage, provided as `typing.Protocol` classes in `property_tax_adapters.release`.

`PreparedReader` SHALL declare three operations and no fourth:

| operation | obligation | failure code |
| --- | --- | --- |
| `__enter__` / `__exit__` | open and close the immutable source | `source_open_failed` / `source_close_failed` |
| `prepare() -> PreparedRelease` | validate the complete layout or schema and return the release metadata | `layout_rejected` |
| `__iter__` | yield one `SourceRowEnvelope` per physical row | `record_rejected` |

`prepare()` is a named method rather than an implicit phase, because the lifecycle and the diagnostic table already distinguish opening a source from validating its layout and assign the two different codes. Without a call to attribute each failure to, an implementation could not decide between `source_open_failed` and `layout_rejected` except by guessing where in `__enter__` the exception arose.

`prepare()` SHALL be called exactly once, after `__enter__` and before the first iteration, and SHALL return metadata carrying the jurisdiction code, release identifier, source member name, layout fingerprint, and parser contract version. It SHALL NOT read a record, so an empty release still has a complete identity.

Every other callable on the boundary SHALL likewise declare an exact signature, so two independent implementations are interchangeable rather than merely similarly shaped:

| callable | signature |
| --- | --- |
| `PreparedReader.__enter__` | `() -> PreparedReader` |
| `PreparedReader.__exit__` | `(exc_type: type[BaseException] \| None, exc: BaseException \| None, traceback: TracebackType \| None) -> None` |
| `PreparedReader.prepare` | `() -> PreparedRelease` |
| `PreparedReader.__iter__` | `() -> Iterator[SourceRowEnvelope]` |
| `ReleaseStage.__enter__` | `() -> ReleaseStage` |
| `ReleaseStage.__exit__` | `(exc_type: type[BaseException] \| None, exc: BaseException \| None, traceback: TracebackType \| None) -> None` |
| `ReleaseStage.write` | `(records: Sequence[AppraisalSourceRecord]) -> None` |
| `ReleaseStage.finalize` | `() -> None` |
| `ReleaseStage.abort` | `() -> None` |
| `ReleaseStage.commit` | `() -> None` |
| `ProgressCallback.__call__` | `(event: ReleaseProgressEvent) -> None` |
| `ResourceGuard.check` | `(physical_rows_processed: int, staged_record_count: int) -> None` |
| `process_release` | `(*, reader: PreparedReader, stage: ReleaseStage, progress: ProgressCallback \| None = None, guard: ResourceGuard \| None = None) -> ReleaseOutcome` |

`write` SHALL take one physical row's records together, because a row is the unit that is accepted or rejected: splitting it across calls would let a stage hold half a row when the row is refused. An envelope with no records SHALL NOT be written at all.

A `write` call SHALL be all-or-nothing. If it raises, the stage SHALL contain none of that call's records, not the prefix it managed before failing. Otherwise a stage could hold part of a row while the processor counted none of it, and `staged_record_count` would describe neither what was attempted nor what is present. This is a per-call guarantee and is independent of the release-level atomicity that `abort` and `commit` provide.

`process_release` SHALL take only keyword arguments, so a caller cannot transpose the reader and the stage, and both optional collaborators SHALL default to absent.

`__enter__` SHALL return the entered object itself, so a caller holds one identity for the resource it opened rather than a proxy whose lifetime it does not control.

`__exit__` SHALL be annotated as returning `None`, not `bool`. A suppressing exit would hide a failure the processor must map to a code, and a `None` return is always falsy, so the prohibition is carried by the signature rather than left to prose an implementation could overlook.

Iteration SHALL yield one `SourceRowEnvelope` per **physical row**, carrying the one-based physical row number, the zero or more `AppraisalSourceRecord` values that row produced, and a bounded `rejected` indicator with an optional approved field name.

An envelope SHALL distinguish three cases that would otherwise be indistinguishable:

| envelope | meaning |
| --- | --- |
| records, not rejected | the row produced output |
| no records, not rejected | the row legitimately produced none |
| rejected, with or without records | the row is invalid |

A reader SHALL signal an invalid row by marking the envelope rejected, **not** by raising. Raising ends iteration at the first bad row, which would make the 100-diagnostic retention cap unreachable and would report one defect where a member has many.

The processor SHALL stage records and SHALL NOT return or yield accepted production records to its caller.

A whole-release `bytes | str -> tuple` API SHALL NOT be a production input.

The processor SHALL NOT create a disk spool, implicitly or otherwise.

#### Scenario: Release identity is complete before the first record
- **GIVEN** a prepared reader over a release containing no physical rows
- **WHEN** preparation completes
- **THEN** the jurisdiction, release identifier, source member name, layout fingerprint, and parser contract version are all readable
- **THEN** no record was read to obtain them

#### Scenario: A legitimately empty row is not a rejected row
- **GIVEN** one envelope with no records and not rejected, and one envelope marked rejected
- **WHEN** the processor runs
- **THEN** the first contributes to the physical row count and produces no diagnostic
- **THEN** the second produces exactly one `record_rejected` diagnostic

#### Scenario: A physical row may produce zero, one, or several records
- **GIVEN** a reader yielding one envelope with no record, one with a single record, and one with two records
- **WHEN** the processor runs
- **THEN** the physical row count is three and the staged record count is three
- **THEN** neither count is derived from the other

#### Scenario: Many rejected rows reach the retention cap
- **GIVEN** a release of 150 physical rows, every one marked rejected
- **WHEN** the processor runs
- **THEN** iteration does not stop at the first rejected row
- **THEN** 100 diagnostics are retained, the preserved total is 150, and truncation is marked

### Requirement: Continue collecting diagnostics after a row is rejected, and stop writing

On the first rejected row the processor SHALL record `record_rejected`, SHALL cease writing records to the stage, and SHALL continue iterating in order to collect further row diagnostics up to the retention cap.

At end-of-input the processor SHALL abort the stage and return a rejected outcome. It SHALL NOT finalize and SHALL NOT commit.

Continuing the traversal is what makes a member's full diagnostic picture available and the retention cap meaningful; ceasing writes is what keeps a doomed release from doing stage work that will be discarded. This mirrors the accepted county parsers, which continue past a bad row and decide blocking at end-of-input.

#### Scenario: Writing stops at the first rejection but reading does not
- **GIVEN** a release whose second of five rows is rejected
- **WHEN** the processor runs with a stage that records its writes
- **THEN** only the first row's records were written
- **THEN** all five physical rows were read
- **THEN** the stage was aborted and neither `finalize` nor `commit` ran

### Requirement: Bound the release identity so a host path is unrepresentable

`release_identifier` and `source_member_name` SHALL each be a `str` of 1 through 128 characters, containing only ASCII letters, digits, `.`, `_`, and `-`, and SHALL NOT begin with `.` or `-`. A value outside that shape SHALL be rejected before the release is processed and SHALL NOT be coerced.

This is the bound the accepted Tarrant contract already sets for the same two fields, adopted rather than reinvented. That alphabet admits no `/`, `\`, `:`, whitespace, or control character, so an absolute path, a UNC path, a drive-qualified path, and a parent-directory traversal are unrepresentable in a progress event rather than merely discouraged.

`jurisdiction_code` SHALL take the shape the shared contracts already require.

#### Scenario: A host path cannot reach a progress event
- **GIVEN** a release identifier of `/var/tmp/dallas-2026` or `../../etc/passwd`
- **WHEN** the processor is invoked
- **THEN** the release is rejected before any row is read
- **THEN** the value is not coerced into an acceptable one

### Requirement: Require every staged record to agree with its release and its row

Before writing a record, the processor SHALL verify that the record's `jurisdiction_code`, and its provenance's `release_identifier`, `source_member_name`, `parser_contract_version`, and `layout_fingerprint`, each equal the corresponding `PreparedRelease` value, and that the provenance's `source_row_number` equals the envelope's `physical_row_number`.

A disagreement SHALL reject the row with `record_rejected` and SHALL NOT be written, corrected, or coerced. A record that disagrees with the release it arrived in is evidence of a reader defect, and staging it would attribute a row to a release or a position it did not come from.

#### Scenario: A record from the wrong release is refused
- **GIVEN** an envelope whose record carries a different `release_identifier` than the prepared release
- **WHEN** the processor runs
- **THEN** the row is rejected with `record_rejected`
- **THEN** the record is not written to the stage

#### Scenario: A record claiming the wrong row is refused
- **GIVEN** an envelope at physical row 7 whose record's provenance reports row 6
- **WHEN** the processor runs
- **THEN** the row is rejected with `record_rejected`
- **THEN** the mismatch is not corrected to match the envelope

### Requirement: Fix the lifecycle order so nothing failable follows the commit

The processor SHALL follow exactly this order for one logical release:

1. enter the county reader;
2. prepare it and validate the complete layout, capturing `PreparedRelease`;
3. enter the stage;
4. call the resource guard once, before the first write;
5. for each row envelope: verify agreement, write its records to the invisible stage, and at every 100,000-physical-row boundary call the guard and emit a non-final progress event;
6. at end-of-input call the guard once and emit exactly one final progress event;
7. exit the reader;
8. finalize;
9. commit exactly once;
10. exit the stage.

Every operation that may fail SHALL complete before step 9. The reader is closed at step 7, **before** the commit, so no reader failure can occur after records become visible.

A stage's `__exit__` SHALL NOT fail after **either** a successful commit or an abort. That is part of the stage contract, it is what makes step 10 safe to place after the only step that changes visibility, and the conformance suite tests both paths.

A stage exit that raises despite that contract is a defect in trusted code, not source data. It SHALL propagate rather than becoming a diagnostic, consistent with how this library already treats authoring defects — a malformed `PacsLayout` raises `ValueError` rather than producing a diagnostic. Giving it a code would imply the boundary can absorb a stage that does not meet its contract, and it cannot.

The final progress event SHALL precede finalization and commit, so a raising final callback can still reject while zero records are visible.

A layout failure SHALL occur before the stage is entered and SHALL NOT enter it.

On rejection the processor SHALL abort instead of finalizing and committing, and SHALL abort **if and only if the stage was entered**.

No outcome SHALL report rejection after a commit has succeeded.

#### Scenario: A layout failure never enters a stage
- **GIVEN** a member whose layout fails validation
- **WHEN** the processor runs with a stage that records whether it was entered
- **THEN** the outcome reports `layout_rejected`
- **THEN** the stage was never entered and `abort` was never called

#### Scenario: The reader is closed before the commit
- **GIVEN** a passing release and a reader that records when it was exited
- **WHEN** the processor runs
- **THEN** the observed order is final progress event, reader exit, finalize, commit, stage exit
- **THEN** no failable operation follows the commit

#### Scenario: A reader that fails to open is not reported as a layout failure
- **GIVEN** a reader whose `__enter__` raises
- **WHEN** the processor runs
- **THEN** the outcome reports `source_open_failed`, not `layout_rejected`
- **THEN** no stage was entered

#### Scenario: A reader that fails on close still rejects before visibility
- **GIVEN** a reader whose `__exit__` raises
- **WHEN** the processor runs an otherwise passing release
- **THEN** the outcome reports `source_close_failed`
- **THEN** `commit` was never called and zero accepted records are exposed

#### Scenario: Commit happens exactly once and is the last thing that can change visibility
- **GIVEN** a member whose rows and release-wide checks all pass
- **WHEN** the processor runs
- **THEN** `commit` is called exactly once
- **THEN** the outcome is accepted, and no later step can change that

### Requirement: Reject the logical release on any boundary failure

A reader, layout, row-rejection, provenance-disagreement, duplicate, resource-guard, progress-callback, stage-entry, stage-write, finalize, commit, abort, or reader-close failure SHALL reject the logical release.

Rejection SHALL return a bounded rejected outcome and SHALL NOT return staged records.

An aborted stage, and a commit that fails, SHALL expose zero accepted records.

An `abort` that itself fails SHALL be reported as `stage_abort_failed` and SHALL NOT change the disposition, which is already rejected.

#### Scenario: Rejection before the stage exists calls no abort
- **GIVEN** a failure that occurs before the stage is entered
- **WHEN** the processor runs
- **THEN** the outcome disposition is rejected and `abort` is not called

#### Scenario: Rejection during finalize or commit
- **GIVEN** a stage whose `finalize` raises, and separately one whose `commit` raises
- **WHEN** the processor runs against each
- **THEN** the outcome reports `stage_finalize_failed` and `stage_commit_failed` respectively
- **THEN** `abort` is called in both cases and zero accepted records are exposed

#### Scenario: A failing abort does not hide the original failure
- **GIVEN** a release rejected for a row failure, whose `abort` also raises
- **WHEN** the processor runs
- **THEN** both `record_rejected` and `stage_abort_failed` are recorded
- **THEN** the disposition remains rejected

### Requirement: Enforce cross-row constraints in the stage, not in the processor

The processor SHALL NOT retain the complete key set for a release.

Duplicate and other release-wide constraints SHALL be enforced by the atomic stage through a bounded external unique or index contract.

A stage SHALL signal a duplicate by raising `DuplicateRecordKey`, a typed exception the release package declares. It MAY raise it from `write`, where an eager index detects the collision, or from `finalize`, where a deferred index does. Both SHALL map to `duplicate_record_key`. Any *other* exception from `write` is `stage_write_failed`, and any other exception from `finalize` is `stage_finalize_failed`.

Permitting both points is deliberate: requiring detection at `write` would exclude any stage whose index is deferred until the end, which is how a bulk-loaded relational stage typically behaves.

This change SHALL provide a stage conformance suite, and a file-backed standard-library test stage, proving duplicate rejection and rollback without introducing production persistence or a new dependency, using a caller-supplied directory, an explicit ceiling, and cleanup on success, failure, and retry.

#### Scenario: A failed write leaves none of its row staged
- **GIVEN** a stage that accepts the first record of a three-record row and then raises
- **WHEN** the processor runs and the release is aborted
- **THEN** the stage contains none of that row's records, not one of them
- **THEN** `staged_record_count` does not count a partially written row

#### Scenario: A duplicate is distinguished from a write failure
- **GIVEN** a stage raising `DuplicateRecordKey` for a repeated key and a different exception for a disk failure
- **WHEN** the processor runs against each
- **THEN** the first is `duplicate_record_key` and the second is `stage_write_failed`
- **THEN** neither decision inspects exception text

#### Scenario: A deferred index reports at finalize
- **GIVEN** a stage that accepts every write and raises `DuplicateRecordKey` from `finalize`
- **WHEN** the processor runs a release containing a repeated key
- **THEN** the outcome reports `duplicate_record_key`, not `stage_finalize_failed`
- **THEN** zero accepted records are exposed

#### Scenario: Rollback leaves nothing behind
- **GIVEN** a stage that has written records and is then aborted
- **WHEN** its backing store is inspected
- **THEN** no accepted record remains and scratch resources are cleaned up

#### Scenario: Stage exit is safe after both commit and abort
- **GIVEN** a conforming stage driven to a successful commit, and separately to an abort
- **WHEN** its `__exit__` runs in each case
- **THEN** it does not raise in either
- **THEN** a stage that raises there fails conformance rather than producing a diagnostic

### Requirement: Check a caller-supplied resource guard at deterministic checkpoints

The boundary SHALL declare a `ResourceGuard` protocol with one synchronous method taking the physical rows processed and the staged record count and returning nothing. A guard that raises SHALL reject the release with `resource_limit_exceeded`.

The processor SHALL call the guard at exactly these checkpoints and no others: once immediately after the stage is entered and before the first write, once at every 100,000-physical-row boundary alongside the progress event, and once at end-of-input before the final progress event. The sequence is a function of the row count alone.

The boundary SHALL define **what** it calls and **when**, and SHALL NOT define what the guard measures, in what units, or by what probe. A guard that measures nothing and never raises conforms and is the default when a caller supplies none. The measured target, probe, and acceptance benchmark belong to the second change.

The guard's exception text SHALL NOT be retained.

#### Scenario: The guard is called at the specified checkpoints only
- **GIVEN** a recording guard and a release of exactly 250,000 physical rows
- **WHEN** the processor runs
- **THEN** the guard is called after the stage is entered, at 100,000, at 200,000, and once at end-of-input
- **THEN** two runs over the same member produce the same call sequence

#### Scenario: A raising guard rejects the release
- **GIVEN** a guard that raises on its second call
- **WHEN** the processor runs
- **THEN** the release is rejected with `resource_limit_exceeded`
- **THEN** the stage is aborted and the guard's exception text is not retained

#### Scenario: The default guard changes nothing
- **GIVEN** a caller supplying no guard
- **WHEN** the processor runs an otherwise valid release
- **THEN** the release is accepted and no `resource_limit_exceeded` diagnostic is produced

### Requirement: Close the failure vocabulary and fix the phase-to-code mapping

The boundary vocabulary SHALL be **exactly** these twelve codes and no others: `source_open_failed`, `layout_rejected`, `record_rejected`, `duplicate_record_key`, `stage_open_failed`, `stage_write_failed`, `stage_finalize_failed`, `stage_commit_failed`, `stage_abort_failed`, `source_close_failed`, `progress_callback_failed`, and `resource_limit_exceeded`.

Issue #43 D5 names eight as a minimum. The four additional codes cover lifecycle failures the boundary can genuinely reach — opening a source, entering a stage, aborting one, and closing a reader — and a failure with no code would otherwise have to borrow one that names a different phase. `source_open_failed` exists for exactly that reason: entering the reader is not layout validation, and reporting it as `layout_rejected` would name a phase that had not yet begun.

The mapping SHALL be deterministic and exhaustive:

| failure | code |
| --- | --- |
| reader `__enter__` | `source_open_failed` |
| reader preparation or layout validation | `layout_rejected` |
| reader iteration or decode | `record_rejected` |
| envelope marked rejected | `record_rejected` |
| record disagrees with its release or row | `record_rejected` |
| stage `__enter__` | `stage_open_failed` |
| `DuplicateRecordKey` from `write` or `finalize` | `duplicate_record_key` |
| any other exception from `write` | `stage_write_failed` |
| any other exception from `finalize` | `stage_finalize_failed` |
| any exception from `commit` | `stage_commit_failed` |
| any exception from `abort` | `stage_abort_failed` |
| any exception from reader `__exit__` | `source_close_failed` |
| any exception from a progress callback | `progress_callback_failed` |
| any exception from the resource guard | `resource_limit_exceeded` |

Every declared code SHALL be reachable, proved by driving inputs through the boundary rather than by comparing the vocabulary with itself.

At most 100 diagnostics SHALL be retained per release, the total SHALL be preserved, and truncation SHALL be marked deterministically: the retained entries SHALL be the first 100 in encounter order.

A diagnostic SHALL carry only its stable code and, where applicable, an approved field name, the one-based physical row number, and the layout fingerprint. Exception text SHALL NOT be retained, from any source.

#### Scenario: The vocabulary is exactly twelve codes
- **GIVEN** the declared boundary vocabulary
- **WHEN** its members are enumerated
- **THEN** there are exactly twelve
- **THEN** each is produced by some input driven through the processor

#### Scenario: Each failure phase maps to one code
- **GIVEN** a failure injected at each row of the mapping table
- **WHEN** the processor runs against each
- **THEN** the code observed is the one the table names
- **THEN** no phase produces a code belonging to another phase

#### Scenario: An exception message never reaches the outcome
- **GIVEN** a reader, a stage, a callback, and a guard that each raise with identifiable text
- **WHEN** the processor runs against each
- **THEN** that text appears in no diagnostic, outcome field, or progress event

### Requirement: Populate the outcome when preparation never completed

`ReleaseOutcome` SHALL declare `layout_fingerprint` as `str | None` and `parser_contract_version` as `int | None`. Both SHALL be `None` when no `PreparedRelease` was produced, and both SHALL carry the prepared values when one was. A half-populated outcome — one field set and the other `None` — SHALL NOT occur, because both come from the same `PreparedRelease` and it either exists or does not.

`boundary_contract_version` SHALL always be populated, because it is the boundary's own constant and is known before any reader is touched.

A `source_open_failed` outcome carries neither: the reader never opened. A `layout_rejected` outcome carries neither either, because layout validation is part of preparation and a failure there means preparation did not complete — whatever a reader computed internally before failing is not a prepared release and SHALL NOT be reported as one. An earlier draft said such an outcome "may or may not" carry a fingerprint, which would have permitted exactly the half-populated outcome this rule forbids. Declaring these fields as always-present would force an implementation to invent a placeholder, and a fabricated fingerprint is worse than an absent one — it would be indistinguishable from a real one in a diagnostic.

The same rule SHALL apply to `ReleaseDiagnostic.layout_fingerprint`, and it SHALL be enforced rather than merely permitted: a diagnostic raised before `prepare()` returned SHALL carry `None`, and every diagnostic raised afterwards SHALL carry the prepared fingerprint. Leaving it `None` throughout would satisfy an optional type while discarding the provenance the field exists to carry.

#### Scenario: A reader that never opened reports no fingerprint
- **GIVEN** a reader whose `__enter__` raises
- **WHEN** the processor runs
- **THEN** the outcome reports `source_open_failed`
- **THEN** `layout_fingerprint` and `parser_contract_version` are both `None`
- **THEN** `boundary_contract_version` is populated

#### Scenario: A layout failure reports neither field, however far it got
- **GIVEN** one reader whose preparation fails before computing a fingerprint, and another that computes one internally and then fails validation
- **WHEN** the processor runs against each
- **THEN** both outcomes report `layout_rejected`
- **THEN** `layout_fingerprint` and `parser_contract_version` are `None` in both
- **THEN** neither outcome is half-populated

#### Scenario: A diagnostic carries the fingerprint once one exists
- **GIVEN** a reader that prepares successfully and then rejects a row
- **WHEN** the processor runs
- **THEN** the `record_rejected` diagnostic carries the prepared layout fingerprint
- **THEN** a diagnostic from a failure before `prepare()` returned carries `None` instead

#### Scenario: A prepared release populates both
- **GIVEN** a reader that prepares successfully and then fails on a later row
- **WHEN** the processor runs
- **THEN** `layout_fingerprint` and `parser_contract_version` carry the prepared values
- **THEN** they are not cleared by the later failure

### Requirement: Fix the outcome schema exactly

`ReleaseOutcome` SHALL be a frozen dataclass whose fields, types, and invariants are exactly these:

| field | type | invariant |
| --- | --- | --- |
| `disposition` | `ReleaseDisposition` | a `StrEnum` of exactly `accepted` and `rejected`; `accepted` exactly when `total_diagnostic_count` is zero. Notices do not affect it |
| `notices` | `tuple[ReleaseNotice, ...]` | at most 100 entries, in encounter order |
| `total_notice_count` | `int` | not negative; `len(notices)` equals `min(total_notice_count, 100)` |
| `notices_truncated` | `bool` | true exactly when `total_notice_count` exceeds 100 |
| `boundary_contract_version` | `int` | always populated; equals `BOUNDARY_CONTRACT_VERSION`, which is `1` |
| `parser_contract_version` | `int \| None` | `None` unless `prepare()` returned |
| `layout_fingerprint` | `str \| None` | `None` unless `prepare()` returned |
| `diagnostics` | `tuple[ReleaseDiagnostic, ...]` | at most 100 entries, in encounter order |
| `total_diagnostic_count` | `int` | not negative; `len(diagnostics)` equals `min(total_diagnostic_count, 100)` |
| `diagnostics_truncated` | `bool` | true exactly when `total_diagnostic_count` exceeds 100 |
| `physical_rows_processed` | `int` | not negative |
| `staged_record_count` | `int` | not negative |
| `committed_record_count` | `int` | zero unless `disposition` is `accepted`; equal to `staged_record_count` when it is |
| `rejected_row_count` | `int` | not negative; zero when `disposition` is `accepted` |

An underspecified outcome is one every implementation renders differently, which is the opposite of a contract.

Disposition is not independent of the diagnostics. Every code in the **diagnostic** vocabulary is a failure code, so a release is accepted exactly when it produced no diagnostic. Leaving the two free of each other would permit an accepted outcome carrying `stage_commit_failed`, which asserts two contradictory things at once.

Notices are the separate channel that makes this rule survivable. County contracts already require warnings on accepted releases — the accepted Dallas contract requires unknown columns to be *accepted* and reported with `extra_columns_present` — and with only one channel a future Dallas reader would have to reject a valid layout or discard a required warning. Notices carry that reporting without touching the disposition. The disposition is a closed enumeration rather than a `bool` or a free string so a third state cannot be invented; the counts are separate named integers for the reason D18 gives; and the truncation flag is derivable from the total, so stating the relationship keeps the two from disagreeing.

#### Scenario: The declared schema is exactly this
- **GIVEN** `ReleaseOutcome`
- **WHEN** its fields and annotations are enumerated
- **THEN** they are exactly the fourteen above, with those types
- **THEN** the type is frozen and refuses attribute assignment after construction

#### Scenario: Nothing is dropped below the cap
- **GIVEN** a release producing exactly 40 diagnostics, and separately one producing 150
- **WHEN** each outcome is inspected
- **THEN** the first retains all 40 and is not marked truncated
- **THEN** the second retains exactly 100 and is marked truncated
- **THEN** in both, `len(diagnostics)` equals `min(total_diagnostic_count, 100)`

#### Scenario: The invariants hold together
- **GIVEN** a constructed outcome
- **WHEN** its counts and flags are compared
- **THEN** `diagnostics_truncated` is true exactly when the total exceeds 100
- **THEN** `committed_record_count` is zero unless the disposition is `accepted`
- **THEN** `rejected_row_count` is zero when the disposition is `accepted`

#### Scenario: The disposition follows from the diagnostics
- **GIVEN** an accepted outcome and a rejected one
- **WHEN** each is inspected
- **THEN** the accepted outcome carries no diagnostic at all, though it may carry notices
- **THEN** the rejected outcome carries at least one
- **THEN** no outcome is accepted while carrying a failure code, and none is rejected while carrying none

#### Scenario: The disposition admits no third state
- **GIVEN** `ReleaseDisposition`
- **WHEN** its members are enumerated
- **THEN** there are exactly two, `accepted` and `rejected`

### Requirement: Define exactly what the outcome counts

`ReleaseOutcome` SHALL carry four counts with these exact meanings, and SHALL NOT carry an ambiguous "accepted" or "rejected" count:

| count | meaning |
| --- | --- |
| `physical_rows_processed` | envelopes read, whether or not they produced records |
| `staged_record_count` | records written to the stage |
| `committed_record_count` | records visible after a successful commit; zero unless the release was committed |
| `rejected_row_count` | envelopes rejected, whether by the reader or by disagreement |

D12 separates physical rows from staged records, so a single count could not have meant both. `committed_record_count` is distinct from `staged_record_count` because a staged record is not an accepted one until the commit that makes it visible.

#### Scenario: A rejected release commits nothing
- **GIVEN** a release whose third row is rejected after two rows were written
- **WHEN** the processor runs
- **THEN** `staged_record_count` reflects what was written before the rejection
- **THEN** `committed_record_count` is zero
- **THEN** `rejected_row_count` is at least one

#### Scenario: An accepted release commits what it staged
- **GIVEN** a release whose rows all pass
- **WHEN** the processor runs
- **THEN** `committed_record_count` equals `staged_record_count`
- **THEN** `rejected_row_count` is zero

### Requirement: Carry non-fatal source notices without rejecting the release

The boundary SHALL provide a `ReleaseNotice` channel separate from `ReleaseDiagnostic`. A notice SHALL NOT affect the disposition, SHALL NOT reject a release, and SHALL NOT be counted in `total_diagnostic_count`.

`ReleaseNotice` SHALL be a frozen type whose fields, types, and invariants are exactly these:

| field | type | invariant |
| --- | --- | --- |
| `code` | `str` | 1 through 64 characters matching `[a-z][a-z0-9_]*` |
| `field_name` | `str \| None` | an approved field name, never a value |
| `physical_row_number` | `int \| None` | one-based when present |

Those SHALL be the whole type, so a notice has nowhere to put a complete row, an arbitrary source value, exception text, a credential, an identity, an address, or a host-local path — the same prohibition a diagnostic carries.

A notice SHALL NOT carry a layout fingerprint. Every carrier exists only after `prepare()` returned, so the fingerprint is a property of the release rather than of each notice, and the outcome already carries it once. Repeating it per notice would create a disagreement that has to be checked and a `None` that has to be interpreted, for provenance the outcome already establishes.

A notice carried on a row envelope SHALL have `physical_row_number` equal to that envelope's, and a disagreement SHALL reject the row with `record_rejected` and SHALL NOT be corrected. An accepted outcome carrying a notice that names a row it did not come from is false lineage, and false lineage on an accepted release is worse than a rejected one, because nothing downstream has cause to doubt it.

Each carrier SHALL bound what it **retains** without rejecting what it observed. `PreparedRelease` and `SourceRowEnvelope` SHALL each carry at most `MAX_CARRIER_NOTICES` retained notices, which is `100`, alongside a preserved total of everything observed and a truncation flag, on the same terms the outcome uses. A carrier SHALL NOT raise on overflow.

Raising would make a non-fatal notice fatal, which contradicts the rule that a notice never rejects: an overflow inside `prepare()` would surface as `layout_rejected` and one inside iteration as `record_rejected`. That is not hypothetical. Dallas emits one `extra_columns_present` per unknown header and its accepted contract sets no limit on how many a release may have, so a release with 101 extra columns would be refused for having too many warnings.

The processor SHALL sum every carrier's preserved total into the outcome's `total_notice_count`, whether retained or not, so the total describes the release rather than any retention window.

A notice code SHALL be a caller-supplied stable identifier of 1 through 64 characters matching `[a-z][a-z0-9_]*`. The boundary SHALL NOT enumerate notice codes, because they are county vocabulary and each county's is closed by its own contract; the accepted Dallas code `extra_columns_present` is an example, not a boundary member. The bound is what keeps a county from putting free text where a code belongs.

Notices SHALL be reportable at two points: on `PreparedRelease`, for an observation about the layout as a whole, and on `SourceRowEnvelope`, for one about a particular row. Dallas's is layout-level, being a fact about the header set rather than any row.

At most 100 notices SHALL be retained per release, the total SHALL be preserved, and truncation SHALL be marked, on the same terms as diagnostics: the retained entries are the first 100 in encounter order, and `len(notices)` equals `min(total_notice_count, 100)`.

#### Scenario: A warning does not reject an accepted release
- **GIVEN** a release whose layout carries one notice and whose rows all pass
- **WHEN** the processor runs
- **THEN** the disposition is `accepted`
- **THEN** `total_diagnostic_count` is zero and the notice is carried on the outcome

#### Scenario: The accepted Dallas warning survives the boundary
- **GIVEN** a reader reporting `extra_columns_present` as a layout notice, as the accepted Dallas contract requires for unknown columns
- **WHEN** the processor runs an otherwise valid release
- **THEN** the release is accepted and the records are committed
- **THEN** the notice appears on the outcome, and no diagnostic does

#### Scenario: A row notice may not claim another row
- **GIVEN** an envelope at physical row 7 carrying a notice reporting row 6
- **WHEN** the processor runs
- **THEN** the row is rejected with `record_rejected`
- **THEN** no accepted outcome carries a notice naming a row it did not come from

#### Scenario: Overflowing notices are truncated, never fatal
- **GIVEN** a layout observing 150 notices, as a Dallas release with 150 unknown columns would
- **WHEN** the carrier is constructed and the processor runs
- **THEN** the carrier retains 100, preserves a total of 150, and marks truncation
- **THEN** no `ValueError` is raised and the release is still accepted
- **THEN** the outcome's `total_notice_count` reflects all 150

#### Scenario: A notice carries no fingerprint of its own
- **GIVEN** any notice on an accepted outcome
- **WHEN** its fields are enumerated
- **THEN** it declares no layout fingerprint
- **THEN** the outcome carries the fingerprint once, for every notice on it

#### Scenario: A notice cannot carry free text
- **GIVEN** a notice code of `Extra Columns!` or one exceeding 64 characters
- **WHEN** the notice is constructed
- **THEN** `ValueError` is raised
- **THEN** the code is not truncated or normalized into an acceptable one

#### Scenario: Notices truncate on the same terms as diagnostics
- **GIVEN** a release producing 150 notices and no diagnostic
- **WHEN** the outcome is inspected
- **THEN** exactly 100 are retained in encounter order and truncation is marked
- **THEN** the disposition is still `accepted`

### Requirement: Emit a bounded, deterministic progress contract

`ReleaseProgressEvent` SHALL be immutable and SHALL carry exactly a `progress_contract_version: int` equal to `PROGRESS_CONTRACT_VERSION`, which is `1`, jurisdiction, release identifier, source member name, parser contract version, layout fingerprint, physical rows processed, staged record count, a deterministic sequence number, and a `final` indicator, and no other field.

Identity fields SHALL come from `PreparedRelease`, so an empty release emits a complete event.

The callback protocol SHALL be synchronous. A non-final event SHALL be emitted after every 100,000 physical rows, and exactly one final event at end-of-input, including for an exact multiple and for an empty release. The final event SHALL precede reader close, finalization, and commit.

Sequence numbers SHALL be deterministic and gapless within a release, starting at zero.

A callback that raises SHALL reject and abort the release with `progress_callback_failed`, and its exception text SHALL NOT be retained.

#### Scenario: Both contract versions are pinned
- **GIVEN** `BOUNDARY_CONTRACT_VERSION` and `PROGRESS_CONTRACT_VERSION`
- **WHEN** their values are read
- **THEN** both are the integer `1`
- **THEN** every outcome carries the first and every progress event carries the second

#### Scenario: An exact multiple still emits one final event
- **GIVEN** a release of exactly 200,000 physical rows
- **WHEN** the processor runs
- **THEN** non-final events are emitted at 100,000 and 200,000
- **THEN** exactly one final event is emitted last, with sequence numbers 0, 1, 2

#### Scenario: An empty release still emits one complete final event
- **GIVEN** a release containing no physical rows
- **WHEN** the processor runs
- **THEN** no non-final event is emitted and exactly one final event is
- **THEN** its identity fields are populated entirely from the prepared release

#### Scenario: A failing final callback prevents the commit
- **GIVEN** a small release whose rows all pass, and a callback that raises on the final event
- **WHEN** the processor runs
- **THEN** the release is rejected with `progress_callback_failed`
- **THEN** `finalize` and `commit` are never called and the stage is aborted

### Requirement: Reject input-proportional read-ahead without forbidding bounded buffering

The conformance suite SHALL detect input-proportional accumulation by construction, not by observing memory.

It SHALL drive a candidate reader from a **guarded pull source** recording every pull, and SHALL compute the *lead* as source pulls minus **row envelopes the processor has consumed**.

The denominator SHALL NOT be records written. A physical row may produce zero or several records, so records and rows are different quantities; and the processor deliberately stops writing at the first rejected row while continuing to read, so a conforming reader on a rejected release would show a lead that grows without bound against a frozen write count. Envelopes consumed is the only quantity that advances once per row for exactly as long as the reader is pulling.

A reader conforms if its maximum observed lead does not exceed the approved constant **and does not grow with release size**. The approved constant SHALL be declared as a named value in the conformance suite and SHALL be 64 envelopes, which admits a fixed block buffer while remaining far below any fixture length. The suite SHALL run the same reader over two fixtures of 1,000 and 8,000 envelopes and require the maximum lead to be equal in both; both lengths exceed the constant by more than an order of magnitude, so a reader that materializes its member reports a maximum lead near 1,000 in one and near 8,000 in the other and cannot pass.

A reader holding a constant-size buffer conforms, because its lead is the same at either length. A reader that materializes its member does not, because its lead scales with the member.

A county SHALL enter the suite through a **reader factory** taking the guarded source, so a real county reader is exercised by the same harness as a synthetic one.

This requirement SHALL observe pull and envelope-consumption order only. It SHALL NOT depend on measured memory, and SHALL read no resident set size, cgroup file, or allocation counter.

#### Scenario: A bounded buffer conforms at both fixture lengths
- **GIVEN** a reader that holds a fixed block of rows ahead of the processor
- **WHEN** the suite drives it over the 1,000-envelope and 8,000-envelope fixtures
- **THEN** the maximum lead does not exceed 64 in either
- **THEN** the two maxima are equal and the reader passes

#### Scenario: An eager reader fails
- **GIVEN** a reader that consumes the guarded source fully before yielding
- **WHEN** the suite drives it over the same two fixtures
- **THEN** the maximum lead is near 1,000 in one and near 8,000 in the other
- **THEN** the maxima differ and the reader fails

#### Scenario: The metric survives a rejected release
- **GIVEN** a conforming single-pass reader over a release whose first row is rejected
- **WHEN** the processor stops writing and continues reading to collect diagnostics
- **THEN** the lead is measured against envelopes consumed, not records written
- **THEN** the reader still conforms, because its lead does not grow while the write count is frozen

#### Scenario: The check needs no memory measurement
- **GIVEN** the conformance suite
- **WHEN** its implementation is inspected
- **THEN** it observes pull and envelope-consumption order only
- **THEN** it reads no resident set size, cgroup file, or allocation counter

### Requirement: Keep the dependency direction one-way without stranding county readers

The `property_tax_adapters.release` package SHALL import no county module.

A county module MAY import the neutral contract surface — the release records and protocols — because a county reader must construct `PreparedRelease` and `SourceRowEnvelope` values to satisfy the protocol at all. Forbidding that would make the boundary unimplementable by the counties it exists for.

A county module SHALL NOT import the processor. Driving a release is the caller's job, not a county's, and a county that imported the processor could invoke a release from inside a parser.

#### Scenario: The boundary depends on no county
- **GIVEN** each module in `property_tax_adapters.release` parsed with `ast` and its docstrings removed
- **WHEN** its imports are collected
- **THEN** no import resolves to a county module or a third-party package

#### Scenario: A county may build envelopes but may not drive releases
- **GIVEN** each county module parsed with `ast`
- **WHEN** its imports are collected
- **THEN** importing the release records or protocols is permitted
- **THEN** importing the release processor is not

### Requirement: Keep the Dallas whole-member helper out of the production path

`parse_dallas_appraisal_csv` SHALL remain a synthetic fixture and contract helper, SHALL NOT be wrapped as the production streaming boundary, and no production DAG or release processor SHALL import or invoke it.

All 52 existing Dallas contract cases SHALL remain collected unchanged, or migrate case-for-case with no scenario lost.

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

It SHALL state that the 900 MiB target supersedes the issue body's 1 GiB wording, because the scheduler's measured 400 MiB peak shares the same 4 GiB container.

It SHALL state that the `ResourceGuard` protocol fixes when the boundary asks and never what is measured, and that the vocabulary is twelve codes because D5's eight are a minimum and four lifecycle failures would otherwise have no code.

It SHALL state that durable quarantine persistence and the production unique index remain owned by bootstrap tasks 3.4 and 3.5, and that the SQLite stage is a test fixture rather than a production stage.

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
