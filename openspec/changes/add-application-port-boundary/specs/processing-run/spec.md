## ADDED Requirements

<!-- Owns: `ProcessingRunRef`, `ProcessingRunRepository` (start with the
     active-run refusal, finish), and `ReleaseProcessingOutcome` with its
     `ReleaseDiagnosticRecord` and `ReleaseNoticeRecord` carriers and the
     evidence seal.
     Cites: `application-port-boundary` for the opaque-locator rule;
     `source-registry-and-discovery` for the promoted `ReleaseIdentity` a run
     starts from; `acquisition-manifest-index` for the `ManifestRef` a run binds
     to; the accepted `bounded-release-processing` spec for the closed
     diagnostic vocabulary and the notice grammar; the accepted
     `canonical-silver-persistence` spec for the reused outcome, diagnostic,
     and notice records. -->

### Requirement: A processing run is created through the boundary
The system SHALL provide an application-owned contract that creates a processing run from the release identity and the manifest it will read, and returns the reference by which that run is named. A caller SHALL NOT be required to construct a run reference itself, because the value that identifies a run is generated where the run is recorded.

The contract SHALL also record that a run has finished.

A run SHALL be *held* from the moment it is started until its worker records it finished or its worker is gone. Starting a run for a release whose run is held SHALL be refused with a named error, and that decision SHALL be made atomically, so two concurrent callers cannot both hold a run for one release. The accepted contract requires overlapping active runs for one county and release to be prevented, and no database constraint expresses it, so the boundary SHALL. How holding is represented — a lock scoped to the worker's connection, or a lease with a deadline the holder renews — is an implementation decision and SHALL NOT be fixed by the port contract; the contract fixes the property.

An unfinished run whose holder is gone SHALL NOT wedge its release. Starting a run for such a release SHALL resume the existing run rather than create a second one: the start result carries that run's reference and states that the run was resumed rather than created, decided atomically so that exactly one retrying worker obtains it. A retried worker therefore continues under the run its acquisition, outcome, load, and evaluations already bind to, and the load's own retry result then states whether the load had already completed. The boundary SHALL NOT require an out-of-band repair of the run record to make a release processable again, and refusal SHALL NOT be decided from the absence of a finish record alone.

A release whose previous run finished SHALL start a new run, because the rule prevents overlap and not repetition.

#### Scenario: A run is started
- **WHEN** a use case begins processing a release it has acquired
- **THEN** it obtains a run reference from the boundary, and the reference identifies a run that has been recorded

#### Scenario: A second run is started for a release already running
- **WHEN** a run is started for a release whose run is held by a live worker
- **THEN** the operation refuses with a named error rather than creating or resuming a second holder, and the decision is made atomically so two concurrent callers cannot both succeed

#### Scenario: A worker is gone before it recorded completion
- **WHEN** a run was started, its worker terminated before recording the run finished, and a retried worker starts a run for that release
- **THEN** the retried worker obtains the same run's reference in a start result that says the run was resumed, and no second run is created for that release

#### Scenario: A retried worker resumes after the load committed
- **WHEN** a resumed run's canonical load had already completed before its first worker was gone, and the retried worker completes the load again for that release and run
- **THEN** the completion reports that the load was already complete and persists nothing further, and the quality evaluations and the publication attempt bind to that same run

#### Scenario: Two retried workers race for one abandoned run
- **WHEN** two callers start a run for a release whose unfinished run's holder is gone
- **THEN** exactly one obtains the resumed run and the other is refused by name

#### Scenario: A run is started after the previous one finished
- **WHEN** a run is started for a release whose previous run finished
- **THEN** a new run is created, because the rule prevents overlap and not repetition

#### Scenario: A run reference is required somewhere
- **WHEN** any port requiring a run reference is examined
- **THEN** it accepts the reference type and no raw persistence value in its place, so a caller is never required to invent one

#### Scenario: A reference that names no run is used
- **WHEN** a reference that does not resolve to a started run is passed to a port that requires one
- **THEN** the operation is refused rather than creating a run implicitly

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
