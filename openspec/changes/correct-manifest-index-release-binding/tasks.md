# Tasks

The promoted
[`acquisition-manifest-index`](../../specs/acquisition-manifest-index/spec.md) capability remains
authoritative. These tasks correct only its queryable attachment grain: `ReleasePartition` stays a
three-part Bronze/source partition, while `(ManifestRef, ReleaseIdentity)` selects one immutable
full-release attachment. No task implements PostgreSQL, changes S3 layout, or resumes bootstrap
3.5.

**Review scope** — one scope, `manifest-index-release-binding`, covering every task in this change.
Issue #138 remains blocked until this correction is implemented, independently reviewed, promoted,
and archived.

## 1. Correct the application contract and focused proof

<!-- countyforge-task: 1.1 paths=libs/property-tax-application/src/property_tax_application/bronze.py,libs/property-tax-application/src/property_tax_application/__init__.py,tests/architecture/test_dependency_direction.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D4,D5 -->

- [x] 1.1 Correct the public `ManifestIndex` boundary — Change `attach_partition` to take `ManifestRef`, complete `ReleaseIdentity`, and `ReleasePartition`; add and export `ManifestAttachmentConflictError`; document that the full pair selects one immutable attachment while the partition remains Bronze evidence; and update the exact public-surface/signature guard. Preserve `partition_for`, `ReleasePartition` fields, `BronzeStore`, object-store operations, and every unrelated export.

<!-- countyforge-task: 1.2 paths=libs/property-tax-application/tests/test_manifest_index.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D3,D4,D5,D6,1.1 -->

- [x] 1.2 Correct the focused manifest-index fake and falsification suite — Key attachments by `(ManifestRef, ReleaseIdentity)`; stop `register()` from turning manifest partitions into full-release attachments; verify all three overlapping fields before mutation; make exact retries no-ops and conflicting repeats raise `ManifestAttachmentConflictError` without overwrite. Prove identifiers `A`/`B` do not alias, wrong identifiers remain absent, distinct and absent freshness remain independent, overlap mismatches leave state unchanged, one acquisition can carry both releases, and `ReleasePartition` gained no identifier.

## 2. Propagate the boundary and document the handoff

<!-- countyforge-task: 2.1 paths=libs/property-tax-application/tests/test_port_contracts.py,libs/property-tax-application/tests/test_publication.py checks=repo.check risk=normal prerequisites=D2,D6,D8,1.2 -->

- [x] 2.1 Update application-contract and publication fakes — Pass the complete release identity at every attachment call, store by the full pair, and preserve the existing publication read path. Prove a later-process publication reads only the indexed attachment for its run's `ManifestRef` and full identity, never aliases an identifier, never rediscovers the page, never substitutes acquisition or clock time, and distinguishes no attachment from attached `source_as_of=None`.

<!-- countyforge-task: 2.2 paths=libs/property-tax-application/README.md checks=repo.check risk=normal prerequisites=D1,D6,D7,D9,2.1 -->

- [x] 2.2 Document the corrected grain and close implementation proof — Explain that `ReleaseManifest.partitions` remain three-part immutable Bronze evidence while `ManifestIndex` explicitly attaches queryable evidence by `(ManifestRef, ReleaseIdentity)`. Record that resumed #138 planning must provide full-release relational storage, not only a freshness column on the three-part table. Run focused and repository gates, confirm no adapter, S3, migration, bootstrap checkbox, or publication API changed, and leave #138 blocked for independent review plus promotion/archive.
