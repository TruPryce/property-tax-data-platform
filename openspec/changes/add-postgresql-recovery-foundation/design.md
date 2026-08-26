# Design: PostgreSQL Recovery Foundation

## Context

The runtime is one Akamai VPS running Docker Compose. PostgreSQL 16.11 holds two databases that matter — `property_tax` and Airflow's `airflow` metadata — on a single Docker named volume, `postgres-data`, backed by the root disk. There is no attached Block Storage despite the accepted contract naming a 250 GB volume, and the operator has decided PGDATA stays where it is for this change.

That makes the host a single point of loss for everything except the Git repository and the Bitwarden vault. ADR-0002 already resolved that S3 is the durable boundary; this design is how that boundary is actually constructed.

## The identity problem, and why a second role

The host already has a working keyless AWS identity. A private CA (`CN=TruPryce Platform Workload CA`) issued a workload certificate (`CN=trupryce-data-platform-vps`), and an IAM Roles Anywhere trust anchor exchanges that certificate for short-lived credentials against `role/trupryce-data-platform-vps`. Verified working: the exchange returns `ASIA`-prefixed temporary credentials, and `sts:GetCallerIdentity` resolves to the assumed role.

That role is a **data** role. It handles county source downloads — untrusted bytes from six appraisal districts — and it is deliberately not allowed to delete objects.

Backups need `s3:DeleteObject` on their own prefix, because pgBackRest expires its own retained cycles. Adding that permission to the data role would mean the identity that processes untrusted county archives could also destroy the backups protecting against a bad county archive. That is the wrong blast radius, so the two are separated:

```text
  workload certificate  CN=trupryce-data-platform-vps
  (one cert, one key, one trust anchor)
            |
            +-- profile A --> role/trupryce-data-platform-vps
            |                  s3:GetObject/PutObject on the data prefix
            |                  NO delete            <- unchanged by this change
            |
            +-- profile B --> role/trupryce-data-platform-backup
                               s3:* on s3://trupryce-property-tax-backups/pgbackrest/platform/*
                               including DeleteObject, for retention expiry only
```

One certificate, two profiles, two roles, disjoint authority. The certificate is reused because host identity is what it attests; the *authority* attached to that identity is what differs. The backup role's trust policy pins both the trust anchor and `x509Subject/CN=trupryce-data-platform-vps`, so a different certificate from the same CA cannot assume it.

## Credential flow

pgBackRest supports `repo1-s3-key-type=process`, which executes a command and reads AWS credentials as JSON from its stdout. The command is a fixed-argument wrapper:

```text
pgbackrest  --repo1-s3-key-type=process
            --repo1-s3-key-process=/usr/local/bin/pgbackrest-aws-signing
                        |
                        v
            aws_signing_helper credential-process
              --certificate  /etc/trupryce/aws/trupryce-data-platform-vps.pem
              --private-key  /etc/trupryce/aws/trupryce-data-platform-vps.key
              --trust-anchor-arn <anchor>
              --profile-arn      <backup profile>
              --role-arn         role/trupryce-data-platform-backup
                        |
                        v
            {"Version":1,"AccessKeyId":...,"SecretAccessKey":...,
             "SessionToken":...,"Expiration":...}   -> passed through unmodified
```

The wrapper does not parse, reformat, cache, or log the response. It `exec`s the helper so the helper's exit status is the wrapper's, and a failure surfaces as pgBackRest's own S3 error rather than as an empty-credential mystery. Nothing is written to disk at any point, and no `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` exists to be stolen.

## Where pgBackRest runs

In the PostgreSQL container, not on the host.

`archive_command` runs as a child of the PostgreSQL backend, so the binary must exist in the container's filesystem and namespace. Installing pgBackRest on the host and shelling out would require the host binary to see PGDATA, which it does not.

So the PostgreSQL image gains three things: `pgbackrest=2.59.1-1.pgdg12+1` from the PGDG repository the official image already configures, `aws_signing_helper` 1.8.4 copied from a pinned release, and the credential wrapper. Bookworm's stock 2.45 is rejected — it predates the `process` key type entirely.

Certificates are **mounted**, never baked: `/etc/trupryce/aws` is bind-mounted read-only. An image containing the private key would be a private key in every layer cache and registry it ever touched.

The host still schedules the work. `docker exec` into the container is how systemd reaches pgBackRest, which keeps scheduling on the host supervisor while execution stays where PGDATA is.

## Why systemd and not Airflow

Airflow's metadata database is one of the two databases being protected. A backup schedule that runs inside Airflow stops when Airflow stops — and Airflow being broken is one of the situations a restore is for. The dependency has to point the other way: backups protect Airflow, so they cannot depend on it.

Units select the container by Compose label rather than by name or ID:

```bash
docker ps --filter label=com.docker.compose.project=property-tax-platform \
          --filter label=com.docker.compose.service=postgres \
          --format '{{.ID}}'
```

A container ID changes on every recreate. The service label does not, and it is the identity Compose itself guarantees.

## Retention and schedule

Operational policy, deliberately kept out of the capability text and expressed once, in `pgbackrest.conf`:

| setting | value | why |
| --- | --- | --- |
| `repo1-retention-full` | 4 | four weekly full cycles ≈ 28 days of point-in-time reach |
| `repo1-retention-full-type` | count | count, not time, so a missed week cannot silently shorten the window |
| weekly | full backup | the base every restore in the window starts from |
| daily | differential backup | bounds restore time to at most one day of WAL replay |
| `archive-async` | y | archiving never blocks a committing backend |
| `archive_timeout` | 300s | bounds the recovery point at five minutes of wall-clock, not five minutes of write volume |
| `repo1-cipher-type` | aes-256-cbc | the repository is encrypted before it leaves the host |
| `compress-type` | zst | cheaper than gzip at the same ratio on this CPU |

`archive_timeout=300` is what makes the RPO a wall-clock guarantee. Without it, an idle database can hold a partially-filled WAL segment indefinitely and the true recovery point drifts arbitrarily far behind the last commit.

## The restore exercise

The point of the exercise is not "a backup exists". It is that a chosen timestamp is honoured in both directions:

```text
  t0  ---- marker 'before' committed, WAL forced to S3
      |
  T   ---- chosen recovery target (between the two)
      |
  t1  ---- marker 'after'  committed, WAL forced to S3

  restore --type=time --target=T  into a NEW temporary volume
      => 'before' present, 'after' absent
```

A restore that only proves `before` is present is satisfied by restoring the full backup and replaying everything, which is not point-in-time recovery. Asserting that `after` is *absent* is what proves the target was actually applied.

The restored cluster runs on a temporary Docker volume, on a loopback-only high port, as a separate container. `postgres-data` is never a target. The exercise also asserts that both databases and all four runtime roles survived, because a physical backup that lost a role would restore a cluster the application cannot log into.

## Alternatives rejected

- **Widening the existing data role** — rejected in D2. It collapses the blast-radius separation that is the reason for a backup identity at all.
- **A separate certificate for the backup role** — rejected. The certificate attests *which host this is*, and it is the same host. Two certificates would double the renewal surface for no isolation gain, since both would live in the same directory on the same disk. Authority is separated at the role, which is where it belongs. A separate certificate *is* correct across hosts, which is why Hostinger gets its own.
- **Long-lived IAM access keys** — rejected, and explicitly forbidden by the constraint. They are the thing Roles Anywhere exists to remove.
- **`repo1-s3-key-type=auto` with an instance profile** — unavailable. Roles Anywhere is not an instance profile and this is not an EC2 instance.
- **Debian stock pgBackRest 2.45** — rejected. No `process` key type, so it cannot use keyless credentials at all.
- **Cron instead of systemd timers** — rejected. No dependency ordering, no `RandomizedDelaySec`, no `systemctl list-timers` visibility, and failure goes to mail nobody reads.
- **Backups via an Airflow DAG** — rejected above; circular dependency.
- **Filesystem snapshots of the Docker volume** — rejected. Not crash-consistent for a running PostgreSQL, and it keeps the recovery material on the host being recovered from.
- **`pg_dump` instead of physical backup** — rejected. Logical dumps cannot do point-in-time recovery and do not restore a cluster with its roles.

## Risks

- **Cipher passphrase loss makes every backup unrecoverable.** Mitigated by escrowing it in Bitwarden under ADR-0003 alongside the other recovery material, and by the runbook stating plainly that the passphrase is as critical as the backups.
- **Certificate expiry on 2026-11-17 silently stops archiving.** Not mitigated by this change; recorded as an unresolved decision and as a runbook renewal step. The observability requirement that would alert on it is unimplemented.
- **WAL accumulates on the host if archiving fails.** `archive-async` with a spool directory bounds the in-flight set, but a sustained S3 outage will grow `pg_wal` until the root disk fills — and PostgreSQL stops when it does. The runbook documents the manual drain.
- **The AWS bootstrap needs administrative credentials.** Confirmed by probe: `iam:*` and `rolesanywhere:*` are denied from the runtime host. This is correct posture, and it means part of the procedure is an operator action rather than an automated one.
- **The restore exercise competes for host memory.** A second PostgreSQL container runs alongside the production stack. It is given a small `mem_limit` and torn down immediately.

## Migration

Nothing to migrate. `archive_mode=on` requires a PostgreSQL restart, which is the only production impact: one restart of the `postgres` service, taken deliberately, with Airflow reconnecting afterwards. The five merged property-tax migrations remain unapplied, by instruction.

## Unresolved questions

- Where the alerting from "Backup and recovery observability" lands — a systemd `OnFailure=` unit, an S3 object-age check, or an external monitor — is not decided here.
- Whether PGDATA eventually moves to Block Storage is left open by design; the amended contract permits either without further amendment.
- Whether the Akamai identity is revoked immediately after Hostinger cutover or kept briefly for rollback is an operator decision recorded in the runbook rather than fixed here.
