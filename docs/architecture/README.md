# Architecture

The platform uses hexagonal boundaries around a lightweight medallion data flow:

```text
Official county sources
        |
        v
Airflow / ingestion worker       inbound adapters
        |
        v
Application use cases            ports and orchestration
        |
        +--> County/HTTP adapters ---> Bronze object storage
        |
        +--> PostgreSQL adapter -----> Silver normalized tables
        |
        +--> Quality/publication ----> Gold versioned products
                                      |              |
                                      v              v
                                appraisal-api   S3 bulk exports
        v
Domain identities and semantics
```

The active [technical design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md) is authoritative while the foundation is being implemented.

The first deployment is an independent Akamai Cloud runtime. Tailscale carries administrative access; consumers use the read-only `appraisal-api` or versioned S3 exports. The VPS and attached volume are replaceable: immutable source artifacts and PostgreSQL point-in-time recovery material live in Amazon S3, while Bitwarden holds the off-host recovery copy of environment secrets.

## Related

- [Documentation hub](../README.md)
- [Shared libraries](../../libs/README.md)
- [DAGs](../../dags/README.md)
- [Decisions](../decisions/README.md)
- [Independent runtime decision](../decisions/0001-independent-akamai-runtime.md)
- [S3 recovery decision](../decisions/0002-s3-durable-recovery-boundary.md)
- [Bitwarden secret recovery decision](../decisions/0003-bitwarden-environment-secret-recovery.md)
- [Appraisal API decision](../decisions/0004-consumer-neutral-appraisal-api.md)
