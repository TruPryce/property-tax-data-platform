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

The boundary SHALL provide a run-level verdict: for one run, against the blocking rule versions active when the verdict is asked for, which active blocking rules have no recorded evaluation for that run at exactly their active version — whether no evaluation exists or the only one is at a version since replaced — which recorded blocking evaluations failed, and which warning evaluations failed. The verdict is complete exactly when no active blocking rule lacks an evaluation at its active version, and clean exactly when it is complete and no blocking evaluation failed. It SHALL be computed from the recorded evaluations and the active rule set, and SHALL NOT be stored as a second model. An absent evaluation SHALL be reported as missing and SHALL NOT be reported as a pass; an evaluation at a replaced version SHALL be reported as stale and SHALL NOT be reported as coverage: the accepted evaluation record notes that a release that passed because a rule never ran otherwise looks identical to one that passed because it did.

The remedy for a missing or stale evaluation SHALL be a new processing run, never re-evaluation within the run: the accepted evaluation record admits one immutable verdict per rule and subject per run, and the loading role cannot replace it. The boundary SHALL NOT name re-evaluation as a remedy.

More than one active version of one blocking rule SHALL be a named configuration error: the verdict SHALL report it and SHALL NOT be complete while it stands, so activation fails closed rather than choosing a version. Keeping exactly one version of a rule active, and switching versions atomically, is the rule owner's obligation and not the boundary's.

#### Scenario: Configured rules are evaluated
- **WHEN** a use case evaluates quality for a run
- **THEN** it obtains the configured rules and their severities through the port and contains no embedded threshold

#### Scenario: A failing evaluation is recorded
- **WHEN** a rule fails
- **THEN** the recorded evaluation carries its measured and expected values and is bound to the run

#### Scenario: A blocking rule was never evaluated
- **WHEN** an active blocking rule has no recorded evaluation for a run
- **THEN** the run's verdict is incomplete, names that rule, and reports no pass for it

#### Scenario: A blocking rule was activated after the run was evaluated
- **WHEN** a blocking rule becomes active after a run's evaluations were recorded and has no evaluation for the run
- **THEN** the verdict reports it as missing and the run as incomplete, and the remedy is a new processing run

#### Scenario: A blocking rule's active version changed after the run was evaluated
- **WHEN** a run holds an evaluation for a blocking rule only at a version that is no longer the active one
- **THEN** the verdict reports that rule as stale and the run as incomplete, and the remedy is a new processing run rather than re-evaluation within this one

#### Scenario: Two versions of one blocking rule are active
- **WHEN** more than one version of one blocking rule is active when the verdict is asked for
- **THEN** the verdict reports a named configuration error and is not complete, and activation refuses rather than choosing a version

#### Scenario: Every active blocking rule passed
- **WHEN** every active blocking rule has a recorded passing evaluation for a run at exactly its active version
- **THEN** the verdict is complete and clean, whatever the warning evaluations recorded

#### Scenario: The boundary is examined for a parallel model
- **WHEN** the quality boundary is examined
- **THEN** it records against the accepted rule and evaluation model rather than a second one

### Requirement: Release-level source freshness reaches publication through the boundary
Where a logical release's evidence carries a source as-of instant, the boundary SHALL carry that release's instant to its publication attempt, so published lineage can state the freshness of what it exposes and two releases drawn from one artifact each publish their own.

That instant SHALL be supplied as the release-level evidence it is, and SHALL NOT be derived from loaded canonical records: the canonical model admits several account snapshots for one release carrying different source as-of values, so any derivation would need a selection rule the accepted contracts do not define.

Where the source establishes no such instant, the attempt SHALL record its absence rather than substituting the acquisition instant or any other available time.

#### Scenario: A release carries a source as-of instant
- **WHEN** a release's evidence carries a source as-of instant and the release is later published
- **THEN** the publication attempt receives that release's instant through the boundary rather than deriving it from canonical records

#### Scenario: Two releases from one artifact publish their own freshness
- **WHEN** two logical releases drawn from one artifact carry different source as-of instants and each is published
- **THEN** each attempt receives its own release's instant, and neither is given the other's

#### Scenario: A release establishes no source as-of instant
- **WHEN** no source as-of instant was established
- **THEN** the attempt records its absence, and no other available time is substituted

### Requirement: The publication boundary owns attempt, lineage, and activation
The publication boundary SHALL record a publication attempt, its lineage to the release and run it rests on, and its transition to current or to failed. Activation SHALL make the new publication current and record the publication it supersedes. A failed attempt SHALL NOT become current and SHALL NOT supersede the publication that is already current.

Activation SHALL refuse with a named error, leaving the previously current publication current, unless the run's quality verdict is clean at the moment of activation. An active blocking rule with no recorded evaluation for the run, one whose only evaluation is at a replaced version, or one with more than one active version SHALL refuse activation exactly as a failed one does. The persisted publication gate counts recorded blocking failures only, so none of those would stop it; the boundary SHALL NOT rely on that gate to detect them. The check is made at admission: a publication already current SHALL remain current whatever becomes active afterwards, and only a new activation is judged.

This boundary SHALL NOT construct the published product itself; the transaction that builds and promotes the published data is owned separately. The boundary SHALL NOT grant, imply, or require raw canonical read access, and SHALL NOT confer permission to publish a sensitive field, which the reviewed field policy continues to govern.

#### Scenario: An attempt fails
- **WHEN** a publication attempt fails
- **THEN** the previously current publication remains current and the failed attempt is not marked current

#### Scenario: An attempt is activated
- **WHEN** an attempt is activated
- **THEN** it becomes current and the publication it replaces is recorded as superseded

#### Scenario: An attempt is activated with an unevaluated blocking rule
- **WHEN** activation is attempted for a run whose verdict is incomplete — a missing evaluation, a stale-version evaluation, or a rule with two active versions — or carries a blocking failure
- **THEN** activation refuses with a named error, the attempt is not marked current, and the previously current publication remains current

#### Scenario: A rule changes after a publication is current
- **WHEN** a blocking rule's active version changes after a publication became current
- **THEN** that publication remains current, because the verdict is checked at admission and a current publication is not re-judged

#### Scenario: An attempt is activated with a clean verdict
- **WHEN** activation is attempted for a run whose verdict is complete and clean
- **THEN** the attempt becomes current and records what it supersedes

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
