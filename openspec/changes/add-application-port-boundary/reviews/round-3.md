# Round 3 — two scopes (transition record) — findings at 2a1a8a6f (resolved: 6710703)

Reconstructed from the Codex review posted on PR #120 at 2026-09-06T10:46Z.
Badge markup and reaction prompts removed; text otherwise verbatim. Line
references are to the reviewed commit.

## Reviewer's report (verbatim)

**Codex Review** — reviewed commit `2a1a8a6f27`.

1. P1 **Allow children to reference parents from prior loads**
   (`spec.md:278`) — Allow the correlation mechanism to resolve an
   already-persisted parent, not only a handle introduced in the current
   session. When a geometry or other child arrives from a second artifact/load
   of the same release, this rule rejects its parent as "never introduced";
   resubmitting the parent would create a new observation rather than link to
   the existing one. That makes the accepted cross-load enrichment scenario in
   `openspec/specs/canonical-silver-persistence/spec.md:191-204`
   unrepresentable, so the port needs a bounded existing-parent reference or
   lookup path.
2. P1 **Bound correlation state within a continuing account** (`spec.md:276`)
   — Bound or spill the live parent mappings within the continuing account
   rather than claiming this shape is release-independent. For an account with
   an unbounded number of owner associations followed by their allocations in
   later batches, every association handle remains potentially needed until
   account completion, so the session must retain an unbounded number of
   mappings despite allowing only one continuing account. Without a per-parent
   completion/order rule or durable spill mechanism, a pathological account can
   still exceed the bounded-memory requirement this design is intended to
   satisfy.
3. P1 **Prevent overlapping active runs when starting a release**
   (`spec.md:197`) — Require `start` to atomically reject or reuse an existing
   active run for the same release. When two workers concurrently start the
   same `ReleaseIdentity`, this contract currently promises only to create and
   return a run, while the database has no active-run uniqueness constraint;
   both therefore become distinct runs and both may create canonical loads.
   That leaves no race-safe boundary through which task 2.4 can satisfy the
   accepted requirement in `source-release-ingestion/spec.md:87-89` that
   overlapping active runs for the same county and release are prevented.

## Dispositions

1. [P1] RESOLVED — `canonical-load`. Fix: the session adopts an account
   snapshot already persisted for the release, named by its `AccountIdentity`
   and release, creating no observation; deeper parents are not adoptable
   (D2q; spec `canonical-load-session` "A child may name a parent persisted by
   an earlier load"; task 3.2). Resolving commit: `671070359`. Round 4 finding
   1 shows the fix is ambiguous at that grain; see there.
2. [P1] RESOLVED — `canonical-load`. Fix: each batch declares the handles that
   must outlive it (`still_needed`); an implementation may release the rest
   (D2p; spec `canonical-load-session`; task 3.1). Resolving commit:
   `671070359`. Round 4 finding 2 shows the declaration bounds retention but
   gives an oversized parent set no path to finish; see there.
3. [P1] RESOLVED — `run-and-manifest`. Fix: `start` refuses an overlapping
   active run by name, atomically, mechanism left to 3.5 (D2o; spec
   `processing-run` "A processing run is created through the boundary"; task
   1.3). Resolving commit: `671070359`. Pinned by task 7.2: starting a run for
   a release with an active run is refused; one whose previous run finished
   starts normally.

## Staleness sweep

Recorded in the resolving commit's body: the falsification clause for the
batch/session split had never reached `tasks.md` either — the same aborted
write as round 2. Restored in the same commit.

## Reviewer's authoritative blocks (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "2a1a8a6f27e4cd56c79cf0bc1992279291833b50",
	"scope_id": "canonical-load",
	"verdict": "REVISE",
	"unresolved_p1_count": 2,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "2a1a8a6f27e4cd56c79cf0bc1992279291833b50",
	"scope_id": "run-and-manifest",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```
