# CountyForge planning agent

The planning agent turns an authorized structured GitHub Issue into a draft OpenSpec change.
Planning is not implementation: the model proposes bounded intent, while trusted workflow code
owns materialization, validation, Git operations, and draft-PR publication.

## Trust boundary

Issue titles, bodies, comments, labels, links, and target revisions are untrusted evidence.
The packet builder labels them explicitly and never treats them as system instructions,
commands, paths, provider settings, or authorization facts. Context is selected from approved
repository documentation and contract roots with symlink confinement, regular-file checks,
stable ordering, per-file/aggregate limits, hashes, and truncation metadata. External URLs are
references only.

The planning model receives a frozen planning packet, context manifest, trusted prompt, and
output schema. It has no writable repository, GitHub token, Git credential, production
credential, arbitrary tool, or ungoverned network. Only the selected provider key is attached
to the model invocation. The review profile remains packet-only and is not broadened.

## Contracts

| Contract | Purpose |
|---|---|
| `countyforge-planning-packet.schema.json` | bounded issue/context evidence |
| `countyforge-planning-context-manifest.schema.json` | source hashes and selection provenance |
| `countyforge-plan-result.schema.json` | strict model output and eligibility gate |
| `countyforge-planning-publication-manifest.schema.json` | rendered OpenSpec files and validation |
| `countyforge-planning-revision.schema.json` | deduplication/supersession lineage |

The runner request binds packet and manifest hashes to one issue, repository, immutable target
SHA, and run ID. The plan profile is read-only and writes only run evidence.

## Materialization and publication

Trusted code renders only `.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`, and one
capability `spec.md` below `openspec/changes/<change-name>/`. It rejects absolute/traversal
paths, workflow/policy/provider/secret paths, and production source paths. Tasks are unmarked.
Validation runs before branch or PR mutation:

```text
openspec validate --all --strict --no-interactive
openspec doctor
python scripts/check_doc_links.py
python scripts/check_repository_artifacts.py
```

The deterministic branch is `countyforge/plan/issue-<issue>-<change-name>` from trusted
default-branch SHA. The draft PR links the originating issue and run, lists assumptions and
unresolved decisions, states that no production code is included, and requires maintainer
approval. A merged planning PR is the initial approval evidence; reactions and labels do not
approve a plan.

## Revisions and recovery

Identical semantic planning identity deduplicates. Changed context creates a revision. The
publisher conservatively preserves every predecessor and creates a linked superseding draft;
an exact same-run publication is idempotently reused. Cancellation before publication creates no branch or PR. A
publication race rereads canonical state and reports any already-created branch/PR honestly.
Canonical issue status is serialized through the existing per-target state lane and records
planning revision/change/PR metadata while implementation eligibility remains false.

## Local checks

Use `make countyforge-plan-check`, `make countyforge-plan-fixtures`, and
`make countyforge-plan-policy-tests`. These are deterministic and do not call a provider. Plan
image construction and paid calls remain explicitly opt-in.

## Related

- [Runner kernel](countyforge-runner-kernel.md)
- [GitHub control plane](countyforge-github-control-plane.md)
- [GitHub operations](../operations/countyforge-github-operations.md)
- [ADR-0007](../decisions/0007-issue-to-openspec-planning.md)
