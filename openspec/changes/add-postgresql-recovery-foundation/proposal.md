## Why

The platform has no PostgreSQL recovery boundary. WAL is not archived, no physical backup exists, and the live `property_tax` and `airflow` databases exist only on one Docker named volume on one VPS root disk. ADR-0002 already decided that S3 — not the host — is the durable recovery boundary, and the accepted runtime contract already requires continuous WAL archiving, scheduled physical backups, and recorded point-in-time restores. None of it is implemented, and the provider-backup removal gate cannot open until it is.

The accepted contract also contains a storage statement that is now wrong in a way that blocks the work. `platform-runtime-operations` requires the runtime to use "a 250 GB attached volume", and ADR-0001 records the same figure. No such volume is attached. PostgreSQL runs on the root disk today, deliberately, and the operator has decided it stays there for this change. Implementing recovery without amending that sentence would either violate an accepted requirement or quietly restate it in code — so the smallest honest amendment comes first, in this change, reviewed rather than assumed.

## Outcome

State the durable storage boundary correctly, then implement it: local VPS storage is replaceable, attached Block Storage is an optional future capacity expansion, and encrypted S3 physical backups plus continuous WAL are the recovery boundary. Deliver a working pgBackRest repository reached by a dedicated, keyless backup identity, scheduled by the host, and prove it with an isolated point-in-time restore.

## Scope

- Originating issue: none; this is bootstrap task 5.7/5.8 foundation work and amends an active bootstrap delta.
- Affected capabilities: platform-runtime-operations (MODIFIED, ADDED)
- Affected decisions: ADR-0001 and ADR-0002 amended by a new ADR-0010

## The amendment, and why it is the smallest one

Three documents state the storage contract. Only the first is normative:

| document | text | disposition |
| --- | --- | --- |
| `platform-runtime-operations` "Independent platform runtime" | "…16 GB shared CPU memory, and a 250 GB attached volume" | **MODIFIED** — the capacity mandate is removed; local storage is replaceable and Block Storage is optional expansion |
| `platform-runtime-operations` "S3 durable recovery boundary" | "…the VPS and attached volume as replaceable" | **MODIFIED** — reworded to "every storage device local to it", so it no longer presumes an attached volume exists |
| ADR-0001, ADR-0002 | "an attached 250 GB volume"; "the database is expected on an attached volume" | **amended by ADR-0010**, with both statuses updated to point at it; the original text is left intact as the record of what was decided in July |

Nothing else in the accepted contract is touched. The existing "PostgreSQL point-in-time recovery", "Provider-backup removal gate", "Bitwarden secret recovery", and "Backup and recovery observability" requirements already say what this change implements, and are not modified.

Per-provider schedules, retention counts, bucket names, and role names are deliberately **absent** from the capability text. A promoted capability describes the system's final state; "four weekly full cycles on Akamai" is operational policy that changes without the contract changing, so it lives in the runbook and in `pgbackrest.conf`. The capability requires only that backups be scheduled under a documented retention policy, which it already did.

## What this change deliberately does not do

- **No Block Storage is provisioned and PGDATA is not moved.** PostgreSQL stays on the existing `postgres-data` Docker named volume. Moving it is a separate, reversible operational decision that the amended contract now permits either way.
- **No property-tax migrations are applied.** The five merged migrations in `infra/postgres/migrations/` remain unapplied to the live database. Proving recovery before loading data is the cheaper order, and the restore evidence is reviewed before schema work resumes.
- **No monitoring or alerting.** "Backup and recovery observability" stays unimplemented and unclaimed; this change delivers the signal sources it will later alert on, not the alerting.
- **No clean-host rebuild is performed.** The runbook documents the Hostinger procedure and the reuse/recreate boundary; exercising it is bootstrap task 5.9.

## Constraints

- The existing `trupryce-data-platform-vps` data role keeps its no-delete posture and gains nothing. Backup access is a separate role reached through a separate Roles Anywhere profile.
- No `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` is created, stored, or passed anywhere. Credentials are exchanged from the existing X.509 workload certificate through the existing trust anchor.
- Trust is bound to certificate subject: the backup role's trust policy restricts assumption to the existing trust anchor **and** `CN=trupryce-data-platform-vps`. A valid chain alone is not authority.
- `BWS_ACCESS_TOKEN` does not enter Compose interpolation or any container, unchanged from the existing boundary. The pgBackRest cipher passphrase is a Bitwarden runtime secret injected by the existing wrapper.
- Certificates, private keys, and the cipher passphrase are never committed, never baked into an image, and never printed by a script.
- Backups are scheduled by systemd on the host, never by Airflow, because Airflow's own metadata database is one of the protected databases.
- pgBackRest is pinned to 2.59.1 from PGDG. Debian Bookworm's stock 2.45 is not used.
- The restore exercise runs against a temporary Docker volume on a loopback-only port and never touches `postgres-data`.

## Non-goals

- Bronze artifact storage, versioned exports, and Airflow remote logging to S3, which are separate parts of bootstrap 5.7.
- Alerting, metrics, and dashboards.
- Disabling the provider backup add-on, which needs the clean-host rebuild in 5.9 as well.
- Managed PostgreSQL, replication, or high availability.

## Decisions

- **D1** — The storage contract states replaceability rather than capacity. The accepted requirement named a device and a size; both are properties of a purchase order, not of the system's behaviour, and neither is verifiable from the repository. The amended requirement states what must remain true — that no requirement depends on a specific local device, mount point, or capacity — and explicitly permits Block Storage as optional expansion so a later capacity decision needs no further amendment.
- **D2** — Backup access is a distinct IAM role, not a widened data role. Granting `s3:DeleteObject` to `trupryce-data-platform-vps` so it could expire its own backups would give the identity that handles untrusted county downloads the authority to destroy the recovery material protecting against that same download. The two identities are separated by construction: `trupryce-data-platform-backup` holds the backup prefix and nothing else, and the data role is not modified.
- **D3** — Credentials are exchanged per invocation through `aws_signing_helper credential-process`, and pgBackRest consumes them with `repo1-s3-key-type=process`. The wrapper is a fixed-argument shell script that adds no parsing and passes the helper's JSON through unchanged, so a malformed or expired response surfaces as pgBackRest's own error rather than as a wrapper bug. No credential is ever written to disk.
- **D4** — pgBackRest 2.59.1 is installed from the PGDG apt repository that the official `postgres:16.11-bookworm` image already configures, pinned to the exact package version `2.59.1-1.pgdg12+1`. Bookworm's stock 2.45 predates the `process` key type this change depends on. Installing into the PostgreSQL image rather than the host is what lets `archive_command` reach the binary, and keeps the host free of a package this change would otherwise have to maintain.
- **D5** — The repository is encrypted with `repo1-cipher-type=aes-256-cbc` and a passphrase held in Bitwarden as `PGBACKREST_CIPHER_PASS`, injected as `PGBACKREST_REPO1_CIPHER_PASS`. pgBackRest reads every option from a `PGBACKREST_`-prefixed environment variable, so the passphrase never appears in `pgbackrest.conf` and the conf file stays committable. Losing the passphrase makes every backup unrecoverable, which is why it is escrowed under ADR-0003 rather than generated on the host.
- **D6** — Timers locate the PostgreSQL container by Compose label, not by a generated container ID or name. A recreated container changes its ID and can change its name suffix; a unit that hardcodes either fails silently the first time the stack is rebuilt, which is exactly when someone stops watching. The label selector is the stable identity Compose guarantees.
- **D7** — `archive_timeout` is 300 seconds, which bounds the recovery point at five minutes of wall-clock during idle periods rather than at five minutes of write volume. This satisfies ADR-0002's "maximum five-minute WAL archive interval" and is the figure the measured RPO in the restore exercise is compared against.

## Unresolved decisions

- **The AWS-side bootstrap requires administrative credentials this host does not hold.** The `trupryce-data-platform-vps` role is correctly scoped as a data role: `iam:*`, `rolesanywhere:*`, and `s3:HeadBucket` against the backup bucket are all denied from the runtime host. Creating the backup bucket, the backup role and its trust policy, and the backup Roles Anywhere profile is therefore an operator action performed with administrative credentials, documented step by step in the runbook. The repository work does not depend on it, but the operational proof does.
- **The Akamai workload certificate expires 2026-11-17.** It was issued 2026-08-19 for 90 days. Renewal is not automated and nothing currently alerts on it. Recorded here because a backup identity that stops authenticating is indistinguishable from a backup that stopped running, and the observability requirement that would catch it is not implemented by this change.
