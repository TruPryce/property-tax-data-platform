# Design: Processing run values

## Context

Five values, owned by the application, that two other changes need before either can be
implemented. They are extracted from `add-application-port-boundary` rather than invented: the
contracts below are the ones that change's `processing-run` capability already settled, and what is
new here is only the separation of the **values** from the **lifecycle** that uses them.

The separation has a specific cause. `add-canonical-load-session` carries a run reference and an
outcome in its signatures, could not import types that did not exist, and its first implementation
substituted local structural protocols. The review measured what that cost: an empty
runtime-checkable protocol returns `True` for `isinstance(None, …)`, `isinstance(7, …)` and
`isinstance("raw-run-id", …)`, so the substitute accepted exactly the raw persistence value the
reference type exists to keep out. A permissive stand-in is not a bridge.

## Why the reference is a type and not the value it wraps

`ingestion.run.run_id` is `GENERATED ALWAYS AS IDENTITY`. A port that accepted the bare integer
would let a caller pass a number it made up, or one it read from somewhere unrelated, and nothing in
the signature would say that is wrong. `ProcessingRunRef` says it: the value is produced where the
run is recorded, and a caller that has one has a run.

It is an **opaque locator** on the same terms as every other persistence-generated handle that
crosses this boundary — equality and hashing, no ordering. Ordering is the tempting mistake, because
the wrapped value really is ascending in practice; the contract refuses it, and a test asserts the
refusal, because a caller sorting by it would be reading a persistence detail as a business fact.

Hashing is not optional. These references are dictionary keys in every implementation that tracks
runs, and a locator that cannot be hashed is a locator that cannot be looked up.

## Why the outcome is the application's own

The adapters already have `ReleaseOutcome`, and the dependency-direction test forbids importing it.
So the application holds its own, and the mapping between them is **total in both directions**: no
adapter outcome is unrepresentable here, and no value here is unrecordable there. A partial mapping
would mean a release that processed successfully and then could not be described at the boundary.

The same reasoning gives the application its own `BOUNDARY_CONTRACT_VERSION`. It cannot import the
adapters' constant, and a copy that drifts is worse than no copy — a value the boundary accepts
would fail the persisted check that pins it. The architecture test asserts the two are equal, which
is the only place in this change that reads the adapters at all, and it is a test rather than the
package.

## The evidence seal, and why it is refused here rather than at commit

`ingestion.assert_outcome_evidence_agrees` runs at COMMIT. An outcome that declares one diagnostic
and retains none satisfies every field-level rule and aborts the canonical transaction — after the
records were written, in a transaction that then has to be undone. So the seal is part of the value:
retained counts equal `least(total, bound)`, each truncation flag is true exactly when its total
exceeds the bound, and every retained diagnostic carries the outcome's layout fingerprint, including
where the outcome carries none.

Two codes, two rules, and they are deliberately not the same rule. A diagnostic code is checked
against the **closed** vocabulary the accepted bounded-processing contract declares, because
`ingestion.release_diagnostic` carries `CHECK (code IN (...))`. A notice code is checked against a
**bounded lowercase grammar**, because `ingestion.release_notice` carries
`CHECK (code ~ '^[a-z][a-z0-9_]{0,63}$')` and the accepted notice contract validates against a
pattern rather than an enum. Reusing the diagnostic set for notices would refuse notices the
database accepts; reusing the grammar for diagnostics would accept diagnostics the database refuses.

## The falsification matrix

The authoritative list of what the suite proves.

- `ProcessingRunRef` compares by equality, hashes, and **raises on every ordering comparison**; a
  port annotated for it does not accept the raw wrapped value.
- `ReleaseDisposition` is closed, and the mapping to the adapters' vocabulary is total in both
  directions — enumerated, not asserted.
- A diagnostic code outside the closed vocabulary is refused; a notice code that is a well-formed
  bounded lowercase identifier outside that vocabulary is **accepted**, because the notice
  vocabulary is open; a malformed notice code is refused.
- A parser contract version without a layout fingerprint, or the reverse, is refused.
- The seal is falsified in each direction: retained counts disagreeing with a declared total below
  the bound, a total above the bound retaining other than the bound, each truncation flag set
  against its total, and a retained diagnostic whose layout fingerprint differs from the outcome's —
  including where the outcome carries none.
- A boundary contract version other than the constant is refused, and the application's constant
  equals the adapters'.
- Every value is frozen, and a bounded field refuses an unbounded one.

## Handoffs

**To `add-canonical-load-session`.** Tasks 1.2 and 2.1 import `ProcessingRunRef` and
`ReleaseProcessingOutcome` from here. The session carries the reference opaquely and reads exactly
one thing from the outcome — its disposition, which selects a completion branch.

**To `add-application-port-boundary`.** Its `processing-run` capability keeps the lifecycle: start
with the held-run refusal and the abandoned-run resume, finish, and the repository that does both.
It cites these values rather than defining them, and its task 1.1 shrinks to the lifecycle half.

**To bootstrap 3.5.** The adapter maps its own outcome onto this one in both directions, and
produces the reference rather than accepting one from a caller.
