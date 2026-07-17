# Pre-PR Review Contract

## Purpose

This contract defines how automated and human-assisted pre-PR reviews work in `property-tax-data-platform`. The reviewer decides whether the current branch is safe and coherent enough to open as a pull request, and identifies the smallest fixes needed when it is not.

## Review Pipeline

1. Deterministic gates run first and must pass: `make check` (lint, typecheck, test, docs, spec, secrets, artifacts).
2. A review packet is generated at `.ai/reviews/review-packet.md`, embedding this contract, the reviewer prompt, and the branch diff against the base ref.
3. The dockerized Codex runner (`.ai/codex/02-run-prepr-review-docker.sh`) reviews the packet against `.ai/schemas/codex-prepr-review.schema.json` and writes self-contained run evidence under `.ai/reviews/codex-prepr/<branch>/<run-id>/`.
4. `BLOCKER` and `MUST_FIX` findings are applied with `.ai/prompts/claude-fix-from-review.md`, then the loop repeats until the verdict is `pass`, or `pass_with_notes` with accepted notes.

## Review Scope

- Review the current branch against the base ref named in the review packet, normally `origin/main`.
- Include staged, unstaged, and untracked files only when they are part of the branch work.
- Review nearby docs, configuration, and OpenSpec artifacts only when needed to understand the changed behavior.
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
- `pass` — no blockers, no must-fix items, and no unresolved questions.

## Related

- [Documentation hub](../README.md)
- [Contribution workflow](../../CONTRIBUTING.md)
- [Agent guide](../../AGENTS.md)
- [Reviewer prompt](../../.ai/prompts/codex-prepr-review.md)
- [Fix prompt](../../.ai/prompts/claude-fix-from-review.md)
- [Dev-loop hardening prompt](../../.ai/prompts/codex-dev-loop-hardening.md)
- [Review output schema](../../.ai/schemas/codex-prepr-review.schema.json)
