## ADDED Requirements

<!-- Owns: `RuleSeverity`, `QualityRule`, `QualityEvaluation`,
     `QualityRepository`; `PublicationProduct`, `PublicationRef`,
     `PublicationAttempt`, `PublicationRepository`, and the source as-of
     instant supplied at the attempt; `Clock`.
     Cites: `processing-run` for `ProcessingRunRef`;
     `application-port-boundary` for the opaque-locator rule;
     `source-registry-and-discovery` for the source as-of evidence; the
     accepted `canonical-silver-persistence` spec for the reused quality and
     publication models; the bootstrap `validated-data-publication` delta for
     the rule that a failed publication leaves the prior one current. -->

### Requirement: The quality boundary is run-bound and reuses the accepted model
The quality boundary SHALL read the configured rules, with their severity and thresholds, and SHALL record measured evaluations against the processing run that produced them. It SHALL NOT define a second quality model, SHALL NOT embed a county-specific threshold, and SHALL NOT require its consumer to express a rule in SQL or to name a stored relation.

A recorded failing evaluation SHALL carry the measured and expected values.

#### Scenario: Configured rules are evaluated
- **WHEN** a use case evaluates quality for a run
- **THEN** it obtains the configured rules and their severities through the port and contains no embedded threshold

#### Scenario: A failing evaluation is recorded
- **WHEN** a rule fails
- **THEN** the recorded evaluation carries its measured and expected values and is bound to the run

#### Scenario: The boundary is examined for a parallel model
- **WHEN** the quality boundary is examined
- **THEN** it records against the accepted rule and evaluation model rather than a second one

### Requirement: Release-level source freshness reaches publication through the boundary
Where discovery establishes a source as-of instant for a release, the boundary SHALL carry it to the publication attempt, so published lineage can state the freshness of what it exposes.

That instant SHALL be supplied as the release-level evidence it is, and SHALL NOT be derived from loaded canonical records: the canonical model admits several account snapshots for one release carrying different source as-of values, so any derivation would need a selection rule the accepted contracts do not define.

Where the source establishes no such instant, the attempt SHALL record its absence rather than substituting the acquisition instant or any other available time.

#### Scenario: A release carries a source as-of instant
- **WHEN** discovery establishes a source as-of instant and the release is later published
- **THEN** the publication attempt receives that instant through the boundary rather than deriving it from canonical records

#### Scenario: A release establishes no source as-of instant
- **WHEN** no source as-of instant was established
- **THEN** the attempt records its absence, and no other available time is substituted

### Requirement: The publication boundary owns attempt, lineage, and activation
The publication boundary SHALL record a publication attempt, its lineage to the release and run it rests on, and its transition to current or to failed. Activation SHALL make the new publication current and record the publication it supersedes. A failed attempt SHALL NOT become current and SHALL NOT supersede the publication that is already current.

This boundary SHALL NOT construct the published product itself; the transaction that builds and promotes the published data is owned separately. The boundary SHALL NOT grant, imply, or require raw canonical read access, and SHALL NOT confer permission to publish a sensitive field, which the reviewed field policy continues to govern.

#### Scenario: An attempt fails
- **WHEN** a publication attempt fails
- **THEN** the previously current publication remains current and the failed attempt is not marked current

#### Scenario: An attempt is activated
- **WHEN** an attempt is activated
- **THEN** it becomes current and the publication it replaces is recorded as superseded

#### Scenario: The boundary is examined for scope
- **WHEN** the publication boundary is examined
- **THEN** it carries attempt, lineage, and activation, grants no canonical read privilege or sensitive-field permission, and does not claim to build the published product

### Requirement: One application-owned clock returns timezone-aware instants
The application SHALL own one time source, and every instant it returns SHALL be timezone-aware. A use case SHALL obtain the current instant through that port rather than by calling a wall-clock API directly, so that a use case can be exercised deterministically.

#### Scenario: The current instant is obtained
- **WHEN** a use case asks the clock for the current instant
- **THEN** it receives a timezone-aware instant

#### Scenario: A use case is exercised deterministically
- **WHEN** a test supplies a fixed time source
- **THEN** the use case observes the supplied instant and reads no wall clock
