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
- Run `make infra-check` and render the Compose configuration before publishing infrastructure changes.

## Related

- [Infrastructure overview](README.md)
- [Runtime operations contract](../openspec/changes/bootstrap-six-county-appraisal-platform/specs/platform-runtime-operations/spec.md)
- [Root agent guidance](../AGENTS.md)
