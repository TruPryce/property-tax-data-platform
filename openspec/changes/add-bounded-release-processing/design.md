## Current-state evidence

Read on `main` at the time of drafting.

`libs/property-tax-adapters/src/property_tax_adapters/` contains `sources/contracts.py`, `sources/pacs.py`, and six county modules. There is **no** reader protocol, no stage, no processor, and no progress event anywhere in the library — a search for `Protocol`, `ReleaseStage`, and `ReleaseProgressEvent` returns nothing. This is greenfield.

Every county entry point today takes a whole member and returns a report: `parse_dallas_appraisal_csv(bytes | str)`, `validate_certified_member`, `validate_property_member`, `validate_child_member`, and their materializing siblings. Those siblings return `tuple[...]` of records built in memory. That shape is exactly what D1 excludes from production, and it is why the boundary has to be new rather than adapted.

What already exists and this change builds on:

- `AppraisalSourceRecord`, `SourceProvenance`, `SourceNativeValue` from PR #80, which is what a reader yields and a stage writes.
- The per-county diagnostic pattern — a closed vocabulary, a four-field diagnostic, a 100-entry cap with the total preserved. The boundary needs its own vocabulary, and copying that shape keeps one idea in the codebase rather than two.
- `materialize_*` entry points that reuse validation rather than repeating it. The prepared reader is the streaming form of the same idea.

## Proposed architecture

One new package, `property_tax_adapters.release`:

```
release/protocols.py    PreparedReader, ReleaseStage, ProgressCallback, ResourceGuard
release/records.py      PreparedRelease, SourceRowEnvelope
release/outcome.py      ReleaseOutcome, ReleaseDiagnostic, ReleaseDiagnosticCode,
                        DuplicateRecordKey
release/progress.py     ReleaseProgressEvent
release/processor.py    process_release(reader, stage, ...) -> ReleaseOutcome
```

The processor is a function, not a class (D10). It receives a reader and a stage the caller opened, drives D2's order, and returns a bounded outcome. Nothing survives the call.

### The order, and why each step is where it is

```
 1  enter the county reader
 2  prepare, validate the layout, capture PreparedRelease   <- before any stage exists
 3  enter the stage
 4  guard checkpoint, before the first write
 5  per row envelope: verify agreement, write records       <- progress + guard every 100,000
 6  end-of-input: guard checkpoint, then the final progress event
 7  exit the reader                                         <- last failable cleanup
 8  finalize
 9  commit exactly once
10  exit the stage                                          <- may not fail, by contract
```

Step 2 precedes step 3 deliberately: a layout failure must occur before the first stage write, so a misidentified member never opens a stage at all. That also means a pre-stage failure calls no `abort` — there is nothing to abort, and requiring one would contradict the step that says no stage was created.

Step 5 precedes steps 6 and 7 for a reason that is easy to get backwards. A final progress callback that raises must be able to reject the release, and it can only do that while zero records are still visible. Emitting the final event after the commit would leave a callback able to report a failure it can no longer prevent.

Steps 7 through 10 are ordered so that **nothing failable follows the commit** (D19). The reader is closed at step 7, before committing, because a reader that fails on close after a successful commit would otherwise force the outcome to report rejection while records were already visible. A stage's exit may not fail after a successful commit, which is what makes step 10 safe to place where it is.

Duplicate detection is the stage's, because it holds the index and the processor holds no key set (D4). A stage may raise `DuplicateRecordKey` from `write` if its index is eager or from `finalize` if it is deferred; both map to the same code. Requiring one point would exclude bulk-loaded stages, which is most relational ones.

### What each protocol owes

`PreparedReader` is a context manager. After preparation and before iteration it exposes a `PreparedRelease` carrying the jurisdiction, release identifier, source member name, layout fingerprint, and parser contract version — the whole identity, so an empty release still emits a complete progress event. Taking identity from the first record would work only for releases that have one.

Iterating yields a `SourceRowEnvelope` per **physical row**, not a bare record. D8 counts physical rows and staged records separately, and the two are not the same number: one accepted Collin row already produces one record per observed family, and a row may produce none. Yielding bare records would force the processor to infer row boundaries it cannot see.

The envelope also carries a bounded rejected indicator, and that is what makes a zero-record envelope legible: without it, a row that legitimately produced nothing and a row that was invalid look identical. A reader signals invalidity by marking the envelope, never by raising — raising ends iteration at the first bad row, which would report one defect for a member with many and would make the 100-entry cap unreachable. On the first rejection the processor stops writing and keeps reading, which is exactly what the accepted county parsers do.

`ReleaseStage` is a context manager with `write`, `finalize`, `abort`, and `commit`. Its contract is the atomicity guarantee: nothing written is visible until `commit` returns, and `abort` or a failed `commit` exposes zero accepted records.

Duplicate keys are the stage's job, and it signals one by raising the typed `DuplicateRecordKey`. Any other exception from `write` is an ordinary write failure. The alternative — inspecting exception text — is forbidden by the privacy rules and could not be relied on across implementations anyway, so the distinction is carried by type.

`ResourceGuard` is one synchronous method over the row and record counts, called at checkpoints the processor fixes and the guard cannot influence. The boundary defines *when* it asks; what is measured, in what units, by what probe, is the guard's and change two's. A guard that measures nothing conforms, and is the default.

`ProgressCallback` is synchronous and returns nothing. A callback that raises rejects the release — progress is part of the contract, not a best-effort notification, because a DAG that silently loses progress cannot tell a stalled release from a slow one.

## Dependency direction

`release` → `sources.contracts` → standard library. The release package imports no county module.

The reverse is not a blanket prohibition, and an earlier draft made it one by mistake. A county reader has to construct `PreparedRelease` and `SourceRowEnvelope` values to satisfy the protocol at all, so a county module **may** import the release records and protocols. What it may not import is the processor: driving a release is the caller's job, and a county able to invoke one from inside a parser would invert the boundary (D16).

An architecture test asserts each direction separately, parsing the AST and stripping docstrings.

## Data and contract changes

Six new frozen types, one typed exception, four protocols, and one function. No existing type changes. `parse_dallas_appraisal_csv` is untouched, and a test asserts the release package does not import it (D6).

## Alternatives considered

- **An iterator instead of a stage.** Rejected by the accepted county contracts, not by preference: a failed release must publish zero accepted records, and an iterator has already yielded by the time a later row fails.
- **A processor class holding reader and stage.** Rejected under D10. State that survives a call is state that can leak between releases, and the caller already owns both resources' lifetimes.
- **Abstract base classes rather than `Protocol`.** Rejected under D9. Inheritance would make the boundary a framework a county must join; structural typing lets a county keep owning its parsing and lets the test stage conform without importing a county.
- **Deferring the diagnostic vocabulary to change two with the rest of D5.** Rejected: the outcome type would have no codes, and `resource_limit_exceeded` would be declared and unreachable — the exact defect the Ellis review rejected.
- **A disk spool to bound memory.** Explicitly forbidden by D1 without separate approval of volume, byte limit, cleanup, and retry.

## Decisions and assumptions

D1 through D8 are issue #43's; D9 through D15 are proposed here and stated in the proposal.

`resource_limit_exceeded` is reachable here without measuring anything, because the guard protocol makes reachability a property of the *contract* rather than of a measurement: a test guard that raises on its second call provokes the code deterministically. That is the difference between the current D11 and the earlier draft, which described a "caller-supplied bound" with no resource, units, probe, cadence, or failure mechanism and then called its sufficiency an assumption.

One assumption remains, checkable at implementation time: SQLite's `UNIQUE` constraint and transaction semantics are sufficient for the test stage's duplicate rejection and rollback. `sqlite3` is standard library, so this adds no dependency.

## Unresolved decisions

- None.

## Risks and compatibility

The boundary is new, so nothing existing changes behaviour and the 52 Dallas cases are untouched. The risk is subtler: a conformance suite that only checks *shape* would pass a reader that materializes its whole member, which is precisely the defect this change exists to prevent.

The suite therefore drives a candidate reader from a **guarded pull source** that records the interleaving of pulls and writes, computes the *lead* as pulls minus records written, and requires the maximum lead to stay within a declared constant **and to be identical across two releases of materially different length**. A county enters through a **reader factory** taking that source, so a real county reader is exercised by the same harness as a synthetic one rather than being asserted about in prose.

Comparing two lengths is the part that matters. An earlier draft required pulls to be at most the number of rows written, which is a stricter rule than the property being protected: it fails a reader holding one row of constant-size lookahead, whose memory is perfectly bounded. What must be rejected is accumulation that *scales with the input*, and a lead that is the same at both lengths cannot be scaling.

This is deliberately structural. An earlier draft proposed a generator that "would exhaust memory if consumed eagerly", which depends on the resource behaviour this change defers to change two and would not fail deterministically. Read-ahead is observable without measuring memory, and observing it that way keeps the two changes genuinely separable.

The second risk is the test stage becoming the specification by accident. It exists to prove the conformance suite has at least one passing implementation; the suite is the contract, and a production stage that satisfies it is bootstrap task 3.4's work.

## Rollout and failure recovery

Protocols and outcome first, then the processor, then the conformance suite and test stage, then documentation. Each lands independently. Nothing is wired into a county or a DAG, so a defect here cannot affect a parser that ships today.

## Testing strategy

Conformance tests prove the D2 order by construction: a layout failure with a stage that records whether it was ever opened, and a row failure after the first staged write with a stage that records whether `abort` ran. A pre-stage failure additionally asserts `abort` was *not* called, which is the lifecycle rule the earlier draft contradicted.

D3's rejection points each get a test — before staging, after the first staged record, during finalize, and during commit. The failure-to-code mapping gets one test per row of its table, so no phase can quietly borrow another's code.

Progress tests cover the boundary cases D8 names specifically: an exact multiple of 100,000, and an empty release, both of which must still emit exactly one final event, the empty one populated entirely from `PreparedRelease`. A separate test raises from the *final* callback on a small release and asserts `finalize` and `commit` were never called — the case that distinguishes a progress contract that can prevent a commit from one that merely reports after it.

Guard tests assert the checkpoint sequence exactly: after the stage opens, at each 100,000-row boundary, and once at end-of-input, with two runs over one member producing identical sequences.

Privacy tests assert the outcome carries no exception text, no complete row, no arbitrary value, and no host-local path, driven by a stage and a reader that raise with identifiable secrets in their messages, so a leak fails rather than being argued about.

Architecture tests assert the dependency direction both ways and that no county module is imported.
