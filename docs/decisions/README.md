# Architecture Decisions

During the bootstrap change, normative behavior lives in the active [OpenSpec design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md) and capability specs. This directory records operator-approved architecture choices and their rationale. Implementation validation remains tracked in OpenSpec tasks.

An ADR records context, decision, alternatives, consequences, status, date, and related issue/OpenSpec change. Do not use ADRs as work intake or duplicate the task list.

| Decision | Status | Summary |
|---|---|---|
| [ADR-0001](0001-independent-akamai-runtime.md) | Accepted | Run the platform on its own Akamai Cloud VPS, database, Airflow, volume, and administrative network. |
| [ADR-0002](0002-s3-durable-recovery-boundary.md) | Accepted | Treat the VPS as replaceable and restore PostgreSQL, Bronze, exports, and logs from Amazon S3. |
| [ADR-0003](0003-bitwarden-environment-secret-recovery.md) | Accepted | Keep environment-secret recovery material in the hosted Bitwarden vault and out of Git and S3. |
| [ADR-0004](0004-consumer-neutral-appraisal-api.md) | Accepted | Serve Gold appraisal facts through a lightweight Python API owned by this platform. |
| [ADR-0005](0005-mode-aware-runner-kernel.md) | Accepted | Use a developer-tool kernel with immutable mode profiles while preserving the isolated packet reviewer. |
| [ADR-0006](0006-github-native-countyforge-control-plane.md) | Accepted | Use GitHub Actions, two trusted/target roots, and canonical bot-owned state for CountyForge commands. |

## Related

- [Documentation hub](../README.md)
- [Architecture](../architecture/README.md)
- [Contribution workflow](../../CONTRIBUTING.md)
- [Active OpenSpec design](../../openspec/changes/bootstrap-six-county-appraisal-platform/design.md)
- [CountyForge control-plane design](../../openspec/changes/add-github-run-control-plane/design.md)
