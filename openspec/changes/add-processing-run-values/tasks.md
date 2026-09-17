# Tasks

Every module below lives in `libs/property-tax-application/src/property_tax_application/`. Where a
task says a type is **frozen**, it means a frozen slotted dataclass validating in `__post_init__`
and raising `ValueError`, matching the established style of `AcquiredArtifact` and the canonical
record model.

The falsification matrix in [`design.md`](design.md) is the authoritative list of what the suite
proves. No task restates a contract the capability spec states; where a task names a rule, the spec
says what it means, and where the two disagree the spec wins and the task is the defect.

This change adds **values only**. No port, no repository, no lifecycle operation, and no use of
these values by anything — those belong to `add-application-port-boundary` and
`add-canonical-load-session`, which cite this capability.

**Review scope** — one scope, `processing-run-values`, covering every task, per
[`reviews/README.md`](reviews/README.md). Implementation waits for an accepting round or a recorded
authorization.

## 1. The values

<!-- countyforge-task: 1.1 paths=libs/property-tax-application/src/property_tax_application/runs.py checks=repo.check risk=higher_risk prerequisites=D1,D4 -->

- [x] 1.1 Add the run reference and the disposition — Add `runs.py` carrying `ProcessingRunRef`, a frozen type wrapping one persistence-generated value, whose docstring states in its first line that it is an **opaque locator**: comparable for equality, hashable, carrying no ordering, no freshness or precedence meaning, and never canonical identity. Give it equality and hashing, and make every ordering comparison raise rather than merely omitting the methods — omission gives a confusing `TypeError` from elsewhere, and the raise says why. Constrain the wrapped value to something immutable and hashable and refuse anything else at construction, since a frozen wrapper around a mutable payload is not frozen. Add `ReleaseDisposition`, a closed vocabulary of exactly `accepted` and `rejected`, as a `StrEnum` matching the established style. Import nothing from `property_tax_adapters`.

<!-- countyforge-task: 1.2 paths=libs/property-tax-application/src/property_tax_application/runs.py checks=repo.check risk=higher_risk prerequisites=D2,D3,1.1 -->

- [x] 1.2 Add the evidence carriers and the sealed outcome — In `runs.py`, add `ReleaseDiagnosticRecord` (code, optional field name, optional physical row number, optional layout fingerprint) and `ReleaseNoticeRecord` (code, optional field name, optional physical row number), each frozen, each bounded, and neither carrying a source value. Validate the two codes by **different** rules, because the accepted contract and the database do: a diagnostic code against the exact closed vocabulary, supplied as a module-level frozen set rather than a second enum so the vocabulary keeps one authority in the bounded-processing boundary; a notice code against the bounded lowercase grammar `^[a-z][a-z0-9_]{0,63}$`. Add `ReleaseProcessingOutcome` carrying the disposition, the boundary contract version, the optional parser contract version and layout fingerprint together or not at all, the processed, staged, committed and rejected counts, and the bounded diagnostics and notices with their totals and truncation flags. Enforce **the evidence seal in the value**, exactly as the capability spec states it. Add `BOUNDARY_CONTRACT_VERSION`, the application's own copy, and refuse an outcome carrying any other.

## 2. Proof

<!-- countyforge-task: 2.1 paths=libs/property-tax-application/tests/test_processing_run_values.py,pyproject.toml checks=repo.check risk=normal prerequisites=D1,D2,D3,1.1,1.2 -->

- [x] 2.1 Prove the values by falsification — Add `libs/property-tax-application/tests/test_processing_run_values.py` implementing **every case in the falsification matrix** in [`design.md`](design.md), which is the authoritative list; add a case there rather than here when one is missing. Add that directory to `testpaths` in `pyproject.toml` if no earlier change has, since a suite the default configuration does not collect proves nothing. Prove the total mapping to the adapters' disposition by enumerating both vocabularies rather than asserting the sentence — this suite may import both packages where the application may not.

<!-- countyforge-task: 2.2 paths=libs/property-tax-application/src/property_tax_application/__init__.py,tests/architecture/test_dependency_direction.py checks=repo.check risk=normal prerequisites=1.1,1.2 -->

- [x] 2.2 Publish the surface and pin the mirrored constant — Export every type this change adds from `__init__.py` through the explicit `__all__`, adding to what is there rather than reordering or removing it. Extend `tests/architecture/test_dependency_direction.py` to assert that the application's `BOUNDARY_CONTRACT_VERSION` equals `property_tax_adapters.release.outcome.BOUNDARY_CONTRACT_VERSION`, so the copy cannot drift, and that `runs.py` names no schema, table, driver or surrogate key.

## 3. Documentation

<!-- countyforge-task: 3.1 paths=docs checks=docs.links,repo.check risk=normal prerequisites=D4,1.1,1.2,2.1 -->

- [x] 3.1 Document the values and who cites them — Describe this vocabulary in the application area's documentation: what each value carries, why the outcome is the application's own and the mapping total, why the seal is refused in the value rather than at commit, and why diagnostics and notices are validated by different rules. Name the two citers — the canonical load session for the reference and the outcome, the run lifecycle for both — and state that neither may redefine what it cites. Add no new document tree.
