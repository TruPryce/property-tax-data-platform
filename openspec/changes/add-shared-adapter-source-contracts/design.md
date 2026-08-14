## Current-state evidence

Read on `main` at the time of drafting.

Dallas already separates county-native from vendor-neutral. `dallas.py` defines `DallasSourceProvenance` and `DallasAppraisalSourceRecord` (county-native, carrying `extras: Mapping[str, str]`) **and** the unprefixed `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord`, with `convert_dallas_appraisal_record` between them. That conversion pattern is what D7 formalizes, and this change keeps it.

Collin defines a parallel set — `CollinSourceNativeValue`, `CollinSourceProvenance`, `CollinObservationProvenance`, `CollinAppraisalSourceRecord`, `CollinAppraisalObservation` — that never converges with Dallas's.

Tarrant (814 lines), Denton (684), and Ellis (777) define none of the three; each accepted contract forbids a county-local substitute until this lands. `sources/pacs.py` (255) is the precedent: shared, county-free, bound by two counties without a fork.

| | Collin | Dallas |
| --- | --- | --- |
| native value | `value: Decimal`, `precision`, `scale`, `source_column` | `lexical_text: str`, `value: str \| Decimal` |
| provenance | `table_name`, `schema_fingerprint` | `observed_headers`, `normalized_headers`, `layout_fingerprint` |
| record key | `prop_id: int`, `geo_id` | `source_account_id: str`, `parcel_reference` |
| value grain | current and certified maps on one record | one values map per row |

D7's field list already anticipates this divergence: optional precision and scale cover Collin's Access NUMERIC decode, and optional table, observed fields, and normalized fields cover both counties' provenance. Adopting D7 as written therefore needs no composition workaround for those fields.

Three source facts that shaped the remaining detail:

- `decode_collin_numeric` takes a 17-byte `bytes` wrapper, so Collin has no lexical text — D7's "optional original lexical text" is what makes Collin representable.
- Collin's contract forbids declaring `prop_id` an account key and forbids equating `geo_id` with it — D7's optional account ID is what makes Collin representable, and its rules say so explicitly.
- Dallas emits `lexical_text=''` and `value=''` for an empty extra column today, verified by running the parser. Treating `''` as absence would break the case-for-case migration D7 requires.

## Proposed architecture

One new module, `property_tax_adapters/sources/contracts.py`, holding three frozen slotted dataclasses, importing the standard library only.

```
sources/contracts.py      <- new: the three D7 contracts
sources/pacs.py              existing: serialization mechanics
sources/texas/dallas.py      imports contracts; unprefixed local copies deleted;
                             DallasSourceProvenance / DallasAppraisalSourceRecord stay
sources/texas/collin.py      imports contracts; Collin* value/provenance copies deleted;
                             CollinAppraisalSourceRecord / *Observation stay county-local
sources/texas/{tarrant,denton,ellis}.py   unchanged by this change
```

County-native input records and diagnostics stay in county modules, as D7 directs. Because the shared provenance carries D7's optional table, observed, and normalized fields, a county populates them directly rather than wrapping the shared type; where a county keeps its own provenance type it holds a shared `SourceProvenance` as a field rather than subclassing it, so one county's mechanism never becomes another's obligation.

This is a boundary between two kinds of type, not a ban on county types. `DallasAppraisalSourceRecord`, `CollinAppraisalSourceRecord`, `CollinObservationProvenance`, and `CollinAppraisalObservation` all remain. What is prohibited is a second definition of a shared shape.

## Dependency direction

`sources/texas/*` → `sources/contracts` → standard library. Nothing in `contracts` imports a county, `pacs`, `property_tax_domain`, or `property_tax_application`, and an architecture test asserts it.

## Data and contract changes

Three types are added. Five definitions are deleted: the unprefixed three from Dallas, and `CollinSourceNativeValue` and `CollinSourceProvenance` from Collin. No persisted schema exists yet, so no migration is required.

## Alternatives considered

- **Excluding precision and scale from the shared value**, on the grounds that they are Collin decode mechanics. Rejected: D7 approves them as optional shared fields, and excluding them would supersede approved input to no benefit while forcing Collin into a composition wrapper.
- **Keeping provenance to the six fields every county shares**, moving the rest county-local. Rejected for the same reason: D7 approves six optional provenance fields, and narrowing them is a supersession with no county requiring it.
- **Admitting `None` as a `SourceNativeValue.value`.** Rejected: D7 says exact `str | int | Decimal`, and a "value" containing no value is not justified by any accepted county contract. Absence is expressed by omitting the entry, or in county-local structures — which is what Collin's `Mapping[str, CollinSourceNativeValue | None]` already does.
- **A shared allowlist of permitted source fields**, to make the privacy claim enforceable. Rejected: contradicts Dallas's accepted "Retain unknown extras" requirement. D6 states the limit instead.
- **Amending Collin's contract to approve an account key.** Rejected: D7's optional account ID exists precisely so this is unnecessary.

## Decisions and assumptions

D1 through D6 are stated in the proposal, with the single supersession isolated in D3. Two assumptions:

- No consumer outside `property_tax_adapters` imports the Dallas or Collin local types. Verified by search at drafting time — none exist — and re-checked by tasks 3.1 and 4.1 before deletion, which stop and report rather than rewrite if one has appeared.
- Dallas supplies `source_account_id` from `account_num` and `parcel_reference` from `gis_parcel_id`, as D7's rules direct and as it does today.

## Unresolved decisions

- None.

## Risks and compatibility

The migration is the risk, not the new module. D7 requires existing Dallas and Collin behaviour and tests to remain case-for-case, so each migration lands with its county's tests unmodified except where a type name or attribute path moved. A behaviour change surfaces as a failure rather than a rewritten expectation, and the 52 Dallas contract cases D6 protects are covered by that rule.

Making three record fields optional is a loosening: a consumer that assumed non-null must handle absence. There is no such consumer today, and the counties that specified concrete values still supply them.

Not addressed: the 663 MiB. These are per-record containers.

## Rollout and failure recovery

Additive first — module and tests land before either migration, so a failed migration reverts to a county-local copy without removing the shared type. Dallas and Collin migrate independently.

## Testing strategy

Contract tests prove immutability including private attributes, that a record cannot be constructed without provenance, that each value-map key equals its `source_field`, that `lexical_text` accepts `''` for an observed empty text and `None` for a binary source, that `value` admits no `None`, and that a caller's mapping cannot reach inside a constructed record. Architecture tests parse the AST and strip docstrings before asserting on imports and class names, because a docstring may legitimately name a county. Privacy tests assert exactly what D6 claims and include a test documenting the property deliberately not claimed, so a later reader does not mistake the weaker guarantee for the stronger one. Each county's migration is proved by its existing suite passing unchanged.
