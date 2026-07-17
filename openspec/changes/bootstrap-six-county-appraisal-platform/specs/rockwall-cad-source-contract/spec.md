## ADDED Requirements

### Requirement: Authoritative Rockwall GIS discovery
The system SHALL discover Rockwall Central Appraisal District's public GIS export from the official GIS Data page, SHALL assign Rockwall County FIPS `48397` from version-controlled configuration, and SHALL preserve the rendered page, visible link label, approved external file-host path, redirect chain, and discovery timestamp as provenance. Discovery MUST NOT extract client-bundle credentials or call an undocumented TrueProdigy backend content API.

#### Scenario: Discover the public GIS export
- **WHEN** the rendered official page exposes a GIS Shapefile Export link through an approved public file host
- **THEN** the system records a Rockwall partial-GIS source candidate without classifying it as the full appraisal roll

#### Scenario: Public link changes destination
- **WHEN** the link resolves to an unapproved host, authenticated portal, or ambiguous folder
- **THEN** discovery stops before artifact acquisition and records the failure for review

### Requirement: Rockwall public source is partial
The system SHALL classify the observed Rockwall ownership, parcel, road, and subdivision shapefiles as partial GIS enrichment. It MUST NOT infer appraised, assessed, capped, agricultural, exemption, jurisdiction-value, land-detail, improvement-detail, or other absent appraisal facts from the available market, land, and improvement subset.

#### Scenario: Normalize the ownership layer
- **WHEN** the ownership DBF contains parcel, owner, situs, legal, jurisdiction-code, and partial market, land, and improvement attributes
- **THEN** the system labels every emitted fact as partial GIS enrichment with layer and artifact provenance and leaves all unsupported canonical appraisal fields absent

#### Scenario: Consumer requests complete Rockwall appraisal data
- **WHEN** only the public GIS artifacts have passed validation
- **THEN** the system reports Rockwall appraisal readiness as blocked and does not represent the partial layer as a certified appraisal roll

### Requirement: Rockwall shapefile bundle integrity
If the partial GIS source is implemented, the system SHALL validate the complete shapefile component set, DBF encoding and field definitions, geometry-to-attribute record alignment, coordinate reference evidence, and deterministic layer identity before loading any geometry or attributes.

#### Scenario: Shapefile sidecar is missing or inconsistent
- **WHEN** a required SHP, SHX, DBF, PRJ, CPG, or approved equivalent component is absent, mismatched, or unsafe
- **THEN** the system quarantines the layer rather than loading misaligned geometry and attributes

#### Scenario: DBF field name is truncated
- **WHEN** the shapefile format exposes a shortened field name
- **THEN** the system maps it only through a versioned Rockwall field dictionary and never guesses the canonical meaning from a prefix alone

### Requirement: Rockwall account and owner-association grain
The system SHALL treat observed duplicate `pid` values as unresolved physical row or owner-association grain and SHALL measure account-level consistency before approving `pid` as an account identifier for either GIS enrichment or a future full roll.

#### Scenario: Duplicate ownership rows differ only by owner
- **WHEN** rows sharing `pid` agree on all required partial property and value facts and differ only in approved owner fields
- **THEN** the system may link the rows to one county-qualified account candidate while retaining distinct owner-association provenance

#### Scenario: Duplicate ownership rows conflict
- **WHEN** rows sharing `pid` disagree on a required account-level fact
- **THEN** the system preserves the source rows and diagnostics and blocks account-level publication for the affected groups

### Requirement: Rockwall ownership privacy gate
The system SHALL classify Rockwall owner names and mailing addresses as sensitive and SHALL keep owner and mailing-address publication disabled until Rockwall confidentiality handling and a reviewed field-level publication policy are approved.

#### Scenario: Inspect the ownership DBF
- **WHEN** the partial GIS layer contains owner identity and mailing fields
- **THEN** those values remain absent from logs, evidence manifests, repository fixtures, and Gold outputs

### Requirement: Full Rockwall appraisal-roll onboarding
The system SHALL require an official open-records release, publisher bulk export, or authorized vendor feed containing the required full appraisal facts before enabling the Rockwall appraisal adapter. The acquired source SHALL receive its own measured artifact, schema, release, identity, privacy, and change-detection contract even if its fields appear PACS-derived.

#### Scenario: Full roll is obtained
- **WHEN** Rockwall or an authorized provider supplies a complete appraisal release
- **THEN** the system preserves it immutably, profiles it independently, and requires an approved source-contract update before canonical loading

#### Scenario: Full roll resembles Denton or Ellis
- **WHEN** the supplied source appears to use the PACS fixed-width format
- **THEN** the system may reuse the reviewed PACS parser only after Rockwall-specific schema and semantic fingerprints pass

### Requirement: Rockwall production-readiness gate
The system SHALL keep Rockwall out of the complete six-county appraisal cohort while only the partial GIS export is available. Implementing the optional shapefile reader SHALL NOT satisfy this gate.

#### Scenario: Partial GIS succeeds without a full roll
- **WHEN** every Rockwall GIS layer passes its enrichment tests but no approved full appraisal release exists
- **THEN** the system may publish a separately labeled Rockwall GIS enrichment but cannot label the six-county appraisal cohort complete
