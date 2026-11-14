# Property Tax Application

The application package owns the infrastructure-neutral ports that coordinate acquisition,
discovery, processing, canonical loading, quality, publication, and application time. Import the
public boundary from `property_tax_application`; adapters implement it without becoming part of it.

## Port Ownership

| Port | Owns | Deliberately does not own |
|---|---|---|
| `ArtifactSink` | Bounded streaming writes and durable commit or abort | Acquisition policy, manifest indexing, or general object-store operations |
| `BronzeStore` | Immutable artifact evidence and its storage locator | The queryable acquisition reference a processing run needs |
| `ManifestIndex` | Idempotent acquisition registration, partition evidence, and `ManifestRef` | Object-store layout or an identity derived from a locator or checksum |
| `SourceRegistry` | Infrastructure-free source selection and release-kind validation | Network access or source parsing |
| `ReleaseDiscovery` and `promote` | Bounded discovery evidence and the single transition to complete release identity | Acquisition, county parsing, or identity synthesis |
| `ProcessingRunRepository` | Starting, resuming, refusing, and finishing processing runs | A particular locking or lease mechanism |
| `CanonicalReleaseRepository` | The already-promoted canonical load session boundary | Re-stating its transition table here |
| `QualityRepository` | Run-bound rules, evaluations, and computed verdicts | Persisting a verdict or re-evaluating an existing run |
| `PublicationRepository` | Publication attempts, lineage, quality-gated activation, failure, and supersession | Gold product construction or promotion mechanics |
| `Clock` | Injectable application current time | Publisher or release freshness |

The canonical load state machine belongs to the
[`canonical-load-session` capability](../../openspec/specs/canonical-load-session/spec.md) and is
explained in the [canonical load engineering guide](../../docs/engineering/canonical-load-session.md).

## Manifest Split

`BronzeStore` and `ManifestIndex` are separate because they promise different things:

```text
BronzeStore    -> immutable object-store evidence -> storage locator
ManifestIndex -> queryable acquisition index      -> ManifestRef

ReleaseManifest.partitions
               -> three-part immutable Bronze/source evidence
ManifestIndex attachment
               -> ManifestRef + full ReleaseIdentity -> ReleasePartition evidence
```

A processing run needs `ManifestRef`. It is a persistence-generated opaque locator and is derivable
from neither the object-store locator nor the artifact checksum. The reference identifies the
acquisition, not a release. A complete `ReleaseIdentity` identifies the logical release within that
acquisition, while `ReleasePartition` remains the overlapping three-part Bronze evidence and optional
source freshness bound to the pair. Registering a manifest therefore records no full-release
attachment by itself, even when the manifest already carries source partitions.

Bootstrap 3.5 must persist that queryable attachment at full-release grain: acquisition reference,
jurisdiction, tax year, release kind, release identifier, and optional source-as-of evidence. Adding
only a nullable `source_as_of` field to the existing three-part `bronze.release_partition` relation
cannot distinguish releases that share jurisdiction, year, and kind but have different identifiers.
The exact PostgreSQL relation remains the adapter implementation's decision.

`ArtifactSink` was retained, and the `BronzeStore` Protocol was retained unchanged. `ReleaseManifest`
and the S3 manifest serialization and storage mechanics received bounded corrections because the old
artifact-grain manifest key conflicted with acquisition-grain evidence. The concrete mechanics remain
documented with the [adapters](../property-tax-adapters/README.md).

## Handoffs

- Bootstrap 2.4 composes these application ports instead of calling adapter types directly. It also
  owns retiring the S3 adapter's `utc_now()` when composition adopts injected `Clock`.
- The publication boundary stops at an admitted attempt and its metadata. Bootstrap 6.2 owns the Gold
  build, product construction, and promotion mechanics.
- The application owns `ReleaseProcessingOutcome` because dependency direction forbids importing the
  adapters' outcome representation. Their mapping must remain total; the architecture suite guards
  the mirrored boundary version.

## Related

- [Shared libraries](../README.md)
- [Architecture](../../docs/architecture/README.md)
- [Canonical load session capability](../../openspec/specs/canonical-load-session/spec.md)
