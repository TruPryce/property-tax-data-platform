## Why

Issue #17 requires a production-quality Dallas appraisal parser foundation without using or
committing county data. Accepted Dallas evidence already distinguishes `ACCOUNT_NUM` from
`GIS_PARCEL_ID`, identifies the account-year grain, and requires `TOT_VAL` to remain
source-native; this planning revision supplies the previously missing physical-layout, record,
lexical, provenance, and diagnostic decisions needed for deterministic implementation.

## What Changes

- Define a UTF-8, comma-delimited CSV contract with optional leading BOM, standard double-quote
  behavior, LF and CRLF support, exact row-width checks, observed-header normalization, and
  deterministic layout fingerprints.
- Define adapter-local `DallasAppraisalSourceRecord`, `AppraisalSourceRecord`, source-native value,
  provenance, and diagnostic contracts under `property_tax_adapters` only.
- Define exact lexical forms for account number, appraisal year, parcel identifier, and `TOT_VAL`,
  including deterministic duplicate account-year rejection.
- Preserve unknown columns as source extras and preserve `TOT_VAL` only as a source-native value;
  no canonical appraisal or tax-collection meaning is approved.
- Require small, synthetic, identity-free, redistribution-safe fixtures and observable tests for
  valid input, layout variation, malformed input, provenance, diagnostics, and redaction.
- Keep implementation eligibility false until an authorized maintainer merges this planning PR;
  the merge is the approval event for subsequent implementation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dallas-cad-source-contract`: add the approved parser-foundation contract for physical CSV
  layout, adapter-local records, lexical forms, provenance, diagnostics, synthetic fixtures, and
  fail-closed behavior.

## Impact

- Permitted implementation paths: `libs/property-tax-adapters` and its adapter-local tests and
  synthetic fixtures, plus `docs`.
- `property_tax_domain` and `property_tax_application` remain unchanged; no domain type is
  approved by this change.
- No new dependency is approved. The implementation uses Python standard-library CSV, decimal,
  hashing, and JSON facilities.
- No service, DAG, workflow, tool, infrastructure, persistence, migration, deployment, or
  production configuration is authorized.

## Constraints

- Parser inputs are caller-supplied bytes or text, source member name, and release identifier; the
  parser performs no network access and does not infer source or release identity from row data.
- Fixtures and expected diagnostics MUST be small, synthetic, identity-free, and
  redistribution-safe. No county archive, CSV extract, appraisal record, owner record, mailing
  address, protected identity, production data, credential, or secret may be committed.
- Owner and mailing-address publication remains default-deny, and diagnostics may not echo
  complete rows or arbitrary source values.
- Appraisal data remains distinct from authoritative tax bills, payments, delinquencies,
  penalties, and interest.

## Non-goals

- Live Dallas discovery, download, HTTP probing, source contact, or network access.
- ZIP acquisition, Bronze persistence, immutable source storage, or release ingestion.
- PostgreSQL loading, database migration, backfill, Silver persistence, Gold publication, or
  release promotion.
- Airflow orchestration, ingestion-service work, workflows, provider changes, infrastructure, or
  deployment.
- New dependencies, owner publication, protected-identity reconstruction, or owner-bearing
  fixtures and diagnostics.
- Cross-county normalization, a shared Dallas-derived parser, or a PACS domain abstraction.
- Canonical market, appraised, assessed, taxable, tax-amount, payment-status, or delinquency
  semantics for `TOT_VAL`.
- A production-ready designation for Dallas or any other county adapter.

This planning contract remains implementation-ineligible until an authorized maintainer merges
PR #31. The merge, not generation or validation, is the human approval event.
