## ADDED Requirements

<!-- Owns: `SourceRegistry`, `UnsupportedSource`, expected media types on
     `CountySourceDefinition`; `ReleaseDiscovery`, `SourceCandidate`,
     `PageEvidence`, `LogicalReleaseEvidence`, `UnchangedRelease`; and the one
     promotion from evidence to `ReleaseIdentity` with
     `IncompleteReleaseIdentity`.
     Cites: the accepted `canonical-identity-and-provenance` spec for
     `ReleaseIdentity`; the bootstrap `source-release-ingestion` delta for the
     registry and discovery requirements this spec refines. -->

### Requirement: Source resolution fails before network acquisition and describes expected media
Source resolution SHALL resolve a jurisdiction to its registered source definition without performing network access, and SHALL fail with a named, actionable error where the jurisdiction is not registered.

A requested release kind SHALL be optional. Where a caller supplies one, resolution SHALL reject an unregistered kind before any network acquisition. Where a caller cannot supply one — because the source establishes its release kinds only in acquired content — resolution SHALL succeed on the jurisdiction alone rather than requiring the caller to name a kind it has not yet learned.

The system SHALL additionally provide validation of a release kind once it is known, and a kind established only by parsing SHALL be validated after parsing and before promotion. Rejecting such a kind before network acquisition is not possible, and the boundary SHALL NOT require a caller to invent one to proceed.

A resolved definition SHALL describe the expected media types of the source, and SHALL NOT carry a credential or a secret value.

#### Scenario: A registered jurisdiction is resolved without a kind
- **WHEN** a caller resolves a registered jurisdiction without naming a release kind
- **THEN** its source definition is returned and no network access is performed

#### Scenario: An unregistered jurisdiction is requested
- **WHEN** a caller requests a jurisdiction that is not registered
- **THEN** resolution fails before network acquisition with a named error identifying what was requested

#### Scenario: An unregistered release kind is requested
- **WHEN** a caller requests a registered jurisdiction together with a release kind that is not registered for it
- **THEN** resolution fails before network acquisition with a named error

#### Scenario: A release kind is established only by content
- **WHEN** a source's release kinds are established only in acquired content
- **THEN** the jurisdiction resolves without one, and the kind is validated after parsing establishes it and before promotion

#### Scenario: A resolved definition is inspected
- **WHEN** a source definition is resolved
- **THEN** it describes the expected media types of the source and carries no credential

### Requirement: Discovery carries bounded evidence and distinguishes a new release from an unchanged one
Release discovery SHALL observe **one jurisdiction per invocation** and SHALL return, for that
source, either a source candidate or a no-change result. It SHALL NOT accept a cohort of
jurisdictions: six counties are six independent publishers, and a cohort operation would have to
either fail all six when one page times out or return a partial result needing a per-jurisdiction
error carrier this boundary does not define. Fanning out across the six is the caller's, which is
where the schedule, the ordering, and the per-county failure handling already live. A source candidate SHALL carry the jurisdiction, the source locator, the remote metadata, the source as-of evidence, and the page evidence the source published. A no-change result SHALL be returned where remote metadata and content identity match a release already acquired, and SHALL NOT require the artifact to be downloaded again.

Discovery SHALL NOT be required to establish a tax year or a release kind. Where the publisher's page establishes those facts, the source candidate SHALL carry the resulting logical release evidence, one entry per logical release; where they are established only by verified source content, the candidate SHALL carry none and that evidence SHALL be produced during parsing instead. One source candidate SHALL therefore be able to yield several logical releases backed by one artifact.

Each logical release evidence SHALL carry the source as-of instant established for that logical release, where one was established. An instant the publisher's page establishes for the export as a whole applies to every logical release drawn from it, whether the page or verified content established the release; an instant verified content establishes for one release takes precedence for that release; where neither established one, the evidence SHALL record absence, and the acquisition instant SHALL NOT be substituted. The candidate's own source as-of evidence remains what discovery preserves for the acquisition; the release-level instant is what promotion carries forward and the publication attempt receives.

**Page evidence SHALL carry a named, bounded field for each fact the county contracts need, and no
field for anything else.** Naming the carrier and leaving its contents to the implementer is what
this replaces: an implementation would have to invent a payload or drop provenance the counties
require, and a fake-only contract test would pass either way. The fields SHALL be:

| Field | Carries | Required |
| --- | --- | --- |
| `observed_at` | The instant discovery read the page, timezone-aware | yes |
| `page_url` | The page the evidence was read from, sanitized, distinct from the artifact locator | yes |
| `rendered` | Whether the link was revealed only by rendering the page rather than by its fetched bytes | yes |
| `section_heading` | The heading the release was listed under | optional |
| `link_label` | The visible text of the link to the artifact | optional |
| `directory_path` | The path the artifact was listed at, where the source is a directory listing | optional |
| `published_label` | What the page displayed as the release's date or version, **as text** | optional |

Each text field SHALL carry a **stated** maximum, not an implied one, because every one of them is
publisher-controlled and an unstated bound is the bound the first implementation happens to pick:

| Field | Maximum | Why that number |
| --- | --- | --- |
| `page_url` | 2,048 characters | The locator bound the acquisition boundary already states as `MAX_LOCATOR_CHARS`; a page URL is a locator and there is no reason for a second number |
| `section_heading`, `link_label`, `directory_path`, `published_label` | 256 characters each | The bounded-field length the application already uses for a name-like fact, stated as `MAX_FIELD_CHARS` |

A value exceeding its maximum SHALL be refused rather than truncated. Truncating would record
something the page did not say while looking like evidence of what it did, and a heading cut at 256
characters is not the heading.

`published_label` SHALL remain text and SHALL NOT be parsed into an instant here. The instant a
release was current as of is `LogicalReleaseEvidence`'s, established by the rules above; a page's
displayed label is evidence of what the page said, which is a different fact and is frequently not
a date at all.

`rendered` SHALL be recorded rather than inferred, because whether a link existed in the fetched
bytes or only after script execution is what decides whether a later retry can reproduce the
discovery without a browser.

Page evidence carrying nothing but `observed_at` and `page_url` SHALL be refused: evidence that
locates nothing on the page is not evidence, and at least one of the remaining facts SHALL be
present.

Every evidence carrier SHALL be bounded, each text field to a stated maximum, and the carrier SHALL have nowhere to put a page body, an HTML fragment, a script, or a credential — not by convention but because no field admits one. Discovery SHALL NOT return credentials, arbitrary source content, or an unbounded payload, and SHALL NOT perform county parsing or county field mapping.

#### Scenario: Discovery is examined for its invocation shape
- **WHEN** the discovery port is examined
- **THEN** it observes one jurisdiction and returns one result for it, and there is no operation taking a cohort, so one publisher being unreachable cannot fail another

#### Scenario: A new release is observed
- **WHEN** discovery observes a release not already acquired
- **THEN** a candidate is returned carrying its locator, remote metadata, source as-of evidence, and page evidence, and carrying no credential and no source row

#### Scenario: An unchanged release is observed
- **WHEN** remote metadata and content identity match a release already acquired successfully
- **THEN** a no-change result is returned, distinguishable from a candidate, and no download is required

#### Scenario: Page evidence is examined for what it carries
- **WHEN** the page evidence carrier is examined
- **THEN** it has a named bounded field for the discovery instant, the page read, whether rendering was required, the section heading, the visible link label, the directory path, and the displayed label, each with the maximum stated above, and no field for a page body, an HTML fragment, or anything unbounded

#### Scenario: A publisher supplies an oversized heading
- **WHEN** a page carries a heading, label, path, or displayed label longer than the stated maximum for that field
- **THEN** the evidence is refused rather than truncated, because a heading cut at its limit is not the heading and would read as evidence of something the page did not say

#### Scenario: A rendered page and a fetched page are distinguished
- **WHEN** one county's link exists in the fetched bytes and another's appears only after the page is rendered
- **THEN** each candidate records which it was, so a later retry knows whether it can reproduce the discovery without a browser

#### Scenario: A directory listing is the source
- **WHEN** a release is found as an entry in a directory listing rather than a link on a page
- **THEN** the evidence carries the listed path, and the fields that do not apply are absent rather than filled with a placeholder

#### Scenario: Page evidence locates nothing
- **WHEN** page evidence carries only the instant it was observed and the page it was read from
- **THEN** it is refused, because evidence that locates nothing on the page is not evidence of anything

#### Scenario: A displayed date label is preserved as text
- **WHEN** a page displays a release date in a format no contract parses
- **THEN** the label is preserved as text and no instant is manufactured from it, the release's own as-of instant being a separate fact established by its own rules

#### Scenario: A source establishes only partial release facts
- **WHEN** the source's page establishes a jurisdiction, tax year, and release kind but no release identifier
- **THEN** the evidence records exactly what was established and does not manufacture the missing component

#### Scenario: Release facts live only in source content
- **WHEN** a publisher offers one mutable export whose tax years and release kinds appear only in its content
- **THEN** discovery returns one source candidate carrying no logical release evidence, and is not required to invent a tax year or a release kind

#### Scenario: One artifact carries two logical releases
- **WHEN** parsing an acquired artifact establishes a current release for one tax year and a certified release for another
- **THEN** two logical release evidences are produced from that one artifact, and neither requires re-acquiring it

#### Scenario: Two logical releases carry their own freshness
- **WHEN** verified content establishes a current and a certified release from one artifact and a release-specific source as-of instant for one of them
- **THEN** each evidence carries its own instant, and neither is given the other's

#### Scenario: A page instant covers every release drawn from the export
- **WHEN** the publisher's page establishes one source as-of instant for the export and two logical releases are later drawn from it
- **THEN** both evidences carry that instant as page-established, and content may replace it for a release only with an instant it established for that release

#### Scenario: No source as-of instant was established for a release
- **WHEN** neither the page nor verified content establishes a source as-of instant for a logical release
- **THEN** its evidence records absence, and the acquisition instant is not substituted

### Requirement: Canonical release identity is promoted from evidence and fails closed
The system SHALL provide one promotion from logical release evidence to canonical release identity, and that promotion SHALL be the only place where an incomplete release becomes a complete one. That evidence SHALL be the single input to promotion whether it was established by the publisher's page during discovery or by verified source content during parsing, so there is one promotion seam rather than one per origin. Where fewer than all four canonical components were established, promotion SHALL fail with a named error naming what was missing.

Canonical release identity SHALL NOT be derived from a filename, a checksum, an acquisition instant, a source field name, a row ordering, or a persistence surrogate. The canonical persistence boundary SHALL accept only a complete canonical release identity, and SHALL NOT accept a Bronze release partition or a partition accompanied by a hint.

#### Scenario: Complete evidence is promoted
- **WHEN** logical release evidence whose four identity components are established is promoted
- **THEN** a canonical release identity is returned

#### Scenario: Evidence from parsing is promoted the same way
- **WHEN** logical release evidence established by source content rather than by a page is promoted
- **THEN** it passes through the same promotion and yields a canonical release identity on the same terms

#### Scenario: A release identifier was never established
- **WHEN** logical release evidence lacking a release identifier is promoted
- **THEN** promotion fails with a named error and no identifier is synthesised

#### Scenario: A Bronze partition is offered as canonical identity
- **WHEN** a caller offers a three-component Bronze release partition where canonical identity is required
- **THEN** the contract does not accept it
