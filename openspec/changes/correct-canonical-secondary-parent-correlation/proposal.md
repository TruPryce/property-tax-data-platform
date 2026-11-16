## Why

Bootstrap 3.5 planning in issue #138 proved that the promoted canonical-load carrier cannot name both exact persisted parents of an owner association, taxable value, or owner-scoped exemption, nor prove that the selected secondary occurrence belongs to the selected primary snapshot occurrence. Issue #147 corrects that prerequisite without weakening durable handle correlation, occurrence multiplicity, or the prohibition on natural keys.

## What Changes

- **BREAKING**: add one optional `secondary_parent: CorrelationHandle | None` field to `CorrelatedRecord`.
- Make B1 require every persisted parent edge explicitly: every non-snapshot record names its primary parent, and only the three declared multi-parent shapes require a secondary parent.
- Extend B6 and B7 across both parent edges while preserving Python object identity and occurrence-ancestry coherence for same-batch bindings.
- Extend W5 across both parent edges and require the selected secondary occurrence's private primary-parent occurrence to equal the occurrence selected by `parent`.
- Keep B9 snapshot-adoption-specific, keep both edges in the existing S4/S5 correlation model, and retain the existing W2 batch count.
- Add the complete thirty-two-case falsification matrix and update the application boundary documentation and public-shape proof.
- Keep issue #138 blocked until this correction is implemented, independently reviewed, promoted, and archived.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `canonical-load-session`: make every primary and secondary persisted parent occurrence explicit and require occurrence-level ancestry coherence through the existing correlation state.

## Impact

- A later implementation changes `property_tax_application.canonical.CorrelatedRecord`, its closed parent helpers, the canonical-load fake, focused falsification tests, and application documentation/architecture guards.
- Domain record types, PostgreSQL schema relationships, `CorrelationHandle`, `AccountSnapshotRef`, session state components, batch sizing, adoption scope, and canonical persistence semantics remain unchanged.
- This planning change adds no runtime implementation, migration, PostgreSQL adapter, COPY/staging behavior, use-case composition, or bootstrap checkbox change.
