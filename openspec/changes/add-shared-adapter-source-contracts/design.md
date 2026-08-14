## Current-state evidence

Read on `main` at the time of drafting:

- `libs/property-tax-adapters/src/property_tax_adapters/sources/texas/collin.py` (971 lines) defines `CollinSourceNativeValue`, `CollinSourceProvenance`, `CollinObservationProvenance`, `CollinAppraisalSourceRecord`, and `CollinAppraisalObservation`.
- `.../texas/dallas.py` (582 lines) defines `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord` — unprefixed, but county-local and pinned to `jurisdiction_code: Literal["tx-dallas"]`.
- `.../texas/tarrant.py` (814), `denton.py` (684), and `ellis.py` (777) define none of the three. Each accepted contract instead states that until Issue #43 is accepted and implemented, the adapter MUST NOT construct a county-local substitute. Their specs reference the shared names 7, 3, and 3 times respectively.
- `.../sources/pacs.py` (255) is the precedent this change follows: shared, county-free, and bound by two counties without a fork.
- `.../texas/rockwall.py` (11) is a stub.

Where the two implementations disagree:

| | Collin | Dallas |
| --- | --- | --- |
| native value | `value: Decimal`, `precision`, `scale`, `source_column` | `lexical_text`, `value: str \| Decimal` |
| provenance | `table_name`, `schema_fingerprint` | `observed_headers`, `normalized_headers`, `layout_fingerprint` |
| record key | `prop_id: int`, `geo_id` | `source_account_id: str`, `parcel_reference` |
| value grain | `current_values` and `certified_values` on one record | one values map per row |

Both carry `source_member_name`, `release_identifier`, `source_row_number`, and `parser_contract_version` identically. That agreement is the shared core; everything above it is county mechanism.

## Proposed architecture

One new module, `property_tax_adapters/sources/contracts.py`, holding three frozen slotted dataclasses and nothing else. It imports from the standard library only, defines no county name, no county field name, no threshold, and no policy, and sits beside `pacs.py` at the same level — a county may import it, and it imports no county.

```
sources/contracts.py      <- new: SourceNativeValue, SourceProvenance, AppraisalSourceRecord
sources/pacs.py              existing: serialization mechanics
sources/texas/collin.py      imports contracts; keeps Collin* observation types
sources/texas/dallas.py      imports contracts; local copies deleted
sources/texas/{tarrant,denton,ellis}.py   unchanged by this change
```

County provenance **composes** rather than extends (D2). Dallas keeps a `DallasSourceProvenance` holding its header vectors and a `shared: SourceProvenance` field; Collin keeps `CollinSourceProvenance` holding `table_name` the same way. Inheritance would put one county's fields in every county's type, which is what the current divergence already costs.

## Dependency direction

`sources/texas/*` → `sources/contracts` → standard library. Nothing in `contracts` imports a county, `pacs`, `property_tax_domain`, or `property_tax_application`, and an architecture test asserts it.

## Data and contract changes

Three types are added and five are deleted (`SourceNativeValue`, `SourceProvenance`, `AppraisalSourceRecord` from Dallas; `CollinSourceNativeValue`, `CollinSourceProvenance` from Collin). `CollinObservationProvenance`, `CollinAppraisalObservation`, and every diagnostic type stay county-local. No persisted schema exists yet, so no migration is required.

## Alternatives considered

- **Promote Dallas's types unchanged.** Cheapest, and wrong for four counties: no `source_field` on the value, no `source_family`, an `observed_headers` vector meaningless to a fixed-width county, and a `Literal["tx-dallas"]` jurisdiction.
- **A generic base class per county to subclass.** Puts Dallas's headers and Collin's table name in one hierarchy, so every county carries fields it cannot populate. Composition (D2) gets the reuse without the coupling.
- **Defer until #43 is planned whole.** Leaves eight tasks blocked behind a streaming design they do not depend on, and repeats the 2,727-second planning timeout.
- **Let each county keep its own copy.** The status quo. Five parsers, five contracts, and no shared type for the layer above to consume — which is the defect Issue #43 was opened for.

## Decisions and assumptions

D1 through D5 are stated in the proposal. Their rationale in one place:

- The value type carries `source_field` and `lexical_text` because tracing a value to its source is the whole point of a source-native container, and three accepted specs require both. Collin's `precision` and `scale` are decode mechanics for an Access NUMERIC, not shared meaning.
- The provenance type carries only what all five counties already agree on, and composition covers the rest.
- `source_account_id` is `str` because Denton compares `000123` and `123` as distinct by an accepted requirement, and an integer type erases that distinction silently.
- `source_family` and `source_status` are free strings because the observed families are county products, and a shared enum would need editing whenever a county discovers a new one.
- Collin's dual-family observation model stays county-local; one account yields one shared record per observed family, which keeps the families distinct as Collin's accepted contract requires.

Assumption: no consumer outside `property_tax_adapters` imports the Dallas or Collin local types. Tasks 3.1 and 4.1 verify this by search before deleting them; if a consumer outside the library exists, the task stops and reports rather than rewriting it.

## Unresolved decisions

- None.

## Risks and compatibility

The migration is the risk, not the new module. Both counties have full test suites, and the migration is required to preserve observable behaviour exactly: same accepted rows, same rejected rows, same diagnostic codes, same counts. Each migration task therefore lands with its county's existing tests unmodified except where a type name changed, so a behaviour change shows up as a test failure rather than a silently rewritten expectation.

Not addressed here: the 663 MiB retained on 200,000 Dallas rows. These types are per-record containers, and making them lighter would not change a design that materializes every row. That is the release-processing work.

## Rollout and failure recovery

Additive first: the module and its tests land before either migration, so a failed migration reverts to a county-local copy without removing the shared type. Each county migrates independently.

## Testing strategy

Contract tests prove immutability, that a record cannot be constructed without provenance, that owner, mailing, and situs values are not representable, and that the three types import nothing from a county. Architecture tests parse the AST and strip docstrings before asserting on imports and class definitions, because a module docstring naming a county is legitimate. Each county's migration is proved by its existing suite passing unchanged.
