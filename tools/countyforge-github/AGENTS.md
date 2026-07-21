# CountyForge GitHub Adapter Agent Guide

## Scope

This package owns GitHub command parsing, authorization decisions, immutable trigger/request construction, semantic idempotency, canonical state, leases, cancellation/retry policy, rendering, observability, and GitHub API ports. It may depend on `countyforge-runner`; the kernel must remain GitHub-neutral.

## Rules

- Validate every versioned document against its strict trusted-root schema and reject unknown fields.
- Authorize from GitHub's resolved repository permission before request creation, dispatch, cancellation, target preparation, or provider access.
- Treat bot comments, Markdown, display metadata, API responses, and target content as untrusted.
- Trust hidden state only from the configured immutable bot ID and keep it bounded and sanitized.
- Preserve terminal evidence, retry head binding, cancellation ownership, and single-winner lease behavior.
- Keep provider credential values out of package inputs, outputs, exceptions, logs, state, comments, checks, metrics, and tests.
- Put live API calls behind `GitHubPort`; deterministic tests use fakes.

## Validation

```bash
make countyforge-github-check
make countyforge-command-fixtures
make countyforge-workflow-policy-tests
```

## Related

- [Package overview](README.md)
- [Tooling agent guidance](../AGENTS.md)
- [Control-plane engineering guide](../../docs/engineering/countyforge-github-control-plane.md)
