# Design: canonical identity and provenance

## Context

Issue #100 lists six decisions that had to be settled before implementation.
All six are recorded here as D1 through D6, each with the evidence that supports
it and the alternatives that were rejected.

**None of them is accepted yet.** They were resolved for this draft in
maintainer direction that is not a durable, linkable artifact: issue #100 still
carries no comments. The repository's approval event is the human merge of this
planning pull request, so every decision below is proposed and requires that
merge, exactly as D7 does. An earlier revision of this document labelled D1
through D6 accepted, which described a decision as settled by an event that had
not happened.

Two points that evidence does not settle are recorded as blockers rather than
answered.

## Decisions

### D1 (proposed by this change, requires human merge): Jurisdiction identity is state and county slug; FIPS is registry metadata

`Jurisdiction` is identified by `state_code` and `county_slug`, rendered
`tx-collin`. `county_fips` is required, validated registry metadata carried on
the same object, and is not a second identity.

The evidence is that the slug is already the identifier everywhere the platform
*keys* on a jurisdiction: `SourceProvenance.jurisdiction_code`,
`ReleasePartition.jurisdiction_code`, the `jurisdiction_code` column and its
pattern constraint in all five merged schemas, and the `releases/{jurisdiction_code}/`
S3 prefix.

FIPS is not marginal, and an earlier revision of this document said it was. It
appears in fourteen files outside this change: `County.fips`, one CLI field, one
unit test, `bootstrap` design, **all six county source contracts**, and the
`county-appraisal-normalization`, `source-release-ingestion`,
`validated-data-publication`, and `appraisal-query-api` requirements. Each county
contract assigns its FIPS from version-controlled configuration, and the
canonical account identity is written in terms of it.

So this decision supersedes an accepted role rather than filling a gap. What it
supersedes is FIPS as an *identifier*; what it keeps is FIPS as the validated
registry attribute those contracts assign. Every one of those sentences remains
true with FIPS as metadata — none of them keys, joins, or compares on it except
the account-identity sentence, which is the one this change amends.

That sentence is the problem this decision removes. The canonical account
identity in `county-appraisal-normalization` reads `(county_fips, source_account_id)`,
which would make the platform identify a county by slug in five places and by
FIPS in a sixth. Two identifiers for one concept is the defect class this whole
change exists to close, and leaving it in a specification is worse than leaving
it in code, because it will be implemented faithfully.

A `Jurisdiction` must reject registry data that disagrees with itself: `tx-collin`
paired with Dallas County's FIPS is unconstructible, not merely discouraged.

The lexical forms are fixed here rather than left to the implementer, because
the registry and the identity disagree on case today. `County.state_code` is
`"TX"`, hard-checked against that literal, while every `jurisdiction_code` the
platform stores matches `^[a-z]{2}-[a-z0-9]+(-[a-z0-9]+)*$` and is lowercase.

Identity takes the lowercase form, because that is what five storage and
provenance layers already hold and what the compact rendering must produce:
`state_code` is exactly two lowercase ASCII letters, and `county_slug` is
`[a-z0-9]+(-[a-z0-9]+)*`. Uppercase is **rejected, not normalized** — a caller
who supplies `TX` gets an error rather than a silently different identity than
the one they asked for, which is the same rule D2 applies to release
identifiers. The registry comparison case-folds on the *registry* side when
matching `County.state_code`, so the uppercase datum stays valid where it lives
and no caller-supplied identity is rewritten.

The tax-year bound is 1900 through 2200 inclusive, matching `ReleasePartition`
and the `partition_tax_year_plausible` constraint in the merged migration, which
are the two places a release's year is already bounded. The narrower 1900–2100
bound in the county parsers is an adapter-level check on a source year and stays
where it is; a release identity and a parsed source year are different values,
and unifying them would be a change to the parsers this plan does not authorize.

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

### D2 (proposed by this change, requires human merge): Release identity is jurisdiction, tax year, kind, and the source-supplied identifier

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

### D3 (proposed by this change, requires human merge): Four canonical release kinds, mapped only where a contract supports it

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

### D7 (proposed by this change, requires human merge): Dallas certified-with-supplemental maps to supplemental

Dallas `certified-with-supplemental` maps to canonical `supplemental`. The accepted
Dallas contract classifies it as a distinct label-derived release, treats it as a
complete replacement snapshot, and requires the dated certified-at-certification
snapshot to be retained separately — so it is already a release of its own kind
rather than a variant of `certified`. Merging this change accepts that reading.
If it is not accepted, the row is struck from the capability's mapping table
before merge and Dallas canonicalizes only `proposed` and `certified`; nothing
else in this change changes.

The capability's table states the row unconditionally, because the promoted spec
describes the final state and by the time it is promoted D7 has necessarily been
accepted. A promoted contract carrying "if D7 is refused" would be describing a
decision that can no longer be refused. The conditionality is planning rationale
and lives here.

**Rejected — widening `ReleaseKind` to hold every county's vocabulary.** A kind
per county label is a vocabulary that describes sources rather than releases, and
the canonical enum would grow with each county rather than converge.

**Rejected — an open string kind.** It would unblock Denton today by letting the
adapter write `preliminary` straight through, which is precisely the inference
this decision refuses to make silently.

### D4 (proposed by this change, requires human merge): Artifact identity is content alone, related to releases by an explicit binding

`ArtifactIdentity` is a SHA-256 digest and nothing else: no S3 URI, bucket, key,
URL, filename, ETag, surrogate ID, or acquisition timestamp. `ReleaseIdentity`
holds no artifact. The relationship is an immutable `ArtifactReleaseBinding`, and
it is many-to-many in both directions:

- one artifact carries several logical releases — measured on Collin, where one
  archive holds current values for one tax year and certified values for another;
- one release is observed in several artifacts — required by Bronze divergence,
  where `BronzeConflict.DIVERGED` names the same release identity arriving with
  a different checksum, both versions are kept and flagged rather than
  overwritten, and the merged `bronze.diverged_release` view counts the distinct
  artifacts behind one identity.

An earlier revision cited Tarrant for that second direction. It is evidence for
the opposite: Tarrant's accepted contract says **every artifact is a separate
release**, which is one artifact per release, not one release across several
artifacts. Tarrant is the source of blocker B1, not of this cardinality.

**Rejected — promoting the existing S3 reference object or the PostgreSQL
association row into the domain.** Both already express this relationship
correctly, which is why the shape is right; neither should become the domain
type, because that would make the domain's vocabulary a consequence of a storage
layout and reintroduce the coupling this change removes.

**Rejected — an artifact list on the release.** It makes the release mutable in
the one way identity must not be: acquiring a second artifact would change the
identity of a release that has not changed.

### D5 (proposed by this change, requires human merge): Domain provenance composes identities and carries nothing free-form

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

Every value is bounded and validated, and there is no generic payload, detail,
extra, metadata, or annotation field, no mapping, and no sequence of arbitrary
values.

What that does and does not guarantee is worth stating precisely, because an
earlier revision of this paragraph overstated it and the normative requirement
had to contradict its own design. Structure prevents a field whose purpose is to
accept whatever a caller has. It does not make owner data, an address, a
credential, or a path *unrepresentable*: a bounded string named
`source_member_name` can still be handed `JOHN_DOE`. Keeping sensitive values
out of what reaches provenance stays the adapter's obligation under the accepted
county contracts. Absence is explicit and never a fabricated placeholder.

**Rejected — a `details` or `extra` mapping for adapter-specific lineage.** It is
the field every one of the above eventually lands in.

### D6 (proposed by this change, requires human merge): Named-field JSON is authoritative; the compact form is derived and reversible

The canonical serialization is named-field JSON. Compact renderings exist for
readability and for adapters to derive keys from, and they are not the contract.

```json
{
  "jurisdiction": {"state_code": "tx", "county_slug": "collin"},
  "tax_year": 2025,
  "release_kind": "certified",
  "release_identifier": "COLLIN-2025-CERT-01"
}
```

**`county_fips` is deliberately absent from the identity document, and this
departs from the example in the issue's D6 — flagged rather than done quietly.**

Including it makes two accepted rules contradict each other. Equality is state
and slug only, so two `Jurisdiction` values carrying different FIPS would be
equal; serialization requires equal values to be byte-identical, so they would
also have to serialize the same. Both hold at once only because registry
validation makes a mismatched pair unconstructible — which means the rule that
FIPS is excluded from identity can never be falsified, and the identity document
silently depends on the registry never changing. A stored identity from before a
registry correction would then no longer serialize as its own identity.

Identity documents therefore carry identity. Registry metadata is a separate
document keyed by the same identity:

```json
{"jurisdiction": {"state_code": "tx", "county_slug": "collin"}, "county_fips": "48085"}
```

D1 is untouched: FIPS remains required, validated registry metadata reachable
from a `Jurisdiction`, and is not a second identity. If the maintainer wants FIPS
inside the identity document, the coherent form is to include it in equality
too — a composite identity rather than a halfway one.

Splitting the document raises a question the split has to answer: a
`Jurisdiction` requires FIPS, and its identity document omits it, so parsing one
cannot reconstruct the value object from the document alone. Resolution: the
identity document parses by resolving FIPS from the version-controlled registry
for the named slug, and fails only when the registry describes no such slug.

What that cannot do is worth stating, because an earlier revision claimed it.
A document written before a registry correction **parses successfully with the
new FIPS**, and cannot detect the correction — the old value is not in the
document to compare against. Claiming it would fail described a check the shape
makes impossible. Round-trip losslessness for the identity document is therefore
scoped to what it carries: the two identity components and equality. The
identity of a jurisdiction survives; its metadata is not being round-tripped,
because it is not in there.

The registry document is the lossless, auditable metadata shape. It carries the
FIPS as written, has its own parser returning the identity together with the
recorded FIPS, and is rejected when that FIPS disagrees with the registry —
which is the check that *can* detect a correction, because the old value is
present. Neither parser invents a FIPS.

### D8 (proposed by this change, requires human merge): the domain's public surface is explicit

`property_tax_domain/__init__.py` maintains an explicit `__all__`, and the new
value objects are exported through it rather than left as module-only imports.
The proposal calls these one stable vocabulary for the rest of the platform;
a vocabulary reached by importing a private module path is not stable, because
the path is then part of the contract.

The exact final set is enumerated here rather than left as "the declared
vocabulary", because an implementer could otherwise remove the existing API and
satisfy a self-authored test that the set is exact:

```python
__all__ = [
    "ARTIFACT_IDENTITY_HEX_LENGTH",
    "ArtifactIdentity",
    "ArtifactReleaseBinding",
    "County",
    "CountySlug",
    "DomainProvenance",
    "INITIAL_COUNTIES",
    "Jurisdiction",
    "ReleaseIdentity",
    "ReleaseKind",
    "county_by_slug",
]
```

The four existing names stay: `CountySlug` and `county_by_slug` are imported
from the package root by seven county adapter modules today, so dropping them
would break every one of them. Serialization functions are **not** exported at
the root and remain reachable as `property_tax_domain.serialization`; they are
operations on the vocabulary rather than part of it.

**Rejected — module-only imports.** It keeps the root namespace small and makes
every consumer depend on file layout.

### D9 (proposed by this change, requires human merge): runtime label mapping is deferred with a named owner

D3 fixes the canonical vocabulary and the contract-supported mapping table as
normative data. It does **not** deliver runtime mapping code in this change,
because the only shared adapter module available is county-neutral by its own
accepted contract and its suite asserts that no county name appears in it.

Runtime mapping is therefore deferred to bootstrap task 2.4, which owns the
county-aware use-case boundary, and it needs its own scope decision authorizing
where the mapping lives.

That deferral is recorded here and **creates no task**. An earlier revision
added a task marked `**BLOCKED**` in prose, which the implementation parser does
not read: measured when that task existed, the parser reported every unchecked
task with status `incomplete` and no other state, so the lane would have
dispatched runtime mapping as ordinary work whose only writable path was a
documentation file. Bold text is not a state. A
decision may name a future owner; it may not manufacture an unchecked pseudo-task
that a machine will pick up.

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

### D10 (proposed by this change, requires human merge): correct the over-broad Tarrant guard

`DomainProvenance` carries `layout_fingerprint`, and an accepted Tarrant test
asserts that string appears nowhere in `property_tax_domain` or
`property_tax_application`. Both are accepted, and they cannot both hold. The
guard is what is wrong, and five independent facts say so:

- The name was introduced by the **Dallas** parser on 2026-08-02 (`ebd60f8`),
  eleven days before the Tarrant parser landed on 2026-08-13 (`e64dd35`). It is
  not a name the Tarrant parser introduces. (The shared `contracts.py` is
  *newer* than Tarrant — 2026-08-14, `deeae43` — so "the shared module predates
  Tarrant" would be false and is not the argument.)
- Issue #43 D7 established `layout_fingerprint` as shared, adapter-neutral
  provenance rather than county vocabulary.
- The merged canonical capability requires it on `DomainProvenance`.
- The accepted Tarrant task states the invariant as "the parser adds no new
  vocabulary to them", and the test's own docstring as "no name **this parser
  introduces**". The tuple contradicts both.
- Denton and Ellis run the identical guard and neither lists it, though their
  parsers use it 23 and 27 times. Tarrant is the outlier.

The correction removes exactly one entry and renames the tuple from
`parser_vocabulary` to `tarrant_specific_vocabulary`. The rename is the durable
half: `parser_vocabulary` is ambiguous enough that the same entry could be
re-added in good faith, while the new name states the invariant the test is
actually enforcing. Every genuinely Tarrant-specific entry is preserved, and the
guard keeps failing on real leakage.

This authorizes one path outside the domain, for one edit, with the entries to
preserve enumerated in the task so the correction cannot quietly widen.

## Blockers

Neither blocks the rest of this change.

**B1 — Tarrant release discrimination.** The accepted Tarrant contract requires
every artifact preserved as a separate release and supplies no discriminator for
two mutable same-year snapshots. Its own scenario already resolves this the same
way: a newer artifact under a mutable or companion locator is stored in Bronze
and blocked until account-set comparison or official documentation classifies it.
Canonical `ReleaseIdentity` construction for that case is therefore blocked on
approved evidence.

Enforcement belongs at the county mapping boundary, not in the domain
constructor. The constructor sees four syntactically valid components and cannot
know whether `TARRANT-2025-01` is an *approved* discriminator or a string
somebody supplied — that is a fact about Tarrant's contract, which the domain
does not and must not import. The domain rejects a missing or malformed
identifier; the Tarrant mapping refuses to produce one at all while no
discriminator is approved, and the specification requires the test at that
boundary.

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
