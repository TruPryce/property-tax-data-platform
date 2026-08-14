## Current-state evidence

Read on `main` at the time of drafting.

Dallas already separates county-native from vendor-neutral. `dallas.py` defines `DallasSourceProvenance` and `DallasAppraisalSourceRecord` (county-native, carrying `extras: Mapping[str, str]`) **and** the unprefixed `SourceNativeValue`, `SourceProvenance`, and `AppraisalSourceRecord`, with `convert_dallas_appraisal_record` between them. Required decision 7's target is that unprefixed set; the conversion pattern it lives in is sound and this change keeps it.

Collin defines a parallel set — `CollinSourceNativeValue`, `CollinSourceProvenance`, `CollinObservationProvenance`, `CollinAppraisalSourceRecord`, `CollinAppraisalObservation` — that never converges with Dallas's.

Tarrant (814 lines), Denton (684), and Ellis (777) define none of the three. Each accepted contract instead forbids a county-local substitute until this change lands. `sources/pacs.py` (255) is the precedent: shared, county-free, bound by two counties without a fork.

Where the two implementations disagree:

| | Collin | Dallas |
| --- | --- | --- |
| native value | `value: Decimal`, `precision`, `scale`, `source_column` | `lexical_text: str`, `value: str \| Decimal` |
| provenance | `table_name`, `schema_fingerprint` | `observed_headers`, `normalized_headers`, `layout_fingerprint` |
| record key | `prop_id: int`, `geo_id` | `source_account_id: str`, `parcel_reference` |
| value grain | current and certified maps on one record | one values map per row |

They agree on `source_member_name`, `release_identifier`, `source_row_number`, and `parser_contract_version`. That agreement is the shared core.

Three facts from the source that shaped the design more than anything else:

- `decode_collin_numeric` takes a 17-byte `bytes` wrapper. Collin has no lexical text, so a required `lexical_text` is unsatisfiable — hence D1's nullability.
- Collin's contract forbids declaring `prop_id` an account key and forbids equating `geo_id` with it, so Collin has no approvable `source_account_id` — hence D3's nullability and D5.
- `convert_dallas_appraisal_record` already funnels every unknown CSV column into the vendor-neutral values map, which Dallas's contract requires — hence D6's honest limit.

## Proposed architecture

One new module, `property_tax_adapters/sources/contracts.py`, holding three frozen slotted dataclasses and a `SOURCE_CONTRACT_VERSION` constant, importing the standard library only.

```
sources/contracts.py      <- new: SourceNativeValue, SourceProvenance, AppraisalSourceRecord
sources/pacs.py              existing: serialization mechanics
sources/texas/dallas.py      imports contracts; unprefixed local copies deleted;
                             DallasSourceProvenance / DallasAppraisalSourceRecord stay
sources/texas/collin.py      imports contracts; Collin* value/provenance copies deleted;
                             CollinAppraisalSourceRecord / *Observation stay county-local
sources/texas/{tarrant,denton,ellis}.py   unchanged by this change
```

County-native types **compose** the shared ones rather than subclassing them. `DallasSourceProvenance` keeps its header vectors and gains a `shared: SourceProvenance` field; Collin's keeps `table_name` the same way. Subclassing would put one county's mechanism in every county's type, which is what the present divergence already costs.

This is a boundary between two kinds of type, not a ban on county types. County-native records are required and stay: `DallasAppraisalSourceRecord`, `CollinAppraisalSourceRecord`, `CollinObservationProvenance`, and `CollinAppraisalObservation` all remain. What is prohibited is a second definition of a shared shape.

## Dependency direction

`sources/texas/*` → `sources/contracts` → standard library. Nothing in `contracts` imports a county, `pacs`, `property_tax_domain`, or `property_tax_application`, and an architecture test asserts it.

## Data and contract changes

Three types are added. Five definitions are deleted: the unprefixed three from Dallas, and `CollinSourceNativeValue` and `CollinSourceProvenance` from Collin. No persisted schema exists yet, so no migration is required.

## Alternatives considered

- **A literal move of the Dallas types, as required decision 7 reads.** Cheapest and faithful, and unusable for four counties: no `source_field`, a required `lexical_text` Collin cannot supply, a required `source_account_id` Collin may not declare, a `Literal["tx-dallas"]` jurisdiction, and header vectors meaningless to a fixed-width county. The revision table in the proposal is the diff.
- **A shared base class counties subclass.** Puts Dallas's headers and Collin's table name in one hierarchy, so every county carries fields it cannot populate.
- **A shared allowlist of permitted source fields, to make the privacy claim enforceable.** Contradicts Dallas's accepted "Retain unknown extras" requirement. D6 states the limit instead of overriding an accepted contract.
- **Amending Collin's contract to approve an account key.** Rejected: this change does not amend accepted contracts. D5 works within the prohibition.
- **Planning #43 whole.** Leaves eight tasks blocked behind decisions they do not depend on, and repeats the 2,727-second timeout.

## Decisions and assumptions

D1 through D6 are stated in the proposal with their county evidence. Two assumptions:

- No consumer outside `property_tax_adapters` imports the Dallas or Collin local types. Verified by search at drafting time — there are none — and re-checked by tasks 3.1 and 4.1 before deletion, which stop and report rather than rewrite if one has appeared.
- Dallas supplies `source_account_id` from `account_num` and `parcel_reference` from `gis_parcel_id`, as it does today; only `source_family` and `source_status` become `None`.

## Unresolved decisions

- None.

## Risks and compatibility

The migration is the risk, not the new module. Both counties have full suites, and migration must preserve observable behaviour exactly — same rows accepted, same rejected, same codes in the same order, same counts. Each migration lands with its county's tests unmodified except where a type name moved, so a behaviour change surfaces as a failure rather than a rewritten expectation. The 52 Dallas contract cases that #43 protects are covered by that rule.

Widening `value` to include `int` and `None`, and making three fields nullable, is a loosening: a consumer that assumed non-null must now handle absence. There is no such consumer today, and the counties that specified concrete values still supply them.

Not addressed: the 663 MiB. These are per-record containers.

## Rollout and failure recovery

Additive first — module and tests land before either migration, so a failed migration reverts to a county-local copy without removing the shared type. Dallas and Collin migrate independently.

## Testing strategy

Contract tests prove immutability including private attributes, that a record cannot be constructed without provenance, that a value's map key must equal its `source_field`, that blank strings are rejected while `None` is accepted where declared, and that a caller's mapping cannot reach inside a constructed record. Architecture tests parse the AST and strip docstrings before asserting on imports and class names, because a docstring may legitimately name a county. Privacy tests assert what D6 actually claims — no named identity field, no untyped payload attribute — and deliberately do not assert the stronger property that Dallas's accepted extras behaviour makes false. Each county's migration is proved by its existing suite passing unchanged.
