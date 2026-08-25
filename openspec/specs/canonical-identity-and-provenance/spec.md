# canonical-identity-and-provenance Specification

## Purpose
Define the one vocabulary the platform names three facts with: which jurisdiction, which logical
release, and which bytes. A jurisdiction identified by its state and county slug with FIPS as
registry metadata rather than a second identity; an artifact identified by content alone, so the
same bytes are one artifact wherever they were found and one name carrying different bytes is two;
a logical release identified by jurisdiction, tax year, a closed kind vocabulary, and the opaque
identifier its source supplied; their relationship as an association rather than a field on either,
many-to-many in both directions; and bounded provenance that composes those identities instead of
restating them, with no field whose purpose is to accept whatever a caller has. It fixes named-field
JSON as the authoritative serialization and the compact renderings as conveniences derived from it,
and it says which county labels an accepted contract lets an adapter canonicalize and which stay
source-native until evidence exists.

## Requirements
### Requirement: Jurisdiction identity
The system SHALL identify an appraisal jurisdiction by `state_code` and `county_slug` only. `county_fips` SHALL be required validated registry metadata reachable from a jurisdiction, SHALL NOT participate in equality or hashing, and SHALL NOT appear in the jurisdiction identity document. No database surrogate key, object-store location, URL, filesystem path, orchestration run identifier, or acquisition timestamp SHALL participate in jurisdiction identity or equality.

`state_code` SHALL be exactly two lowercase ASCII letters and `county_slug` SHALL match `[a-z0-9]+(-[a-z0-9]+)*`, together composing the `^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$` jurisdiction code the platform already stores. An uppercase or mixed-case component SHALL be rejected and MUST NOT be normalized, so a caller never receives an identity other than the one supplied. `county_fips` SHALL be exactly five digits. Where the version-controlled registry stores a state code in another case, the comparison SHALL case-fold on the registry side, and caller-supplied identity SHALL NOT be rewritten to match it.

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

#### Scenario: A caller supplies an uppercase state code
- **WHEN** a jurisdiction is constructed with `TX` rather than `tx`
- **THEN** construction fails and the value is not case-folded into a valid identity

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

The digest length SHALL be published as `ARTIFACT_IDENTITY_HEX_LENGTH`, whose value SHALL be 64, so a consumer asserting the bound reads it from the vocabulary rather than repeating the literal.

#### Scenario: The published digest length is read
- **WHEN** a consumer reads `ARTIFACT_IDENTITY_HEX_LENGTH`
- **THEN** its value is 64 and it is the same bound artifact construction enforces

#### Scenario: Digest is malformed
- **WHEN** a digest is not exactly sixty-four lowercase hexadecimal characters
- **THEN** construction fails rather than trimming, padding, or case-folding the value

### Requirement: Logical release identity
The system SHALL identify a logical release by `Jurisdiction`, `tax_year`, `ReleaseKind`, and a required source-supplied `release_identifier`. The release identifier SHALL be a `str` of 1 through 128 characters drawn from `[A-Za-z0-9._-]` and SHALL NOT begin with `.` or `-`, matching the alphabet already accepted across the repository. It SHALL be opaque and namespaced by its jurisdiction, and SHALL NOT be assumed globally unique, inferred from a filename or archive member name, or normalized into a different identifier.

Case SHALL be preserved and SHALL be significant: `ABC` and `abc` are both valid and denote different releases, because both letter cases are inside the accepted alphabet. Rejecting an identifier for differing only in case would invalidate half that alphabet or impose an unstated canonical case. Surrounding whitespace SHALL be rejected because whitespace is outside the grammar, which is a different rule from case and SHALL NOT be grouped with it. `ReleaseIdentity` SHALL contain no artifact identity.

#### Scenario: Two counties reuse one source label
- **WHEN** a Dallas release and a Collin release carry the same source-supplied release identifier, tax year, and kind
- **THEN** their release identities do not compare equal, and neither identifier is renamed

#### Scenario: One county issues two releases of one kind in one year
- **WHEN** two releases share a jurisdiction, tax year, and kind and differ only in release identifier
- **THEN** their release identities do not compare equal

#### Scenario: Two identifiers differ only by case
- **WHEN** one release identifier is `ABC` and another is `abc`, all else equal
- **THEN** both are valid and the two release identities are unequal, because case is inside the accepted alphabet and the identifier is opaque

#### Scenario: An identifier would be altered to be accepted
- **WHEN** a supplied release identifier carries surrounding whitespace, a path separator, or any other character outside the accepted alphabet, or falls outside 1 through 128 characters, or begins with `.` or `-`
- **THEN** construction fails and the identifier is not trimmed, lowercased, slugified, or otherwise rewritten

The tax year SHALL be an `int` from 1900 through 2200 inclusive, matching the bound `ReleasePartition` and the merged `partition_tax_year_plausible` constraint already enforce, and `bool` SHALL be rejected. The narrower 1900–2100 bound applied to source years at the county parser boundary is a different value and remains unchanged.

#### Scenario: A tax year is outside 1900 through 2200
- **WHEN** a tax year is not an `int` from 1900 through 2200 inclusive
- **THEN** construction fails rather than clamping or coercing the value

### Requirement: Canonical release kind vocabulary
The system SHALL define a closed canonical `ReleaseKind` vocabulary of exactly `proposed`, `certified`, `supplemental`, and `current`. A county-native label SHALL be mapped to a canonical kind only where an accepted county contract supports semantic equivalence, and the source-native label SHALL be retained at the adapter or source boundary. The vocabulary SHALL NOT be widened to carry an unresolved county label.

The mapping table is fixed here as normative data, in this document rather than in a design or engineering note, because the promoted capability spec is the only one of those that survives archival as contract.

Supported mappings, each resting on an accepted county contract:

| jurisdiction | source-native label | canonical `ReleaseKind` |
|---|---|---|
| `tx-dallas` | `proposed` | `proposed` |
| `tx-dallas` | `certified` | `certified` |
| `tx-dallas` | `certified-with-supplemental` | `supplemental` |
| `tx-collin` | `current` | `current` |
| `tx-collin` | `certified` | `certified` |
| `tx-denton` | `certified` | `certified` |
| `tx-ellis` | `certified` | `certified` |
| `tx-tarrant` | `certified` | `certified` |

Unmapped, and SHALL NOT be canonicalized without a separate decision establishing equivalence:

| jurisdiction | source-native label | why it is unmapped |
|---|---|---|
| `tx-denton` | `preliminary` | It resembles `proposed`, and no accepted contract establishes equivalence; Denton's contract leaves preliminary-to-certified replacement semantics subject to unmeasured same-year evidence. |
| `tx-denton` | `roll-correction` | It resembles `supplemental`, and both are described as full replacement snapshots — a similarity between two descriptions rather than evidence that they are one release kind. |

This table deliberately has no canonical-kind column. Naming the kind each label *resembles* in the position the supported table uses for the kind each label *maps to* is how a reader, or a checker, comes to treat a resemblance as a mapping.

No jurisdiction absent from the supported table SHALL have a native label canonicalized, and `tx-rockwall` publishes no appraisal roll and appears in neither table.

Runtime county-native label mapping belongs at the county-aware use-case boundary. The shared adapter source-contract module SHALL remain county-neutral and SHALL NOT host county-specific mapping behavior. The scenarios below define the contract the county-aware mapping boundary must satisfy.

#### Scenario: A contract-supported label is canonicalized
- **WHEN** an adapter maps a county-native label for which an accepted contract establishes equivalence
- **THEN** the canonical kind is used and the source-native label is retained separately

#### Scenario: A Dallas supplemental release is classified
- **WHEN** a Dallas release carries the source-native label `certified-with-supplemental`
- **THEN** it maps to canonical kind `supplemental` and the verbatim label is retained, and it is not classified as `certified`

#### Scenario: A Denton preliminary release is presented
- **WHEN** a Denton release carries the source-native label `preliminary` or `roll-correction`
- **THEN** no canonical kind is produced, the source-native label is retained, and the label is not canonicalized as `proposed` or `supplemental`

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
The system SHALL define named-field JSON as the authoritative canonical serialization for every serialized identity and provenance value, and SHALL produce byte-identical output for equal values.

Round-trip losslessness SHALL be scoped to what each document carries. A jurisdiction identity document SHALL round-trip its two identity components and compare equal to the original; it SHALL NOT be described as round-tripping `county_fips`, which it does not carry and therefore cannot detect a change in — a document written before a registry correction parses successfully with the corrected value. The separate registry-metadata document IS the lossless auditable metadata shape: it carries the FIPS as written and can detect that disagreement. Every other serialized value SHALL round-trip without loss and with no altered component. Compact string renderings MAY be derived for readability and for adapter key composition, and SHALL NOT be the authoritative contract. Any compact release rendering SHALL be reversible for every accepted release identifier, and that reversibility SHALL be proved against the accepted identifier alphabet rather than asserted.

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

Registry metadata SHALL serialize as its own document keyed by the identity rather than inside it, and that document is the sixth normative shape:

```json
{"jurisdiction": {"state_code": "tx", "county_slug": "collin"}, "county_fips": "48085"}
```

Identity values SHALL nest as objects rather than as pre-rendered strings, so no reader parses a string to recover a field the writer held. An absent optional value SHALL be emitted as JSON `null` and SHALL NOT be omitted, so that a field's absence and a reader's older schema are distinguishable. Key order SHALL be the declaration order shown above for all six shapes and SHALL NOT depend on insertion or hashing.

Parsing SHALL be defined as follows, because a `Jurisdiction` requires a FIPS its identity document omits. Parsing a jurisdiction identity document SHALL resolve `county_fips` from the version-controlled registry for the named slug — the same source construction validates against — and SHALL fail when the registry describes no such slug, rather than producing a jurisdiction with an invented or stale value. The registry document SHALL have its own parser, SHALL be rejected when its FIPS disagrees with the registry, and SHALL NOT be used to reconstruct identity in place of the registry.

#### Scenario: Equal values serialize identically
- **WHEN** two equal identity values are serialized
- **THEN** the output is byte-identical, including field order

#### Scenario: Serialized identity round-trips
- **WHEN** an identity value other than a jurisdiction identity document is serialized and parsed back
- **THEN** the result compares equal to the original and carries no altered component

#### Scenario: A jurisdiction identity document round-trips its identity
- **WHEN** a jurisdiction identity document is serialized and parsed back
- **THEN** the result compares equal to the original on state code and county slug, and its FIPS is whatever the registry currently assigns rather than a value recovered from the document

#### Scenario: A jurisdiction identity document is parsed
- **WHEN** a jurisdiction identity document is parsed
- **THEN** its FIPS is resolved from the version-controlled registry, and a document naming a slug the registry does not describe fails to parse rather than resolving to an invented value

#### Scenario: A registry document disagrees with the registry
- **WHEN** a registry metadata document carries a FIPS the registry does not assign to that slug
- **THEN** it is rejected rather than preferred over the registry, and this is the only shape in which such a disagreement is detectable

#### Scenario: A registry document is parsed
- **WHEN** a registry metadata document is parsed
- **THEN** the parser returns the jurisdiction identity together with the FIPS the document recorded, so the recorded value remains available for audit rather than being replaced by the registry's

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

### Requirement: Explicit public domain surface
The system SHALL export the canonical identity and provenance types through the `property_tax_domain` package root with an explicit `__all__`, and SHALL NOT require consumers to import a submodule directly. The exported set SHALL be exactly `ARTIFACT_IDENTITY_HEX_LENGTH`, `ArtifactIdentity`, `ArtifactReleaseBinding`, `County`, `CountySlug`, `DomainProvenance`, `INITIAL_COUNTIES`, `Jurisdiction`, `ReleaseIdentity`, `ReleaseKind`, and `county_by_slug`, and SHALL be asserted against that enumeration rather than against a set the implementation declares for itself.

The four existing names SHALL be retained: `CountySlug` and `county_by_slug` are imported from the package root by seven county adapter modules, and removing them would break each. Serialization functions SHALL NOT be exported at the root and remain reachable through the serialization module, being operations on the vocabulary rather than part of it.

#### Scenario: A consumer imports the vocabulary
- **WHEN** another layer imports the canonical identity and provenance types
- **THEN** they are available from the package root without the consumer importing the submodule each type lives in

#### Scenario: The export set drifts from the enumeration
- **WHEN** a public name is added to or removed from the package root
- **THEN** the export-surface test fails against the enumerated set, including removal of any of the four pre-existing names

