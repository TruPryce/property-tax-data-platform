# CountyForge GitHub Adapter

`countyforge-github` is the Python 3.12 GitHub control-plane adapter for CountyForge. It parses bounded `/countyforge` comments, applies repository-permission authorization, creates immutable triggers and runner requests, derives semantic identities, enforces lifecycle/lease/cancel/retry policy, renders one canonical status comment, and isolates GitHub REST access behind typed ports. Its planning adapter builds bounded issue context, validates strict plan results, and publishes only deterministic OpenSpec draft files.

It depends on `countyforge-runner`. The runner kernel does not depend on this package or import GitHub workflow concepts.

## Trust Boundary

- package code, profiles, policies, schemas, prompts, and adapters load from one trusted default-branch `contract_root` SHA;
- target issue or pull-request content is immutable untrusted data under a separate `target_root`; fork source identity and the ancestor merge base are explicit trigger facts;
- packet preparation has no provider secret and executes no target code;
- provider execution has no target worktree; and
- `review.packet-only.v1` and `plan.read-only.v1` execute; implement/fix/validate remain
  fail-closed.

## Commands

Pure local/workflow commands emit JSON:

```bash
uv run --package countyforge-github countyforge-github parse-command --event event.json
uv run --package countyforge-github countyforge-github authorize \
  --event event.json --permission permission.json
uv run --package countyforge-github countyforge-github idempotency-key --trigger trigger.json
uv run --package countyforge-github countyforge-github transition \
  --state state.json --transition transition.json
uv run --package countyforge-github countyforge-github render-status --state state.json
uv run --package countyforge-github countyforge-github build-planning-packet \
  --trigger trigger.json --issue issue.json --output-dir "$RUNNER_TEMP/planning"
uv run --package countyforge-github countyforge-github check
```

The `intake`, `claim-run`, `advance-run`, and `maintain` commands are workflow mutation boundaries. Their JSON includes strict structured audit events and matching low-cardinality metric samples. They require a scoped `GITHUB_TOKEN`; never supply a provider credential to this package.

## Validation

```bash
make countyforge-github-check
make countyforge-plan-check
make countyforge-plan-fixtures
make countyforge-command-fixtures
make countyforge-workflow-policy-tests
make runner-contract-tests
```

Tests use fake GitHub ports. They make no live GitHub mutation or paid model call.

## Related

- [Developer tooling](../README.md)
- [Control-plane engineering guide](../../docs/engineering/countyforge-github-control-plane.md)
- [GitHub operations](../../docs/operations/countyforge-github-operations.md)
- [GitHub-native control-plane ADR](../../docs/decisions/0006-github-native-countyforge-control-plane.md)
- [Control-plane OpenSpec](../../openspec/changes/add-github-run-control-plane/specs/github-agent-control-plane/spec.md)
