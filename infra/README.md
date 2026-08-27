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
PGBACKREST_CIPHER_PASS
```

`PGBACKREST_CIPHER_PASS` encrypts the pgBackRest repository. It is recovery-critical
rather than access-critical: rotating it does not re-encrypt backups already in S3, so
the previous value stays required for every backup taken under it, and losing it makes
those backups permanently unreadable.

Generate the values rather than composing them by hand:

```bash
./infra/scripts/generate-runtime-secrets.sh --write ~/runtime-secrets.env
```

Every value except the Fernet key is 48 alphanumeric characters. Compose
interpolates `AIRFLOW_DB_PASSWORD` into a SQLAlchemy URL, where a generator's
default punctuation silently corrupts the connection — `p@ss/w0rd` parses as host
`ss` with password `p`. That failure surfaces as an authentication error against
a credential that looks correct everywhere you would think to check, because the
PostgreSQL bootstrap quotes the same value safely. `AIRFLOW_FERNET_KEY` is 32
random bytes in url-safe base64, which is what Airflow validates before it will
decrypt a stored connection.

Load the file into the Bitwarden project and delete it. Secrets can also be
created directly with a write-capable machine account, which must not be the
read-only account the runtime uses:

```bash
BWS_ACCESS_TOKEN=... ./infra/scripts/generate-runtime-secrets.sh --bws "$BWS_PROJECT_ID"
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

## Administrative Access

Both services default to loopback. PostgreSQL stays there: reach it by connecting to the host over Tailscale and using a local client, rather than publishing port `5432` to the tailnet.

The Airflow UI is published by setting `AIRFLOW_API_BIND_ADDRESS` in `infra/.env` to the host's Tailscale address, which serves the UI at `http://<tailscale-ip>:8080`. Two consequences follow from binding a container port to that address:

Docker has no ordering dependency on `tailscaled`, so after a reboot `docker-proxy` can try to bind the address before `tailscaled` has assigned it and fail with *cannot assign requested address*. `restart: unless-stopped` does not recover this, because the container fails at start rather than crashing later. Allow the bind to precede the address:

```bash
echo 'net.ipv4.ip_nonlocal_bind=1' | sudo tee /etc/sysctl.d/99-nonlocal-bind.conf
sudo sysctl --system
```

The UI is also served over plain HTTP. Tailscale encrypts the transport between nodes, so this is not exposed traffic, but the session cookie is unencrypted on each node's loopback and browsers treat the origin as insecure.

`tailscale serve` avoids both points by keeping the container on loopback and terminating TLS with a tailnet certificate:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
```

That requires HTTPS certificates enabled for the tailnet under **DNS → HTTPS Certificates** in the admin console; without it `tailscale status --json` reports `CertDomains: None` and the `--https` form fails.

The wrapper refuses any `POSTGRES_BIND_ADDRESS` or `AIRFLOW_API_BIND_ADDRESS` outside loopback and the Tailscale CGNAT range `100.64.0.0/10`. This is the only enforcement point: Docker publishes ports through its own iptables chain ahead of the host `INPUT` rules, so a `ufw` policy will not contain a misconfiguration here.

Reaching the tailnet is not authorization to administer the platform. Tailscale's default policy accepts every source to every destination, so the administrative surface needs an explicit rule:

```json
{
  "tagOwners": {
    "tag:platform-runtime": ["autogroup:admin"]
  },
  "acls": [
    {
      "action": "accept",
      "src": ["autogroup:admin"],
      "dst": ["tag:platform-runtime:443"]
    }
  ]
}
```

Neither port may be exposed with `tailscale funnel`, which would publish it to the public internet.

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

This foundation does not configure TLS beyond the tailnet, S3 remote logs, Bronze storage, monitoring, or deployment automation. Those controls remain required before production promotion.

The workload certificate and key are bind-mounted read-only from `/etc/trupryce/aws` and are never
baked into an image. Because the container's `postgres` user is uid 999 and the key belongs to the
operator, a read-only mount alone gives immutability without readability: the directory and key are
owned by `TRUPRYCE_AWS_GID` (2000) at `0750`/`0640`, and the PostgreSQL service joins that GID as a
supplementary group. The key is never world-readable. See
[section 2.7 of the runbook](../docs/operations/postgresql-recovery.md#27-certificate-file-permissions).

Backup timers are installed with `sudo SERVICE_USER=<user> ./infra/scripts/install-systemd-units.sh`,
which resolves the service user, repository path, and Docker group at install time; the committed
units are templates so a rebuilt host does not inherit this one's paths. A point-in-time restore runs
through `./infra/scripts/pgbackrest-restore.sh --target "<timestamp>"`, which resolves the repository
passphrase from Bitwarden itself and refuses to restore over the production volume.

WAL archiving and physical backups **are** configured: PostgreSQL runs with `archive_mode=on`,
`archive_command='pgbackrest --stanza=platform archive-push %p'`, and `archive_timeout=300`,
writing to an encrypted pgBackRest repository in S3 reached by a dedicated keyless identity.
The host workload certificate is bind-mounted read-only from `/etc/trupryce/aws` and is never
baked into an image. Backups are scheduled by systemd timers, never by Airflow. See
[PostgreSQL backup and recovery](../docs/operations/postgresql-recovery.md); the recorded
restore exercise there is not yet filled in. Runtime values are fetched from Bitwarden Secrets Manager by a read-only machine account and injected through the host wrapper; they never belong in Git or images.

The machine access token is a separate bootstrap credential. On the host it lives only in `.bws.env`, owned by the invoking user with mode `0600`; the wrapper refuses to run if that file grants any group or world permission. Because the token cannot bootstrap itself from Secrets Manager, a second copy belongs in the Bitwarden vault alongside the other escrowed recovery material, and the credentials guarding that vault belong in offline custody.

Rotating a database password in Bitwarden does not reach PostgreSQL: `postgres/init/10-create-runtime-databases.sh` runs only against an empty data directory. A rotation must also `ALTER ROLE ... PASSWORD` on the running cluster, and rotating `AIRFLOW_FERNET_KEY` strands existing encrypted connections unless the previous key is retained in the comma-separated list Airflow accepts for that setting.

## Validation

```bash
make infra-check
./infra/scripts/compose-with-bitwarden.sh config --quiet
```

## Related

- [Infrastructure agent guidance](AGENTS.md)
- [PostgreSQL schema and migrations](postgres/README.md)
- [Operations documentation](../docs/operations/README.md)
- [PostgreSQL backup and recovery](../docs/operations/postgresql-recovery.md)
- [Independent runtime decision](../docs/decisions/0001-independent-akamai-runtime.md)
- [Airflow DAG guidance](../dags/README.md)
