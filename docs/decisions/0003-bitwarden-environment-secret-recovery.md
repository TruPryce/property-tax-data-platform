# ADR-0003: Bitwarden Environment-Secret Recovery

## Status

Accepted on 2026-07-16.

## Context

A clean-host recovery requires database, S3, Airflow, API, TLS, and administrative credentials without depending on files from the failed VPS. The repository is public, and neither Git nor ordinary S3 objects are an acceptable secret escrow mechanism.

## Decision

Environment-secret recovery material will be maintained in the hosted Bitwarden vault at [vault.bitwarden.com](https://vault.bitwarden.com). Deployment injects the minimum required values into each runtime without committing them to Git, copying them into documentation, or embedding them in S3 manifests and backups.

Airflow connections and runtime secret files will be generated from reviewed deployment inputs. Local secret files must have restrictive permissions, remain ignored by Git, and be replaceable from Bitwarden during a clean-host rebuild.

## Alternatives

- Repository `.env` files were rejected because the repository is public and Git history is durable.
- Plaintext secret backups in S3 were rejected because data recovery credentials and application data would share a compromise path.
- Depending on secrets stored only on the VPS was rejected because it makes host loss unrecoverable.

## Consequences

- Bitwarden access, organization ownership, recovery access, and multi-factor authentication become disaster-recovery dependencies.
- Secret rotation must update both the running environment and the escrowed recovery record.
- Recovery exercises must prove that a new host can be configured without reading secrets from the old host.
- Machine-to-machine secret injection remains an implementation decision; this ADR selects the recovery system, not a specific runtime secrets agent.

## Related

- [Architecture decisions](README.md)
- [ADR-0002: S3 durable recovery boundary](0002-s3-durable-recovery-boundary.md)
- [Active OpenSpec design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md)
