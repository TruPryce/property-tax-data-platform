# OpenSpec Agent Guide

## Scope

This area owns accepted requirements, change designs, and task checklists. It does not own runtime documentation or implementation code.

## Rules

- Run `openspec status --change <name> --json` and the relevant `openspec instructions` command before editing an artifact.
- Use one spec directory per capability named in the proposal.
- Requirements use SHALL/MUST and four-hash `#### Scenario` headings with WHEN/THEN steps.
- Designs record decisions, rejected alternatives, risks, migration, and unresolved questions.
- Tasks use `- [ ] X.Y` checkboxes and are updated immediately after verified completion.
- Non-bootstrap changes reference their originating GitHub Issue before implementation.
- Do not archive changes with incomplete implementation unless the user explicitly accepts the warning.

## Validation

```bash
openspec validate <change-name>
openspec doctor
```

## Related

- [OpenSpec overview](README.md)
- [Contribution workflow](../CONTRIBUTING.md)
