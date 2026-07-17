# ADR-0001: Independent Akamai Runtime

## Status

Accepted on 2026-07-16. Implementation validation remains open in the bootstrap OpenSpec change.

## Context

The platform must evolve independently from TruPryce and other consumers. Source acquisition and county parsing are batch-heavy workloads with different release, scaling, and failure behavior from a consumer application API.

## Decision

The first environment will run in the Akamai Cloud Dallas `us-central` region on an Ubuntu 24.04 LTS Shared CPU instance with 16 GB RAM and an attached 250 GB volume.

This deployment owns its PostgreSQL infrastructure, Airflow deployment, ingestion workers, and appraisal API. PostgreSQL will use separate logical databases and least-privilege roles for platform data and Airflow metadata. Tailscale is the administration path for SSH, Airflow administration, and database maintenance; it is not the consumer API contract.

TruPryce and other consumers will not connect directly to the platform database or run county ingestion code.

## Alternatives

- Hosting the pipeline inside TruPryce was rejected because it couples county releases and data operations to one consumer.
- Sharing TruPryce's Airflow or database was rejected because it creates cross-system deployment and recovery dependencies.
- Managed PostgreSQL is deferred until availability, operations, or growth justify its additional cost.

## Consequences

- The initial environment is one compute failure domain and is not highly available.
- Resource limits must prevent parsing and Airflow work from starving PostgreSQL or the API.
- All durable recovery must work without the original Akamai instance or attached volume.
- Consumer traffic requires a separately reviewed TLS, authentication, authorization, and rate-limit configuration.

## Related

- [Architecture decisions](README.md)
- [Active OpenSpec design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md)
- [ADR-0002: S3 durable recovery boundary](0002-s3-durable-recovery-boundary.md)
- [ADR-0004: Consumer-neutral appraisal API](0004-consumer-neutral-appraisal-api.md)
