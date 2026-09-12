# Round 1 — both scopes and more (transition record) — findings at d1df8830 (resolved: 7905449)

Reconstructed from the GitHub reviews Devin and Codex posted on PR #120 at
2026-09-03T08:23Z and 08:24Z against the first commit. Unscoped: the findings
fall in three scopes, so this file carries three review-time blocks. Badge
markup and reaction prompts are removed; the text is otherwise verbatim. Line
references are to the reviewed commit.

## Reviewer's report (verbatim)

**Devin Review** found 3 potential issues.

1. 🟡 **Missing identifiers raise the wrong error** (`tasks.md:31`) —
   `CanonicalReleaseRepository.open` only accepts an already-complete
   `ReleaseIdentity`. Missing identifiers fail during identity construction, so
   callers never receive `MissingReleaseIdentifier`. Prompt for agents:
   Reconcile the canonical repository input with the named missing-identifier
   failure. ReleaseIdentity always contains a validated identifier, so
   CanonicalReleaseRepository.open cannot inspect an incomplete ReleaseIdentity
   or raise MissingReleaseIdentifier. Define an application-owned pre-promotion
   input that can represent the three established partition facts plus an
   optional source-established identifier, or move the named failure to the
   explicit promotion operation that constructs ReleaseIdentity. Update the
   requirement, protocol task, and falsification test consistently.
2. 🟡 **Processing runs cannot be created** (`tasks.md:15`) —
   `ProcessingRunRef` represents only an existing run. No application port
   creates one, so orchestration must bypass the boundary before canonical
   persistence can start. Prompt for agents: Add an application-owned
   processing-run lifecycle port or assign run creation to an existing port
   explicitly. The current plan only defines ProcessingRunRef, yet
   CanonicalReleaseRepository, QualityRepository, and PublicationRepository all
   require a reference to a pre-existing ingestion.run. Specify the application
   values needed to create a run from its manifest and release facts, its
   returned ProcessingRunRef, retry behavior, and tests proving orchestration
   never calls an adapter or database API directly.
3. 🟡 **Outcome evidence has no valid type** (`tasks.md:15`) —
   `ReleaseProcessingOutcome` includes diagnostics and notices without defining
   their element types. Implementers must use forbidden adapter types or lose
   the required structured evidence. Prompt for agents: Define the
   application-owned diagnostic and notice value types used by
   ReleaseProcessingOutcome, including their exact fields, bounds, validation,
   and tuple annotations. Specify the adapter mapping from
   property_tax_adapters.release ReleaseDiagnostic and ReleaseNotice. Include
   these values in the public surface and falsification tests, while preserving
   the dependency direction and the existing diagnostic privacy and retention
   invariants.

**Codex Review** — reviewed commit `d1df883047`.

4. P1 **Preserve the complete processing outcome metadata** (`tasks.md:15`) —
   For every prepared release, mapping the existing adapter `ReleaseOutcome`
   into this value drops `boundary_contract_version`,
   `parser_contract_version`, and `layout_fingerprint`. The first is required by
   `ingestion.release_outcome`, while the latter two are the persisted evidence
   identifying the parser contract and layout that produced the result; an
   adapter implementing this plan would therefore have to invent values or
   discard provenance. Include these fields and their existing pairing/version
   invariants in the application-owned outcome.
5. P1 **Define application-owned diagnostic and notice carriers**
   (`tasks.md:15`) — When an outcome contains diagnostics or notices, this task
   specifies only untyped tuples and defines no application-owned element
   types. Reusing `property_tax_adapters.release.ReleaseDiagnostic` and
   `ReleaseNotice` would reverse the required dependency direction, while using
   generic objects would lose the bounded, secret-safe vocabulary and
   validation. Define the carrier types that cross this port so the adapter can
   map its values without making the application depend on adapters.
6. P2 **Preserve page evidence in discovery candidates** (`tasks.md:23`) — For
   sources such as Dallas or Tarrant whose release semantics come from an
   official download page, this candidate shape preserves remote metadata and
   source-as-of evidence but omits the separately required page evidence. The
   accepted `source-release-ingestion` requirement explicitly requires page
   evidence to be preserved before acquisition, so implementing this task would
   leave the discovery use case with nowhere to carry that provenance. Add a
   bounded page-evidence value to `ReleaseCandidate` and its scenarios.
7. P2 **Make the missing-identifier failure reachable** (`tasks.md:31`) — When
   discovery returns a candidate without a release identifier, the planned
   `open()` cannot raise `MissingReleaseIdentifier` as specified because its
   parameter is already a `ReleaseIdentity`; that domain type requires a
   nonblank identifier in `__post_init__`, so no incomplete value can reach the
   repository and the falsification test in task 7.2 cannot call this path.
   Accept an explicitly partial candidate at the promotion boundary, or move the
   named failure to a separate candidate-to-identity operation and update the
   contract and test accordingly.

## Dispositions

1. [P2] RESOLVED — `canonical-load` as filed; the fix moved the failure to
   `registry-and-discovery`. The named error was
   unreachable because `ReleaseIdentity.__post_init__` refuses an incomplete
   value. Fix: promotion from evidence is the one seam where a partial release
   becomes a whole one and raises `IncompleteReleaseIdentity`; the canonical
   port takes a complete identity and has no such branch (D3a; spec
   `source-registry-and-discovery` "Canonical release identity is promoted from
   evidence and fails closed"; task 2.2). Resolving commit: `7905449b6`.
   Pinned by task 7.2: promoting evidence without an identifier raises
   `IncompleteReleaseIdentity` naming the missing component.
2. [P2] RESOLVED — `run-and-manifest`. Fix: `ProcessingRunRepository.start`
   returns the reference and nothing accepts a caller-constructed one (D2c;
   spec `processing-run`; task 1.3). Resolving commit: `7905449b6`. Pinned by
   task 7.2: a reference resolving to no started run is refused.
3. [P2] RESOLVED — `run-and-manifest`. Duplicate of 5. Fix: application-owned
   `ReleaseDiagnosticRecord` and `ReleaseNoticeRecord` (task 1.1). Resolving
   commit: `7905449b6`.
4. [P1] RESOLVED — `run-and-manifest`. Fix: the outcome carries every fact
   `ingestion.release_outcome` requires, including the paired parser version
   and layout fingerprint (D10; spec `processing-run` "The outcome crossing the
   boundary is a lossless representation"). Resolving commit: `7905449b6`.
   Pinned by task 7.2: a parser contract version without a layout fingerprint
   is refused.
5. [P1] RESOLVED — `run-and-manifest`. As 3. Resolving commit: `7905449b6`.
6. [P2] RESOLVED — `registry-and-discovery`. Fix: the candidate carries page
   evidence; expected media types and the new-versus-unchanged distinction were
   restored in the same commit. Resolving commit: `7905449b6`. Superseded in
   shape by round 4 finding 4 (`PageEvidence` fields still unspecified).
7. [P2] RESOLVED — `canonical-load` as filed. Duplicate of 1. Resolving
   commit: `7905449b6`.

## Staleness sweep

Not recorded; the round predates this ledger. The commit body for `7905449b6`
names the five gaps it closed and the whole-account batch design it introduced,
which round 2 then rejected.

## Reviewer's authoritative blocks (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d1df883047b9e88ae0a845062d117faffed3ff04",
	"scope_id": "run-and-manifest",
	"verdict": "REVISE",
	"unresolved_p1_count": 2,
	"unassigned_p2_p3_count": 2
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d1df883047b9e88ae0a845062d117faffed3ff04",
	"scope_id": "canonical-load",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 2
}
```

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "d1df883047b9e88ae0a845062d117faffed3ff04",
	"scope_id": "registry-and-discovery",
	"verdict": "REVISE",
	"unresolved_p1_count": 0,
	"unassigned_p2_p3_count": 1
}
```
