# Tasks

The promoted transition table in
[`specs/canonical-load-session/spec.md`](specs/canonical-load-session/spec.md) remains authoritative.
These tasks correct only its persistence-boundary interpretation: `B7` and `B9` still compare
co-resident objects by identity, while `W4` and `W5` resolve an occurrence by the existing locator
or handle and use canonical value equality only as a consistency check. No task adds a public
identifier, state component, migration, PostgreSQL adapter, or bootstrap 3.5 implementation.

**Review scope** — one scope, `durable-correlation`, covering every task in this change. Issue #138
remains blocked until this change is implemented, independently reviewed, promoted, and archived.

## 1. Correct the application contract proof

<!-- countyforge-task: 1.1 paths=libs/property-tax-application/src/property_tax_application/canonical.py checks=repo.check risk=normal prerequisites=D1,D2,D3,D4 -->

- [ ] 1.1 Clarify the identity boundary in the existing carriers — Update comments and docstrings in `canonical.py` so `AdoptableSnapshot`, `AdoptedParent`, `CorrelationHandle`, `CanonicalRecordBatch`, and the parent helper state the accepted distinction: `B7`/`B9` compare by Python identity only inside one batch; across batches or a persisted lookup, `CorrelationHandle`/`AccountSnapshotRef` selects the occurrence and equality verifies its canonical value. Change no signature, field, `__all__` entry, validation rule, exception name, public identifier, or executable same-batch identity check.

<!-- countyforge-task: 1.2 paths=libs/property-tax-application/tests/_fake_load.py checks=repo.check risk=higher_risk prerequisites=D2,D3,D4,D5,1.1 -->

- [ ] 1.2 Make the contract fake model durable occurrences — Replace the fake's retained-object `S4` representation with a test-only durable/value representation that stores the selected parent occurrence and account without referencing the original canonical object. Resolve cross-batch `W5` by handle first and compare the rehydrated canonical parent value second; resolve `W4` by `AccountSnapshotRef` within `S0`'s release and compare the rehydrated snapshot value second. Preserve `UnknownAccountSnapshot` for no selected occurrence and `AdoptableSnapshotMismatch` for a selected occurrence with a different value. Keep `S5` derived from the mappings, retain six state components, and change no public carrier.

## 2. Falsify the corrected boundary

<!-- countyforge-task: 2.1 paths=libs/property-tax-application/tests/test_canonical_load_session.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D3,D5,1.2 -->

- [ ] 2.1 Prove durable cross-batch `W5` correlation — Add the design matrix's `W5` cases: retain `P` under `H`, replace its mapping with a durable primitive/value representation that cannot reach `P`, then accept a later child holding equal new `Q`; refuse a child whose parent value differs from the occurrence selected by live `H` while leaving all state unchanged; and retain equal parents under `H1`/`H2` without collapse, proving each handle selects its own occurrence. Mutation-check handle-first lookup, value consistency, and removal of the original-object spill.

<!-- countyforge-task: 2.2 paths=libs/property-tax-application/tests/test_canonical_load_session.py checks=repo.check risk=higher_risk prerequisites=D1,D4,D5,D6,2.1 -->

- [ ] 2.2 Prove persisted `W4` and preserve same-batch identity — Add a persistence round trip in which a locator selects an equal newly rehydrated snapshot and adoption succeeds, then mutate the stored value under that locator and require `AdoptableSnapshotMismatch`; retain the unknown/stale locator case as `UnknownAccountSnapshot`. Preserve explicit attacks proving `B7` and `B9` still reject equal-but-distinct objects in one batch, assert no new public identifier or carrier field appears, run the focused suite and repository gates, and confirm the implementation changes no migration or bootstrap 3.5 artifact. The accepted nullable `source_as_of` forward-migration handoff remains recorded for #138 only.
