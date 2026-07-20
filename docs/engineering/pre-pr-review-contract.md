# Pre-PR Review Contract

## Purpose

This contract defines how automated and human-assisted pre-PR reviews work in `property-tax-data-platform`. The reviewer decides whether the current branch is safe and coherent enough to open as a pull request, and identifies the smallest fixes needed when it is not.

## Review Pipeline

1. Deterministic gates run first and must pass: `make check` (lint, typecheck, test, docs, spec, secrets, artifacts).
2. `make review-packet` deterministically generates `.ai/reviews/review-packet.md` plus `.ai/reviews/review-packet.provenance.json`, embedding machine-readable repository/merge-base/HEAD metadata before this contract, the reviewer prompt, applicable repository context, repository status, and the branch diff while binding the exact packet bytes to those immutable facts.
3. `make prepr` performs the complete loop: it reruns the deterministic gates, atomically refreshes the canonical packet and strict provenance sidecar, builds a versioned CountyForge request containing both hashes, and invokes `review.packet-only.v1` through the `countyforge-runner` kernel.
4. The runner reviews only that packet against `.ai/schemas/codex-prepr-review.schema.json` and writes self-contained run evidence under `.ai/reviews/codex-prepr/<safe-branch>/<run-id>/`.
5. `BLOCKER` and `MUST_FIX` findings are applied with `.ai/prompts/claude-fix-from-review.md`, then the loop repeats until the verdict is `pass`, or `pass_with_notes` with accepted notes.

`BASE=<ref>` overrides the default `origin/main` comparison for both packet generation and the
complete loop. `make prepr-no-ai` runs the deterministic gates and packet builder without a paid
model call.

After the GitHub control workflows exist on the default branch, `/countyforge review` performs the
same packet-only profile through a two-root pipeline: trusted default-branch tooling prepares a
frozen packet from an immutable target in a no-secret job, and the provider job receives no target
worktree. The local `make prepr` contract and evidence paths remain unchanged.

## Packet Context and Redaction

The packet builder selects context from the frozen checkout without querying GitHub or another
network service. It includes:

- the root `AGENTS.md` and ancestor `AGENTS.md` files for changed or untracked paths;
- `openspec/AGENTS.md`, every active non-archived change's proposal, design, tasks, and delta specs;
- accepted specs under `openspec/specs/`; and
- accepted decision records under `docs/decisions/`.

Paths are emitted in byte-sorted order. `MAX_CONTEXT_BYTES` defaults to 400,000 bytes for the
whole context section and `MAX_CONTEXT_FILE_BYTES` defaults to 160,000 bytes per file. Truncation
is explicit in the packet. An applicable issue reference must be present in the repository's
active OpenSpec artifacts for non-bootstrap work; this read-only profile does not fetch issue or
PR text.

High-confidence literal credential assignments and literal Basic/Bearer authorization values are
redacted before packet content is emitted. Source expressions remain intact, including shell
parameter expansions such as `${VAR:-default}` and `${VAR:=default}`, so the review evidence does
not become syntactically misleading. Secret-looking paths remain excluded rather than redacted.

## Runner Profile Boundary

This runner is the strict read-only review profile. The model receives one self-contained packet
on stdin and has no model-invokable shell, browser, app, image-generation, or web-search tool. The
container mounts only the repository's `.ai/schemas/` contract directory read-only and the claimed
run directory read-write; its root filesystem is read-only and it runs without Linux capabilities
or privilege escalation. The mounted schema directory contains version-controlled runner contracts;
the model is constrained to the profile-declared review-output schema and has no filesystem tool
with which to inspect other schemas.

Repository mutation, code writing, GitHub publishing, issue dispatch, and command execution are
outside this profile.

The runner replaces every branch-name character outside `[A-Za-z0-9._-]` with `__` when deriving
`<safe-branch>`. For example, `feature/ai-runner` becomes `feature__ai-runner`.

## Review Scope

- Review the current branch against the base ref named in the review packet, normally `origin/main`.
- Include staged, unstaged, and untracked files only when they are part of the branch work.
- Review the repository context embedded in the packet only when needed to understand the changed behavior.
- Do **not** request unrelated cleanup or implementation outside the stated issue/OpenSpec scope.
- Do **not** suggest broad rewrites when a targeted fix would address the risk.

## Severity Levels

| Severity | Meaning | Use for |
|---|---|---|
| `BLOCKER` | Must be fixed before PR. | Committed secrets or county source artifacts, dependency-direction violations, Bronze immutability or lineage regressions, owner-data publication or protected-identity reconstruction, fabricated canonical value semantics, unsafe migrations, or contradictions that make implementation unsafe. |
| `MUST_FIX` | Should be fixed before PR. | Material ambiguity, missing edge-case handling, incomplete deterministic checks or fixtures, schema/doc inconsistencies, or moderate migration/compatibility risk. |
| `NICE_TO_FIX` | Can be deferred. | Low-risk cleanup, wording polish, naming, or maintainability improvements that do not affect the PR decision. |
| `QUESTION` | Requires a human decision. | Product, architecture, rollout, or scope choices where multiple answers may be valid. Do not use this for confirmed defects. |

## Focus Areas

Review in this order:

1. OpenSpec / stated-scope compliance
2. Secret and source-artifact hygiene
3. Dependency-direction and package-boundary violations
4. County source-contract fidelity (identity, grain, release semantics, layout fingerprints)
5. Bronze immutability, lineage, and release-state correctness
6. Privacy and confidentiality (owner-data default-deny)
7. Quality-gate and publication-blocker coverage
8. Test and deterministic-gate coverage
9. Migration safety, backfill behavior, and rollback
10. Schema consistency (Silver/Gold models, manifests, `.ai/schemas/`)
11. Operational failure modes (retries, quarantine, drift observability)
12. Documentation accuracy and link hygiene

## Platform Rules

These rules distill `AGENTS.md` and the accepted OpenSpec artifacts; when they conflict, OpenSpec wins. Keep them in sync with `.ai/prompts/codex-prepr-review.md`.

- OpenSpec is the accepted contract. Code and tests implement specs; they do not redefine them. Non-bootstrap implementation references an accepted GitHub Issue and OpenSpec change.
- Hexagonal dependency direction only: `dags/services -> adapters -> application -> domain`. The domain is infrastructure-free; county formats and vendor (PACS) vocabulary stop at the adapters.
- `dags/` declares orchestration only — no county parsing, mapping, or SQL; XCom carries release IDs and object URIs, never records.
- Bronze is immutable evidence: SHA-256 is artifact identity; mutable source slots never overwrite earlier captures; conflicting content is retained and flagged.
- Appraisal values are never presented as authoritative tax bills, payments, or delinquency records.
- All six counties (Dallas, Collin, Tarrant, Denton, Rockwall, Ellis) stay behind the same application port; one county's layout is never generalized into the domain.
- Physical owner-row grain `(prop_id, owner_sequence)` is preserved without an approved account roll-up rule; owner and mailing-address publication is default-deny.
- No secrets, full county releases, or source-record artifacts in Git; fixtures are small, synthetic or redistribution-safe, with documented provenance. `.artifact-allowlist` exceptions require PR justification.
- Quality rules are publication gates; blocking rules preserve prior Gold state.
- An adapter is not `production_ready` until its OpenSpec tasks and required checks pass.
- Generated AI review artifacts belong under `.ai/reviews/` and must not be committed except `.gitkeep`.

## Finding Requirements

Every finding must include:

- severity;
- title;
- file and line when known;
- description;
- why it matters;
- minimum acceptable fix.

Separate confirmed issues from assumptions. Prefer specific, actionable feedback over generic advice.

## Output Expectations

Reviews must match `.ai/schemas/codex-prepr-review.schema.json` and include:

- `verdict`;
- `summary`;
- `blockers`;
- `must_fix`;
- `nice_to_fix`;
- `questions`;
- `recommended_next_action`.

## Verdict Rules

- `block` — one or more `BLOCKER` findings exists.
- `pass_with_notes` — no blockers, but at least one `MUST_FIX`, `NICE_TO_FIX`, or `QUESTION` exists.
- `pass` — `blockers`, `must_fix`, `nice_to_fix`, and `questions` are all empty.

## Related

- [Documentation hub](../README.md)
- [Contribution workflow](../../CONTRIBUTING.md)
- [Review artifact contract](review-artifact-contract.md)
- [Runner observability](codex-runner-observability.md)
- [CountyForge runner kernel](countyforge-runner-kernel.md)
- [CountyForge GitHub control plane](countyforge-github-control-plane.md)
- [Agent guide](../../AGENTS.md)
- [Reviewer prompt](../../.ai/prompts/codex-prepr-review.md)
- [Fix prompt](../../.ai/prompts/claude-fix-from-review.md)
- [Dev-loop hardening prompt](../../.ai/prompts/codex-dev-loop-hardening.md)
- [Review output schema](../../.ai/schemas/codex-prepr-review.schema.json)
