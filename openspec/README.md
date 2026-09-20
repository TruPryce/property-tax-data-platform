# OpenSpec

OpenSpec is the repository's requirements and implementation-planning system. GitHub Issues capture intake; accepted issues become OpenSpec changes before non-trivial implementation.

## Active Changes

- [`bootstrap-six-county-appraisal-platform`](changes/bootstrap-six-county-appraisal-platform/README.md) defines the repository foundation and initial six-county appraisal capability.
- [`add-application-port-boundary`](changes/add-application-port-boundary/proposal.md) defines the application ports for release ingestion.

## Accepted Specs and Archives

Completed capabilities live in [`specs/`](specs/). Their proposals, designs, delta specs, and completed task lists are preserved in dated directories under [`changes/archive/`](changes/archive/).

The [accepted runtime specification](specs/platform-runtime-operations/spec.md) includes the completed PostgreSQL recovery foundation. Remaining runtime requirements and unfinished implementation tasks stay in the active bootstrap change.

## Commands

```bash
openspec list
openspec status --change bootstrap-six-county-appraisal-platform
openspec validate bootstrap-six-county-appraisal-platform
openspec doctor
```

Run `openspec instructions <artifact> --change <name>` before authoring an artifact. Completed changes are archived only after their implementation tasks and repository checks pass.

## Related

- [Repository overview](../README.md)
- [Contribution workflow](../CONTRIBUTING.md)
- [Architecture](../docs/architecture/README.md)
