# Round 1 — whole-change review — findings at 51ef6bd, resolved at 1605458

The `canonical-load` scope's review history runs through
[PR #120](https://github.com/TruPryce/property-tax-data-platform/pull/120), where this capability
was one scope of five; that ledger is
[`../../add-application-port-boundary/reviews/`](../../add-application-port-boundary/reviews/) and
is not repeated here. This is the first round against the capability as its own change, reviewed on
that PR's head before the extraction.

## Reviewer's report (verbatim)

> I reviewed exact head `51ef6bdbfde2ef68185228b1ee1ec2c5ba27bfd0`. The task-ID round trip,
> accepted metadata vocabulary, `__enter__` signature, W10 state visibility, W11 account scope, and
> runtime non-suppression requirement are fixed. Both changes now pass the real
> implementation-readiness gate. Three reconciliation defects remain.
>
> **BLOCKER — renumbering the application decisions did not repair their task provenance.** The
> proposal now declares D12–D24, but the parsed task markers cite only D1 and D7–D11. All thirteen
> of D12–D24 are declared and none is present in any task's `decision_prerequisites`. This is the
> same round-5 finding with valid names substituted for invalid ones; the syntax gate passes now,
> but the implementation packet still does not say which work each decision authorizes. Also
> replace the current task prose at `tasks.md:40`, which still cites `D2a and D2c`. If historical
> task references are intentionally preserved, record `1.2b -> 1.3` and old `1.3 -> 1.4` beside the
> decision mapping.
>
> **BLOCKER — one retained W10 scenario still promises acceptance for a retained delta that W9 must
> reject.** The scenario says a batch carrying "one delta value" for S2 and no continuation is
> accepted. A retained value cannot be accepted: W9 requires every retained handle to belong to the
> account named as continuing, and this scenario names none. The later dedicated delta-only
> scenario correctly uses a **released** handle.
>
> **HIGH — D7 and the completion rationale still describe the pre-`closing` model.** D7 still says
> `continuing` alone decides completion; the normative rationale still says S2 plus `continuing`
> are the complete sources, and the design repeats that "continuing already carries it". The
> authoritative table now also permits explicit `closing`, guarded by B10/W12.
>
> **Recommended path.** Make one final mechanical correction for the three items above, then
> extract/accept `add-canonical-load-session` and implement its five tasks without another
> architecture round. Keep `add-application-port-boundary` open for its unresolved scopes, four
> oversized tasks, and repaired D12–D24 provenance. Implementation will now provide better evidence
> than further expansion of the canonical plan.

## Dispositions

1. **[P1] RESOLVED** at `1605458` — task provenance. Each of D12–D24 is attached to the task that
   implements it and to 7.2, which falsifies them; the prose at task 1.2 names D23 and the sibling
   change rather than `D2a and D2c`; the proposal records the task renames beside the decision
   mapping, and the five decisions that *left* rather than moved. Measured, not asserted: every
   declared decision in both changes is cited by at least one task marker, and no task cites one
   that is not declared.

2. **[P1] RESOLVED** at `1605458` — the W10 scenario. The broad "closes by touching" scenario is
   narrowed to one entry; the delta case keeps its own scenario, which uses a released handle.

3. **[P2] RESOLVED** at `1605458` — D7 and both completion rationales state the decision actually
   retained: there is no separate session operation, and `continuing`, `closing` and a legitimate
   touch are signals carried inside one atomic batch.

## Verdict

**ACCEPT**, on the recommended path: the three corrections landed at `1605458`, and this change was
extracted to its own branch and implemented without a further architecture round.

## Found while implementing

One correction the implementation forced, recorded here because the suite is evidence and the spec
had claimed something it could not deliver. `W8` was listed in the falsification matrix as a
refusal, and it has **no reachable counterexample**: `W9` confines a retained handle to the
continuing account, the success transition sweeps the rest at completion, and `W7` confines a
release to what is live, so `S4` only ever holds the open account's handles and the attempt lands on
`W9` first. The spec and the matrix now state `W8` as the invariant it guards, and the suite proves
that invariant rather than a refusal it cannot produce.

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "51ef6bd",
	"scope_id": "canonical-load",
	"verdict": "ACCEPT",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 0
}
```
