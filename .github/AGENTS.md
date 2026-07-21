# GitHub Control-Plane Agent Guide

## Scope

`.github/` owns repository intake forms and thin GitHub Actions orchestration. CountyForge parsing, authorization, idempotency, state transitions, request construction, and rendering belong in `tools/countyforge-github/`, not workflow YAML.

## Rules

- Treat issue/comment text, branch names, pull-request files, and all target-revision content as untrusted data.
- Use `issue_comment: created`; never combine `pull_request_target`, a target checkout, and a secret-bearing step.
- Pin every action to a full commit SHA and declare least-privilege job permissions.
- Keep trusted default-branch tooling and immutable target data in separate roots.
- Packet preparation receives no provider secret and executes no target script, hook, test, package, Make target, workflow, or binary.
- Provider jobs never check out a target worktree and receive exactly one selected provider secret on the invocation step.
- Do not add broad contents/package/deployment/OIDC/security-event write access or code-push credentials.
- The sole v1 exception is the trusted `countyforge-run.yml` `publish` job for deterministic planning-branch and draft-PR publication required by Issue #6. It receives no provider secret and no model or target-revision execution; every other job remains forbidden from write access.
- Plan, implement, fix, and validate remain fail-closed until their owning issue and OpenSpec change add separate executors. The Issue #6 planning profile is the explicitly approved read-only model exception.

## Validation

```bash
make countyforge-workflow-policy-tests
make runner-contract-tests
```

## Related

- [Root agent guidance](../AGENTS.md)
- [Control-plane engineering guide](../docs/engineering/countyforge-github-control-plane.md)
- [GitHub operations](../docs/operations/countyforge-github-operations.md)
