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
release/protocols.py    PreparedReader, ReleaseStage, ProgressCallback  (typing.Protocol)
release/outcome.py      ReleaseOutcome, ReleaseDiagnostic, ReleaseDiagnosticCode
release/progress.py     ReleaseProgressEvent
release/processor.py    process_release(reader, stage, ...) -> ReleaseOutcome
```

The processor is a function, not a class (D10). It receives a reader and a stage the caller opened, drives D2's order, and returns a bounded outcome. Nothing survives the call.

### The order, and why each step is where it is

```
1  open the immutable source through the county reader
2  validate the complete layout, capture the fingerprint      <- before any stage exists
3  open one atomic stage for the logical release
4  per row: decode, validate, write to the invisible stage    <- progress every 100,000
5  finalize release-wide checks after end-of-input
6  commit exactly once
```

Step 2 precedes step 3 deliberately: a layout failure must occur before the first stage write, so a misidentified member never opens a stage at all. Step 5 is where duplicate detection lands, because the stage holds the index and the processor holds no key set (D4).

### What each protocol owes

`PreparedReader` is a context manager. It exposes the layout fingerprint and parser contract version *after* preparation and before iteration, so the processor can record provenance without reading a row. Iterating yields one validated observation at a time; a reader that materialized its member first would satisfy the type and defeat the purpose, so the conformance suite drives readers with a generator that would exhaust memory if consumed eagerly.

`ReleaseStage` is a context manager with `write`, `finalize`, `abort`, and `commit`. Its contract is the atomicity guarantee: nothing written is visible until `commit` returns, and `abort` or a failed `commit` exposes zero accepted records. Duplicate keys are the stage's job, reported as `duplicate_record_key`.

`ProgressCallback` is synchronous and returns nothing. A callback that raises rejects the release — progress is part of the contract, not a best-effort notification, because a DAG that silently loses progress cannot tell a stalled release from a slow one.

## Dependency direction

`release` → `sources.contracts` → standard library. The release package imports no county module, and no county module imports the release package. A county is a *supplier* of a reader, not a dependency of the boundary, which is what lets the test stage and the conformance suite exist without any county at all.

An architecture test asserts both directions, parsing the AST and stripping docstrings.

## Data and contract changes

Four new types and one function. No existing type changes. `parse_dallas_appraisal_csv` is untouched, and a test asserts the release package does not import it (D6).

## Alternatives considered

- **An iterator instead of a stage.** Rejected by the accepted county contracts, not by preference: a failed release must publish zero accepted records, and an iterator has already yielded by the time a later row fails.
- **A processor class holding reader and stage.** Rejected under D10. State that survives a call is state that can leak between releases, and the caller already owns both resources' lifetimes.
- **Abstract base classes rather than `Protocol`.** Rejected under D9. Inheritance would make the boundary a framework a county must join; structural typing lets a county keep owning its parsing and lets the test stage conform without importing a county.
- **Deferring the diagnostic vocabulary to change two with the rest of D5.** Rejected: the outcome type would have no codes, and `resource_limit_exceeded` would be declared and unreachable — the exact defect the Ellis review rejected.
- **A disk spool to bound memory.** Explicitly forbidden by D1 without separate approval of volume, byte limit, cleanup, and retry.

## Decisions and assumptions

D1 through D8 are issue #43's; D9 through D11 are proposed here and stated in the proposal.

Assumptions, both checkable at implementation time:

- A caller-supplied resource bound is enough to make `resource_limit_exceeded` reachable without measuring RSS. If it is not, the code stays unreachable until change two, and that would be a finding rather than an acceptable gap.
- SQLite's `UNIQUE` constraint and transaction semantics are sufficient for the test stage's duplicate rejection and rollback. `sqlite3` is standard library, so this adds no dependency.

## Unresolved decisions

- None.

## Risks and compatibility

The boundary is new, so nothing existing changes behaviour and the 52 Dallas cases are untouched. The risk is subtler: a conformance suite that only checks *shape* would pass a reader that materializes its whole member, which is precisely the defect this change exists to prevent. The suite therefore drives readers with input that cannot be consumed eagerly, and asserts on observed peak retention rather than on types alone.

The second risk is the test stage becoming the specification by accident. It exists to prove the conformance suite has at least one passing implementation; the suite is the contract, and a production stage that satisfies it is bootstrap task 3.4's work.

## Rollout and failure recovery

Protocols and outcome first, then the processor, then the conformance suite and test stage, then documentation. Each lands independently. Nothing is wired into a county or a DAG, so a defect here cannot affect a parser that ships today.

## Testing strategy

Conformance tests prove the D2 order by construction: a layout failure with a stage that records whether it was ever opened, and a row failure after the first staged write with a stage that records whether `abort` ran. D3's three rejection points each get a test — before staging, after the first staged record, and during finalize and commit.

Progress tests cover the boundary cases D8 names specifically: an exact multiple of 100,000, and an empty release, both of which must still emit exactly one final event.

Privacy tests assert the outcome carries no exception text, no complete row, no arbitrary value, and no host-local path, driven by a stage and a reader that raise with identifiable secrets in their messages, so a leak fails rather than being argued about.

Architecture tests assert the dependency direction both ways and that no county module is imported.
