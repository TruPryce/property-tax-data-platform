## 1. Correct occurrence binding and session validation

- [ ] 1.1 Extend `CorrelatedRecord` with the optional `secondary_parent` handle and enforce the closed B1 parent-shape table at batch construction without changing domain record types, existing handles, state components, or the public repository/session operations.
<!-- countyforge-task: 1.1 paths=libs/property-tax-application/src/property_tax_application/canonical.py,libs/property-tax-application/tests/test_canonical_load_session.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D3,D10 -->

- [ ] 1.2 Generalize B6 and B7 over both occurrence edges: reject self/collapsed handles, preserve Python-identity checks for every local edge, and require a local secondary occurrence to select the same primary occurrence as the child.
<!-- countyforge-task: 1.2 paths=libs/property-tax-application/src/property_tax_application/canonical.py,libs/property-tax-application/tests/test_canonical_load_session.py checks=repo.check risk=higher_risk prerequisites=D4,D5,1.1 -->

- [ ] 1.3 Extend the contract fake's private durable occurrence representation with optional primary-parent ancestry and generalize W5 across prior/current/adopted combinations, using handles and private locators for selection while preserving all six state components and atomic refusal.
<!-- countyforge-task: 1.3 paths=libs/property-tax-application/tests/_fake_load.py,libs/property-tax-application/tests/test_canonical_load_session.py checks=repo.check risk=higher_risk prerequisites=D6,D7,D8,D9,1.2 -->

## 2. Falsify and document the corrected boundary

- [ ] 2.1 Implement F1-F32 as focused canonical-load tests, including all three secondary-parent shapes, four mixed-boundary ancestry combinations, equal-but-distinct occurrence attacks, complete-state atomicity assertions, spill reachability proof, and bounded mutations that fail if value lookup replaces handle or private-locator selection.
<!-- countyforge-task: 2.1 paths=libs/property-tax-application/tests/test_canonical_load_session.py,libs/property-tax-application/tests/_fake_load.py checks=repo.check risk=higher_risk prerequisites=D1,D2,D3,D4,D5,D6,D7,D8,D9,1.3 -->

- [ ] 2.2 Update application and engineering documentation plus architecture/public-surface guards to explain the fixed primary/secondary binding table and private ancestry representation, proving there is no generic parent map, public persistence locator, new handle type, new state component, or changed domain model.
<!-- countyforge-task: 2.2 paths=libs/property-tax-application/README.md,docs/engineering/canonical-load-session.md,tests/architecture/test_dependency_direction.py checks=docs.links,repo.check,repo.prepr-no-ai risk=normal prerequisites=D10,2.1 -->
