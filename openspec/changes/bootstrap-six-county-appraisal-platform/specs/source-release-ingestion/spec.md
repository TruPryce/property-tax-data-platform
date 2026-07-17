## ADDED Requirements

### Requirement: Official source registry
The system SHALL maintain a version-controlled registry of supported source endpoints, acquisition methods, expected media types, and parser identifiers for each county and release kind. Runtime credentials and secret values MUST NOT be stored in the registry.

#### Scenario: Resolve a supported source
- **WHEN** an ingestion run requests a registered county and release kind
- **THEN** the system resolves a source adapter, endpoint metadata, and parser identifier without embedding county-specific branches in the orchestrator

#### Scenario: Reject an unsupported source
- **WHEN** an ingestion run requests an unregistered county or release kind
- **THEN** the system fails before network acquisition with an actionable unsupported-source error

### Requirement: Release discovery
The system SHALL discover source release candidates using stable remote metadata where available and SHALL preserve county FIPS, source locator, source as-of evidence, page evidence, and remote metadata before acquisition. The system SHALL assign tax year and release kind to logical release partitions when those values are established by authoritative page metadata or verified source content.

#### Scenario: Discover a new release
- **WHEN** the official source exposes a release not present in the release manifest store
- **THEN** the system records the release as discovered and schedules acquisition

#### Scenario: Observe an unchanged release
- **WHEN** remote metadata and content identity match a successfully acquired release
- **THEN** the system records a no-change outcome without downloading or republishing the release

#### Scenario: Release semantics exist only in source content
- **WHEN** an official artifact contains multiple tax years or release kinds that are not identified by its page label or filename
- **THEN** discovery records one source candidate and parsing creates separately identified logical release partitions backed by the same immutable artifact

### Requirement: Safe source redirects
The system SHALL validate the scheme and host of the initial source request and every redirect before contacting the destination, SHALL limit redirect hops, and SHALL NOT rely on automatic redirect following for source acquisition.

#### Scenario: Source redirects to an approved file host
- **WHEN** an official publisher page redirects to a configured HTTPS file-distribution host
- **THEN** the system validates the destination before requesting it and records the complete redirect chain as provenance

#### Scenario: Source redirects to an unapproved destination
- **WHEN** any redirect targets an unapproved scheme or host or exceeds the configured hop limit
- **THEN** the system stops before contacting that destination and records a non-retryable security failure

### Requirement: Immutable Bronze acquisition
The system SHALL stream every acquired source artifact to S3-compatible Bronze storage, calculate a SHA-256 checksum, and persist its manifest before any source record is normalized.

#### Scenario: Complete an artifact download
- **WHEN** the downloaded byte count and checksum are finalized
- **THEN** the system records the immutable object URI, checksum, byte count, media type, acquisition timestamp, and remote metadata in the release manifest

#### Scenario: Detect conflicting content
- **WHEN** an existing release identity is observed with a different content checksum
- **THEN** the system stores a distinct artifact version and flags the release for review instead of overwriting prior Bronze content

#### Scenario: Fail during download
- **WHEN** acquisition terminates before the complete artifact is verified
- **THEN** the system does not mark the release as Bronze-complete and does not expose the partial object as an immutable source artifact

### Requirement: Multiple logical releases per artifact
The system SHALL permit one immutable source artifact to support multiple logical release partitions while retaining one artifact checksum, one acquisition event, and partition-specific tax year and release semantics.

#### Scenario: One artifact carries current and certified values
- **WHEN** a verified artifact contains current values for one tax year and certified values for another tax year
- **THEN** the system links both logical release partitions to the same artifact without duplicating or relabeling the original bytes

### Requirement: Safe archive handling
The system SHALL inspect archives before extraction and SHALL enforce configured limits for member count, expanded byte count, path traversal, compression ratio, and supported member types.

#### Scenario: Accept a valid archive
- **WHEN** an archive passes all safety limits and contains supported members
- **THEN** the system makes the verified members available to the registered parser

#### Scenario: Reject an unsafe archive
- **WHEN** an archive contains a traversal path, exceeds a safety limit, or contains a prohibited member type
- **THEN** the system quarantines the release before parsing and records the violated rule

### Requirement: Bounded resource processing
The system SHALL parse and load large source artifacts using bounded-memory batches and bulk database operations.

#### Scenario: Process a large release
- **WHEN** an extracted member exceeds the configured batch size
- **THEN** the system processes successive batches without materializing the complete member as an in-memory collection

### Requirement: Idempotent orchestration
The system SHALL make discovery, acquisition, parsing, loading, validation, and publication independently retryable using release and artifact identities.

#### Scenario: Retry after a transient failure
- **WHEN** a task is retried after a previously committed stage
- **THEN** the system resumes from the last verified stage without duplicating canonical records or Bronze objects

#### Scenario: Run counties concurrently
- **WHEN** the scheduled six-county workflow begins
- **THEN** county releases may execute independently while overlapping active runs for the same county and release are prevented

### Requirement: Externalized runtime configuration
The system SHALL resolve database, object-store, and protected source credentials through Airflow Connections or an approved secrets backend.

#### Scenario: Missing required credential
- **WHEN** a runtime requires a credential that cannot be resolved
- **THEN** the run fails before acquisition and logs the configuration key without logging a secret value
