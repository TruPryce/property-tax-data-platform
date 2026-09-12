# Round 5 — all five scopes (transition record) — findings at 67107035 (open)

A read-only review of the same head Codex reviewed in round 4, performed on
2026-09-06 in the Claude Code session that split the spec and started this
ledger. Unscoped, so it carries one block per scope. Findings that duplicate
round 4 are noted, not counted twice. Line references are to the reviewed
commit unless a split-file path is given.

## Reviewer's report

1. P1 **Adoption contradicts the accepted snapshot grain** — the same defect as
   round 4 finding 1, confirmed against the accepted
   `canonical-silver-persistence` requirement "Snapshot grain admits divergent
   evidence", which says the grain "SHALL NOT be expressed as a uniqueness
   constraint". D2q's phrase "which the accepted contract fixes as exactly that
   snapshot's grain" is true of the grain and false of a key. Not counted again
   here.
2. P2 **Task prerequisites cite decisions that do not exist, and skip the ones
   that do** — tasks cite only `D1`–`D11`; the eighteen decisions added during
   review (`D2a`–`D2q`, `D3a`) are cited by no task; tasks 2.1 and 2.2 cite
   `D1`, which is about the run, for registry and discovery work; task 1.2
   cites `D1` and `1.1` for work that D2f, D2g, D2h, and D2i decide. The
   trusted implementation tooling's prerequisite grammar is `^D[0-9]{1,3}$`
   (`tools/countyforge-github/src/countyforge_github/implementation.py`), so a
   lettered decision id cannot be cited at all under the machine path; the
   letters exist only because decisions were inserted between numbers as
   rounds went by.
3. P3 **Eight scenarios assert nothing observable** — each is phrased as the
   boundary being "examined" or "inspected" and concludes with a property
   rather than an outcome a test can observe. After the split:
   `application-port-boundary/spec.md:13`, `source-registry-and-discovery/spec.md:37`,
   `acquisition-manifest-index/spec.md:114`, `canonical-load-session/spec.md:98`,
   `:136`, `:153`, `run-bound-quality-and-publication/spec.md:27`, `:59`. The
   canonical-load one at `:98` is the oversized-parent disclaimer round 4
   finding 2 already names.
4. P2 **Seven tasks exceed the task bound** — the trusted materializer renders
   at most 2,048 characters of task text (`planning.py`); measured at the
   reviewed commit: 1.2 (8,024), 7.2 (5,581), 3.1 (4,521), 1.1 (3,184), 3.2
   (3,159), 2.2 (2,954), 2.1 (2,083). Task 7.2 is one item holding roughly
   fifty assertions across every scope, so no scope can claim its proof without
   claiming all of them.
5. P2 **Two tasks write outside the issue's non-goals with no scope-policy
   entry** — task 1.2 edits `objectstore/s3.py` and its tests; task 2.1 edits
   all six county modules. Issue #119 lists adapter and county changes as
   non-goals, the plan argues bounded exceptions, and
   `.ai/policies/countyforge-planning-scope.v1.json` has no entry for issue
   119, so under the trusted path both would be refused. The storage-grain
   half of task 1.2 (the `acquisition-manifest-index` requirement "An
   acquisition manifest is stored at acquisition grain", 12 scenarios) is a
   redesign of a shipped adapter's keying and version, which is a separate
   issue's worth of change.
6. P3 **The PR body narrates closure that the head contradicts** — it says
   "Third round — two blockers plus three corrections, all closed"; a fourth
   round with three P1 and one P2 was open at the reviewed commit.
7. P3 **The change carried no `.openspec.yaml`** — every other issue-backed
   change declares schema, created, issue, parent, and capability.
8. P3 **Design question, not a defect** — the correlation-handle protocol
   (`CorrelationHandle`, `CorrelatedRecord`, `continuing`, `still_needed`,
   strictly increasing handles, adoption, object-identity checks) is now the
   most complex contract in the boundary and prescribes 2.4's bookkeeping. An
   alternative the design does not weigh: the port accepts records whose
   parents are object references, the caller obeys a one-open-account rule,
   and key resolution is 3.5's mechanism, with no handle vocabulary crossing
   the port. Rounds 2–4 all found holes in the handle mechanism; the
   alternative removes the mechanism rather than patching it.

## Dispositions

1. [P1] — `canonical-load`. See round 4 finding 1; disposition recorded
   there. Not counted in this round's block.
2. [P2] UNRESOLVED — `surface-and-proof`, because the fix is a tasks-metadata
   sweep across every group. Needs: renumber the decisions in `proposal.md` to
   plain `D<n>` in dependency order, then re-derive every task's
   `prerequisites=` from the decisions its text actually rests on. A checker
   that every cited decision exists is one line in a future guard.
3. [P3] UNRESOLVED — filed per scope (see the blocks): `surface-and-proof` for
   the umbrella scenario, `registry-and-discovery`, `run-and-manifest`
   (manifest index), `canonical-load` (three), `quality-publication-clock`
   (two). Needs: each rewritten so the THEN names an observable outcome (a
   test that fails, a refusal with a name, a value that is present), or
   deleted where the requirement text already states the property.
4. [P2] UNRESOLVED — `surface-and-proof`. Needs: split 7.2 into one
   falsification task per scope, and split 1.1, 1.2, 3.1, 3.2, 2.1, 2.2 at
   their natural seams (1.2 is at least three tasks: the value corrections, the
   serializer and version, the storage grain and its hostile tests). The
   per-scope proof tasks then move inside their scopes.
5. [P2] UNRESOLVED — `run-and-manifest` (task 1.2), with task 2.1 in
   `registry-and-discovery`. Needs a maintainer decision: add issue 119 to the
   scope policy with `libs/property-tax-application/`,
   `libs/property-tax-adapters/src/property_tax_adapters/objectstore/`, and
   the six county modules as write roots, or cut the storage-grain redesign
   into its own change under its own issue and leave task 1.2 with the value
   and serializer corrections only.
6. [P3] UNRESOLVED — `surface-and-proof`. Needs: the PR body replaced by a
   short summary that links to `reviews/README.md` for round and scope status.
7. [P3] RESOLVED — `surface-and-proof`. `.openspec.yaml` added in the commit
   that introduced this ledger.
8. [P3] UNRESOLVED — `canonical-load`. A question for the maintainer, recorded
   so the next scope-bound round on `canonical-load` answers it explicitly
   rather than reviewing the handle mechanism again by default.

## Out of scope

Nothing; every finding above is filed under a scope.

## Staleness sweep

Not applicable: this round changed no spec authority. The split that
accompanies it moved every requirement verbatim and was verified by
reassembly (21 requirements, 93 scenarios before and after).

## Reviewer's authoritative blocks (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "run-and-manifest",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 2
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

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "canonical-load",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 2
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "quality-publication-clock",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 1
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "67107035918a9db72ee6581c35f3c3a77f3c76c9",
	"scope_id": "surface-and-proof",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 4
}
```
