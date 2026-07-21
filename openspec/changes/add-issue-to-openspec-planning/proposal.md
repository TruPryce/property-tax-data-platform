## Why

Issue #6 needs a safe first planning executor. The existing control plane can authorize and dispatch `plan`, but the kernel intentionally returns `profile_not_implemented`; there is no bounded issue context, strict planning result, or trusted publication path for a reviewable OpenSpec change.

## What changes

- Promote `plan.read-only.v1` to an executable, provider-policy-driven profile without changing the packet-only review boundary.
- Add bounded, provenance-bound planning packet and context-manifest contracts assembled from trusted repository material and untrusted issue evidence.
- Add a strict planning-result contract and deterministic materializer that can write only an OpenSpec planning change.
- Add trusted validation and draft-PR publication orchestration with deterministic branch identity, revision/supersession metadata, and human approval gating.
- Preserve fail-closed behavior for implementation, fix, and validation profiles and preserve the existing review path.

## Scope and non-goals

Planning is read-only model reasoning over bounded evidence. The model never receives Git credentials, GitHub write tokens, production credentials, a writable repository, arbitrary tools, or external retrieval. Trusted workflow code owns Git operations, validation, commit/push, draft PR creation, and canonical status publication.

This change does not implement code-writing, remediation, arbitrary validation, automatic approval/merge, production deployment, external state stores, or unrestricted shell access.

## Traceability

This change implements GitHub Issue #6 under parent program Issue #2. A generated plan remains a draft until an authorized maintainer approves it under the documented approval contract.
