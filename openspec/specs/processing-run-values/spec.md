# processing-run-values Specification

## Purpose
Define the vocabulary the application owns for one processing run: the reference that names it, the
disposition that judges it, the bounded carriers that evidence it, and the sealed outcome that
describes it. Values only — starting a run, holding it, resuming an abandoned one, finishing it,
and the repository that does all four belong to the run lifecycle and are specified elsewhere.

Two rules here are enforced twice, once by these values and once by a database constraint, and the
point is that the two agree: a value this boundary accepts has to be a value that can be recorded.
The evidence seal is the sharpest case. It runs at COMMIT, so an outcome that satisfies every
field-level rule and fails the seal aborts the canonical transaction after its records are written
— refusing it here costs a caller one exception, refusing it there costs a load.

The reference exists so no caller invents one. The value identifying a run is generated where the
run is recorded, and a port that accepted the bare value would let a number a caller made up name a
run that never existed.

## Requirements
### Requirement: A run is named by an opaque reference the caller never invents

A processing run SHALL be named across ports by `ProcessingRunRef`, a value the layer that records
the run produces. A caller SHALL NOT be required to construct one, because the value identifying a
run is generated where the run is recorded.

The reference SHALL be an **opaque locator**: comparable for equality, hashable, carrying no
ordering, no freshness or precedence meaning, and never canonical identity.

The value it wraps SHALL be constrained to an **explicitly immutable representation** and refused at
construction otherwise. Hashability SHALL NOT be taken as evidence of immutability: an object whose
`__hash__` reads a mutable attribute passes a `hash()` probe, hashes differently after that
attribute changes, and leaves the mapping entry filed under it unreachable with nothing raising. The
admitted representation SHALL cover what a database hands back — an identity value, a textual
identifier, or a composite of them — and SHALL NOT be widened to whatever happens to hash.

Admission SHALL be by **exact type**, not by `isinstance`. A subclass of an admitted type may
override `__hash__` and `__eq__` to read a mutable attribute: it satisfies `isinstance`, hashes
differently once that attribute moves, and leaves the entry filed under it unreachable — the same
corruption, arriving through the very type the rule admits. A composite SHALL be flat and non-empty,
matching what it is declared to be rather than exceeding it: a nested composite is a composite of
composites no key this locator names has, and an empty one locates nothing.

The reference SHALL wrap the persistence-generated value without interpreting it, and no port SHALL
accept a raw persistence value in its place — a port that took the bare value would let a caller
invent a reference to a run that was never recorded, which is the one thing the type exists to
prevent.

#### Scenario: A run reference is required somewhere
- **WHEN** any port requiring a run reference is examined
- **THEN** it accepts the reference type and no raw persistence value in its place, so a caller is never required to invent one

#### Scenario: A locator is offered a subclass of an admitted type
- **WHEN** a reference is constructed over a subclass of an admitted type that overrides `__hash__` to read a mutable attribute
- **THEN** it is refused, because admission is by exact type: the subclass satisfies every `isinstance` check and still moves underneath the entry filed under it

#### Scenario: A locator is offered a nested or empty composite
- **WHEN** a reference is constructed over a composite containing another composite, or over an empty one
- **THEN** each is refused, the first because no key this locator names is a composite of composites and the second because it would locate nothing

#### Scenario: A locator is offered a hashable but mutable value
- **WHEN** a reference is constructed over an object that hashes at that moment but whose hash reads a mutable attribute
- **THEN** it is refused, because the probe would pass and the entry filed under it would become unreachable the moment that attribute changed

#### Scenario: A reference that names no run is used
- **WHEN** a reference that does not resolve to a started run is passed to a port that requires one
- **THEN** the operation is refused rather than creating a run implicitly

### Requirement: The disposition is a closed vocabulary the application owns

A release's disposition SHALL be one of a closed set the application declares — accepted or
rejected — rather than a string a caller composes. The adapters declare their own; the application
SHALL NOT import it, because the dependency direction forbids it, and the mapping between the two
SHALL be total in both directions so that no adapter outcome is unrepresentable here and no value
here is unrecordable there.

#### Scenario: A disposition outside the vocabulary is supplied
- **WHEN** an outcome is constructed with a disposition the closed set does not contain
- **THEN** it is refused, rather than accepted and rejected at the write

#### Scenario: The mapping to the adapters' vocabulary is examined
- **WHEN** the two vocabularies are compared
- **THEN** every member of each maps to exactly one member of the other, so neither side can carry a value the other cannot express

### Requirement: The outcome crossing the boundary is a lossless representation
The processing outcome the boundary accepts SHALL carry every fact the accepted outcome record requires: the disposition, the boundary contract version, the parser contract version and layout fingerprint where the release was prepared, the processed, staged, committed, and rejected counts, and the bounded diagnostics and notices with their totals and truncation flags.

The outcome SHALL also satisfy the evidence seal the accepted outcome record enforces at completion, so that a value the boundary accepts cannot abort the canonical transaction. The number of retained diagnostics SHALL equal the smaller of the declared diagnostic total and the retention bound, and the number of retained notices SHALL equal the smaller of the declared notice total and that bound. Each truncation flag SHALL be true exactly when its declared total exceeds the bound. Every retained diagnostic SHALL carry the same layout fingerprint the outcome carries, including where the outcome carries none.

A diagnostic code SHALL be one the accepted closed vocabulary admits. A notice code SHALL NOT be closed to that vocabulary; it SHALL satisfy the bounded lowercase identifier grammar the accepted notice contract admits. Either way a value valid at this boundary SHALL be a value that can be recorded.

The boundary contract version SHALL equal the accepted boundary's constant, so a value the boundary accepts cannot fail the persisted check that pins it. The application SHALL hold its own copy of that constant, because it cannot import the adapters', and the dependency-direction test SHALL assert the two are equal so the copy cannot drift.

An implementation SHALL be able to record the accepted outcome from this value alone, without obtaining any of those facts from outside the boundary. The paired invariants the accepted record enforces SHALL be enforced here, so a violation is refused at the boundary rather than at commit.

#### Scenario: A prepared release reports its parser evidence
- **WHEN** an outcome describes a release whose layout was prepared
- **THEN** it carries both the parser contract version and the layout fingerprint

#### Scenario: One prepared field is supplied without the other
- **WHEN** an outcome carries a parser contract version without a layout fingerprint, or the reverse
- **THEN** the outcome is refused

#### Scenario: An implementation records the outcome
- **WHEN** an implementation records the accepted outcome from the value the boundary supplied
- **THEN** every required fact is present and none is obtained from elsewhere

#### Scenario: An outcome declares more evidence than it retains
- **WHEN** an outcome declares a diagnostic total below the retention bound but retains a different number of diagnostics
- **THEN** it is refused at the boundary, rather than accepted here and rejected when the load completes

#### Scenario: An outcome exceeds the retention bound
- **WHEN** an outcome declares a total above the retention bound
- **THEN** it is accepted only if it retains exactly the bound and its truncation flag is true, and refused otherwise

#### Scenario: A truncation flag disagrees with its total
- **WHEN** a truncation flag is set on an outcome whose declared total does not exceed the retention bound, or is unset on one whose total does
- **THEN** the outcome is refused

#### Scenario: A retained diagnostic names another layout
- **WHEN** an outcome retains a diagnostic whose layout fingerprint differs from the outcome's, including where the outcome carries none
- **THEN** the outcome is refused

#### Scenario: A diagnostic carries a code outside the accepted vocabulary
- **WHEN** an outcome carries a diagnostic whose code is not one the accepted vocabulary admits
- **THEN** the outcome is refused at the boundary, rather than accepted here and rejected when written

#### Scenario: A notice carries a code outside the closed diagnostic vocabulary
- **WHEN** an outcome carries a notice whose code is a well-formed bounded lowercase identifier that the diagnostic vocabulary does not contain
- **THEN** the outcome is accepted, because the notice vocabulary is open where the diagnostic vocabulary is closed

#### Scenario: A notice carries a malformed code
- **WHEN** an outcome carries a notice whose code does not satisfy the bounded lowercase identifier grammar
- **THEN** the outcome is refused

#### Scenario: An outcome carries another boundary contract version
- **WHEN** an outcome is constructed with a boundary contract version other than the accepted constant
- **THEN** it is refused at the boundary rather than accepted here and rejected at persistence

