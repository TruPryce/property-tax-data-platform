# OpenSpec

OpenSpec is the repository's requirements and implementation-planning system. GitHub Issues capture intake; accepted issues become OpenSpec changes before non-trivial implementation.

## Active Change

- [`bootstrap-six-county-appraisal-platform`](changes/bootstrap-six-county-appraisal-platform/README.md) defines the repository foundation and initial six-county appraisal capability.

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
