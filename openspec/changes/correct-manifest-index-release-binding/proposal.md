## Why

`ManifestIndex.partition_for()` reads by full `ReleaseIdentity`, while `attach_partition()` can
record only a three-part `ReleasePartition`; two releases differing only by `release_identifier`
therefore alias. Issue #143 corrects that prerequisite before blocked bootstrap 3.5 planning in
#138 resumes.

## What Changes

- **BREAKING**: require `ManifestIndex.attach_partition()` to receive the `ManifestRef`, complete
  `ReleaseIdentity`, and three-part `ReleasePartition` it binds.
- Key queryable attachments by `(ManifestRef, ReleaseIdentity)`, require the three overlapping
  partition components to agree, and preserve attached absence separately from no attachment.
- Make exact reattachment idempotent and refuse conflicting evidence rather than overwriting it.
- Stop `register()` from manufacturing full-release attachments from manifest partitions that
  contain no release identifier.
- Preserve `ReleasePartition`, acquisition manifests, Bronze classification, and S3 partition
  layout at their existing three-part source-partition grain.
- Correct source-freshness authority: immutable object-store evidence remains, while the queryable
  index must durably retain freshness at full-release attachment grain for publication retries.
- Hand the future relational attachment and any migration back to #138 only after this correction
  is implemented, reviewed, promoted, and archived.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `acquisition-manifest-index`: correct queryable partition attachment from three-part aliasing to
  an explicit full-release binding without changing Bronze partition semantics.

## Impact

The later implementation changes the application-owned `ManifestIndex` Protocol, its in-memory
contract fakes and falsification tests, and documentation that currently implies object-store
partition evidence alone provides an unambiguous publication read path. It changes no database,
S3 behavior, publication API, county behavior, bootstrap checkbox, or runtime composition in this
planning change. Issue #138 remains blocked and owns the eventual PostgreSQL relation and migration.
