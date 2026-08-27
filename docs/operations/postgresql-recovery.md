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

Every command in this part runs with **administrator** credentials as `aws --profile boss`. That profile is deliberately not present on the runtime host: its `trupryce-data-platform-vps` role is denied `iam:*` and `rolesanywhere:*`, which is the posture we want. Run Part 1 from an administrator workstation.

The workload verification commands at the end deliberately use `--profile trupryce-data-vps` and `--profile trupryce-backup` instead, because those are testing Roles Anywhere, not administrator authority. Never substitute `boss` there — it would prove only that an administrator can read S3.

Do not rely on ambient or default credentials anywhere in this part.

### What already exists and is reused

| Component | Value |
|---|---|
| Account / region | `099427795947` / `us-east-1` |
| CA | `CN=TruPryce Platform Workload CA`, private, valid to 2036 |
| Trust anchor | `arn:aws:rolesanywhere:us-east-1:099427795947:trust-anchor/63c0a64e-843d-4603-9f55-0ddc7045ecaa` |
| Workload certificate | `CN=trupryce-data-platform-vps` at `/etc/trupryce/aws/`, **expires 2026-11-17** |
| Data role | `arn:aws:iam::099427795947:role/trupryce-data-platform-vps` — no delete, not modified here |
| Source-data bucket | `trupryce-property-tax-data` — reachable by the data role only |

### 1.1 Create the backup bucket

**`us-east-1` must omit `--create-bucket-configuration`.** It is the S3 API's default region, and passing `LocationConstraint=us-east-1` fails with `InvalidLocationConstraint`. A generic create command copied from another region's runbook does not work here:

```bash
# Correct for us-east-1. In any other region, add
#   --create-bucket-configuration LocationConstraint=<region>
aws --profile boss s3api create-bucket \
  --bucket trupryce-property-tax-backups --region us-east-1
```

Harden it before anything is written. Each of these is a separate call, and each is required:

```bash
aws --profile boss s3api put-public-access-block \
  --bucket trupryce-property-tax-backups \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# ACLs off entirely: ownership is the bucket owner's, and no ACL grant can
# reintroduce cross-account access.
aws --profile boss s3api put-bucket-ownership-controls \
  --bucket trupryce-property-tax-backups \
  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'

aws --profile boss s3api put-bucket-versioning \
  --bucket trupryce-property-tax-backups --versioning-configuration Status=Enabled

aws --profile boss s3api put-bucket-encryption \
  --bucket trupryce-property-tax-backups \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

Versioning matters because pgBackRest's retention deletes current versions; the noncurrent versions are the floor under a mistake. That floor has to be bounded or it becomes unbounded cost, and incomplete multipart uploads have to be swept because a failed backup leaves parts behind that are billed but invisible in a normal listing:

```bash
aws --profile boss s3api put-bucket-lifecycle-configuration \
  --bucket trupryce-property-tax-backups \
  --lifecycle-configuration '{"Rules":[{
    "ID":"expire-noncurrent","Status":"Enabled","Filter":{"Prefix":"pgbackrest/"},
    "NoncurrentVersionExpiration":{"NoncurrentDays":30},
    "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}'
```

TLS-only, enforced by the bucket rather than trusted from the client:

```bash
aws --profile boss s3api put-bucket-policy \
  --bucket trupryce-property-tax-backups --policy '{
  "Version":"2012-10-17",
  "Statement":[{
    "Sid":"DenyInsecureTransport","Effect":"Deny","Principal":"*","Action":"s3:*",
    "Resource":["arn:aws:s3:::trupryce-property-tax-backups",
                "arn:aws:s3:::trupryce-property-tax-backups/*"],
    "Condition":{"Bool":{"aws:SecureTransport":"false"}}}]}'
```

### 1.2 Create the backup role

The permission policy is confined to the repository prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::trupryce-property-tax-backups/pgbackrest/platform/*" },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::trupryce-property-tax-backups",
      "Condition": {"StringLike": {"s3:prefix": ["pgbackrest/platform/*"]}} }
  ]
}
```

`s3:DeleteObject` is present because pgBackRest expires its own retained cycles, and `s3:AbortMultipartUpload` because pgBackRest uploads large files in parts and must be able to clean up a failed one. Both are confined to this prefix. This is the reason for a **separate role**: granting delete to `trupryce-data-platform-vps` would let the identity that handles untrusted county downloads destroy the backups protecting against them.

The trust policy pins the trust anchor **and** the certificate subject:

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

Both conditions matter. The trust anchor alone would let **any** certificate the CA ever issues assume the backup role, so pinning the CN is what makes a valid chain insufficient on its own.

```bash
aws --profile boss iam create-role --role-name trupryce-data-platform-backup \
  --assume-role-policy-document file://backup-trust-policy.json
aws --profile boss iam put-role-policy --role-name trupryce-data-platform-backup \
  --policy-name pgbackrest-repository --policy-document file://backup-permission-policy.json
```

**Retrieve the role ARN explicitly.** Do not reuse a shell variable populated earlier in the session — a re-run, a new shell, or a failed create leaves it stale or empty, and an empty `--role-arns` produces a profile that authorizes nothing while reporting success:

```bash
BACKUP_ROLE_ARN="$(aws --profile boss iam get-role \
  --role-name trupryce-data-platform-backup --query Role.Arn --output text)"
[ -n "$BACKUP_ROLE_ARN" ] && printf 'role: %s\n' "$BACKUP_ROLE_ARN" \
  || { echo 'role ARN did not resolve; stop here'; }
```

### 1.3 Create the Roles Anywhere profile

**`--enabled` is required.** A profile created without it exists, appears in listings, and refuses every credential exchange:

```bash
aws --profile boss rolesanywhere create-profile \
  --name trupryce-data-platform-backup \
  --role-arns "$BACKUP_ROLE_ARN" \
  --enabled
```

Retrieve and validate the profile ARN explicitly rather than reading it from the create output:

```bash
BACKUP_PROFILE_ARN="$(aws --profile boss rolesanywhere list-profiles \
  --query "profiles[?name=='trupryce-data-platform-backup'].profileArn" --output text)"
aws --profile boss rolesanywhere list-profiles \
  --query "profiles[?name=='trupryce-data-platform-backup'].[name,enabled,profileArn]" --output table
```

Confirm `enabled` reads `True` before continuing.

### 1.4 Configure the VPS-local backup profile

On the runtime host. The existing data profile is `trupryce-data-vps`; the new one is `trupryce-backup`. Both use `credential_process`, and neither stores a key:

```ini
# ~/.aws/config, mode 0600
[profile trupryce-data-vps]
region = us-east-1
credential_process = /usr/local/bin/aws_signing_helper credential-process --certificate /etc/trupryce/aws/trupryce-data-platform-vps.pem --private-key /etc/trupryce/aws/trupryce-data-platform-vps.key --trust-anchor-arn arn:aws:rolesanywhere:us-east-1:099427795947:trust-anchor/63c0a64e-843d-4603-9f55-0ddc7045ecaa --profile-arn <DATA_PROFILE_ARN> --role-arn arn:aws:iam::099427795947:role/trupryce-data-platform-vps

[profile trupryce-backup]
region = us-east-1
credential_process = /usr/local/bin/aws_signing_helper credential-process --certificate /etc/trupryce/aws/trupryce-data-platform-vps.pem --private-key /etc/trupryce/aws/trupryce-data-platform-vps.key --trust-anchor-arn arn:aws:rolesanywhere:us-east-1:099427795947:trust-anchor/63c0a64e-843d-4603-9f55-0ddc7045ecaa --profile-arn <BACKUP_PROFILE_ARN> --role-arn arn:aws:iam::099427795947:role/trupryce-data-platform-backup
```

There must be no `~/.aws/credentials` file and no `aws_access_key_id` anywhere. If you find yourself creating one, stop.

### 1.5 Verify the isolation, from the runtime host

Four assertions. The third and fourth are the ones that actually prove separation, and both must be **run**, not assumed:

```bash
# 1. the backup identity resolves to the backup role
aws --profile trupryce-backup sts get-caller-identity --query Arn --output text
#    expect: .../assumed-role/trupryce-data-platform-backup/...

# 2. the backup identity can reach the backup bucket
aws --profile trupryce-backup s3 ls s3://trupryce-property-tax-backups/

# 3. the data identity CANNOT reach the backup bucket
aws --profile trupryce-data-vps s3 ls s3://trupryce-property-tax-backups/
#    expect: AccessDenied

# 4. the backup identity CANNOT reach the source-data bucket
aws --profile trupryce-backup s3 ls s3://trupryce-property-tax-data/
#    expect: AccessDenied
```

Recorded results are in [Part 5](#part-5--recorded-evidence).

### 1.6 Bucket hardening is not verifiable from the runtime host

The backup role is denied `s3:GetBucketPolicy`, `s3:GetBucketVersioning`, `s3:GetEncryptionConfiguration`, `s3:GetBucketPublicAccessBlock`, `s3:GetLifecycleConfiguration`, and `s3:GetBucketOwnershipControls` — correct least privilege for a role that only reads and writes objects, and it means hardening must be verified with `--profile boss`:

```bash
for check in get-public-access-block get-bucket-versioning get-bucket-encryption \
             get-bucket-ownership-controls get-bucket-lifecycle-configuration get-bucket-policy; do
  printf '== %s\n' "$check"
  aws --profile boss s3api "$check" --bucket trupryce-property-tax-backups
done
```

Re-run this after any bucket change. A backup repository whose public-access block was removed is not detectable from the host that writes to it.

## Part 2 — pgBackRest and WAL operation

### 2.1 Host prerequisites — do these first

On a fresh host, in this order. Each one is a prerequisite of the next, and skipping any of them fails later in a way that looks like a credential problem rather than a missing step.

```bash
# 1. the signing helper the HOST's AWS profiles invoke.
#    The PostgreSQL image ships its own copy; ~/.aws/config does not use that one.
sudo ./infra/scripts/install-signing-helper.sh

# 2. non-secret runtime configuration and the Bitwarden bootstrap
./infra/scripts/bootstrap-env.sh
#    then edit infra/.env: certificate paths for THIS host and all three ARNs.
#    bootstrap-env.sh prints exactly which values still need attention.

# 3. certificate group, file modes, and identity.env -- derived from infra/.env
sudo ./infra/scripts/install-certificate-identity.sh
```

Step 3 is the gate: it refuses to run while any identity value is unset, and refuses to adopt a GID that already belongs to another group. Nothing below will archive until it has succeeded.

### 2.2 Secrets and configuration

The cipher passphrase is a Bitwarden secret in the `tax-platform` project:

```bash
BWS_ACCESS_TOKEN=… ./infra/scripts/generate-runtime-secrets.sh --bws "$BWS_PROJECT_ID"
```

**Losing `PGBACKREST_CIPHER_PASS` makes every existing backup permanently unreadable.** It is recovery-critical in a way the database passwords are not: rotating it does not re-encrypt what is already in S3, so the old value stays required for every backup taken under it. It is escrowed under [ADR-0003](../decisions/0003-bitwarden-environment-secret-recovery.md).

Everything else is non-secret configuration in `infra/.env` — the certificate paths and the three ARNs. See `infra/.env.example`.

### 2.3 Enable archiving

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

### 2.4 Schedule

The committed units are **templates**. A durable unit must not carry one host's operator account or home directory, or a rebuilt VPS inherits a path that does not exist there and the timer fails at its first fire — silently, because a timer whose service cannot start is not a visible outage.

```bash
sudo SERVICE_USER=<runtime-user> ./infra/scripts/install-systemd-units.sh
systemctl list-timers 'pgbackrest-*'
```

The installer resolves the service user, the repository path, and the Docker group; creates the certificate group at the GID Compose passes as a supplementary group; refuses to continue if any placeholder survives substitution; and **checks** that the service user can already reach the Docker socket rather than granting it — Docker group membership is root-equivalent and is an operator decision, not a side effect of installing a timer.

Both timers are `Persistent=true`, so a run missed while the host was down fires at boot rather than waiting for the next window. That matters most for the weekly full: without it, a host down over a Sunday leaves the differentials with no base inside the retention window. The differential unit `Conflicts` with the full so the two never run together.

The units select the container by Compose label, not by ID or name, because an ID changes on every recreate and a unit pinned to one keeps running while protecting nothing.

### 2.5 Routine checks

```bash
./infra/scripts/pgbackrest-backup.sh info     # backup set, WAL range, sizes
./infra/scripts/pgbackrest-backup.sh check    # archive + repository reachable
docker exec <container> psql -U platform_admin -c \
  "SELECT archived_count, failed_count, last_archived_time FROM pg_stat_archiver"
```

`failed_count` rising with `last_archived_time` stalling is the signature of a broken archive. Alerting on it belongs to the unimplemented "Backup and recovery observability" requirement; until then it is a manual check.

### 2.6 Failure mode: WAL accumulation

If archiving fails, PostgreSQL keeps every unarchived segment. `pg_wal` grows until the root disk fills, and PostgreSQL stops when it does — an outage caused by the backup system, not prevented by it.

```bash
docker exec <container> du -sh /var/lib/postgresql/data/pg_wal
docker exec <container> ls /var/spool/pgbackrest/archive/platform/out | head
```

Fix the cause and drain with `pgbackrest --stanza=platform archive-push` before the disk fills. Do **not** delete WAL segments by hand: a segment removed before it reaches S3 is a permanent hole in the recovery timeline, and every point after it becomes unreachable.

### 2.7 Certificate renewal — due before 2026-11-17

The workload certificate was issued 2026-08-19 for 90 days. When it expires, credential exchange fails, archiving stops, and the symptom is indistinguishable from a backup that quietly stopped running.

**Nothing alerts on this.** There is no renewal automation and no monitoring; this change exposes the signal, it does not watch it. Until observability exists, run the check:

```bash
./infra/scripts/check-certificate-expiry.sh
```

It prints the not-after date and days remaining, and exits non-zero inside the warning window so it is usable from a timer or a CI job later. Manually, the same fact:

```bash
openssl x509 -in /etc/trupryce/aws/trupryce-data-platform-vps.pem -noout -enddate -subject
```

Renewing: issue a new leaf from the same CA with the same CN, replace the `.pem` and `.key` in `/etc/trupryce/aws/`, re-apply the group and mode contract from [§2.8](#28-certificate-directory-permissions-and-identity), and restart PostgreSQL. The trust anchor and role need no change, because trust is anchored to the CA and the subject rather than to a particular certificate.

### 2.8 Certificate directory: permissions and identity

Two things live in `/etc/trupryce/aws` that no image can carry, and both are installed by one script.

**The permission contract.** `archive_command` runs as the container's `postgres` user (uid 999) and the key is owned by the operator on the host. A read-only mount gives immutability, not readability, so without a shared group the archive fails at runtime.

| Path | Owner | Group | Mode |
|---|---|---|---|
| `/etc/trupryce/aws` | operator | `TRUPRYCE_AWS_GID` (2000) | `0750` |
| `trupryce-data-platform-vps.key` | operator | `TRUPRYCE_AWS_GID` | `0640` |
| `trupryce-data-platform-vps.pem` | operator | `TRUPRYCE_AWS_GID` | `0644` |
| `root-ca.pem` | operator | `TRUPRYCE_AWS_GID` | `0644` |
| `identity.env` | operator | `TRUPRYCE_AWS_GID` | `0640` |

The group must also exist **inside the image** with `postgres` as a member — see [§2.9](#29-why-group_add-is-not-enough).

**`identity.env`.** The signing wrapper reads its identity from this file when the environment does not carry it; environment takes precedence where set.

It is worth being accurate about why it exists, because an earlier draft of this runbook was not. It was introduced on the theory that the asynchronous archive worker runs with a cleaned environment. Instrumenting the wrapper during the actual failure disproved that — five `TRUPRYCE_AWS_*` variables were present and the supplementary group was missing. The file is kept because it makes a clean host reproducible from one non-secret source, and because it removes an assumption about what a daemonized worker inherits.

It contains **only** non-secret values — the certificate and key paths and the three Roles Anywhere ARNs. It holds no cipher passphrase, no Bitwarden token, and no AWS credential: temporary credentials are exchanged per invocation from the certificate, and the passphrase comes from Bitwarden. The installer refuses to write any of those names.

Install both with one command, run as root on the host:

```bash
sudo ./infra/scripts/install-certificate-identity.sh
```

Values are **derived from `infra/.env`**, the reviewed non-secret host configuration, so an ARN is changed in one place and re-applied by re-running the script. There is no hand-edited duplicate to drift. The script creates the certificate group if absent, applies every mode in the table, and fails closed if the private key ends up world-accessible.

Verify from the container that will actually use it, not from the host:

```bash
docker exec --user postgres <postgres-container> \
  test -r /etc/trupryce/aws/trupryce-data-platform-vps.key && echo readable
docker exec --user postgres <postgres-container> \
  env -i /usr/local/bin/pgbackrest-aws-signing >/dev/null && echo "credentials exchanged with no environment"
```

The `env -i` form proves the wrapper does not depend on inherited environment at all. The `test -r` check above it is the one that reproduces the failure actually observed.

### 2.9 Why `group_add` is not enough

Compose's `group_add` sets supplementary groups on the container's *initial* process. The postgres entrypoint starts as root and switches to the `postgres` user, re-deriving supplementary groups from the image's `/etc/group` and discarding everything Docker added.

The consequence is asymmetric and misleading: `docker exec --user postgres` keeps the Docker-added group and reads the key, so every check an operator runs by hand succeeds, while the archiver — a child of the postmaster — runs without it and cannot read the certificate at all.

So the group is created in the image, with `postgres` as a member, at the GID Compose passes as a build argument:

```dockerfile
ARG TRUPRYCE_AWS_GID=2000
RUN groupadd --gid "${TRUPRYCE_AWS_GID}" trupryce-certificates \
 && usermod --append --groups trupryce-certificates postgres
```

`group_add` is retained so `docker exec` behaves the same way, but the image membership is what makes archiving work.

## Part 3 — Point-in-time restore

### The rule

**Never restore over `postgres-data`.** A restore is a hypothesis about what went wrong; testing it by overwriting the only surviving copy of production turns a recoverable incident into an unrecoverable one. `pgbackrest-restore.sh` refuses the production volume by name and refuses any Compose-managed volume by label, so the rule is enforced rather than remembered.

### 3.1 Choose a target

```bash
./infra/scripts/pgbackrest-backup.sh info
```

The target must lie inside the WAL range of a full backup that precedes it.

### 3.2 Restore

```bash
./infra/scripts/pgbackrest-restore.sh --target "2026-08-27 01:23:45+00"
```

That single command creates a temporary volume, restores into it, and starts an isolated cluster on `127.0.0.1:55432`. Add `--keep` to leave both in place for inspection; without it they are removed on exit.

**The passphrase is never typed.** The wrapper resolves `PGBACKREST_CIPHER_PASS` from Bitwarden itself and hands it to Docker by reference as `-e PGBACKREST_REPO1_CIPHER_PASS`, so the value never appears in argv, in shell history, or in a process listing. Do not write the literal form:

```bash
# Never do this. The value that makes every backup in S3 readable would land in
# shell history and in `ps` output for the duration of the restore.
docker run -e PGBACKREST_REPO1_CIPHER_PASS=<the-passphrase> ...
```

The Bitwarden access token stays host-only. It is read from `infra/.bws.env` on the host and never enters Compose interpolation or any container.

### 3.3 Why the recovered container needs the certificate too

The first version of this runbook gave the certificate and configuration to the *restore* step and then started the recovered cluster with only the restored volume. That is not enough.

Reaching the requested timestamp requires PostgreSQL to run `restore_command` — `pgbackrest archive-get` — during startup, to fetch the WAL segments between the base backup and the target. That needs working S3 credentials **inside the recovering container**. Without them PostgreSQL restores the base backup, fails to fetch WAL, and stops short of the target while appearing to have succeeded.

So the isolated cluster starts with all of:

| | |
|---|---|
| image | the same pinned `property-tax-postgres:16.11` |
| data | an isolated temporary volume, never `postgres-data` |
| certificate | `/etc/trupryce/aws` mounted read-only, plus the certificate GID |
| identity | the backup trust anchor, profile, and role ARNs |
| passphrase | from Bitwarden, by reference |
| network | `127.0.0.1` on a non-production port |

### 3.4 What the restored cluster must prove

Six assertions. The first five are integrity; the sixth is what makes it *point-in-time* rather than merely a restore:

| # | Assertion |
|---|---|
| 1 | `property_tax` database exists |
| 2 | `airflow` database exists |
| 3 | all four runtime roles exist |
| 4 | `pg_is_in_recovery()` is false after promotion |
| 5 | the marker committed **before** the target is present |
| 6 | the marker committed **after** the target is **absent** |

Assertion 6 cannot be faked. A restore that simply replays all available WAL satisfies 1–5 too, so proving only those proves that a restore happened — not that the target was honoured.

The wrapper prints all six, plus the restored volume name and proof that the production volume was not among the container's mounts.

### 3.5 Creating the markers

```sql
CREATE TABLE IF NOT EXISTS public.recovery_marker (
    state text PRIMARY KEY, recorded_at timestamptz NOT NULL DEFAULT now());
INSERT INTO public.recovery_marker(state) VALUES ('before');
SELECT pg_switch_wal();
-- wait past the boundary, choose a target timestamp here
INSERT INTO public.recovery_marker(state) VALUES ('after');
SELECT pg_switch_wal();
```

Forcing a WAL switch after each marker is what puts the segment containing it into S3; without it the marker is committed locally but not yet recoverable, and the exercise measures nothing.

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

| Component | Recreated by | Why it must be new |
|---|---|---|
| Leaf certificate and private key | issue from the CA **on the new host** | A private key that exists in two places has two ways to leak, and revoking one host revokes the other |
| Host-specific certificate CN authorization | trust-policy edit, `--profile boss` | The trust policy pins a CN; a new host is a new subject |
| Certificate GID, file modes, and `identity.env` | `sudo ./infra/scripts/install-certificate-identity.sh` | Host-local ownership; `identity.env` is derived from that host's `infra/.env` |
| Local AWS CLI profiles (`~/.aws/config`) | hand-written per [§1.4](#14-configure-the-vps-local-backup-profile) | Points at host-local certificate paths |
| `infra/.env` | `./infra/scripts/bootstrap-env.sh` | Holds this host's paths, bind addresses, and ARNs |
| Bitwarden bootstrap (`infra/.bws.env`) | `./infra/scripts/bootstrap-env.sh` | The access token is host-only and never leaves it |
| Docker runtime and images | `compose-with-bitwarden.sh build` | Host software, rebuilt from the repository |
| systemd units | `sudo SERVICE_USER=... ./infra/scripts/install-systemd-units.sh` | Resolve this host's service user and repository path |
| Restored PostgreSQL volume | the restore itself | Created by `pgbackrest-restore.sh` |

Nothing in that column is copied from the retired host. Every row is a command run on the new one.

### Procedure

Top to bottom on the new host. Each step depends on the one above it, and the ordering is the point: the identity must exist before anything tries to archive, and the isolation must be proven before anything is restored.

```text
 1  install host dependencies         Docker Engine + Compose V2, bws, git, curl
 2  install pinned signing helper     sudo ./infra/scripts/install-signing-helper.sh
 3  bootstrap configuration           ./infra/scripts/bootstrap-env.sh
 4  fill + validate host identity     edit infra/.env: certificate paths for THIS
                                      host, and all three ARNs
 5  issue the Hostinger certificate   new key generated ON this host, signed by the
                                      existing CA as CN=trupryce-data-platform-hostinger
 6  authorize the new subject         add that CN to both trust policies, --profile boss
 7  install identity + permissions    sudo ./infra/scripts/install-certificate-identity.sh
 8  configure local AWS profiles      ~/.aws/config: trupryce-data-vps, trupryce-backup
 9  prove identity isolation          STS + the four S3 assertions from §1.5
10  build the PostgreSQL image        ./infra/scripts/compose-with-bitwarden.sh build postgres
11  restore into a fresh volume       ./infra/scripts/pgbackrest-restore.sh --target ...
12  verify the six assertions         before present, after absent, roles, databases
13  start the restored cluster        promote and point the runtime at it
14  verify asynchronous archiving     force a WAL switch, confirm it reaches S3
15  install and prove the timers      sudo SERVICE_USER=... ./infra/scripts/install-systemd-units.sh
                                      then systemctl start pgbackrest-diff.service
16  cut over
17  revoke the Akamai identity        remove its CN from both trust policies, revoke the
                                      certificate at the CA, destroy the key on the old host
```

**Step 2 is easy to miss.** The PostgreSQL image installs its own signing helper for pgBackRest, but `~/.aws/config` invokes `/usr/local/bin/aws_signing_helper` on the *host*. Without step 2 every `aws --profile trupryce-backup …` command fails, including the step 9 checks that gate everything after them.

**Step 4 is not optional.** `bootstrap-env.sh` copies a template that carries a deliberately blank `TRUPRYCE_AWS_PROFILE_ARN` and certificate paths named for the Akamai host. It prints exactly which values need attention; step 7 refuses to run until they are set.

**Step 5 generates the key on the new host.** Do not copy `trupryce-data-platform-vps.key`, and do not reuse it under a new filename.

**Step 6 may authorize both identities at once.** During migration the old host may still be archiving while the new one restores:

```json
"StringEquals": {
  "aws:PrincipalTag/x509Subject/CN": [
    "trupryce-data-platform-vps",
    "trupryce-data-platform-hostinger"
  ]
}
```

**Step 17 is the one that gets skipped.** A migration is not finished while a decommissioned machine can still write to the backup repository. Revoke *after* step 12 has passed, never before — revoking early leaves no working identity if the restore fails.

## Part 5 — Recorded evidence

Exercised on the Akamai host on 2026-08-27 against the live cluster. Recorded from actual command output; no credential, certificate material, passphrase, or production row is reproduced here.

### Identity isolation

| Assertion | Result |
|---|---|
| `trupryce-backup` STS identity | `arn:aws:sts::099427795947:assumed-role/trupryce-data-platform-backup/…` |
| `trupryce-backup` lists the backup bucket | allowed |
| `trupryce-data-vps` on the backup bucket | **AccessDenied** |
| `trupryce-backup` on `s3://trupryce-property-tax-data/` | **AccessDenied** |
| `trupryce-backup` outside `pgbackrest/platform/` | **AccessDenied** |
| `trupryce-backup` PUT/GET/LIST/DELETE inside its prefix | allowed (delete is required for retention expiry) |
| Long-lived keys anywhere on the host | none; no `~/.aws/credentials`, no `aws_access_key_id` |

Both directions were tested rather than inferred.

### Repository proof

| Step | Result |
|---|---|
| Private key readable by container `postgres` | yes — uid 999, groups 999, 101, 2000 |
| Credential exchange as `postgres` | exit 0, temporary `ASIA…` credentials, all fields present |
| `stanza-create` | completed successfully |
| `check` | completed successfully, WAL segment `000000010000000000000043` archived |
| WAL reaches S3 | segment `000000010000000000000044` present, **3.61s** after `pg_switch_wal()` |
| First full backup | label **`20260827-005558F`**, 40.8 MB database, 4.7 MB in repository |
| `info` | `status: ok`, `cipher: aes-256-cbc` |
| Backup objects in S3 | 1937 objects; `backup.manifest` begins `Salted__`, so the repository is encrypted before it leaves the host |
| `pg_stat_archiver` | `archived=9 failed=0` |

### Point-in-time restore

| | |
|---|---|
| Backup restored from | `20260827-005558F` |
| Target timestamp | `2026-08-27 00:57:48+00` |
| `before` committed | 00:57:35.114187+00 |
| `after` committed | 00:57:53.583189+00 |
| Measured RPO | **3.61s** from `pg_switch_wal()` to the segment being present in S3, archiving healthy |
| Measured RTO | **56s** end to end — restore, start, replay to target, promote, assert |

All six assertions passed, through the committed wrapper:

```text
  1. property_tax database exists  : true
  2. airflow database exists       : true
  3. runtime roles present (want 4): 4
  4. pg_is_in_recovery() is false  : true
  5. marker before present         : true
  6. marker after ABSENT           : true
```

Isolation: restored into `pitr-verify-20260827010147-…`; `property-tax-platform_postgres-data` was **not** among the container's mounts; published on `127.0.0.1:55432` only. Container and volume removed afterwards, and the disposable marker table dropped from production.

### Backup failure no longer takes the database with it

The restart loop above was possible because PostgreSQL ran as PID 1, so a daemonized pgBackRest worker was orphaned onto the postmaster itself. Documenting that mechanism does not remove it: any future credential, network, or S3 failure that leaves an async worker exiting nonzero would do the same thing.

`init: true` on the PostgreSQL service (and `--init` on the isolated recovery containers) puts `docker-init` at PID 1 instead:

```text
before                     after
  PostgreSQL (PID 1)         docker-init (PID 1)
    └── orphaned worker        ├── PostgreSQL
                               └── orphaned worker
```

Proven behaviourally, not by reading the YAML. With `init: true` in place, the private key was made unreadable to the container — reproducing the exact failure that caused the original loop — and WAL was forced:

| | Before (`PostgreSQL` as PID 1) | After (`docker-init` as PID 1) |
|---|---|---|
| async worker | `ERROR: [103] … terminated unexpectedly [2]` | `ERROR: [103] … terminated unexpectedly [2]` |
| archiver | failing | `failed=3` |
| postmaster restarts | every ~10 s | **0** |
| `reinitializing` events | continuous | **0** |
| container restart count | — | **0** |
| accepting queries | intermittently | **yes, throughout** |

Restoring the key drained the pending segment to S3 in **62 s** with no intervention, and `check` passed again. The archive subsystem can now fail, back up, and be repaired without touching database availability — which is the property that makes an archive failure an operational annoyance rather than an outage.

### What this exercise cost, and what it caught

Four defects surfaced only by running it, none of which any static check would have found:

1. **`PGBACKREST_*` is pgBackRest's own option namespace.** Identity variables named `PGBACKREST_AWS_…` were parsed as pgBackRest options, rejected as invalid, and warned about on every command. Renamed to `TRUPRYCE_AWS_…`.
2. **pgBackRest connects as the OS user it runs as.** This cluster's superuser is `platform_admin`, so `stanza-create` failed with `role "postgres" does not exist` until `pg1-user` was set.
3. **Compose `group_add` does not survive the entrypoint.** The postgres entrypoint re-derives supplementary groups from the image's `/etc/group` when it switches from root, dropping what Docker added. `docker exec --user postgres` kept the group and read the key, so every hand-run check passed — while the archiver ran without it and could not read the certificate. Fixed by creating the group inside the image with `postgres` as a member. The resulting archive failure **restarted the cluster repeatedly**; the mechanism is [documented below](#why-a-failing-archive-restarted-the-cluster), and it is not the one you would guess.
4. **Compose bakes project and service labels into the image.** Every container started from it inherits them, so the backup script's label selector matched both the production cluster and the temporary restore cluster. Its refuse-on-ambiguity guard turned that into a clean failure rather than a backup of the wrong cluster; the selector now also requires `com.docker.compose.oneoff=False`, and the restore container overwrites the inherited labels.

Points 3 and 4 are the argument for this exercise being mandatory rather than optional: a green `check` and a successful backup were both true while the cluster was restarting in a loop, and neither would have revealed it.

### Why a failing archive restarted the cluster

The obvious explanation is wrong, and it is worth being precise because the wrong version leads an operator to the wrong fix.

**An ordinary nonzero `archive_command` exit does not restart anything.** PostgreSQL logs `archive command failed with exit code N` and retries, as PostgreSQL 16 documents. Verified in isolation against `postgres:16.11`:

| Experiment | Result |
|---|---|
| `archive_command=exit 103` | 9 archive failures, **0** postmaster restarts |
| `archive_command` killed by `SIGQUIT` | archiver `FATAL ... exit code 131`, **0** postmaster restarts |
| `archive_command` spawns a detached child that exits 103, parent returns 0 | **1 postmaster restart**, reproducing the observed lines verbatim |

The third is what happened. `archive-async=y` makes pgBackRest daemonize a worker; the worker is orphaned and reparented to PID 1, and in this image PID 1 **is the postmaster**. The postmaster reaps a child it does not recognise, treats the nonzero exit as a crashed backend, and performs full crash recovery:

```text
[1] LOG:  server process (PID 65) exited with exit code 103
[1] LOG:  terminating any other active server processes
[1] LOG:  all server processes terminated; reinitializing
```

The archiver's `archive command was terminated by signal 3: Quit` appears 150 ms later and is collateral from that shutdown, not its cause — reading it as the cause is what sends you looking for a signal source that does not exist.

Practical consequence for a rebuild: any archive-side failure that leaves a daemonized pgBackRest worker exiting nonzero will present as cluster restarts rather than as archive errors, for as long as the postmaster runs as PID 1.

## Related

- [Operations](README.md)
- [ADR-0010: Replaceable local storage and a segregated S3 backup repository](../decisions/0010-replaceable-local-storage-and-s3-backup-repository.md)
- [ADR-0002: S3 durable recovery boundary](../decisions/0002-s3-durable-recovery-boundary.md)
- [ADR-0003: Bitwarden environment-secret recovery](../decisions/0003-bitwarden-environment-secret-recovery.md)
- [Runtime infrastructure](../../infra/README.md)
- [PostgreSQL schema and migrations](../../infra/postgres/README.md)
