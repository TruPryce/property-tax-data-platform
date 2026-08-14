## Current-state evidence

- Issue #20 requires a reusable adapter-layer PACS fixed-width component plus a Denton-specific mapping, keeping PACS vocabulary out of the canonical domain.
- The accepted Denton source contract requires 1-indexed inclusive positions, validation of order, non-overlap, declared length, and required-field end positions, a layout fingerprint versioned separately from the export-header version, and a rule that a field ending beyond the observed record width is never emitted as a valid truncated value.
- The same contract requires `prop_id` as account identity, `(prop_id, owner_sequence)` as physical owner-row grain with no derived roll-up, `ten_percent_cap` preserved as a source-native cap amount, relationship thresholds applied by child type, and owner and mailing-address publication disabled.
- Issue #21 requires Ellis to bind to this component by fingerprint and forbids forking it, so the component must carry no county field name or policy.
- The merged Tarrant foundation establishes the precedent this change follows: a bounded validator, a closed diagnostic vocabulary whose permitted metadata is enforced by the type, release-level atomic rejection, and no county-local substitute for a contract Issue #43 owns.
- `libs/property-tax-adapters/src/property_tax_adapters/sources/texas/denton.py` currently holds only `DENTON_SOURCE`, which the registry imports.

## Proposed architecture

Two modules, with a one-way dependency from the county binding to the shared component.

`property_tax_adapters.sources.pacs` — serialization mechanics only:

1. `PacsField` — name, 1-indexed inclusive `start` and `end`, required flag.
2. `PacsLayout` — layout identifier, layout version, ordered fields. Validates ascending order, non-overlap, and length agreement at construction and raises `ValueError`, because those are authoring defects in trusted code rather than source data.
3. `layout_fingerprint` — the canonical five-key document from D2.
4. `slice_record` — 1-indexed inclusive slicing that never emits a partial value, reports a required field ending beyond the observed width, and returns a structural fingerprint of any undocumented trailing region.

The component names no county, no field of any county, no threshold, and no policy. That is what makes the Ellis binding in #21 a binding rather than a fork.

`property_tax_adapters.sources.texas.denton` — the county binding:

5. The versioned Denton layout, declared with the component's field type.
6. Denton lexical validation: the D3 grammars, empty-text-only nulls, and the tax-year match.
7. Grain rules: `prop_id` account identity compared as text, `(prop_id, owner_sequence)` owner-row grain, duplicate-owner-row rejection, conflicting-account-fact rejection, and no derived roll-up.
8. Child classification: core appraisal orphans block, legal orphans warn.
9. The closed diagnostic vocabulary and release-level atomic rejection.

Both entry points return one `DentonValidationReport`: counts, diagnostics, the layout fingerprint and version, and the trailing-region byte count. No field values, no records.

Making the interim scope a validator rather than a row producer is the point. Issue #20's acceptance criteria name a typed Denton record and an approved vendor-neutral record, and both require contracts Issue #43 owns. Returning rows today would mean writing a county-local `SourceNativeValue` — the substitute the accepted decisions forbid, and the fourth such copy in this repository after Collin and Dallas. Deferring costs nothing else: every physical, lexical, grain, relationship, diagnostic, and privacy rule in the Denton contract is validated now.

## Dependency direction

`pacs` depends on nothing in this repository. `denton` depends on `pacs`. Neither adds vocabulary to `property_tax_domain` or `property_tax_application`. `DENTON_SOURCE` already imports both packages for the registry and is preserved unchanged, so the boundary is that neither package is modified and neither gains PACS or Denton parser vocabulary — not that the adapter imports nothing from them.

## Data and contract changes

The Denton capability specification in this change is the governing behavior contract. No schema, migration, or persisted artifact is added.

## Alternatives considered

- **A Denton-local fixed-width reader.** Rejected: Issue #21 requires Ellis to bind to a shared component and forbids forking, so the component must exist before the second PACS county rather than being extracted afterwards.
- **Returning typed records now.** Rejected: it requires a county-local substitute for a contract Issue #43 owns.
- **Putting the Denton layout in the shared component.** Rejected: field names are county policy. A shared component that knows `prop_id` cannot be bound by a county that spells it differently.

## Decisions and assumptions

- **D1** (proposed by this change, requires human merge): 1-indexed inclusive positions with construction-time validation of order, non-overlap, and length, raising `ValueError`.
- **D2** (proposed by this change, requires human merge): the exact five-key canonical fingerprint document and its serialization.
- **D3** (proposed by this change, requires human merge): the Denton lexical bounds.
- **D4** (proposed by this change, requires human merge): core appraisal orphans block, legal orphans warn, undocumented trailing regions warn.

D1 through D4 come from this change rather than from an issue comment, so they are listed explicitly and merging is what accepts them.

- The foundation receives one already-selected, caller-supplied member; discovery, archives, and network access remain outside its scope.
- The synthetic layout and lexical rules are a deterministic foundation contract and do not prove compatibility with a live Denton release.
- No new dependency is approved; the implementation uses the standard library.

## Unresolved decisions

- Issue #43 has not supplied the shared adapter contracts, so typed record output is deferred. No task in this change depends on it.

## Risks and compatibility

- The synthetic layout may differ from the published Denton PACS layout, so this establishes no live compatibility.
- The observed record width, the true field positions, the account and owner-sequence alphabets, monetary scale, and the real orphan rates remain unproved.
- `ten_percent_cap` semantics remain unapproved, and the parser therefore preserves it without interpretation.

## Rollout and failure recovery

Validation commands: `make check`, `make prepr-no-ai`, `openspec validate add-denton-cad-pacs-parser-foundation --strict`. Failures remain blocked and authorize no implementation.

## Testing strategy

Component tests for position slicing, construction-time layout defects, fingerprint stability, truncation, and trailing regions. Denton tests for the physical layer, every lexical boundary, owner-row grain, duplicate and conflict rejection, child classification, the closed vocabulary and its bounded metadata, deterministic truncation, atomic rejection, privacy exclusion, and the architectural boundary. Fixtures are independently authored with literal expected results.
