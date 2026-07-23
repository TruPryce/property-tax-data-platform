# CountyForge Runner

`countyforge-runner` is the Python 3.12 developer-tool kernel for versioned requests, immutable capability profiles, provider/model compatibility, hard budgets, fail-closed dispatch, and generic evidence.

`review.packet-only.v1`, `plan.read-only.v1`, and `implement.workspace-write.v1` execute through separate locked-down adapters. Planning receives only a frozen packet/context manifest. Implementation receives a frozen accepted-plan packet and ephemeral workspace; fix and validate remain `profile_not_implemented` before credential or executor access.

## Commands

```bash
uv run --package countyforge-runner countyforge-runner list-profiles --json
uv run --package countyforge-runner countyforge-runner validate-request --request request.json --json
uv run --package countyforge-runner countyforge-runner resolve-profile --request request.json --json
uv run --package countyforge-runner countyforge-runner explain --request request.json --json
uv run --package countyforge-runner countyforge-runner run --request request.json --json
```

GitHub-dispatched runs keep trusted contracts separate from the immutable target:

```bash
uv run --package countyforge-runner countyforge-runner run \
  --request request.json \
  --contract-root /path/to/trusted-tools \
  --target-root /path/to/immutable-target.git \
  --json
```

`--repo-root` remains the local compatibility option and defaults both roots to one checkout.

## Validation

```bash
make countyforge-runner-check
make countyforge-profile-tests
make countyforge-request-fixtures
```

## Related

- [Developer tooling](../README.md)
- [Runner engineering guide](../../docs/engineering/countyforge-runner-kernel.md)
- [Agent-runner OpenSpec](../../openspec/changes/build-mode-aware-runner-kernel/specs/agent-runner-kernel/spec.md)
- [Mode-aware runner ADR](../../docs/decisions/0005-mode-aware-runner-kernel.md)
- [GitHub control-plane package](../countyforge-github/README.md)
- [GitHub control-plane guide](../../docs/engineering/countyforge-github-control-plane.md)
