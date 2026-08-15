## Why

PR #42 measured what the current Dallas API costs: 165 MiB retained on 50,000 rows, and **663 MiB on 200,000**, against a scheduler capped at 4 GiB running `AIRFLOW__CORE__PARALLELISM=4`. Memory grows linearly with row count because `parse_dallas_appraisal_csv` accepts `bytes | str` and retains both county-native and converted tuples.

That API cannot become the production DAG boundary, and swapping it for an iterator is not enough: every accepted county contract requires a failed logical release to commit or publish **zero** accepted records, which an iterator alone cannot promise.

Issue #43 decides how to close this. D7 — the shared records — landed in PR #80. This change implements the rest of the boundary.

## Outcome

Add `property_tax_adapters.release`: a prepared-reader protocol, an atomic release-stage protocol, a bounded outcome, a progress-event contract, and the processor that drives them. A county reader validates its layout before a stage is opened, yields one validated observation at a time, and the processor stages records that stay invisible until exactly one commit.

## Scope

- Originating issue: #43, decisions **D1, D2, D3, D4, D6, D8**, and the diagnostic half of **D5**
- Affected capability: bounded-release-processing (ADDED)

## The split, and where D5 actually falls

Review proposed two changes: this one, then resource enforcement and the benchmark. That split is right, but D5 does not sit wholly on one side of it.

| D5 states | belongs to |
| --- | --- |
| diagnostics capped at 100 retained, total preserved, truncation marked | **this change** |
| the stable boundary codes, which D5 gives as a minimum of eight | **this change**, at twelve |
| exception text, complete rows, arbitrary values, credentials, identities, addresses, host paths prohibited | **this change** |
| 1,000,000 rows, 90 columns, under 900 MiB peak RSS | change two |
| memory must not grow linearly with row count | change two |
| cgroup `memory.peak`, `ru_maxrss` fallback, `tracemalloc` insufficient | change two |
| the reproducible benchmark command | change two |

The processor cannot emit an outcome without codes to put in it, and cannot cap diagnostics it does not produce. Deferring those to change two would leave this change specifying an outcome type with no vocabulary. The resource *target* and how to *measure* it are genuinely separable and are deferred.

Note that D5 supersedes the issue body: the target is **under 900 MiB**, not 1 GiB, because the scheduler's measured 400 MiB peak shares the same 4 GiB container.

## Constraints

Authorized paths are `libs/property-tax-adapters/`, its tests and synthetic generators, stage conformance fixtures, directly related engineering documentation, and this change.

Not authorized, and not present here: DAGs, services, network acquisition, database migrations, durable persistence, Bronze/Silver/Gold publication, infrastructure, workflows, deployment, `property_tax_domain` or `property_tax_application` changes, owner publication, or any production-ready claim.

- No new dependency. The standard library only, including the test stage.
- No implicit disk spool. D1 forbids one, and any future spool needs its own approved bounded volume, byte limit, cleanup contract, and retry behaviour.
- The processor never retains the complete key set, so duplicate detection belongs to the stage.
- Layout fingerprinting, release-level atomicity, bounded diagnostics, provenance, exact-decimal handling, and dependency direction are not weakened.
- Synthetic, identity-free, redistribution-safe fixtures only. No county releases, owner data, addresses, credentials, or production records, and no committed million-row fixture.

## Non-goals

- The resource target, its measurement, and the benchmark — change two, which depends on this.
- Durable quarantine persistence, owned by bootstrap task 3.4, and the PostgreSQL unique index, owned by tasks 3.4 and 3.5.
- A production Dallas reader. D6 says a future one implements this protocol directly; none is written here.
- Unblocking Tarrant's remaining conversion work, which stays in its own change.

## Decisions

D1 through D8 below are **issue #43's decisions**, numbered to match it exactly so a reader can map one to one. D9 onward are proposed by this change to close gaps those decisions leave open, and merging is what accepts them.

- **D1** (issue #43): the production boundary is a single-pass, context-managed county reader plus a caller-supplied atomic release stage. A prepared reader validates layout before the stage opens, then yields one validated observation at a time. The processor stages records and never returns or yields accepted production records. Whole-release `bytes | str -> tuple` APIs are not production inputs. No implicit disk spool.
- **D2** (issue #43): open the source, validate the complete layout and capture its fingerprint, open one atomic stage, decode and validate each row writing only to the invisible stage, finalize release-wide checks after end-of-input, and commit exactly once after everything succeeds. No accepted record is consumer-visible during those steps.
- **D3** (issue #43): reader, parser, row-validation, duplicate, resource-guard, progress-callback, stage-write, finalize, or commit failure rejects the logical release. Rejection aborts the stage **if the stage was entered** and returns a bounded rejected outcome, never staged records. A failure before the stage opens calls no abort, because D2 says no stage exists to abort. Aborted or failed commits expose zero accepted records. Tests prove rejection before staging, after the first staged record, and during finalize and commit.
- **D4** (issue #43): the processor does not retain the complete key set. Duplicate and other release-wide constraints are enforced by the stage through a bounded external unique index. This change provides a stage conformance suite and a standard-library test stage proving duplicate rejection and rollback, with a caller-supplied directory, an explicit ceiling, and cleanup on success, failure, and retry.
- **D5** (issue #43, diagnostic half only): diagnostics are capped at 100 retained per release, the total is preserved, and truncation is marked deterministically. The stable codes are `layout_rejected`, `record_rejected`, `duplicate_record_key`, `stage_write_failed`, `stage_finalize_failed`, `stage_commit_failed`, `progress_callback_failed`, and `resource_limit_exceeded`. Exception text, complete rows, arbitrary values, credentials, identities, addresses, and host-local paths are prohibited.
- **D6** (issue #43): `parse_dallas_appraisal_csv` remains a synthetic fixture helper, is not wrapped as the production boundary, and no production processor imports or invokes it. All 52 Dallas cases remain collected unchanged or migrate case-for-case.
- **D8** (issue #43): an immutable `ReleaseProgressEvent` and a synchronous callback protocol, carrying only the progress contract version, jurisdiction and bounded release identity, parser contract version and layout fingerprint, physical rows processed, staged adapter records, a deterministic sequence number, and a `final` indicator. A non-final event after every 100,000 physical rows and exactly one final event at end-of-input, including for an exact multiple and for an empty release. Callback failure rejects the release with `progress_callback_failed`, and callback exception text is not retained.
- **D9** (proposed by this change): the protocols are `typing.Protocol` classes, not base classes a county must inherit. A county adapter already owns its parsing; requiring inheritance would invert that and make the boundary a framework. Structural typing also lets the test stage satisfy the contract without importing anything county-specific.
- **D10** (proposed by this change): the processor is a function over a reader and a stage, not an object holding either. Nothing survives a call, so no release state can leak into the next one, and the caller keeps the lifetime of both resources it supplied.
- **D11** (proposed by this change): the boundary declares a `ResourceGuard` protocol with one synchronous method taking the physical rows processed and the staged record count and returning nothing; a guard that raises rejects with `resource_limit_exceeded`. The processor calls it at exactly three kinds of checkpoint and no others — once after the stage opens and before the first write, once at every 100,000-row boundary alongside the progress event, and once at end-of-input before finalization — so the call sequence is a function of the row count and is identical across runs. The boundary fixes **when** it asks and never **what** is measured: units, probe, and target are the guard's, and change two supplies a measuring implementation. A guard that measures nothing and never raises conforms, and is the default. This replaces the earlier "caller-supplied bound", which named no resource, units, probe, cadence, or failure mechanism and was an assumption wearing a decision's clothes.
- **D12** (proposed by this change): the reader exposes `PreparedRelease` metadata before iteration and yields one `SourceRowEnvelope` per physical row, carrying the row number, the zero or more records that row produced, and a bounded rejected indicator. The indicator is not decoration: without it a zero-record envelope cannot be told from an invalid row, and a reader that signalled invalidity by raising would end iteration at the first bad row, making the 100-entry retention cap unreachable and reporting one defect where a member has many. On the first rejection the processor stops writing and keeps reading, which is what the accepted county parsers already do. Yielding bare records cannot support D8, which counts physical rows and staged records separately: one accepted Collin row already produces one record per observed family, and an empty release yields no record from which to take an identity at all. The envelope makes row completion explicit and lets both counts come from one traversal.
- **D13** (proposed by this change): the vocabulary is exactly **twelve** codes and the failure-to-code mapping is an exhaustive table. D5 gives eight as a minimum; the boundary can genuinely reach four more lifecycle failures — opening a source, entering a stage, aborting one, and closing a reader — and a failure with no code would have to borrow one naming a different phase. Reporting a reader that fails to open as `layout_rejected` would name a phase that had not begun, which is the borrowing this decision exists to prevent. A stage signals a duplicate by raising the typed `DuplicateRecordKey`, from `write` where an eager index detects it or from `finalize` where a deferred index does; both map to `duplicate_record_key`, because requiring detection at `write` would exclude any bulk-loaded stage. Without a typed signal the processor would have to read exception text, which the privacy rules forbid.
- **D14** (proposed by this change): `release_identifier` and `source_member_name` are each 1 through 128 characters of `[A-Za-z0-9._-]` not beginning with `.` or `-`, which is the bound the accepted Tarrant contract already sets for the same two fields. Adopting it rather than inventing a second one keeps one rule in the repository, and its alphabet admits no path separator, so a host-local path is unrepresentable in a progress event rather than merely prohibited by prose.
- **D15** (proposed by this change): the conformance suite rejects **input-proportional** accumulation, not buffering. It drives a candidate reader from a guarded pull source and computes the lead as pulls minus **row envelopes the processor has consumed** — not records written. Records are the wrong denominator twice over: a row may produce zero or several, and the processor deliberately stops writing at the first rejected row while continuing to read, so a conforming reader on a rejected release would show a lead growing against a frozen write count. The maximum lead must stay within a declared constant of 64 envelopes *and* be identical across fixtures of 1,000 and 8,000 envelopes. A constant-size one-row buffer conforms, because its lead does not grow; a reader that materializes its member does not. An earlier draft required pulls at most equal to rows written, which would have failed a legitimate bounded buffer, and the draft before that depended on a generator that "would exhaust memory", which is resource behaviour this change defers.

- **D16** (proposed by this change): the release package imports no county module, and a county module may import the neutral contract surface — the release records and protocols — but not the processor. A county reader must construct `PreparedRelease` and `SourceRowEnvelope` values to satisfy the protocol at all, so a blanket prohibition would make the boundary unimplementable by the counties it exists for. Importing the processor stays prohibited: driving a release is the caller's job, and a county that could invoke one from inside a parser would invert the boundary.
- **D17** (proposed by this change): before writing, the processor verifies that a record's jurisdiction, release identifier, source member name, parser contract version, and layout fingerprint equal the prepared release's, and that its provenance row number equals its envelope's. A disagreement rejects the row and is never corrected. A record that disagrees with the release it arrived in is evidence of a reader defect, and staging it would attribute a row to a release or a position it did not come from.
- **D18** (proposed by this change): the outcome carries `physical_rows_processed`, `staged_record_count`, `committed_record_count`, and `rejected_row_count`, and no ambiguous accepted or rejected count. Once D12 separates rows from records, one number cannot mean both, and a staged record is not an accepted one until the commit that makes it visible.
- **D19** (proposed by this change): every operation that may fail completes before the commit. The reader is closed *before* committing, so no reader failure can occur after records become visible, and a stage's exit may not fail after **either** a commit or an abort, which is what makes it safe to place last. A stage exit that raises regardless is a defect in trusted code and propagates rather than becoming a diagnostic, exactly as a malformed `PacsLayout` raises `ValueError` rather than diagnosing; giving it a code would imply the boundary can absorb a stage that does not meet its contract. No outcome may report rejection after a commit succeeded.

- **D20** (proposed by this change): `layout_fingerprint` and `parser_contract_version` on the outcome are optional and are `None` when the failure preceded a successful preparation; `boundary_contract_version` is always populated because it is the boundary's own constant. Both come from the same `PreparedRelease`, so they are set together or not at all and a half-populated outcome cannot occur. A `source_open_failed` outcome has no reader to have produced either, and a `layout_rejected` one has no completed preparation, whatever a reader computed internally before failing. Declaring them always-present would force an implementation to invent a placeholder, and a fabricated fingerprint is worse than an absent one because a diagnostic could not tell the two apart.

**Provenance.** Issue #43's decision comments are the authoritative input. D1 through D8 restate them; where wording is condensed, the comment governs. D9 through D20 are this change's own and no prior maintainer selection is claimed for them. D14 adopts a bound the accepted Tarrant contract already sets rather than proposing a new one.

## Unresolved decisions

- None.

## Cross-issue boundaries

- #17 (related_to): the Dallas fixture helper D6 preserves.
- #60 (related_to): a Dallas production reader implementing this protocol is that issue's work, and remains blocked on #78 for live source material.

This draft requires human maintainer approval before implementation. No decision recorded here is accepted until an authorized maintainer merges this change.
