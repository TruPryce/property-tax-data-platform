# Canonical identity and provenance

The vocabulary in `property_tax_domain` for three facts the platform was already
representing five different ways: which jurisdiction, which logical release, and
which bytes.

Normative behaviour is the accepted capability, not this page. Where the two
disagree, the capability governs and this page is wrong.

## The values

| type | identity | notes |
|---|---|---|
| `Jurisdiction` | `state_code` + `county_slug` | `county_fips` is required registry metadata, excluded from equality and hashing |
| `ArtifactIdentity` | the SHA-256 digest | nothing else — no location, name, entity tag, surrogate key, or timestamp |
| `ReleaseKind` | closed vocabulary | `proposed`, `certified`, `supplemental`, `current` |
| `ReleaseIdentity` | jurisdiction + tax year + kind + `release_identifier` | carries no artifact |
| `ArtifactReleaseBinding` | the pair | many-to-many in both directions |
| `DomainProvenance` | composes release and artifact | plus four bounded lineage fields |

Caller identity is never rewritten. An uppercase state code, an identifier
carrying whitespace, and a digest in uppercase hex are each refused rather than
folded, because a caller that receives a different identity than the one it
supplied has no way to know.

## Release kind mappings

Mirrored from the accepted capability for readers. The capability holds the
normative table; runtime mapping is deferred under D9 to bootstrap task 2.4 and
**no code in the domain performs it**.

Supported, each resting on an accepted county contract:

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

Unmapped, and not to be canonicalized without a separate decision:

| jurisdiction | source-native label | why it is unmapped |
|---|---|---|
| `tx-denton` | `preliminary` | It resembles `proposed`, and no accepted contract establishes equivalence. |
| `tx-denton` | `roll-correction` | It resembles `supplemental`; both being described as full replacement snapshots is a similarity between descriptions, not evidence. |

There is deliberately no canonical-kind column on the second table. Naming the
kind a label *resembles* where the first table names the kind it *maps to* is how
a reader comes to treat a resemblance as a mapping.

`tx-rockwall` publishes no appraisal roll and appears in neither table.

## Serialization

Named-field JSON is the contract; the compact forms are conveniences.

```json
{"state_code": "tx", "county_slug": "collin"}
{"jurisdiction": {"state_code": "tx", "county_slug": "collin"}, "county_fips": "48085"}
{"sha256": "<64 lowercase hex>"}
```

`county_fips` sits in its own registry document rather than in the identity
document. Including it would make two rules contradict each other: equality is
state and slug only, so two jurisdictions carrying different FIPS would be equal,
while equal values must serialize identically. Both hold at once only because
registry validation makes a mismatched pair unconstructible — which also means a
jurisdiction identity document cannot detect that the registry corrected a FIPS.
The registry document can, because the recorded value is in it.

The compact release form is `tx-collin/2025/certified/<release_identifier>` and
needs no escaping. That is a property of the alphabets rather than of the
renderer: the identifier alphabet is `[A-Za-z0-9._-]` and a jurisdiction is
lowercase alphanumeric segments joined by hyphens, so no component can contain a
`/`. The test proves that by discovering the alphabet from the validator, so
widening it later fails rather than making the rendering ambiguous.

## What existing layers map to

Nothing below is rewritten by this change. Each row records where the mapping
will be performed.

| existing representation | maps to | performed by |
|---|---|---|
| `ReleasePartition(jurisdiction_code, tax_year, release_kind)` | three of four `ReleaseIdentity` components; the identifier is caller-supplied | bootstrap task 3.4 |
| `StoredArtifact.sha256` | `ArtifactIdentity` | bootstrap task 3.4 |
| `bronze.release_partition` row | `ArtifactReleaseBinding` | bootstrap task 3.4 |
| `SourceProvenance` | `DomainProvenance` plus retained adapter fields | bootstrap task 2.4 |
| `silver.source_record` provenance columns | `DomainProvenance` | bootstrap task 3.5 |
| `artifact_key` / `partition_prefix` | adapter renderings derived from identities | unchanged |

`table_name`, `source_family`, `source_status`, `observed_fields`, and
`normalized_fields` stay on the adapter's `SourceProvenance`. The last two are
vectors of county field *names*, and admitting them would put county vocabulary
in the domain.

## Deferred

- **Runtime label mapping** — D9, bootstrap task 2.4, needs its own scope
  decision. The shared adapter contracts module is county-neutral by its
  accepted contract and its suite asserts no county name appears in it.
- **Tarrant release discrimination** — the accepted Tarrant contract requires
  every artifact preserved as a separate release and supplies no discriminator
  between two mutable same-year snapshots. The domain constructor validates the
  syntax of a supplied identifier and cannot know whether a county contract
  authorized it; that refusal belongs to the county-aware boundary.

## Validated state

Recorded under task 6.1 of the accepted change, from the default repository gate
rather than a direct package invocation. Checkboxes in the OpenSpec change and
bootstrap task 2.1 are deliberately untouched; those belong to the separate
completion and archival pull request.

| gate | result |
|---|---|
| `pytest` (default collection) | 1,319 passed, 142 skipped |
| `make check` | pass, 464 repository files validated |
| `make prepr-no-ai` | pass |
| `make docs` | 58 documents, local links validated |
| `openspec validate --all --strict` | 14 passed, 0 failed |
| `openspec doctor` | pass |
| `ruff format --check .` and `ruff check .` | pass |
| `mypy` | pass, 40 source files |

Collected by the default configuration, which is the number that matters — a
suite outside `testpaths` exists while every gate ignores it:

| module | tests |
|---|---:|
| `tests/unit/property_tax_domain/test_identity.py` | 50 |
| `tests/unit/property_tax_domain/test_serialization.py` | 67 |
| `tests/unit/property_tax_domain/test_provenance.py` | 23 |
| `tests/unit/property_tax_domain/test_public_surface.py` | 17 |
| `tests/unit/property_tax_domain/test_binding.py` | 7 |
| `tests/architecture/test_dependency_direction.py` | 5 |

Canonical serialization takes a domain value rather than a mapping, so the bytes
cannot depend on a caller's insertion order and an undeclared field is
unrepresentable rather than merely rejected on the way back in.

## Related

- [Engineering documentation](../README.md)
- [Property tax domain](../../libs/property-tax-domain/README.md)
- [Canonical identity capability](../../openspec/changes/add-canonical-identity-and-provenance-domain/specs/canonical-identity-and-provenance/spec.md)
