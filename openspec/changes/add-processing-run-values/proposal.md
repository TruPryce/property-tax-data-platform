## Why

Two changes need these values before they can be implemented, and neither owns them.
`add-canonical-load-session` (PR #121) carries them in its signatures and cannot import a type that
does not exist; its first implementation attempt substituted local structural protocols and the
review found what that costs — an empty runtime-checkable protocol accepts every object, including
the raw persistence value the reference type exists to exclude.

They sit today inside `add-application-port-boundary` (PR #119/#120), whose `run-and-manifest` scope
still has open findings and whose run **lifecycle** work is properly reviewed there. The values are
separable from the lifecycle: a reference, a disposition, two bounded evidence carriers and an
outcome are settled by their own contracts, while starting, holding, resuming and finishing a run is
a protocol over a repository.

## What Changes

- **ADDED** capability `processing-run-values`: `ProcessingRunRef`, `ReleaseDisposition`,
  `ReleaseDiagnosticRecord`, `ReleaseNoticeRecord`, `ReleaseProcessingOutcome` with its evidence
  seal, and the application's own copy of the boundary contract version.
- **MODIFIED** `add-application-port-boundary`: its `processing-run` capability keeps the run
  lifecycle and the repository, and cites this capability for the reference and the outcome instead
  of defining them. That edit belongs to that change's own branch and is not made here.
- **UNBLOCKS** `add-canonical-load-session`, whose tasks 1.2 and 2.1 import these concrete types and
  are forbidden a substitute.
- No migration, no adapter change, and no orchestration change.

## Outcome

The value half of the processing-run vocabulary, owned by the application, implementable on its own,
and citable by both the canonical load session and the run lifecycle.

## Scope

- Originating issue: #119 (bootstrap task 2.3), carried out of PR #120
- Affected capabilities: one, ADDED — `processing-run-values`
- Affected decisions: D1, D10 and D13 move here from `add-application-port-boundary`; D12 and D23,
  which are lifecycle, stay there

### Capabilities

| Capability | Owns | Cites |
| --- | --- | --- |
| `processing-run-values` | `ProcessingRunRef`, `ReleaseDisposition`, `ReleaseDiagnosticRecord`, `ReleaseNoticeRecord`, `ReleaseProcessingOutcome`, the evidence seal, `BOUNDARY_CONTRACT_VERSION` | `application-port-boundary` for the opaque-locator rule; accepted `bounded-release-processing` for the closed diagnostic vocabulary and the notice grammar; accepted `canonical-silver-persistence` for the records these values must be recordable as |

## Decisions

- **D1 — The run is an application concept, and its persistence key is not.** `ProcessingRunRef` names a run across ports. `ingestion.run.run_id` is `GENERATED ALWAYS AS IDENTITY`, so the reference is documented and typed as an **opaque locator**: it is comparable and passable, and it is not canonical identity, not ordering, and not a business fact. Ports that accept one say so in their contract.

- **D2 — The processing outcome crossing the port is application-owned, and the mapping is total.** The adapters' `ReleaseOutcome` cannot be used: the dependency-direction test forbids the application from importing adapters, and five county modules already import from the application, so the arrow points inward. The application defines the outcome value, and it carries every fact `ingestion.release_outcome` requires — including the boundary contract version and the paired parser version and layout fingerprint — so an implementation can write that row from this value alone. A duplicate representation is acceptable here because the direction forbids reuse; a *lossy* one is not, because the missing facts would have to be fetched from outside the port. The boundary contract version is pinned to the accepted constant in the value itself — `ingestion.release_outcome` carries `CHECK (boundary_contract_version = 1)`, so an unpinned integer would pass the port and abort the canonical completion — and the dependency-direction test holds the application's copy equal to the adapters'.

- **D3 — The outcome value carries the evidence seal, not just the counts.** `ingestion.assert_outcome_evidence_agrees` runs at COMMIT and requires retained diagnostics to equal `least(total, 100)`, each truncation flag to equal `total > 100`, and every retained diagnostic's layout fingerprint to equal the outcome's under `IS DISTINCT FROM`. An outcome declaring one diagnostic and retaining none satisfied every invariant the first draft listed and would have aborted the canonical completion transaction, so the seal belongs in the value.
- **D4 — The values land before the lifecycle, and separately.** The run lifecycle is a protocol
  over a repository with its own open findings; these five values are settled by their own
  contracts. Splitting them is what lets the canonical load session be implemented against concrete
  types rather than against substitutes, which is the defect this change exists to remove. The
  identifiers here are this change's own: `D1`, `D2` and `D3` are the decisions recorded as `D1`,
  `D10` and `D13` in PR #120's ledger, and that mapping is below.

| Recorded in PR #120's ledger as | Here |
| --- | --- |
| `D1` | `D1` |
| `D10` | `D2` |
| `D13` | `D3` |

## Constraints

- No new dependency in `property-tax-application`, and no import of `property_tax_adapters`: the
  application holds its own copy of the boundary contract version, and a test asserts the two are
  equal so the copy cannot drift.
- No port, repository, or lifecycle operation is added here. This change adds values only.
- The accepted `bounded-release-processing` contract keeps one authority for the diagnostic
  vocabulary and the notice grammar; this change validates against them and defines no second enum.

## Non-goals

- The run lifecycle, `ProcessingRunRepository`, holding, resuming and finishing — PR #120.
- Any use of these values by a session or a use case — PR #121 and bootstrap 2.4.

## Unresolved decisions

None.
