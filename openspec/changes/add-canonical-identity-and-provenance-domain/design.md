# Design: canonical identity and provenance

## Context

Issue #100 lists six decisions that had to be settled before implementation.
All six were settled by the maintainer and are recorded here as D1 through D6,
each with the evidence that supports it and the alternatives that were rejected.
Two points that evidence does not settle are recorded as blockers rather than
answered.

## Decisions

### D1 (accepted): Jurisdiction identity is state and county slug; FIPS is registry metadata

`Jurisdiction` is identified by `state_code` and `county_slug`, rendered
`tx-collin`. `county_fips` is required, validated registry metadata carried on
the same object, and is not a second identity.

The evidence is that the slug is already the identifier everywhere the platform
actually keys on a jurisdiction: `SourceProvenance.jurisdiction_code`,
`ReleasePartition.jurisdiction_code`, the `jurisdiction_code` column and its
pattern constraint in all five merged schemas, and the `releases/{jurisdiction_code}/`
S3 prefix. FIPS appears in exactly two places — `County.fips` and one CLI
field — and in one specification sentence.

That sentence is the problem this decision removes. The canonical account
identity in `county-appraisal-normalization` reads `(county_fips, source_account_id)`,
which would make the platform identify a county by slug in five places and by
FIPS in a sixth. Two identifiers for one concept is the defect class this whole
change exists to close, and leaving it in a specification is worse than leaving
it in code, because it will be implemented faithfully.

A `Jurisdiction` must reject registry data that disagrees with itself: `tx-collin`
paired with Dallas County's FIPS is unconstructible, not merely discouraged.

**Rejected — FIPS as identity.** It is a stable federal code, which is a real
argument. It is also absent from every storage key, every provenance field, and
every constraint the platform has already shipped, so adopting it would mean
rewriting all of them to gain nothing the slug does not already provide. It also
names a county rather than an appraisal district, and the platform's unit of
source authority is the district that publishes the roll.

**Rejected — an opaque jurisdiction string.** The current
`^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$` pattern admits `tx-collin` and would keep
working. It also admits `tx-collin-old-2` and cannot say which part is the state,
so equality and rendering would depend on parsing a string the domain claims to
own.

### D2 (accepted): Release identity is jurisdiction, tax year, kind, and the source-supplied identifier

`ReleaseIdentity` carries all four. `release_identifier` is required, bounded,
opaque, caller-supplied, namespaced by `Jurisdiction`, never assumed globally
unique, never inferred from a filename, and never normalized into a different
identifier.

The three-part form `(Jurisdiction, tax_year, ReleaseKind)` was considered and is
insufficient: a county can issue two distinct releases in one year under one
kind, and the three-part form collapses them into one identity with two
artifacts — which the divergence view would then report as an alarm on a
legitimate refresh. Including the source-supplied identifier is also what makes
the requirement that two counties may reuse one label harmless: the label is
namespaced by the jurisdiction inside the identity, so `tx-dallas` and
`tx-collin` carrying `2025-CERT` are unequal without either of them being
renamed.

Normalization is prohibited rather than discouraged. An identifier that is
lowercased, trimmed, or slugified on the way in is a different identifier than
the county published, and the platform would have no way to say which one it
holds.

**Rejected — the artifact checksum as an implicit discriminator.** It would
resolve Tarrant immediately and it is wrong: it makes every re-acquisition of
identical bytes the same release and every byte-level difference a new one,
which is a statement about storage, not about what a county published.

**Rejected — an acquisition timestamp in identity.** It discriminates, and it
means the same release acquired twice has two identities.

### D3 (accepted): Four canonical release kinds, mapped only where a contract supports it

`ReleaseKind` is a closed vocabulary of `proposed`, `certified`, `supplemental`,
and `current` — the four the accepted `county-appraisal-normalization` contract
already names. County-native labels are retained separately at the adapter
boundary.

Mappings supported by accepted contracts today:

| county | native label | canonical | basis |
|---|---|---|---|
| Dallas | `proposed` | `proposed` | label-derived classification, verbatim label retained |
| Dallas | `certified` | `certified` | same |
| Collin | `current` | `current` | derived from the explicit `curr_val_yr` family |
| Collin | `certified` | `certified` | derived from the explicit `cert_val_yr` family |
| Ellis | `certified` | `certified` | certified all-property roll |
| Tarrant | `certified` | `certified` | certified core member |
| Denton | `certified` | `certified` | authoritative directory path |

Not mapped, deliberately:

| county | native label | why it stays source-native |
|---|---|---|
| Denton | `preliminary` | Resembles `proposed`. No accepted contract establishes equivalence, and Denton's own contract leaves preliminary-to-certified replacement semantics subject to unmeasured same-year evidence. |
| Denton | `roll-correction` | Resembles `supplemental`. Both are described as full replacement snapshots, which is a similarity between two descriptions, not evidence that they are the same release kind. |
| Dallas | `certified-with-supplemental` | **D7 proposes** mapping this to `supplemental`; see below. |

**D7 (proposed by this change, requires human merge):** Dallas
`certified-with-supplemental` maps to canonical `supplemental`. The accepted
Dallas contract classifies it as a distinct label-derived release, treats it as a
complete replacement snapshot, and requires the dated certified-at-certification
snapshot to be retained separately — so it is already a release of its own kind
rather than a variant of `certified`. Merging this change accepts that reading.
If it is not accepted, Dallas keeps the native label and canonicalizes only
`proposed` and `certified`, and nothing else in this change changes.

**Rejected — widening `ReleaseKind` to hold every county's vocabulary.** A kind
per county label is a vocabulary that describes sources rather than releases, and
the canonical enum would grow with each county rather than converge.

**Rejected — an open string kind.** It would unblock Denton today by letting the
adapter write `preliminary` straight through, which is precisely the inference
this decision refuses to make silently.

### D4 (accepted): Artifact identity is content alone, related to releases by an explicit binding

`ArtifactIdentity` is a SHA-256 digest and nothing else: no S3 URI, bucket, key,
URL, filename, ETag, surrogate ID, or acquisition timestamp. `ReleaseIdentity`
holds no artifact. The relationship is an immutable `ArtifactReleaseBinding`, and
it is many-to-many in both directions:

- one artifact carries several logical releases — measured on Collin, where one
  archive holds current values for one tax year and certified values for another;
- one release is observed in several artifacts — required by Tarrant, and the
  case that makes divergence observable rather than destructive.

**Rejected — promoting the existing S3 reference object or the PostgreSQL
association row into the domain.** Both already express this relationship
correctly, which is why the shape is right; neither should become the domain
type, because that would make the domain's vocabulary a consequence of a storage
layout and reintroduce the coupling this change removes.

**Rejected — an artifact list on the release.** It makes the release mutable in
the one way identity must not be: acquiring a second artifact would change the
identity of a release that has not changed.

### D5 (accepted): Domain provenance composes identities and carries nothing free-form

`DomainProvenance` carries `ReleaseIdentity`, `ArtifactIdentity`,
`source_member_name`, `source_row_number` where applicable,
`parser_contract_version`, and a layout fingerprint where applicable. It does not
restate jurisdiction, tax year, kind, or release identifier as independent
strings, because `ReleaseIdentity` already contains them and two copies of one
fact is the defect being removed.

These stay outside `property_tax_domain`, at the adapter boundary: `table_name`,
`source_family`, `source_status`, `observed_fields`, `normalized_fields`, and
every county-native field vector. The last two are vectors of county field
*names*, and admitting them would put county vocabulary in the domain.

Every value is bounded and validated. There is no free-form field, which is
enforced structurally rather than by review: with no field capable of holding
one, a complete source row, an arbitrary source value, owner information, a
mailing or situs address, a credential, a signed URL, a host-local path, and
exception text are all unrepresentable. Absence is explicit and never a
fabricated placeholder.

**Rejected — a `details` or `extra` mapping for adapter-specific lineage.** It is
the field every one of the above eventually lands in.

### D6 (accepted): Named-field JSON is authoritative; the compact form is derived and reversible

The canonical serialization is named-field JSON. Compact renderings exist for
readability and for adapters to derive keys from, and they are not the contract.

```json
{
  "jurisdiction": {"state_code": "tx", "county_slug": "collin", "county_fips": "48085"},
  "tax_year": 2025,
  "release_kind": "certified",
  "release_identifier": "COLLIN-2025-CERT-01"
}
```

The compact release rendering is `tx-collin/2025/certified/COLLIN-2025-CERT-01`,
and it needs no escaping. That is measured rather than assumed: every accepted
identifier alphabet in the repository is `[A-Za-z0-9._-]` bounded to 1–128
characters, and the jurisdiction pattern is `[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*`.
Neither admits `/`, the canonical kinds are four lowercase words, and a tax year
renders as digits — so a four-way split on `/` recovers the components exactly.
Verified across 5,328 round trips over the full single-character alphabet and
adversarial forms including `a`×128, `a..b`, `a--b`, and `DCAD2025_CURRENT`, with
zero failures and zero collisions across 1,920 distinct renderings.

Because that reversibility is a property of the accepted alphabets rather than of
the renderer, the specification requires it to be re-proved against the alphabet
rather than asserted, so widening the alphabet later fails a test instead of
silently making the rendering ambiguous.

`ArtifactIdentity` renders as its 64 lowercase hexadecimal characters, bare.
`Jurisdiction` renders as `tx-collin`.

**Rejected — making `partition_prefix()` the domain format.** The S3 layout
already renders three of the four components in this order, which is why the
compact form resembles it. Adopting the storage key as the domain contract would
mean a bucket reorganization changes domain identity.

**Rejected — a compact form as the only serialization.** Every reader would parse
a string to recover fields the writer already had.

## Blockers

Neither blocks the rest of this change.

**B1 — Tarrant release discrimination.** The accepted Tarrant contract requires
every artifact preserved as a separate release and supplies no discriminator for
two mutable same-year snapshots. Its own scenario already resolves this the same
way: a newer artifact under a mutable or companion locator is stored in Bronze
and blocked until account-set comparison or official documentation classifies it.
Canonical `ReleaseIdentity` construction for that case is therefore blocked on
approved evidence. A Tarrant snapshot without an approved discriminator must fail
construction rather than be coerced, and the specification requires a test
proving it.

**B2 — Denton `preliminary` and `roll-correction`.** Unmapped, as recorded in D3.
Denton's `certified` releases are unaffected.

## Cross-layer mapping, without rewriting any layer

| existing representation | maps to | when |
|---|---|---|
| `ReleasePartition(jurisdiction_code, tax_year, release_kind)` | three of four `ReleaseIdentity` components; the source-supplied identifier is supplied by the caller | task 3.4 completion |
| `StoredArtifact.sha256` | `ArtifactIdentity` | task 3.4 completion |
| `bronze.release_partition` row | `ArtifactReleaseBinding` | task 3.4 completion |
| `SourceProvenance` | `DomainProvenance` plus retained adapter fields | task 2.4 |
| `silver.source_record` provenance columns | `DomainProvenance` | task 3.5 |
| `artifact_key` / `partition_prefix` | adapter renderings derived from identities | unchanged now |

No layer is rewritten in this change, and existing tests stay green.
