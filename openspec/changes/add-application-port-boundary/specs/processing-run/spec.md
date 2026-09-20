## ADDED Requirements

<!-- Owns: `ProcessingRunRepository` — starting a run with the held-run
     refusal and the abandoned-run resume, and finishing one.  The run
     *lifecycle*, and nothing of the run *vocabulary*.
     Cites: the promoted `processing-run-values` capability for
     `ProcessingRunRef` and `ReleaseProcessingOutcome`, which it owns and
     which this capability neither defines nor redefines;
     `application-port-boundary` for the opaque-locator rule;
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
