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

1. [P1] **RESOLVED (a)** at `e6a3a24`+1 — `canonical-load`. Confirmed against the accepted
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

   **Maintainer chose (a).** Adoption names the snapshot by an opaque locator,
   `AccountSnapshotRef`, on the same terms as `ProcessingRunRef`; adoption by
   account identity and release no longer exists, because the grain names both
   snapshots. Within (a) this change took the bounded reading rather than the
   literal one: the boundary offers `AdoptableSnapshot` candidates — a locator
   paired with the `DomainProvenance` that distinguishes it — for one account and
   release, bounded by acquisitions of that release, instead of
   `ReleaseLoadCompletion` carrying one locator per account, which would grow with
   the release and undo the bound the rest of the capability keeps. The completion's
   `ProcessingRunRef` is what ties a locator to the load that wrote it. Landed in
   the `canonical-load-session` spec (the adoption requirement and three
   scenarios), `design.md` under "A parent that is already in the database", the
   falsification matrix, and tasks 3.1 and 3.2. If the literal bulk return was
   intended, say so and it changes back.

   **Corrected once, at review.** The first application of (a) paired each locator
   with the `DomainProvenance` "that distinguishes it" and claimed one candidate per
   acquisition. Both were wrong against a contract this change cites:
   `canonical-silver-persistence` retains two snapshots sharing one *load, account,
   release, and provenance* that differ only in a composed situs address or legal
   description, and forbids the uniqueness that would collapse them. Provenance
   therefore presents those two as one — the same ambiguity as grain, moved a field
   along — and one acquisition can persist several snapshots at one grain, so no
   per-acquisition bound holds. `AdoptableSnapshot` now carries the **snapshot
   value**, and candidate access is **paged or streamed** rather than resting on a
   cardinality no accepted contract promises.

   **Corrected twice.** The next round found that `adopt(ref)` discarded the object
   the candidate had just supplied, so an adopted parent was the one class of parent
   the object-identity check could not reach — the check that exists because two
   legitimate parents can be equal by value. Adoption now takes the **candidate**,
   binding the handle to that exact snapshot object. The same round found that "paged
   or streamed" is an adjective a list called a page satisfies, so the port now names
   the shape: `Iterator[AdoptableSnapshot]`, with the implementation forbidden from
   drawing every candidate before the caller consumes the first.

   **Corrected three times.** The round after that found the candidate is an ordinary
   value a caller can assemble, so a valid locator could be paired with a snapshot it
   does not locate — binding the handle to an object the locator never named, which is
   the original ambiguity arriving through the value introduced to remove it. Adoption
   now resolves the locator and refuses unless it locates the snapshot the candidate
   carries. The same round found the active design diagram and several normative
   scenarios still prescribing `adopt(locator)` and "paged or streamed" beneath prose
   that had moved on; both are now swept, and only the historical record here and the
   sentence explaining why the adjective is inadequate still use those words.

   **Corrected four times, and the fourth found the decision record itself.** D2q in
   `proposal.md` still carried the rejected reasoning verbatim — "names an existing
   snapshot by its `AccountIdentity` and release, which the accepted contract fixes as
   exactly that snapshot's grain — declared identity, not a key over observed values" —
   so the proposal was arguing for the shape three rounds had removed. Rewritten. The
   mismatch between a candidate's locator and its snapshot also had no declared
   exception, only "a named error"; it is now `AdoptableSnapshotMismatch`, distinct
   from `UnknownAccountSnapshot`, because a stale locator and an assembly mistake are
   different facts a caller must be able to separate.

   **And the spill obligation contradicted the contract it was handed under.**
   `still_needed` lets an implementation release every mapping a batch does not
   declare, and naming a released handle afterwards is refused — so no durable spill
   can rescue an undeclared handle, and 3.5 had been handed something unsatisfiable.
   The scope is now stated precisely: the spill keeps a **declared** still-needed set
   resolvable when it outgrows memory, which is a real obligation, and does not touch
   handles the caller never declared, which are gone by contract. The risk, the
   handoff, the matrix, and bootstrap 3.5 and 3.6 all say that.

   **Corrected five times, and the fifth found the arithmetic.** A "large declared
   still-needed set" cannot exist: the declaration is carried by a bounded batch, so it
   caps the live set at one batch's worth, and the second remedy was as unsatisfiable
   as the first. Correlation is now expressed as **bounded retain and release deltas**
   over an accumulating live set, on the reviewer's recommendation. Every declaration
   stays bounded because the batch is; the live set is bounded by the caller's own
   discipline and by account completion, not by any batch; and task 3.5's obligation is
   finally coherent — durably maintaining that logical live set when one continuing
   account's exceeds memory. A released handle stays released: the spill maintains the
   set, it does not extend it.

   **Corrected six times.** The delta architecture was accepted, and the round after
   found two things it had left undone. D2p still argued the superseded full
   re-declaration — "each batch names the handles that must outlive it… a parent needed
   several batches later is re-declared in each" — so the proposal again disagreed with
   the spec, which is the second time a decision record outlived its decision here.
   And the deltas themselves were unspecified beyond their existence: an accumulating
   set each batch edits is only as trustworthy as the edits, so the capability now
   fixes **validity** (a delta names only live or newly introduced handles),
   **contradiction** (one handle in both deltas is refused rather than ordered, because
   the two orders give opposite results), **atomicity** (deltas apply only if the batch
   is accepted in full), and **account ownership** (a batch touches no other account's
   values). Six scenarios carry them, plus one stating that a handle introduced and not
   retained is well-formed and dies with its batch.
2. [P1] **RESOLVED (c) then (b)** at `e6a3a24`+1 — `canonical-load`. The `still_needed` declaration bounds
   retention but the scenario "An account carries more parents than a batch can
   hold" only disclaims. Needs a maintainer decision among: (a) an ordering
   contract — a child is written within N batches of its parent, and a parent
   not re-declared is released, so the caller in 2.4 orders the walk; (b) state
   the bound honestly as "one account's parents" and accept that a single
   pathological account may exceed memory, recording it as a risk; (c) a
   durable spill the adapter owns, which is 3.5's mechanism and leaves the port
   contract as (b). The scenario as written asserts nothing testable and is
   also round 5 finding 3.

   **Maintainer chose (c) then (b).** The port states the bound as one account's
   parents, refuses nothing, and names no mechanism — no ordering contract pushed
   onto callers, and no N no accepted contract establishes. A durable spill is the
   implementation's and belongs to task 3.5. The scenario now asserts that rather
   than disclaiming it, `design.md` carries the residual case as a recorded risk
   and a handoff to 3.5, and the falsification matrix requires proving the port
   refuses nothing and offers no spill.

   **The handoff was not binding until it landed in 3.5's own contract.** Attributing
   the spill to task 3.5 in this change's prose left an obligation nothing would carry:
   bootstrap 3.5's task line said only "bounded batch parsing and PostgreSQL
   COPY-to-staging plus set-based idempotent merges", with no mention of a spill, a
   parent, or correlation. That line now names both obligations this change hands it —
   the durable spill, and paged or streamed candidate access. Text only; its checkbox
   is untouched and stays `[ ]`.
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
