## Context

Issue #138 stopped when PostgreSQL planning reached `canonical.owner_association.owner_key`. The promoted carrier gives each `CorrelatedRecord` one optional `parent`, while three accepted domain records have two persisted parent edges. The existing helper binds an `OwnerAssociation`'s one handle to its snapshot, leaving no occurrence selector for its owner; the same gap exists for a taxable value's taxing unit and an owner-scoped exemption's association.

The first correction draft exposed a second part of the same problem. Selecting both parent values independently is insufficient: PostgreSQL's composite foreign keys require the selected owner, taxing unit, or association occurrence to be parented by the same exact snapshot occurrence selected for the child. Domain constructors require only snapshot value equality, and equal snapshots may be distinct occurrences. Issue comment `6905061473` recorded that stop; the owner decision in `6905443293` requires occurrence-ancestry coherence.

The prior durable-correlation correction remains authoritative: inside one `CanonicalRecordBatch`, Python identity proves occurrence bindings; across batches, a live `CorrelationHandle` selects a retained occurrence and equality only verifies its rehydrated value. The full-release ManifestIndex correction is unrelated and remains settled. Issue #147 owns this correction, and #138 stays blocked until it is implemented, independently reviewed, promoted, and archived.

## Goals / Non-Goals

**Goals:**

- Name every persisted parent occurrence explicitly in one bounded carrier.
- Preserve strict same-batch identity and durable cross-batch handle-first resolution for both edges.
- Require the selected secondary occurrence to have the same selected primary occurrence as the child.
- Cover primary/secondary current/prior combinations without co-locating descendants or exposing persistence locators.
- Keep the authoritative six-state transition model, precondition identifiers, adoption scope, and no-natural-key rule unchanged.
- Provide an implementation-ready thirty-two-case falsification matrix.

**Non-Goals:**

- Changing domain constructors, domain record types, or canonical PostgreSQL foreign keys.
- Adding a generic graph model, persistence locator, public occurrence type, S-state component, or precondition identifier.
- Implementing PostgreSQL, migrations, COPY, staging, bootstrap 3.5/3.6, or bootstrap 2.4.
- Broadening adoption beyond persisted `AccountSnapshot` occurrences.

## Decisions

### D1 — Add exactly one named secondary selector

`CorrelatedRecord` becomes:

```python
@dataclass(frozen=True, slots=True)
class CorrelatedRecord:
    record: CanonicalRecord
    handle: CorrelationHandle | None = None
    parent: CorrelationHandle | None = None
    secondary_parent: CorrelationHandle | None = None
```

The field is appended, so the existing positional meanings of `record`, `handle`, and `parent` do not move. It is still a `CorrelationHandle`: the edge gains no new identity or persistence token. A free-form mapping would let callers invent relationship roles; an arbitrary tuple would make roles positional; a binding class would add a public concept without adding type safety to a graph whose maximum arity is already known. All three are rejected.

### D2 — The record type fixes a closed relationship table

The application contract uses this exhaustive table:

| Canonical record | `parent` selects | `secondary_parent` selects |
| --- | --- | --- |
| `AccountSnapshot` | none | none |
| `OwnerObservation` | snapshot | none |
| `OwnerAssociation` | snapshot | owner |
| `OwnerValueAllocation` | association | none |
| `AppraisalValueObservation` | snapshot | none |
| `TaxingUnitObservation` | snapshot | none |
| `TaxableValueObservation` | snapshot | taxing unit |
| account-scoped `ExemptionObservation` | snapshot | none |
| owner-scoped `ExemptionObservation` | snapshot | association |
| `GeometryObservation` | snapshot | none |
| `ImprovementObservation` | snapshot | none |
| `LandObservation` | snapshot | none |

`canonical.py` replaces the singular parent helper with exhaustive closed helpers equivalent to `_primary_parent_object_of()` and `_secondary_parent_object_of()`. They return domain objects or `None`; they do not return dictionaries or role strings. `ExemptionObservation.scope` remains authoritative and is never inferred from the handle.

### D3 — B1 owns the complete binding shape

B1 continues to decide whether an entry is well formed. `AccountSnapshot` rejects either parent field. Every other accepted record requires `parent`. Exactly `OwnerAssociation`, `TaxableValueObservation`, and owner-scoped `ExemptionObservation` require `secondary_parent`; every other record rejects it.

This validation belongs in `CorrelatedRecord.__post_init__`, before a batch or session exists. It does not compare records or resolve handles. The implementation uses exact closed type/scope dispatch so adding a new canonical record type without defining its parent shape fails tests rather than silently defaulting.

The prior optional-primary behavior is rejected: PostgreSQL needs a selected occurrence, and finding one from an identical or equal object would make value or object search an undeclared occurrence key.

### D4 — B6 forbids every self or collapsed edge

B6 remains one intrinsic rule. An introduced `handle` must differ from `parent` and `secondary_parent`; on a multi-parent record, `parent` and `secondary_parent` must differ. The primary and secondary parent types are distinct in every supported row, so one handle cannot truthfully select both embedded occurrences.

No new rule identifier is created. B6 still settles only relationships visible inside one entry and does not resolve anything from session history.

### D5 — B7 proves local edge identity and local ancestry

The batch builds one handle-to-occurrence map from entries and snapshot adoptions. For each primary and secondary handle introduced by that batch, the corresponding closed helper supplies the embedded domain object, and B7 requires `held is denoted`.

For a multi-parent child, B7 also proves occurrence ancestry whenever enough of the graph is local. The secondary occurrence's own `parent` binding must select the same primary occurrence as the child's `parent`. In the wholly local case, the owner/taxing-unit/association object's embedded snapshot must be the exact snapshot object selected for the child, not merely equal. In a mixed case, the local entry's binding is compared with the retained or adopted primary occurrence selected by the child.

Equality remains insufficient inside one batch. Two equal owners, taxing units, associations, or snapshots are separate occurrences. B9 remains the adoption-specific statement that a child using an adopted snapshot handle holds the exact candidate snapshot object. Adoption can satisfy a child's primary snapshot edge but does not adopt deeper observations.

### D6 — W5 proves durable edge consistency and occurrence ancestry

The fake and later adapters iterate both declared edges. If an edge is not introduced in the current batch, W5 requires its handle in S5, selects the retained occurrence from S4 by handle, rehydrates its canonical value, and compares that value with the object returned by the corresponding closed helper.

For every multi-parent record, after both selected occurrences are known, W5 requires the secondary occurrence's infrastructure-private primary-parent occurrence locator to equal the primary occurrence locator selected by `parent`. This comparison is occurrence identity. It does not compare snapshot values, search S4, retarget a secondary occurrence, duplicate it, or substitute an equal snapshot.

The validation order is:

```text
resolve each handle -> select each occurrence -> verify each canonical value
                    -> compare secondary ancestry locator with primary locator
```

The four combinations are explicit:

| Primary | Secondary | Enforcement |
| --- | --- | --- |
| prior | prior | W5 resolves both S4 occurrences and compares private locators |
| prior | current | B7/W5 compare the current secondary entry's primary binding with the retained primary occurrence |
| current or adopted | prior | W5 compares retained secondary ancestry with the local/adopted primary occurrence |
| current | current | B7 validates both bindings and ancestry entirely inside the batch |

There is no value-search fallback. Equal secondary observations retained under `H1` and `H2` remain two mappings and two choices. A valid primary with a missing, mismatched, or wrongly parented secondary, and the inverse, refuse the whole write before mutation.

### D7 — S4 represents a selected occurrence, including its existing ancestry

Both edges use the same S4 mapping and S5 key set. No S7, parallel secondary map, or second high-water mark exists; S6 still orders every introduced handle. An infrastructure-private retained occurrence may contain:

```text
occurrence locator
encoded canonical value
account
primary-parent occurrence locator | none
```

That locator describes the selected occurrence's existing parent relationship. It is not a second logical state component, public field, domain identity, or business key. The original Python objects remain unreachable after spill.

The fake extends `_RetainedParentOccurrence` and `_StagedRecord` with private primary-parent ancestry. When a handle is retained, its occurrence captures the already-selected primary occurrence locator from that entry's staged binding. A retained snapshot has no parent locator. A secondary occurrence later exposes its stored ancestry for W5 without reconstructing or searching by canonical value.

### D8 — State, boundedness, and atomicity otherwise do not change

W2 remains:

```text
entries + adoptions + retain + release <= max_batch_entries
```

An entry remains one bounded value with at most two fixed handle fields. Parent references are not counted as additional entries. The success transition retains and releases handles exactly as before, independent of which edge later names them.

B1/B6/B7 failures occur during construction and create no session mutation. W5 resolves and validates both values and ancestry before `_apply`; any failure leaves S1 through S6 and staged metadata byte-for-byte unchanged. The external invariant proof continues to derive S5 from S4 rather than trusting the fake to assert itself.

### D9 — Cross-batch secondary parents are required behavior

The correction explicitly permits an owner, taxing unit, or owner association to be retained in one batch and referenced by descendants in later bounded batches. A same-batch-only alternative is rejected because it turns a missing selector into a co-location constraint and can force one parent plus all descendants into one batch.

The required owner sequence spills both snapshot and owner occurrences, then accepts equal newly rehydrated values only when the owner's stored snapshot occurrence is the selected primary occurrence. Equivalent cases cover a retained taxing unit and a retained owner association. The no-natural-key rule remains unchanged: handles select occurrences; equality only verifies values; private locators verify ancestry.

### D10 — Public and documentation change is narrow

The only public shape change is the appended `secondary_parent` field. `CorrelationHandle`, `CanonicalRecordBatch`, `AdoptedParent`, every Protocol, every exception, every export, and all domain classes remain unchanged. Architecture/public-shape tests assert that exact result and that there are still six S-components.

The application README and canonical-load engineering guide explain the two fixed parent slots, occurrence-ancestry coherence, and unchanged snapshot-only adoption, then link to the promoted capability rather than copying its transition table.

## Falsification Matrix

| ID | Attack | Expected authority/result |
| --- | --- | --- |
| F1 | `AccountSnapshot` carries either parent field | B1 refusal |
| F2 | Any single-parent child omits `parent` | B1 refusal, table-driven over every single-parent type |
| F3 | A single-parent child carries `secondary_parent` | B1 refusal |
| F4 | `OwnerAssociation` omits either edge | B1 refusal |
| F5 | `TaxableValueObservation` omits either edge | B1 refusal |
| F6 | Owner-scoped exemption omits either edge | B1 refusal |
| F7 | Account-scoped exemption carries a secondary edge | B1 refusal; explicit scope stays authoritative |
| F8 | An entry's handle equals either parent handle | B6 refusal for each edge |
| F9 | Primary and secondary handles are equal | B6 refusal |
| F10 | Same-batch primary handle denotes an equal-but-distinct object | B7 refusal using `is` |
| F11 | Same-batch secondary handle denotes an equal-but-distinct object | B7 refusal using `is` for all three multi-parent types |
| F12 | Cross-batch primary resolves to an equal newly rehydrated value | W5 accepts, preserving the durable-correlation correction |
| F13 | Cross-batch secondary resolves to an equal newly rehydrated value | W5 accepts when ancestry is coherent |
| F14 | Secondary handle selects a different canonical value | W5 refuses and S1-S6/staging are unchanged |
| F15 | Equal secondary observations are retained under different handles | Both mappings survive and remain separately selectable |
| F16 | Association names snapshot and owner handles from earlier batches | Each exact private occurrence locator is staged on the correct edge |
| F17 | Taxable value names snapshot and taxing-unit handles from earlier batches | The intended taxing-unit occurrence is selected; an equal other occurrence is not substituted |
| F18 | Owner-scoped exemption names snapshot and association handles | The intended association occurrence is selected; account scope needs no secondary |
| F19 | Fake is mutated to find an occurrence by value instead of handle | Distinct-occurrence attacks fail the mutation |
| F20 | Public surface/state is inspected | Only `secondary_parent` is added; no token, Protocol operation, state component, or persistence locator appears |
| F21 | Local owner association selects coherent snapshot and owner occurrences | B7 accepts |
| F22 | Local owner is parented by an equal-but-distinct snapshot occurrence | B7 refuses despite value equality |
| F23 | Retained owner ancestry names the selected retained snapshot occurrence | W5 accepts after spill |
| F24 | Retained owner ancestry names a distinct equal snapshot occurrence | W5 refuses atomically |
| F25 | Taxable value selects a taxing unit parented by its selected snapshot | B7/W5 accepts across local and retained cases |
| F26 | Taxing unit is parented by a distinct equal snapshot occurrence | B7/W5 refuses |
| F27 | Owner-scoped exemption selects an association parented by its selected snapshot | B7/W5 accepts across local and retained cases |
| F28 | Association is parented by a distinct equal snapshot occurrence | B7/W5 refuses |
| F29 | Current or adopted primary plus retained secondary have coherent ancestry | Mixed-boundary write succeeds |
| F30 | Current or adopted primary plus retained secondary disagree on occurrence ancestry | Mixed-boundary write refuses atomically |
| F31 | Durable spill removes Python objects but retains private ancestry | W5 still resolves values and ancestry; originals are unreachable |
| F32 | Ancestry comparison is mutated from private locators to canonical equality | Equal-distinct snapshot attack fails the mutation |

Mutation proofs remove or weaken each branch in turn: primary/secondary requiredness, B6's three inequalities, B7 identity and local ancestry, W5 handle lookup, W5 value verification, W5 locator ancestry, and atomic pre-mutation validation. All temporary mutations are restored before commit.

## Implementation Decomposition

```text
1.1 carrier and closed parent-shape helpers
  -> 1.2 B1/B6/B7 local binding and ancestry
       -> 1.3 fake durable occurrence ancestry and generalized W5
            -> 2.1 complete F1-F32 falsification and mutation proof
                 -> 2.2 public surface, docs, architecture, and gate closure
```

Tasks 1.1 and 1.2 are sequential even though both touch `canonical.py`; separating shape from behavior keeps each review bounded without inviting parallel edits to the same carrier. Task 1.3 owns the fake representation and mixed-boundary session logic. Task 2.1 consolidates behavior in the existing canonical session suite rather than creating a second transition-table suite. Task 2.2 contains no runtime behavior.

## Rejected Alternatives

- **Require secondary parents in the same batch.** Rejected because bounded batching must allow one retained parent to serve later descendants and because it hides the missing selector as an ordering rule.
- **Accept independently valid parent values without ancestry coherence.** Rejected because PostgreSQL's composite foreign keys bind each secondary occurrence to one exact snapshot occurrence.
- **Infer ancestry from equal snapshots.** Rejected because equal snapshots may be distinct occurrences and equality is not an occurrence key.
- **Retarget or duplicate the secondary occurrence.** Rejected because it changes observed evidence and manufactures a record the batch did not submit.
- **Use `Mapping[str, CorrelationHandle]`.** Rejected because role strings create open graph metadata and move schema authority to callers.
- **Use `tuple[CorrelationHandle, ...]`.** Rejected because binding becomes positional and an incorrect order remains representable.
- **Add typed primary/secondary binding values.** Rejected because two named fixed fields already make every current relationship unambiguous.
- **Add a second S4 or secondary-handle type.** Rejected because both edges select the same kind of occurrence under the same lifetime and high-water rules.
- **Adopt deeper observations.** Rejected because no accepted domain identity names them and correlation already supplies the required occurrence selector.
- **Change domain constructors to occurrence identity.** Rejected because domain values have no persistence occurrence identity; that authority belongs at this application boundary.

## Risks / Trade-offs

- **[Breaking carrier validation]** Existing tests and future callers that omitted primary handles will fail immediately. → Update all canonical-load fixtures in the bounded implementation and retain table-driven B1 proof.
- **[Closed table drift]** A later canonical type could be added without parent semantics. → Make both helpers exhaustive and mutation-test every current type/scope row.
- **[False proof through equality]** A fake could pass happy paths while looking up values or ancestry by equality. → Retain equal snapshots and equal secondary observations under distinct handles and assert selected private locators.
- **[Mixed-boundary blind spot]** Local/local and prior/prior tests alone could miss current/prior combinations. → Exercise all four combinations, including adopted primary plus retained secondary.
- **[Partial W5 mutation]** One edge could stage before ancestry validation fails. → Snapshot complete state and staging before each asymmetric failure and compare after refusal.
- **[Private locator leaks]** Test infrastructure could accidentally become public vocabulary. → Assert dataclass fields, exports, Protocol operations, and state count exactly.
- **[Documentation restates the machine]** Explanatory text could become a second transition table. → Document only carrier ownership and point to permanent authority for rules.

## Migration Plan

This correction requires no database or data migration. Implementation order is carrier shape, intrinsic validation, fake/session ancestry, complete falsification, then documentation/public guards. After independent review and merge, a separate reconciliation transaction promotes the modified `canonical-load-session` requirements and archives this change. Only then may #138 planning resume.

Rollback before promotion is a normal code revert. After promotion, rollback requires a governed correction because callers and permanent authority will rely on explicit secondary bindings and ancestry coherence.

## Open Questions

None. The owner decision fixes the carrier shape, relationship table, occurrence-ancestry rule, rule identifiers, state model, mixed-boundary cases, and excluded alternatives.
