# PostgreSQL Backup and Recovery

How the platform's PostgreSQL cluster is protected, how it is restored to a point in time, and how it is rebuilt on a different provider.

The durable boundary is Amazon S3, not the host. Every storage device on the VPS — root disk, container volume, and any attached Block Storage — is replaceable capacity, per [ADR-0010](../decisions/0010-replaceable-local-storage-and-s3-backup-repository.md). Recovery must work with none of them.

| | |
|---|---|
| Tool | pgBackRest 2.59.1, pinned, inside the PostgreSQL image |
| Stanza | `platform` |
| Repository | `s3://trupryce-property-tax-backups/pgbackrest/platform` |
| Encryption | `aes-256-cbc`, passphrase from Bitwarden, applied before anything leaves the host |
| Identity | `trupryce-data-platform-backup` via IAM Roles Anywhere, no stored keys |
| Schedule | weekly full, daily differential, continuous WAL, `archive_timeout=300` |
| Retention | 4 full cycles, counted |
| Scheduled by | systemd on the host, never Airflow |

## Why backups are not an Airflow DAG

Airflow's metadata database is one of the two databases being protected. A backup that runs inside Airflow stops when Airflow stops, and Airflow being broken is one of the situations a restore exists for. The dependency runs one way: backups protect Airflow, so they cannot depend on it.

---

## Part 1 — AWS and IAM Roles Anywhere bootstrap for an external VPS

This part needs **administrative AWS credentials**. The runtime host deliberately does not hold them — its `trupryce-data-platform-vps` role is denied `iam:*` and `rolesanywhere:*`, which is the correct posture and is why this is an operator procedure rather than automation.

### What already exists

| Component | Value |
|---|---|
| Account | `099427795947`, `us-east-1` |
| CA | `CN=TruPryce Platform Workload CA`, private, valid to 2036 |
| Trust anchor | `arn:aws:rolesanywhere:us-east-1:099427795947:trust-anchor/63c0a64e-843d-4603-9f55-0ddc7045ecaa` |
| Workload certificate | `CN=trupryce-data-platform-vps`, at `/etc/trupryce/aws/`, **expires 2026-11-17** |
| Data role | `arn:aws:iam::099427795947:role/trupryce-data-platform-vps` — no delete, unchanged by this work |

The CA, the trust anchor, and the workload certificate are reused. Only the backup-side authority is new.

### 1.1 Create the backup bucket

```bash
aws s3api create-bucket --bucket trupryce-property-tax-backups --region us-east-1
aws s3api put-public-access-block --bucket trupryce-property-tax-backups \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket trupryce-property-tax-backups \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket trupryce-property-tax-backups \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

Versioning is on so that a deletion — including one by the backup role — is recoverable. pgBackRest's own retention deletes current versions; the noncurrent versions are the floor under a mistake.

Bound noncurrent growth, or versioning silently becomes unbounded cost:

```bash
aws s3api put-bucket-lifecycle-configuration --bucket trupryce-property-tax-backups \
  --lifecycle-configuration '{"Rules":[{
    "ID":"expire-noncurrent","Status":"Enabled","Filter":{"Prefix":"pgbackrest/"},
    "NoncurrentVersionExpiration":{"NoncurrentDays":30},
    "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}'
```

### 1.2 Create the backup role

The permission policy is confined to the repository prefix and nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject"],
      "Resource": "arn:aws:s3:::trupryce-property-tax-backups/pgbackrest/platform/*" },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::trupryce-property-tax-backups",
      "Condition": {"StringLike": {"s3:prefix": ["pgbackrest/platform/*"]}} }
  ]
}
```

`s3:DeleteObject` is present because pgBackRest expires its own retained cycles. It is confined to this prefix, and it is the reason this is a **separate role**: granting delete to `trupryce-data-platform-vps` would let the identity that handles untrusted county downloads destroy the backups protecting against them.

The trust policy restricts assumption to the existing trust anchor **and** the certificate subject:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "rolesanywhere.amazonaws.com"},
    "Action": ["sts:AssumeRole","sts:TagSession","sts:SetSourceIdentity"],
    "Condition": {
      "ArnEquals": {
        "aws:SourceArn": "arn:aws:rolesanywhere:us-east-1:099427795947:trust-anchor/63c0a64e-843d-4603-9f55-0ddc7045ecaa"
      },
      "StringEquals": {
        "aws:PrincipalTag/x509Subject/CN": "trupryce-data-platform-vps"
      }
    }
  }]
}
```

Both conditions matter. The trust anchor alone would let **any** certificate the CA ever issues assume the backup role; pinning the CN means a valid chain is not by itself authority.

```bash
aws iam create-role --role-name trupryce-data-platform-backup \
  --assume-role-policy-document file://backup-trust-policy.json
aws iam put-role-policy --role-name trupryce-data-platform-backup \
  --policy-name pgbackrest-repository --policy-document file://backup-permission-policy.json
```

### 1.3 Create the Roles Anywhere profile

```bash
aws rolesanywhere create-profile --name trupryce-data-platform-backup \
  --role-arns arn:aws:iam::099427795947:role/trupryce-data-platform-backup --enabled
```

Record the returned profile ARN as `PGBACKREST_AWS_PROFILE_ARN` in `infra/.env`. It is not a secret — it names which role may be assumed, not how to prove entitlement. The proof is the certificate.

### 1.4 Verify from the runtime host

```bash
aws --profile trupryce-backup sts get-caller-identity
aws --profile trupryce-backup s3 ls s3://trupryce-property-tax-backups/
```

Expect an ARN ending `assumed-role/trupryce-data-platform-backup/…`. Also confirm the separation still holds — the data role must **not** reach the backup prefix:

```bash
aws --profile trupryce-data-vps s3 ls s3://trupryce-property-tax-backups/   # expect AccessDenied
```

No `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` is created at any point in this procedure. If you find yourself creating one, stop.

---

## Part 2 — pgBackRest and WAL operation

### 2.1 Secrets and configuration

The cipher passphrase is a Bitwarden secret in the `tax-platform` project:

```bash
BWS_ACCESS_TOKEN=… ./infra/scripts/generate-runtime-secrets.sh --bws "$BWS_PROJECT_ID"
```

**Losing `PGBACKREST_CIPHER_PASS` makes every existing backup permanently unreadable.** It is recovery-critical in a way the database passwords are not: rotating it does not re-encrypt what is already in S3, so the old value stays required for every backup taken under it. It is escrowed under [ADR-0003](../decisions/0003-bitwarden-environment-secret-recovery.md).

Everything else is non-secret configuration in `infra/.env` — the certificate paths and the three ARNs. See `infra/.env.example`.

### 2.2 Enable archiving

`archive_mode` is not reloadable, so this costs one restart:

```bash
./infra/scripts/compose-with-bitwarden.sh build postgres
./infra/scripts/compose-with-bitwarden.sh up -d postgres
```

Then create the stanza and check it:

```bash
./infra/scripts/pgbackrest-backup.sh check   # fails until stanza-create has run
docker exec --user postgres <container> pgbackrest --stanza=platform stanza-create
./infra/scripts/pgbackrest-backup.sh check
```

`check` is the one command that proves the whole chain end to end: configuration parses, credentials exchange, the bucket is writable, and PostgreSQL's `archive_command` actually reaches the repository. A green `check` is worth more than a successful backup, because a backup can succeed while archiving is broken — and then the backup is unrestorable to any point after it.

### 2.3 Schedule

```bash
sudo cp infra/systemd/pgbackrest-*.service infra/systemd/pgbackrest-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pgbackrest-full.timer pgbackrest-diff.timer
systemctl list-timers 'pgbackrest-*'
```

Both timers are `Persistent=true`, so a run missed while the host was down fires at boot rather than waiting for the next window. That matters most for the weekly full: without it, a host down over a Sunday leaves the differentials with no base inside the retention window.

The units select the container by Compose label, not by ID or name, because an ID changes on every recreate and a unit pinned to one keeps running while protecting nothing.

### 2.4 Routine checks

```bash
./infra/scripts/pgbackrest-backup.sh info     # backup set, WAL range, sizes
./infra/scripts/pgbackrest-backup.sh check    # archive + repository reachable
docker exec <container> psql -U platform_admin -c \
  "SELECT archived_count, failed_count, last_archived_time FROM pg_stat_archiver"
```

`failed_count` rising with `last_archived_time` stalling is the signature of a broken archive. Alerting on it belongs to the unimplemented "Backup and recovery observability" requirement; until then it is a manual check.

### 2.5 Failure mode: WAL accumulation

If archiving fails, PostgreSQL keeps every unarchived segment. `pg_wal` grows until the root disk fills, and PostgreSQL stops when it does — an outage caused by the backup system, not prevented by it.

```bash
docker exec <container> du -sh /var/lib/postgresql/data/pg_wal
docker exec <container> ls /var/spool/pgbackrest/archive/platform/out | head
```

Fix the cause and drain with `pgbackrest --stanza=platform archive-push` before the disk fills. Do **not** delete WAL segments by hand: a segment removed before it reaches S3 is a permanent hole in the recovery timeline, and every point after it becomes unreachable.

### 2.6 Certificate renewal — due before 2026-11-17

The workload certificate was issued 2026-08-19 for 90 days. When it expires, credential exchange fails, archiving stops, and the symptom is indistinguishable from a backup that quietly stopped running. Renewal is not automated.

Issue a new leaf from the same CA with the same CN, replace the `.pem` and `.key` in `/etc/trupryce/aws/`, and restart PostgreSQL. The trust anchor and role need no change, because trust is anchored to the CA and the subject, not to a specific certificate.

---

## Part 3 — Point-in-time restore

### The rule

**Never restore over `postgres-data`.** A restore is a hypothesis about what went wrong; testing it by overwriting the only surviving copy of production makes a recoverable incident unrecoverable. Restore into a new volume, verify, and only then decide about promotion.

### 3.1 Choose a target

```bash
./infra/scripts/pgbackrest-backup.sh info
```

The target must lie inside the WAL range of a full backup that precedes it.

### 3.2 Restore into an isolated volume

```bash
docker volume create pitr-verify-$(date +%s)      # never postgres-data
docker run --rm \
  -v pitr-verify-…:/var/lib/postgresql/data \
  -v /etc/trupryce/aws:/etc/trupryce/aws:ro \
  -e PGBACKREST_REPO1_CIPHER_PASS=… \
  -e PGBACKREST_AWS_… \
  --user postgres property-tax-postgres:16.11 \
  pgbackrest --stanza=platform --type=time \
    --target="2026-08-26 23:45:00+00" --target-action=promote restore
```

Start it on a loopback-only non-production port, never `5432`:

```bash
docker run -d --name pitr-verify -p 127.0.0.1:55432:5432 \
  -v pitr-verify-…:/var/lib/postgresql/data property-tax-postgres:16.11
```

### 3.3 What the restored cluster must prove

Six assertions. The first five are integrity; the sixth is what makes it *point-in-time* rather than merely a restore:

| # | Assertion |
|---|---|
| 1 | `property_tax` database exists |
| 2 | `airflow` database exists |
| 3 | all four runtime roles exist (`airflow_metadata`, `property_tax_migrator`, `property_tax_ingestion`, `property_tax_api`) |
| 4 | PostgreSQL starts cleanly and recovery completes |
| 5 | the marker committed **before** the target is present |
| 6 | the marker committed **after** the target is **absent** |

Assertion 6 is the one that cannot be faked. A restore that replays all available WAL also satisfies 1–5, so proving only those proves a restore happened, not that the target was honoured.

```sql
SELECT datname FROM pg_database WHERE datname IN ('property_tax','airflow');
SELECT rolname FROM pg_roles WHERE rolname LIKE 'property_tax%' OR rolname = 'airflow_metadata';
SELECT state, note FROM public.recovery_marker ORDER BY recorded_at;  -- 'before' only
SELECT pg_is_in_recovery();
```

Tear down afterwards:

```bash
docker rm -f pitr-verify && docker volume rm pitr-verify-…
```

### 3.4 Recorded exercise

> **Not yet exercised.** The AWS-side bootstrap in Part 1 requires administrative credentials the runtime host does not hold, so the repository does not yet exist and no backup has been taken. This section is filled in from a real run, not from expectation.
>
> | Field | Value |
> |---|---|
> | Date | *pending* |
> | Backup label | *pending* |
> | Target timestamp | *pending* |
> | Measured RPO | *pending* |
> | Measured RTO | *pending* |
> | Assertions 1–6 | *pending* |

Record no credential, no certificate material, no passphrase, and no production source data here.

---

## Part 4 — Clean-host restore onto another provider

Moving to Hostinger is a **restore**, not a volume transfer. Nothing from the Akamai host's disks is needed.

### Reused — do not recreate

| Component | Why it survives the move |
|---|---|
| CA (`TruPryce Platform Workload CA`) | Identity authority is not host-specific |
| Roles Anywhere trust anchor | Anchored to the CA, not to a host |
| S3 data bucket | Contains Bronze evidence and exports |
| S3 backup bucket | Contains the recovery material being restored from |
| pgBackRest repository (`pgbackrest/platform`) | The stanza and its history are the thing being restored |
| Bitwarden project (`tax-platform`) | Holds the cipher passphrase and runtime secrets |
| Git repository | Holds the runtime definition |

### Recreated per host — never copied

| Component | Why it must be new |
|---|---|
| Leaf certificate and private key | A private key that exists in two places has two ways to leak, and revoking one host revokes the other |
| Host-specific certificate CN authorization | The trust policy pins a CN; a new host is a new subject |
| AWS local profile and config (`~/.aws/config`) | Points at host-local certificate paths |
| Docker runtime | Host software, rebuilt from the repository |
| Restored PostgreSQL volume | Created by the restore itself |

### Procedure

1. **Issue a new leaf** from the existing CA as `CN=trupryce-data-platform-hostinger`, with its own key generated **on the Hostinger host**. Do not copy `/etc/trupryce/aws/trupryce-data-platform-vps.key`. Do not reuse the Akamai key under a new filename.
2. **Authorize the new subject.** Add the new CN to the backup and data role trust policies. During migration **both identities may be temporarily authorized** — the old host may still be archiving while the new one restores:

   ```json
   "StringEquals": {
     "aws:PrincipalTag/x509Subject/CN": [
       "trupryce-data-platform-vps",
       "trupryce-data-platform-hostinger"
     ]
   }
   ```

3. **Install the runtime** from Git, write `infra/.env` with the new certificate paths, and bootstrap secrets from Bitwarden.
4. **Restore** into a fresh volume as in Part 3, targeting the latest recoverable point.
5. **Verify** all six assertions before pointing anything at the new host.
6. **Cut over**, then stop archiving from Akamai.
7. **Remove the Akamai identity.** Delete `trupryce-data-platform-vps` from both trust policies, revoke its certificate at the CA, and destroy the key on the retired host. Leaving it authorized after cutover means a decommissioned machine retains write access to the backup repository.

Step 7 is the one that gets skipped. A migration is not finished while the old identity can still write.

### Order matters

Restore and verify **before** cutover, and revoke **after**. Revoking the Akamai identity before the Hostinger restore is verified leaves no working identity if the restore fails.

## Related

- [Operations](README.md)
- [ADR-0010: Replaceable local storage and a segregated S3 backup repository](../decisions/0010-replaceable-local-storage-and-s3-backup-repository.md)
- [ADR-0002: S3 durable recovery boundary](../decisions/0002-s3-durable-recovery-boundary.md)
- [ADR-0003: Bitwarden environment-secret recovery](../decisions/0003-bitwarden-environment-secret-recovery.md)
- [Runtime infrastructure](../../infra/README.md)
- [PostgreSQL schema and migrations](../../infra/postgres/README.md)
