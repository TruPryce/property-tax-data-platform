# Round 4 — three scopes (transition record) — findings at 67107035 (open)

Reconstructed from the Codex review posted on PR #120 at 2026-09-06T11:39Z
against the current head. Every finding is open. Badge markup and reaction
prompts removed; text otherwise verbatim. Line references are to the reviewed
commit, before the spec was split into six files: `spec.md:335` and
`spec.md:326` now live in `specs/canonical-load-session/spec.md`, and
`tasks.md:48` is task 2.2.

## Reviewer's report (verbatim)

**Codex Review** — reviewed commit `6710703591`.

1. P1 **Identify the exact snapshot when adopting a parent** (`spec.md:335`) —
   When an account has multiple snapshots for the same `AccountIdentity` and
   release, this lookup is ambiguous: both the accepted canonical spec and this
   change's own divergent-evidence scenario permit that grain to contain
   several snapshots with different provenance. Moreover, the session later
   requires a handle to denote the exact parent object embedded in the child,
   but `adopt(account_identity, release)` supplies neither that object nor
   distinguishing lineage. Add a locator or other evidence-backed selector that
   resolves the exact existing snapshot; otherwise enrichment can attach to the
   wrong observation or cannot satisfy the parent check.
2. P1 **Provide a bounded path for oversized parent sets** (`spec.md:326`) —
   When one account has more parent observations than a batch can retain and
   their children arrive later, omitting some handles from `still_needed` makes
   those children fail as naming released parents, while retaining every handle
   violates the promised bound. The newly added oversized-parent scenario
   exposes this failure but merely disclaims holding the mappings; it provides
   no ordering guarantee, durable spill, or lookup mechanism that would let the
   valid account finish. Add such a mechanism or an enforceable parent/child
   ordering contract.
3. P1 **Persist source freshness before later publication retries**
   (`tasks.md:48`) — When publication resumes after discovery, acquisition, or
   loading has completed in an earlier process, the historical source-as-of
   instant exists only on the transient `SourceCandidate`: neither
   `ReleaseManifest`, `LogicalReleaseEvidence`, `ManifestRef`, nor
   `ProcessingRunRef` retains it. The new publication-attempt parameter
   therefore still cannot be populated after an independently retryable stage,
   and rediscovering a mutable page may yield a different timestamp. Persist
   this evidence at the manifest/run handoff or provide another durable
   retrieval path before claiming it reaches publication.
4. P2 **Specify the fields carried by PageEvidence** (`tasks.md:48`) — Define
   the bounded fields of `PageEvidence` rather than only naming the carrier.
   The county contracts require distinct facts such as fetched/rendered-page
   evidence, section headings, visible labels, directory paths, and discovery
   timestamps, but this task gives the implementer no application-owned
   vocabulary for any of them while also forbidding raw or unbounded content.
   As written, an implementation must invent an arbitrary payload or omit
   required provenance, and the planned fake-only contract test can pass
   without proving that the real county evidence is representable.

## Dispositions

1. [P1] UNRESOLVED — `canonical-load`. Confirmed against the accepted
   `canonical-silver-persistence` requirement "Snapshot grain admits divergent
   evidence": the grain "SHALL NOT be expressed as a uniqueness constraint",
   and two snapshots sharing an account and a release with different provenance
   are both retained. D2q's "which the accepted contract fixes as exactly that
   snapshot's grain" conflates grain with key, so
   `adopt(account_identity, release)` is ambiguous by construction. Needs a
   maintainer decision among: (a) adoption names the existing snapshot by an
   opaque locator returned when it was persisted, which means the earlier
   load's completion must hand one back; (b) adoption is refused with a named
   error when more than one snapshot matches the grain, so enrichment of a
   divergent account fails closed; (c) adoption is dropped and a cross-load
   child carries a provenance-qualified parent reference instead. Each changes
   D2q, the `canonical-load-session` spec, and tasks 3.1–3.2, and (a) touches
   `ReleaseLoadCompletion`.
2. [P1] UNRESOLVED — `canonical-load`. The `still_needed` declaration bounds
   retention but the scenario "An account carries more parents than a batch can
   hold" only disclaims. Needs a maintainer decision among: (a) an ordering
   contract — a child is written within N batches of its parent, and a parent
   not re-declared is released, so the caller in 2.4 orders the walk; (b) state
   the bound honestly as "one account's parents" and accept that a single
   pathological account may exceed memory, recording it as a risk; (c) a
   durable spill the adapter owns, which is 3.5's mechanism and leaves the port
   contract as (b). The scenario as written asserts nothing testable and is
   also round 5 finding 3.
3. [P1] UNRESOLVED — `quality-publication-clock`, with the likely landing in
   `run-and-manifest`: the durable home the finding asks for is at the
   manifest/run handoff, so the fix probably adds the instant to what
   `ManifestIndex` records or to what `start` binds, and the publication spec
   then cites it. Needs a maintainer decision on which record carries it;
   `bronze.release_manifest` has no column for it, so the plan must say whether
   this is a migration (excluded by the constraints) or a run-scoped fact.
4. [P2] UNRESOLVED — `registry-and-discovery`. Needs the bounded field list for
   `PageEvidence`, taken from what the six county source contracts actually
   require (Dallas and Tarrant page labels and section headings, directory
   paths, discovery timestamps), in task 2.2 and the discovery spec.

## Staleness sweep

Pending the dispositions.

## Reviewer's authoritative blocks (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "canonical-load",
	"verdict": "REVISE",
	"unresolved_p1_count": 2,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "quality-publication-clock",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "registry-and-discovery",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 1
}
```
