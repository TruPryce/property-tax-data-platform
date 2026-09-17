# Processing-run values

The vocabulary the application owns for a processing run: the reference that names one, and the
outcome that describes what processing it produced. Normative behaviour lives in the
[processing-run values capability](../../openspec/changes/add-processing-run-values/specs/processing-run-values/spec.md);
this page records what each value carries and why, and the consequences a caller has to know. Where
the two disagree the capability wins. The capability is still a change rather than a promoted spec,
so the link points into `openspec/changes/`; archiving moves it to `openspec/specs/` and this link
moves with it.

This is **values only**. Starting a run, holding it, resuming an abandoned one, finishing it, and
the repository that does all four belong to the run lifecycle and are planned separately.

## `ProcessingRunRef`

An opaque locator for one run. Equality and hashing, and **every ordering comparison raises**.

Ordering is the tempting mistake and the raise is deliberate: `ingestion.run.run_id` is
`GENERATED ALWAYS AS IDENTITY`, so the wrapped value really is ascending, and a caller sorting by it
would be reading a persistence detail as a business fact. Omitting the methods would produce a
`TypeError` from somewhere else that does not say why. Hashing is not optional — these references
are dictionary keys in every implementation that tracks runs.

The wrapped value is constrained **by type**, to a string, an int that is not a bool, or a tuple of
those: between them they cover every generated key a database hands back. An earlier version probed
with `hash()` instead, and that proves nothing. An object whose `__hash__` reads a mutable attribute
passes the probe, hashes differently once that attribute changes, and leaves the mapping entry filed
under it unreachable — with nothing raising, which is the part that makes it dangerous. "It hashed
once" is one observation of a value that was free to change afterwards.

The type exists so no caller invents one. A port that accepted the bare integer would let a number a
caller made up name a run that was never recorded, and nothing in the signature would say so.

## `ReleaseDisposition`, and why the application has its own

Exactly two states. The adapters declare their own and the dependency direction forbids importing
it, so the application holds a copy and the **mapping is total in both directions** — no adapter
outcome is unrepresentable here, no value here unrecordable there. A partial mapping would mean a
release that processed successfully and then could not be described at the boundary. The suite
proves it by enumerating both vocabularies, not by asserting the sentence.

`BOUNDARY_CONTRACT_VERSION` is the same argument: the application cannot import the adapters'
constant, and a copy that drifts is worse than no copy, because a value the boundary accepts would
fail the persisted check that pins it. The architecture test asserts the two are equal. That test is
the only place in this area that reads the adapters at all, and it is a test rather than the package.

## Two codes, two rules

`ReleaseDiagnosticRecord` validates its code against the **closed** vocabulary, supplied as a frozen
set rather than a second enum so the bounded-processing boundary keeps one authority for it.
`ingestion.release_diagnostic` carries `CHECK (code IN (...))`, so an unvalidated code would pass the
port and fail at the write.

`ReleaseNoticeRecord` validates its code against a **bounded lowercase grammar**,
`^[a-z][a-z0-9_]{0,63}$`, because `ingestion.release_notice` carries exactly that regex and the
accepted notice contract validates against a pattern rather than an enum. A notice code is county
vocabulary; the bound is what stops free text arriving where a code belongs.

The two rules are deliberately not one rule. Reusing the closed set for notices would refuse notices
the database accepts; reusing the grammar for diagnostics would accept diagnostics it refuses.

Neither carrier has anywhere to put a complete row, an arbitrary source value, exception text, a
credential, an identity, an address, or a host-local path.

## The evidence seal, refused in the value

`ingestion.assert_outcome_evidence_agrees` runs at COMMIT. An outcome that declares one diagnostic
and retains none satisfies every field-level rule and aborts the canonical transaction — after the
records were written, in a transaction that then has to be undone. So `ReleaseProcessingOutcome`
enforces the seal itself: retained counts equal `min(total, 100)`, each truncation flag is true
exactly when its total exceeds the bound, and every retained diagnostic carries the outcome's layout
fingerprint, including where the outcome carries none.

It also enforces the paired invariants the accepted record enforces: the two prepared fields are set
together or not at all, a release is accepted exactly when it produced no diagnostic, a rejected
release commits no record, and an accepted one commits what it staged and rejected no row.

Refusing these here costs a caller one exception. Refusing them at COMMIT costs a load.

## Who cites this, and what they may not do

The **canonical load session** carries the reference opaquely and reads exactly one thing from the
outcome — `accepted`, which selects a completion branch. The **run lifecycle** produces the
reference and records the outcome. Neither may redefine what it cites, and neither may accept a raw
persistence value where the reference belongs: a substitute that accepts everything accepts exactly
the value the reference type exists to keep out.
