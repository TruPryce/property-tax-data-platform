# ADR-0004: Consumer-Neutral Appraisal API

## Status

Accepted on 2026-07-16.

## Context

TruPryce needs low-latency appraisal facts for off-market property composition, while other consumers need the same source-neutral contract. Making a TruPryce NestJS service the system-of-record API would couple this platform to one consumer and duplicate its Python domain model.

## Decision

The property-tax data platform will operate a lightweight Python `appraisal-api` service on its VPS. The API will use the workspace's application ports and domain contracts, read only published Gold projections, and expose county-qualified account identity, release status, tax year, freshness, and field provenance.

The API will not expose owner names or mailing addresses by default and will not label appraisal facts as authoritative tax bills, balances, payments, or delinquencies. It will provide operational point lookups; bulk and model-training consumers use versioned S3 exports instead of per-row API calls.

TruPryce will implement a typed client adapter and property-composition use case. It will not connect directly to PostgreSQL or host the county ingestion implementation.

## Alternatives

- A TruPryce-owned NestJS tax-provider API was rejected as the source-of-truth interface because it makes the producer consumer-specific.
- Direct consumer database access was rejected because it couples schemas, credentials, deployments, and incident blast radius.
- Serving bulk training workloads through point-lookups was rejected because it creates avoidable API and database load.

## Consequences

- The API needs a versioned OpenAPI contract and compatibility tests for external clients.
- API availability shares the initial VPS failure domain, but it remains independent from Airflow process availability and continues serving the last successful Gold publication.
- External TLS, authentication, authorization, request limits, and rate limits must be selected before production exposure.
- The service should remain thin; normalization and county parsing stay in adapters and application use cases rather than HTTP handlers.

## Related

- [Architecture decisions](README.md)
- [ADR-0001: Independent Akamai runtime](0001-independent-akamai-runtime.md)
- [Active OpenSpec design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md)
