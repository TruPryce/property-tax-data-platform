# OpenSpec

OpenSpec is the repository's requirements and implementation-planning system. GitHub Issues capture intake; accepted issues become OpenSpec changes before non-trivial implementation.

## Active Changes

- [`bootstrap-six-county-appraisal-platform`](changes/bootstrap-six-county-appraisal-platform/README.md) defines the repository foundation and initial six-county appraisal capability.

## Accepted Specs and Archives

Completed capabilities live in [`specs/`](specs/). Their proposals, designs, delta specs, and completed task lists are preserved in dated directories under [`changes/archive/`](changes/archive/).

The accepted release-ingestion boundary is split across
[`application-port-boundary`](specs/application-port-boundary/spec.md),
[`source-registry-and-discovery`](specs/source-registry-and-discovery/spec.md),
[`acquisition-manifest-index`](specs/acquisition-manifest-index/spec.md),
[`processing-run`](specs/processing-run/spec.md), and
[`run-bound-quality-and-publication`](specs/run-bound-quality-and-publication/spec.md). Canonical
loading and processing-run values remain in their separately promoted capabilities.

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
