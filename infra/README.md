# Runtime Infrastructure

This area contains the version-pinned Docker foundation for the independent property-tax runtime. It follows the accepted [runtime operations contract](../openspec/changes/bootstrap-six-county-appraisal-platform/specs/platform-runtime-operations/spec.md) without claiming that production provisioning, backup, restore, or deployment tasks are complete.

## Topology

| Service | Image or command | Purpose |
|---|---|---|
| PostgreSQL | `postgres:16.11-bookworm` | Airflow metadata and property-tax databases with separate roles |
| Airflow initialization | `airflow version` after entrypoint initialization | One-shot metadata migration and initial administrator creation |
| Airflow API server | `airflow api-server` | Administrative UI and API |
| Airflow scheduler | `airflow scheduler` with `LocalExecutor` | Bounded single-host task execution |
| Airflow DAG processor | `airflow dag-processor` | Required Airflow 3 DAG parsing boundary |
| Airflow triggerer | `airflow triggerer` | Deferrable task execution support |

Redis and Celery workers are intentionally absent. The initial 16 GB single-host deployment uses `LocalExecutor` with bounded parallelism. PostgreSQL uses regular tables rather than TimescaleDB.

## Bootstrap

Requirements are Docker Engine with Compose V2, Python 3.12 development tooling, Bash, and the [Bitwarden Secrets Manager CLI](https://bitwarden.com/help/secrets-manager-cli/).

Create a read-only Bitwarden machine account scoped only to the property-tax runtime project. Add these exact secret names to that project:

```text
POSTGRES_SUPERUSER_PASSWORD
AIRFLOW_DB_PASSWORD
PROPERTY_TAX_MIGRATOR_PASSWORD
PROPERTY_TAX_INGESTION_PASSWORD
PROPERTY_TAX_API_PASSWORD
AIRFLOW_FERNET_KEY
AIRFLOW_API_SECRET_KEY
AIRFLOW_JWT_SECRET
AIRFLOW_ADMIN_PASSWORD
```

The machine-account access token is the only bootstrap credential stored on the VPS. Export it and the Bitwarden project ID without placing the token in shell history:

```bash
read -rsp "Bitwarden access token: " BWS_ACCESS_TOKEN && echo
read -rp "Bitwarden project ID: " BWS_PROJECT_ID
export BWS_ACCESS_TOKEN BWS_PROJECT_ID
./infra/scripts/bootstrap-env.sh
unset BWS_ACCESS_TOKEN BWS_PROJECT_ID
```

This creates separate mode-`0600` files: `infra/.env` contains non-secret Compose settings, while `infra/.bws.env` contains only `BWS_ACCESS_TOKEN` and `BWS_PROJECT_ID`. The files are ignored by Git.

From the repository root:

```bash
./infra/scripts/compose-with-bitwarden.sh build
./infra/scripts/compose-with-bitwarden.sh up airflow-init
./infra/scripts/compose-with-bitwarden.sh up -d
```

The wrapper authenticates `bws` with the access token, requests only the configured project, and uses `--no-inherit-env` before starting trusted Docker Compose. Bitwarden runtime secrets reach Compose by their exact names; `BWS_ACCESS_TOKEN` does not. Neither the access token nor a resolved value is passed into a container unless the Compose service explicitly requires that runtime value.

The Airflow API defaults to `http://127.0.0.1:8080`; PostgreSQL defaults to loopback port `5432`. Set bind addresses only to an approved Tailscale address on the Akamai host.

Inspect health without printing configuration or credentials:

```bash
./infra/scripts/compose-with-bitwarden.sh ps
./infra/scripts/compose-with-bitwarden.sh exec airflow-scheduler airflow version
```

Stop services while retaining database and log volumes:

```bash
./infra/scripts/compose-with-bitwarden.sh down
```

Do not add `--volumes` unless permanent local runtime state is intentionally being destroyed.

## Database Roles

| Role | Initial access |
|---|---|
| `airflow_metadata` | Owns only the `airflow` metadata database |
| `property_tax_migrator` | Owns the `property_tax` database and applies reviewed migrations |
| `property_tax_ingestion` | Connect-only until migrations grant bounded Silver write privileges |
| `property_tax_api` | Connect-only until migrations grant bounded Gold read privileges |

The PostgreSQL bootstrap creates no Silver or Gold tables. Schema, object privileges, and default privileges belong to the migration task so role capabilities evolve with the persistence contract.

## Production Boundary

This foundation does not configure Tailscale, TLS, S3 remote logs, Bronze storage, WAL archiving, physical backups, restore exercises, monitoring, or deployment automation. Those controls remain required before production promotion. Runtime values are fetched from Bitwarden Secrets Manager by a read-only machine account and injected through the host wrapper; they never belong in Git or images. The machine access token is a separate bootstrap credential and must remain in the root-readable `.bws.env` file and approved off-host recovery custody.

## Validation

```bash
make infra-check
./infra/scripts/compose-with-bitwarden.sh config --quiet
```

## Related

- [Infrastructure agent guidance](AGENTS.md)
- [Operations documentation](../docs/operations/README.md)
- [Independent runtime decision](../docs/decisions/0001-independent-akamai-runtime.md)
- [Airflow DAG guidance](../dags/README.md)
