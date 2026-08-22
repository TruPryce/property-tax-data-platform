## ADDED Requirements

### Requirement: Jurisdiction identity
The system SHALL identify an appraisal jurisdiction by `state_code` and `county_slug` only. `county_fips` SHALL be required validated registry metadata reachable from a jurisdiction, SHALL NOT participate in equality or hashing, and SHALL NOT appear in the jurisdiction identity document. No database surrogate key, object-store location, URL, filesystem path, orchestration run identifier, or acquisition timestamp SHALL participate in jurisdiction identity or equality.

The set of attributes participating in equality SHALL be exactly `state_code` and `county_slug`, and that set SHALL be assertable directly. Stating instead that equality holds "regardless of any other attribute" would be unfalsifiable, because registry validation makes a jurisdiction whose FIPS differs from its slug's registered value unconstructible.

#### Scenario: Equal state and slug are one jurisdiction
- **WHEN** two `Jurisdiction` values carry the same state code and county slug
- **THEN** they compare equal and hash equally

#### Scenario: Different counties are different jurisdictions
- **WHEN** two `Jurisdiction` values carry the same state code and different county slugs
- **THEN** they do not compare equal

#### Scenario: The equality basis is inspected
- **WHEN** the attributes participating in jurisdiction equality are enumerated
- **THEN** they are exactly the state code and the county slug, and the identity document contains exactly those two fields

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
The system SHALL define domain provenance that composes `ReleaseIdentity` and `ArtifactIdentity` rather than restating jurisdiction, tax year, release kind, or release identifier as independent values.

Its remaining fields SHALL be exactly the following, with these types and bounds and no others:

| field | type | rule |
|---|---|---|
| `source_member_name` | `str` | 1–128 characters of `[A-Za-z0-9._-]`, not beginning with `.` or `-`, matching the identifier grammar already accepted across the repository |
| `source_row_number` | `int \| None` | one-based; `bool` rejected; a value below 1 rejected; `None` only where the source has no row grain |
| `parser_contract_version` | `int` | required, `>= 1`, `bool` rejected |
| `layout_fingerprint` | `str \| None` | exactly 64 lowercase hexadecimal characters, matching the SHA-256 hexdigest the county adapters already produce; `None` only where the source has no layout |

A value outside its type, bound, or alphabet SHALL be rejected at construction rather than truncated, padded, case-folded, or otherwise coerced. Absence SHALL be `None` and MUST NOT be a fabricated placeholder such as an empty string, a zero row number, or a zero-filled fingerprint.

#### Scenario: Provenance identifies its evidence
- **WHEN** a domain fact carries provenance
- **THEN** its originating jurisdiction, logical release, artifact, source member, row position, parser contract version, and layout identity are recoverable without consulting an adapter

#### Scenario: A lineage value is unbounded
- **WHEN** a provenance value exceeds its accepted bound or falls outside its accepted alphabet
- **THEN** construction fails rather than truncating or sanitizing the value

### Requirement: Domain provenance carries no payload
Domain provenance SHALL expose only closed, purpose-specific, bounded lineage fields and SHALL have no generic payload, detail, extra, metadata, or annotation field, no mapping, and no sequence of arbitrary values. Adapter and source vocabulary SHALL remain outside `property_tax_domain`, including table names, source families, source statuses, observed-field vectors, normalized-field vectors, and county-native field names.

This is what structure can enforce, and the guarantee SHALL be stated as that rather than as a claim that no field can receive identifying data. A bounded string named `source_member_name` can still be handed `JOHN_DOE`; what the shape prevents is a field whose purpose is to accept whatever a caller has. Keeping sensitive values out of the values that reach provenance remains the adapter's obligation under the accepted county contracts.

#### Scenario: A caller looks for somewhere to attach source content
- **WHEN** a caller seeks a field on domain provenance for a source row, an arbitrary source value, an owner value, an address, a credential, a signed URL, a host-local path, or exception text
- **THEN** no general-purpose field exists to receive it, and every field present is a named lineage field with a declared type and bound

#### Scenario: Adapter vocabulary is proposed for the domain
- **WHEN** a change would add a table name, source family, source status, or field-name vector to domain provenance
- **THEN** the domain rejects it and the concept remains at the adapter boundary

### Requirement: Deterministic serialization
The system SHALL define named-field JSON as the authoritative canonical serialization for every serialized identity and provenance value, SHALL produce byte-identical output for equal values, and SHALL round-trip without loss. Compact string renderings MAY be derived for readability and for adapter key composition, and SHALL NOT be the authoritative contract. Any compact release rendering SHALL be reversible for every accepted release identifier, and that reversibility SHALL be proved against the accepted identifier alphabet rather than asserted.

The complete named-field shapes SHALL be:

```json
{"state_code": "tx", "county_slug": "collin"}

{"sha256": "<64 lowercase hex>"}

{"jurisdiction": {"state_code": "tx", "county_slug": "collin"},
 "tax_year": 2025, "release_kind": "certified", "release_identifier": "COLLIN-2025-CERT-01"}

{"artifact": {"sha256": "<64 lowercase hex>"}, "release": { ...release identity... }}

{"release": { ...release identity... }, "artifact": {"sha256": "<64 lowercase hex>"},
 "source_member_name": "PROP.TXT", "source_row_number": 1,
 "parser_contract_version": 1, "layout_fingerprint": "<64 lowercase hex>"}
```

Identity values SHALL nest as objects rather than as pre-rendered strings, so no reader parses a string to recover a field the writer held. An absent optional value SHALL be emitted as JSON `null` and SHALL NOT be omitted, so that a field's absence and a reader's older schema are distinguishable. Key order SHALL be the declaration order shown above and SHALL NOT depend on insertion or hashing. Registry metadata SHALL serialize as its own document keyed by the identity rather than inside it.

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

Enforcement SHALL sit at the county mapping boundary that knows the contract, and SHALL NOT be assigned to the generic domain constructor, which sees four syntactically valid components and cannot know whether an identifier was approved.

#### Scenario: A mutable same-year snapshot has no approved discriminator
- **WHEN** a second mutable same-year artifact is acquired for a county whose contract supplies no approved release discriminator
- **THEN** the county mapping refuses to produce a canonical release identity, the artifact is preserved in Bronze, and no existing identity is reused, no release kind is invented, and the artifact digest is not used as the discriminator

#### Scenario: A syntactically valid identifier arrives from an unapproved source
- **WHEN** a well-formed release identifier is supplied for a county whose discriminator is unapproved
- **THEN** the refusal comes from the county mapping rather than from the domain constructor, which has no basis to distinguish it from an approved one
