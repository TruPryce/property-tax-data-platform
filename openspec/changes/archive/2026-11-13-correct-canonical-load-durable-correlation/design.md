## Context

Issue #138 stopped bootstrap 3.5 planning on the smallest durable-correlation counterexample: batch one retains parent object `P` under handle `H`, a durable adapter spills that mapping and releases `P`, and batch two supplies equal rehydrated value `Q` under `H`. The promoted contract currently requires `Q is P`, although no persistence boundary can preserve a Python instance after it leaves memory.

The contradiction is limited to cross-boundary checks. `B7` and `B9` compare objects that coexist inside one immutable `CanonicalRecordBatch`, so identity remains both available and necessary there. The existing `CorrelationHandle` and `AccountSnapshotRef` already select occurrences across boundaries; no new public token is needed.

The `canonical-load-session` transition table remains authoritative. This change edits its existing `S4`, `W4`, and `W5` meanings and the requirements that explain them; it does not create another state machine.

## Goals / Non-Goals

**Goals:**

- Make retained `S4` mappings implementable by a durable adapter without preserving Python instances.
- Preserve identity-based same-batch validation under `B7` and `B9`.
- Keep equal parent observations distinct when different handles or locators select them.
- Keep `S5` exactly the keys of `S4` and retain six state components.
- Distinguish unknown/stale adoption locators from locators whose persisted value disagrees with the candidate.
- Prove the original retained parent need not remain reachable from `S4` after a spill.

**Non-Goals:**

- No PostgreSQL staging, COPY, correlation table, run locking, ManifestIndex, or canonical merge implementation.
- No migration is written, and migration `0001` is not edited.
- No application carrier, public identifier, state component, or persistence mechanism is added.
- Bootstrap 3.5 and 3.6 remain incomplete; issue #138 remains blocked until this correction is promoted.

## Decisions

### D1 — Python identity ends at the in-memory batch boundary

Python object identity SHALL be authoritative only when both objects coexist in one `CanonicalRecordBatch`. `B7` and `B9` therefore remain identity checks: an equal-but-distinct object in the same batch is still refused.

Across a batch or persistence boundary, the original instance is not part of the contract. Requiring it would prohibit the durable spill bootstrap 3.5 explicitly needs.

**Rejected:** weaken `B7` or `B9` to equality. That would let a same-batch child name one occurrence while holding another equal observation.

### D2 — S4 records occurrence, account, and no parallel liveness state

`S4` SHALL mean `CorrelationHandle -> parent record occurrence + account`. A record occurrence is the specific parent selected by the handle. An implementation MAY represent that occurrence with infrastructure-private durable state, including a staging or persistence locator, but that state SHALL NOT enter a domain value, public carrier, business identity, or application-visible key.

`S5` remains exactly the key set of `S4`. No `S7`, second live-handle map, or seventh state component is introduced.

**Rejected:** add a public stable observation token. The handle already performs session-local correlation, and a second token would create a competing identity policy.

### D3 — W5 uses the handle to select and equality only to verify

For a parent introduced in an earlier batch, `W5` SHALL first require a live handle and resolve that handle through `S4` to the retained occurrence. It SHALL then compare the child-held parent value with that occurrence's canonical value for consistency. The comparison does not select the occurrence.

Two equal observations retained under `H1` and `H2` remain two occurrences. A child naming `H1` belongs to the `H1` occurrence; naming `H2` belongs to the `H2` occurrence. No equality comparison may find a parent, deduplicate it, merge it, or manufacture identity.

**Rejected:** retain the original object strongly. That makes pathological `S4` application-memory-resident. **Rejected:** look up by canonical value. Equal observations are intentionally retained and value lookup is ambiguous by construction.

### D4 — W4 uses the opaque locator to select and equality only to verify

`AccountSnapshotRef` SHALL resolve, within `S0`'s release, to one persisted snapshot occurrence. The persisted occurrence's canonical value SHALL equal the candidate's snapshot value, but it need not be the same Python instance. `UnknownAccountSnapshot` remains the refusal for no occurrence in the named release; `AdoptableSnapshotMismatch` remains the distinct refusal for a locator whose selected occurrence has a different canonical value.

`B9` remains identity-based after this lookup check, because the candidate snapshot and child-held snapshot coexist in the same batch.

**Rejected:** use the candidate value as the lookup key. The opaque locator selects; equality only detects a caller-assembled mismatch.

### D5 — The fake models a spill rather than copying an object

The contract fake SHALL be able to replace a retained parent object with a test-only durable/value representation between writes and later rehydrate an equal new instance. The representation SHALL contain no reference to the original canonical object. Tests SHALL inspect the fake's retained state to prove `S4` no longer reaches the original object, rather than merely storing a copied object in another field.

The fake SHALL also retain two equal encoded occurrences under different handles and resolve each by its handle, proving that value agreement does not collapse them.

### D6 — Source-as-of schema work remains with bootstrap 3.5

The separate #138 finding is accepted: if planning confirms no existing durable location satisfies the promoted `acquisition-manifest-index` contract, bootstrap 3.5 may propose the smallest new forward migration adding:

```sql
bronze.release_partition.source_as_of timestamptz NULL
```

The column has no default, existing rows remain `NULL`, and neither acquisition time nor clock time substitutes for absence. Migration `0001` is not edited. This decision records a handoff only and changes no `canonical-load-session` behavior.

## Falsification Matrix

| Rule | Attack | Required result |
| --- | --- | --- |
| B7 | Introduce `P` and let a child name its handle while holding equal-but-distinct `Q` in the same batch | Batch construction refuses by identity |
| B9 | Adopt `P` and let an in-batch child hold equal-but-distinct `Q` | Batch construction refuses by identity |
| W5 success | Retain `P` under `H`, spill the occurrence so `P` is absent from `S4`, then submit a child holding equal new `Q` under live `H` | Write succeeds and correlates to the occurrence selected by `H` |
| W5 mismatch | Submit a child under live `H` whose parent value differs from the occurrence selected by `H` | Write refuses by `W5`; every state component remains unchanged |
| Distinct equal occurrences | Retain equal `P` and `Q` under `H1` and `H2` | Both mappings remain and each handle selects its own occurrence |
| Spill reachability | Replace retained object state with a primitive durable/value representation between batches | Inspection proves no retained mapping references the original object |
| W4 success | Resolve a persisted locator to an equal newly rehydrated snapshot | Adoption is accepted; instance identity is irrelevant to lookup verification |
| W4 mismatch | Resolve the same locator to a changed snapshot value | `AdoptableSnapshotMismatch` is raised, distinct from `UnknownAccountSnapshot` |

## Risks / Trade-offs

- **[Risk] Equality is mistaken for occurrence identity.** → Normative text orders the operation: resolve by handle or locator first, compare value second, and prohibits value-based lookup, merge, or deduplication.
- **[Risk] A fake appears to spill while retaining the original object elsewhere.** → The proof inspects the retained representation and requires the original object to be unreachable from `S4`.
- **[Risk] Infrastructure-private locators leak into the public model.** → Implementation paths are limited to existing carriers, fake, and tests; no public field or export is added.
- **[Risk] Historical scenarios are read as changing same-batch identity.** → `B7` and `B9` remain verbatim and receive explicit regression attacks.

## Migration Plan

1. Promote the corrected `canonical-load-session` requirements.
2. Update application comments/docstrings to state the same-batch versus persisted-occurrence boundary.
3. Update the contract fake and falsification suite without changing the public carrier or surface.
4. Independently review and archive this correction.
5. Resume #138 planning only after promotion; any `source_as_of` schema migration remains a separate bootstrap 3.5 design decision.

Rollback is the inverse spec/application-test change before bootstrap 3.5 depends on it. No stored data or deployed schema changes in this correction.

## Open Questions

None. The owner decision fixes the identity boundary, and the concrete PostgreSQL representation remains intentionally delegated to bootstrap 3.5.
