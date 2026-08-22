## ADDED Requirements

### Requirement: Jurisdiction identity
The system SHALL identify an appraisal jurisdiction by `state_code` and `county_slug` only, and SHALL carry `county_fips` as required validated registry metadata that is not an identity. Two `Jurisdiction` values SHALL compare equal when and only when their state code and county slug are equal. No database surrogate key, object-store location, URL, filesystem path, orchestration run identifier, or acquisition timestamp SHALL participate in jurisdiction identity or equality.

#### Scenario: Identity ignores registry metadata
- **WHEN** two `Jurisdiction` values carry the same state code and county slug
- **THEN** they compare equal and hash equally regardless of any other attribute

#### Scenario: Different counties are different jurisdictions
- **WHEN** two `Jurisdiction` values carry the same state code and different county slugs
- **THEN** they do not compare equal

### Requirement: Jurisdiction registry consistency
The system SHALL reject construction of a `Jurisdiction` whose registry metadata contradicts its identity. A county slug paired with another county's FIPS SHALL fail at construction rather than be normalized, corrected, or accepted.

#### Scenario: Slug and FIPS disagree
- **WHEN** a caller constructs a jurisdiction with the Collin slug and Dallas County's FIPS
- **THEN** construction fails and no jurisdiction value is produced

#### Scenario: FIPS is malformed
- **WHEN** a caller supplies a FIPS that is not exactly five digits
- **THEN** construction fails rather than padding, truncating, or coercing the value

### Requirement: Artifact content identity
The system SHALL identify an artifact by its SHA-256 content digest alone. `ArtifactIdentity` SHALL contain no object-store URI, bucket, key, source URL, filename, entity tag, database surrogate identifier, or acquisition timestamp, and none of those SHALL participate in its equality.

#### Scenario: Same bytes from different locations
- **WHEN** the same digest is observed under two different source URLs and two different filenames
- **THEN** the artifact identities compare equal

#### Scenario: Different bytes under one name
- **WHEN** two artifacts published under one source name carry different digests
- **THEN** their artifact identities do not compare equal

#### Scenario: Digest is malformed
- **WHEN** a digest is not exactly sixty-four lowercase hexadecimal characters
- **THEN** construction fails rather than trimming, padding, or case-folding the value

### Requirement: Logical release identity
The system SHALL identify a logical release by `Jurisdiction`, `tax_year`, `ReleaseKind`, and a required source-supplied `release_identifier`. The release identifier SHALL be bounded, opaque, namespaced by its jurisdiction, and SHALL NOT be assumed globally unique, inferred from a filename or archive member name, or normalized into a different identifier. `ReleaseIdentity` SHALL contain no artifact identity.

#### Scenario: Two counties reuse one source label
- **WHEN** a Dallas release and a Collin release carry the same source-supplied release identifier, tax year, and kind
- **THEN** their release identities do not compare equal, and neither identifier is renamed

#### Scenario: One county issues two releases of one kind in one year
- **WHEN** two releases share a jurisdiction, tax year, and kind and differ only in release identifier
- **THEN** their release identities do not compare equal

#### Scenario: An identifier would be altered to be accepted
- **WHEN** a supplied release identifier differs from an accepted form only by case, surrounding whitespace, or a character outside the accepted alphabet
- **THEN** construction fails and the identifier is not lowercased, trimmed, slugified, or otherwise rewritten

#### Scenario: A tax year is outside the plausible range
- **WHEN** a tax year is not an integer within the accepted range
- **THEN** construction fails rather than clamping or coercing the value

### Requirement: Canonical release kind vocabulary
The system SHALL define a closed canonical `ReleaseKind` vocabulary of exactly `proposed`, `certified`, `supplemental`, and `current`. A county-native label SHALL be mapped to a canonical kind only where an accepted county contract supports semantic equivalence, and the source-native label SHALL be retained at the adapter or source boundary. The vocabulary SHALL NOT be widened to carry an unresolved county label.

#### Scenario: A contract-supported label is canonicalized
- **WHEN** an adapter maps a county-native label for which an accepted contract establishes equivalence
- **THEN** the canonical kind is used and the source-native label is retained separately

#### Scenario: An unresolved label is presented for canonicalization
- **WHEN** an adapter presents a county-native label that no accepted contract establishes as equivalent
- **THEN** the mapping fails rather than selecting the nearest-looking canonical kind

#### Scenario: A kind outside the vocabulary is supplied
- **WHEN** a release kind outside the closed vocabulary is supplied
- **THEN** construction fails rather than accepting an open string

### Requirement: Artifact and release association
The system SHALL relate artifacts and logical releases through an immutable association value rather than by embedding either identity in the other. The association SHALL support one artifact carrying several logical releases and one logical release observed in several artifacts, and observing an additional artifact for a release SHALL NOT change that release's identity.

#### Scenario: One artifact carries two logical releases
- **WHEN** one artifact holds current values for one tax year and certified values for another
- **THEN** two distinct release identities bind to one unchanged artifact identity

#### Scenario: One release is observed twice
- **WHEN** a second artifact is observed for an existing logical release
- **THEN** a second association is recorded and the release identity is unchanged

### Requirement: Bounded domain provenance
The system SHALL define domain provenance that composes `ReleaseIdentity` and `ArtifactIdentity` rather than restating jurisdiction, tax year, release kind, or release identifier as independent values. It SHALL carry the source member name, the source row number where applicable, the parser contract version, and the layout fingerprint where applicable, each bounded and validated. Absence SHALL be explicit and MUST NOT be represented by a fabricated placeholder.

#### Scenario: Provenance identifies its evidence
- **WHEN** a domain fact carries provenance
- **THEN** its originating jurisdiction, logical release, artifact, source member, row position, parser contract version, and layout identity are recoverable without consulting an adapter

#### Scenario: A lineage value is unbounded
- **WHEN** a provenance value exceeds its accepted bound or falls outside its accepted alphabet
- **THEN** construction fails rather than truncating or sanitizing the value

### Requirement: Domain provenance carries no payload
Domain provenance SHALL have no field capable of holding a complete source row, an arbitrary source value, owner information, a mailing or situs address, a credential, a signed URL, a host-local path, or arbitrary exception text. Adapter and source vocabulary SHALL remain outside `property_tax_domain`, including table names, source families, source statuses, observed-field vectors, normalized-field vectors, and county-native field names.

#### Scenario: A caller attempts to attach source content
- **WHEN** a caller tries to place a source row, an owner value, an address, a credential, or exception text on domain provenance
- **THEN** no field exists to receive it

#### Scenario: Adapter vocabulary is proposed for the domain
- **WHEN** a change would add a table name, source family, source status, or field-name vector to domain provenance
- **THEN** the domain rejects it and the concept remains at the adapter boundary

### Requirement: Deterministic serialization
The system SHALL define named-field JSON as the authoritative canonical serialization for identity and provenance values, SHALL produce byte-identical output for equal values, and SHALL round-trip without loss. Compact string renderings MAY be derived for readability and for adapter key composition, and SHALL NOT be the authoritative contract. Any compact release rendering SHALL be reversible for every accepted release identifier, and that reversibility SHALL be proved against the accepted identifier alphabet rather than asserted.

#### Scenario: Equal values serialize identically
- **WHEN** two equal identity values are serialized
- **THEN** the output is byte-identical, including field order

#### Scenario: Serialized identity round-trips
- **WHEN** an identity value is serialized and parsed back
- **THEN** the result compares equal to the original and carries no altered component

#### Scenario: A compact rendering is reversed
- **WHEN** a compact release rendering is parsed for any accepted release identifier
- **THEN** all four identity components are recovered exactly, with no component altered

#### Scenario: The accepted alphabet is widened
- **WHEN** an identifier alphabet is widened to admit the compact rendering's separator
- **THEN** the reversibility proof fails rather than the rendering becoming ambiguous

### Requirement: Domain independence
`property_tax_domain` SHALL import no adapter, infrastructure, object-store, database, orchestration, or county-specific implementation module, and SHALL be constructible and testable without them.

#### Scenario: Domain is exercised alone
- **WHEN** the domain identity and provenance types are constructed and compared
- **THEN** no object-store client, database driver, orchestration package, or county adapter is imported

### Requirement: Unresolved release discrimination is blocked
Where an accepted county contract requires distinct releases but supplies no approved discriminator between them, the system SHALL NOT construct a canonical release identity for those releases. Bronze acquisition MAY continue to preserve each artifact, and canonical identity construction SHALL remain blocked until an evidence-backed discriminator is approved.

#### Scenario: A mutable same-year snapshot has no approved discriminator
- **WHEN** a second mutable same-year artifact is acquired for a county whose contract supplies no approved release discriminator
- **THEN** the artifact is preserved and canonical release identity construction fails rather than reusing an existing identity, inventing a release kind, or using the artifact digest as the discriminator
