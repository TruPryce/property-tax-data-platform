# 9. Maintainer decision input and trusted planning semantics

Date: 2026-08-03

## Status

Accepted

## Context

PR #46 generated a planning change for issue #18 that was syntactically valid and
semantically useless. It filed a Collin change against `issue-to-openspec-planning`
— the planner's own capability — rendered every requirement as "The implementation
SHALL satisfy this criterion", authorised every task to write
`libs,services,dags,docs,tools,tests,README.md,CONTRIBUTING.md`, and emitted
`prerequisites=-` for tasks whose own prose named their dependencies.

Four of those failures had one cause. `task_slices`, `acceptance_criteria`,
`affected_capabilities`, and `unresolved_decisions` were arrays of strings, so
trusted materialization had nothing structured to render and invented the rest.
The defect was in the contract, not in the code that read it.

Separately, a detailed D1–D4 decision package posted on the issue was clipped at
4,000 characters per comment. The truncation was silent: nothing in the packet or
the manifest recorded it, so the model reasoned over a fragment and correctly
reported that it could not decide.

## Decision

**Contract version 2.** The four string arrays become structured: capabilities
carry a change type, requirements carry a normative rule and observable
scenarios, tasks carry write paths and prerequisites, and decisions become
first-class objects. The generation schema is a mechanical projection of the
result schema onto the provider-compatible keyword subset, so the two cannot
drift.

**A trusted semantic gate.** `planning_semantics.py` enforces what a schema
cannot express and only ever refuses, never repairs. It runs inside
`validate_planning_result`, which the local check, the plan-validation job, and
publication already share.

**A new trust boundary for decision input.** A maintainer may split a decision
package across comments carrying an exact versioned marker:

```
<!-- countyforge-plan-input:v1 issue=18 input=collin-decoder-decisions-1 part=1/4 -->
```

This introduces a boundary worth naming precisely, because it looks like an
exception to "issue text is untrusted" and is not one:

- The marker changes **selection**, never trust. A marked comment is still
  untrusted evidence and nothing in it becomes policy.
- Authorization is independent of the marker. Only the actor the trigger already
  authorized may supply decision content; `authorized_author_ids` is a required
  argument with no default, and an empty allowlist authorizes nobody.
- The package is bound at packet construction — comment ID, author, content
  digest, and `updated_at` per part — and rebound at publication. Publication
  re-reads the comments and refuses if either the digest or the timestamp moved,
  before the first Git object is created.
- Bounds are refusal points, not truncation points. An oversized part is
  excluded with `comment_too_large`; a missing, duplicated, or conflicting set
  fails closed as `incomplete_decision_input`.

**Scope and boundaries are trusted inputs, not model outputs.**
`.ai/policies/countyforge-planning-scope.v1.json` declares the maximum write
roots and required cross-issue boundaries per issue and capability. A plan may
narrow the ceiling; nothing it emits can widen it.

**A plan never authorises its own implementation.** A maintainer-supplied
decision may be `resolved_for_draft` for the purpose of drafting.
`implementation_eligibility` stays false until an authorized maintainer merges
the generated OpenSpec PR.

## Consequences

Existing v1 planning results are readable but not republishable: the gate refuses
`contract_version: 1` with `contract_version_unsupported` rather than silently
upgrading a document whose fields it cannot interpret. PR #46 stays unmerged.

A run whose decision comments change mid-flight now fails instead of publishing.
That is the intended trade: a plan built on evidence that no longer exists is
worse than no plan.

The scope policy is a file a human must maintain. An issue absent from it
collapses to the change's own OpenSpec directory, which is restrictive by design —
a forgotten entry produces a refusal, not a wide grant.

## Alternatives considered

**Keep the string arrays and harden the materializer.** Rejected: the
materializer cannot infer a write scope or a prerequisite that was never stated.
Every heuristic it applied is what produced PR #46.

**Treat marked comments as trusted policy.** Rejected outright. It would make a
comment marker a privilege escalation primitive.

**Derive the write ceiling from the plan's own proposed files.** Rejected: the
provider would still author both sides of the check.

## References

- Issue #18, issue #43, PR #44, PR #46, PR #47
- [`docs/engineering/countyforge-planning-agent.md`](../engineering/countyforge-planning-agent.md)
- [ADR 0007](0007-issue-to-openspec-planning.md)
