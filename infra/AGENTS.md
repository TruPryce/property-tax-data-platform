# Infrastructure Agent Guide

## Rules

- Keep image versions explicit and validate upgrades before changing them.
- Never commit credentials, generated `.env` files, private keys, or runtime data.
- Keep the Bitwarden access token host-only; it must never enter Compose interpolation or a container environment.
- Bind PostgreSQL and Airflow administration to loopback or the approved Tailscale address.
- Keep database bootstrap limited to databases and least-privilege roles; application schema belongs in migrations.
- Keep county parsing, business rules, and SQL out of Compose and Dockerfiles.
- Use a one-shot Airflow initialization service; runtime services must not race to migrate metadata.
- Resolve runtime secrets through the read-only Bitwarden machine account wrapper.
- Schedule backups from the host supervisor, never from Airflow: Airflow's metadata database is one of the databases a backup protects.
- Never grant object deletion to the source-data AWS role, and never widen it to cover the backup repository.
- Never create, store, or pass an `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY`; durable-storage access is exchanged from the workload certificate.
- Mount certificates and private keys read-only; never copy them into an image layer.
- Run `make infra-check` and render the Compose configuration before publishing infrastructure changes.

## Related

- [Infrastructure overview](README.md)
- [PostgreSQL migration agent guidance](postgres/AGENTS.md)
- [PostgreSQL backup and recovery runbook](../docs/operations/postgresql-recovery.md)
- [Runtime operations contract](../openspec/changes/bootstrap-six-county-appraisal-platform/specs/platform-runtime-operations/spec.md)
- [Root agent guidance](../AGENTS.md)
