# Completion reconciliation

Issue #119 requires bootstrap task 2.3 to remain incomplete until a separate transaction verifies
the implementation by substance. This audit was performed from `main` at
`5c6e754158013ceba7785b372bfa33764561b918`, after PR #136's hosted CI completed successfully.

## Acceptance matrix

| Criterion | Repository evidence | Result |
| --- | --- | --- |
| 1 | The responsibility inventory and disposition table in the archived `proposal.md`, the ownership table in `libs/property-tax-application/README.md`, and the explicit package surface in `libs/property-tax-application/src/property_tax_application/__init__.py` account for source registry, discovery, artifact storage, manifests, runs, canonical loading, quality, publication, and time. | PASS |
| 2 | The capability ownership table in `proposal.md` and the port-ownership table in `libs/property-tax-application/README.md` assign distinct responsibilities to each public port and explain the intentional `BronzeStore`/`ManifestIndex` split. | PASS |
| 3 | `ArtifactSink` remains the bounded streaming contract in `libs/property-tax-application/src/property_tax_application/acquisition.py`; the `BronzeStore` Protocol remains in `libs/property-tax-application/src/property_tax_application/bronze.py`; only the documented manifest value and S3 manifest mechanics were corrected, with adapter coverage in `libs/property-tax-adapters/tests/objectstore/test_s3_bronze.py`. | PASS |
| 4 | `tests/architecture/test_dependency_direction.py` parses every application module, rejects adapter/SDK/driver/orchestrator imports and infrastructure vocabulary, proves isolated import, and guards the mirrored boundary version. | PASS |
| 5 | `SourceRegistry` and `ReleaseDiscovery` in `libs/property-tax-application/src/property_tax_application/sources.py` and `libs/property-tax-application/src/property_tax_application/discovery.py` resolve one jurisdiction without network access, reject unsupported input by name, and return bounded candidate or unchanged evidence; their focused application tests falsify those rules. | PASS |
| 6 | `CanonicalReleaseRepository.open_load` in `libs/property-tax-application/src/property_tax_application/canonical.py` accepts the promoted `ReleaseIdentity`; the `canonical-load-session` capability and its tests refuse raw persistence values and define no canonical identity from a Bronze partition, filename, field name, or surrogate. | PASS |
| 7 | The promoted `canonical-load-session` transition table defines bounded successive batches, explicit commit and abort, and empty failure transitions; `libs/property-tax-application/tests/test_canonical_load_session.py` proves multi-batch loading, abandonment, rollback, and completion without whole-release materialization. | PASS |
| 8 | The canonical session commits `ReleaseProcessingOutcome` and the canonical load through one completion operation; accepted, rejected, failed, and retry branches are exercised in `libs/property-tax-application/tests/test_canonical_load_session.py` without independent outcome/load commits. | PASS |
| 9 | `ReleaseLoadCompletion.already_complete` is a bounded machine-readable retry result; canonical session tests prove repeated completion writes no additional records or outcome evidence. | PASS |
| 10 | The retry key is release plus `ProcessingRunRef`; `test_a_second_distinct_run_is_a_new_load_and_both_are_retained` proves another run for one release remains a distinct load. | PASS |
| 11 | The promoted canonical-load requirement defines no key over observed values, and canonical session falsification tests retain equal records, divergent same-grain snapshots, multiple children, multiple geometries, and cross-load children. | PASS |
| 12 | `libs/property-tax-application/src/property_tax_application/quality.py` defines the run-bound configurable rule/evaluation/verdict repository over the accepted model; verdicts are computed, not persisted, and tests cover missing, stale, ambiguous, blocking, and warning evidence without county thresholds. | PASS |
| 13 | `libs/property-tax-application/src/property_tax_application/publication.py` defines attempts whose activation derives quality atomically and whose failure preserves the prior current publication; the capability, README, and tests state that Gold construction, canonical read privilege, and sensitive-field permission are outside this port. | PASS |
| 14 | `libs/property-tax-application/src/property_tax_application/clock.py` defines one injectable `Clock` returning timezone-aware instants, and `libs/property-tax-application/tests/test_clock.py` proves fixed-time deterministic use without a required wall-clock read. | PASS |
| 15 | `ProcessingRunRef`, `ManifestRef`, `PublicationRef`, and `AccountSnapshotRef` are documented and tested as equality-capable opaque locators with no ordering or business-identity meaning and with immutable wrapped values. | PASS |
| 16 | `libs/property-tax-application/tests/test_port_contracts.py`, the focused application suites, `libs/property-tax-application/tests/test_canonical_load_session.py`, and `tests/architecture/test_dependency_direction.py` falsify bounded lifecycle, retry, atomicity, locator, public-surface, and infrastructure-independence rules; the focused reconciliation run passed 203 tests. | PASS |
| 17 | The `design.md` handoff assigns `ManifestIndex`, `ProcessingRunRepository`, the held-run mechanism, and the durable canonical session to bootstrap 3.5; bootstrap task 3.5 retains COPY-to-staging and set-based persistence, absent from application signatures. | PASS |
| 18 | The `design.md` handoff and application README assign discover, acquire, parse, normalize, validate, and publish coordination—and retirement of the S3 time helper—to bootstrap 2.4 using application ports rather than adapters. | PASS |
| 19 | All 12 implementation tasks were complete while bootstrap 2.3 remained unchecked through PR #136; this separate reconciliation audited criteria 1–20 and promoted the permanent capability specs before changing that bootstrap checkbox. | PASS |
| 20 | Before reconciliation, bootstrap 2.4, 2.5, 3.5, and 3.6 were all unchecked. This transaction changes only 2.3 among those five tasks and leaves their handoffs intact. | PASS |

## Promotion audit

The five delta specs promote 14 requirements and 85 scenarios. From each first requirement through
its final scenario, the promoted body matches the accepted delta exactly. The separately promoted
`canonical-load-session` and `processing-run-values` capabilities are not duplicated.

## Deferred handoffs

- Bootstrap 2.4 still owns orchestration of discover, acquire, parse, normalize, validate, and
  publish, plus replacement of the S3 adapter's direct time helper with injected `Clock`.
- Bootstrap 2.5 remains incomplete.
- Bootstrap 3.5 still owns PostgreSQL implementations, COPY-to-staging and set-based operations,
  durable canonical-session mechanics, `ManifestIndex`, and processing-run holder/locking behavior.
- Bootstrap 3.6 still owns real PostgreSQL/object-store concurrency, rollback, retry, and failure
  integration proof.

No runtime implementation, migration, county behavior, or infrastructure implementation is changed
by this reconciliation.
