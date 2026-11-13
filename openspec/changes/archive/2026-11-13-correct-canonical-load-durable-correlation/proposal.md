## Why

The promoted `canonical-load-session` capability requires retained cross-batch parent mappings to preserve Python object identity after those mappings spill durably, which issue #138 proves is impossible without retaining an oversized account in application memory. Issue #139 corrects that persistence-boundary contradiction while preserving same-batch identity checks and the prohibition on value-based identity or deduplication.

## What Changes

- Define Python object identity as authoritative only while both objects coexist inside one `CanonicalRecordBatch`.
- Correct `S4` to map a correlation handle to one parent record occurrence and its account, with `S5` remaining exactly the keys of `S4`.
- Correct cross-batch `W5` so the handle selects the retained occurrence and canonical value equality only verifies consistency after resolution.
- Correct persisted-adoption `W4` so `AccountSnapshotRef` selects one persisted occurrence and equality only verifies a rehydrated value.
- Preserve identity-based `B7` and `B9`, keep equal observations distinct under different handles, and add spill/rehydration falsification coverage.
- Record the accepted bootstrap 3.5 handoff for a nullable `bronze.release_partition.source_as_of` forward migration without implementing it here.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canonical-load-session`: distinguish same-batch Python identity from durable occurrence correlation across batches and persistence lookups.

## Impact

- **Originating issue:** #139; bootstrap 3.5 issue #138 remains blocked until this correction is promoted.
- **Application contract:** comments and docstrings in `property_tax_application.canonical` will describe the identity boundary without exposing infrastructure locators.
- **Contract fake and tests:** the canonical-load fake will model durable occurrence state, and tests will preserve `B7`/`B9` while falsifying corrected `W4`/`W5` behavior.
- **Public surface:** no new identifier, token, state component, port, dependency, or runtime service is introduced.
- **Excluded:** no PostgreSQL adapter, staging, COPY, migration, run locking, ManifestIndex, bootstrap 3.5, or bootstrap 3.6 implementation.
