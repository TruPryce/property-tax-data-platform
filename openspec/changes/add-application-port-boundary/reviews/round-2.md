# Round 2 — four scopes (transition record) — findings at d812ce33 (resolved: 2a1a8a6)

Reconstructed from the Codex review posted on PR #120 at 2026-09-06T09:58Z,
after the PR left draft. Between rounds 1 and 2 the branch took eleven
commits (`050bb0a` through `d812ce3`) with no external review; their commit
bodies record the self-found defects they closed, including the rejection of
whole-account batches, the manifest index, acquisition-first manifesting, the
acquisition-grain storage rule, and the batch-versus-session validation split.
Badge markup and reaction prompts removed; text otherwise verbatim. Line
references are to the reviewed commit.

## Reviewer's report (verbatim)

**Codex Review** — reviewed commit `d812ce3380`.

1. P1 **Enforce the outcome evidence seal in the value** (`tasks.md:18`) —
   When a rejected outcome declares one diagnostic but retains none, it
   satisfies every invariant enumerated here, yet
   `ingestion.assert_outcome_evidence_agrees` rejects it at commit because
   retained entries must equal `min(total, 100)`. The task likewise omits the
   exact truncation-flag rules and the requirement that each diagnostic
   fingerprint equal the outcome fingerprint. Require these relationships in
   `ReleaseProcessingOutcome` and cover them in the falsification tests;
   otherwise values accepted by the application boundary can abort the
   canonical completion transaction.
2. P1 **Verify handles identify the record's embedded parent** (`spec.md:258`)
   — When a batch contains multiple possible parents, these checks only
   require the supplied handle to resolve; they never require it to resolve to
   the same parent object already embedded in the canonical record. For
   example, an `OwnerValueAllocation` referencing association A can be paired
   with association B's live handle, causing an adapter to persist the
   allocation under B while accepting a domain value that names A. Require
   batch/session validation that every resolved handle corresponds to the
   record's actual direct parent.
3. P1 **Carry source-as-of evidence into publication attempts**
   (`tasks.md:61`) — When discovery produces a non-null source-as-of instant,
   neither `ReleaseIdentity` nor `ProcessingRunRef` carries it, and this
   planned `PublicationRepository.open(product, release, run)` signature
   provides no way to write it into `publication.publication.source_as_of`.
   Deriving it from canonical snapshots is ambiguous because the canonical
   model permits multiple snapshots with differing source-as-of values. Pass
   the release-level evidence through the run or publication boundary so Gold
   lineage can expose the required freshness instead of recording null or
   inventing a selection rule.
4. P2 **Reject reuse of completed correlation handles** (`spec.md:256`) —
   Once an account completes, this contract releases its handle mapping while
   requiring uniqueness across the entire session; because callers mint
   arbitrary positive integers and the session only rejects values that are
   currently live, a later account can reuse a completed handle undetected. A
   delayed child using that old value can then resolve to the new account
   instead of being refused. Make the session mint monotonic handles, retain
   bounded uniqueness state, or weaken and redesign the invariant so
   completed-handle reuse cannot silently retarget records.
5. P2 **Populate expected media types for every county** (`tasks.md:42`) —
   With the six existing `CountySourceDefinition` constants left unchanged,
   adding only one shared default cannot accurately describe each source's
   expected media types, and an empty default would make every resolved
   production definition omit the newly required information. Update each
   county registration with its actual bounded media-type tuple rather than
   relying on a compatibility default; otherwise the real registry fails the
   requirement even though the planned fake-only contract test can pass.

## Dispositions

1. [P1] RESOLVED — `run-and-manifest`. Fix: the seal is part of the value —
   retained counts equal the smaller of the total and the bound, truncation
   flags equal total-exceeds-bound, every retained diagnostic's fingerprint
   equals the outcome's under `IS DISTINCT FROM` semantics (D2j; spec
   `processing-run`; task 1.1). Resolving commit: `2a1a8a6f2`. Pinned by task
   7.2: the seal falsified in each direction.
2. [P1] RESOLVED — `canonical-load`. Fix: a resolved handle must denote the
   very parent the record holds, checked by object identity — by the batch for
   in-batch parents, by the session for earlier ones (D2k; spec
   `canonical-load-session`; tasks 3.1, 3.2). Resolving commit: `2a1a8a6f2`.
3. [P1] RESOLVED — `quality-publication-clock`. Fix: opening an attempt takes
   the release's source as-of instant, optional, never derived from snapshots
   (D2m; spec `run-bound-quality-and-publication` "Release-level source
   freshness reaches publication through the boundary"; task 4.2). Resolving
   commit: `2a1a8a6f2`. Reopened in substance by round 4 finding 3: nothing
   durable carries the instant between independently retried stages.
4. [P2] RESOLVED — `canonical-load`. Fix: handles increase strictly over the
   session and the session retains the highest yet introduced (D2l; spec
   `canonical-load-session`; task 3.1). Resolving commit: `2a1a8a6f2`.
5. [P2] RESOLVED — `registry-and-discovery`. Fix: task 2.1 populates the six
   county definitions with their real media types (D2n). Resolving commit:
   `2a1a8a6f2`. Pinned by task 7.2: every one of the six registered counties
   carries a non-empty tuple of its own.

## Staleness sweep

Recorded in the resolving commit's body: while checking finding 2 the author
found the session-authority sentence had never reached `tasks.md` — the script
that added it to the spec aborted before writing the task file in the round
that introduced the split. Restored in the same commit. This is the incident
the ledger's standing practice exists for.

## Reviewer's authoritative blocks (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d812ce3380644264087e9cacc45617e7dd89b3f3",
	"scope_id": "run-and-manifest",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d812ce3380644264087e9cacc45617e7dd89b3f3",
	"scope_id": "canonical-load",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 1
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d812ce3380644264087e9cacc45617e7dd89b3f3",
	"scope_id": "quality-publication-clock",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d812ce3380644264087e9cacc45617e7dd89b3f3",
	"scope_id": "registry-and-discovery",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 1
}
```
