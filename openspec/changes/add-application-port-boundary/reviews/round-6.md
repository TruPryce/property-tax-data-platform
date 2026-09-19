# Round 6 — run-and-manifest scope — findings at e960fe69 (resolved: this commit)

Codex review requested on PR #120 at 2026-09-06T13:31Z and posted at 13:35Z
against the head that split the spec and started this ledger. One finding,
in one scope. Badge markup and reaction prompts removed; text otherwise
verbatim.

## Reviewer's report (verbatim)

**Codex Review** — reviewed commit `e960fe697`.

1. P1 **Return the existing active run to retried workers**
   (`specs/processing-run/spec.md:20`) — When a worker crashes after
   `start()` commits but before `finish()`, `ingestion.run.finished_at`
   remains null, and this rule makes every retry refuse that active run while
   exposing no lookup, reuse, or stale-run recovery operation for obtaining
   its opaque `ProcessingRunRef`. The release is therefore permanently
   wedged—or requires an out-of-band database repair—instead of resuming from
   the committed run as required by `source-release-ingestion/spec.md:80-85`;
   make the atomic start operation return/reuse the active run or add an
   explicit recovery path.

## Dispositions

1. [P1] RESOLVED — `run-and-manifest`. Confirmed: `ingestion.run` carries
   only `started_at` and `finished_at`, no accepted spec names a lease or
   stale-run concept, and the requirement's "active" meant "unfinished", so a
   dead worker wedged its release behind a database edit. Fix: the rule is
   about a run being *held*, not about `finished_at`. A run held by a live
   worker refuses, atomically, which keeps the accepted overlap scenario. An
   unfinished run whose holder is gone is resumed by `start`, which returns the
   existing reference in a `ProcessingRunStart` with `resumed=True`, exactly
   one of two racing retries winning; the load's own `already_complete` result
   (D4) then says whether the load had already happened, so both crash cases
   resume from the last verified stage without a second run loading the
   release again. A finished run starts a new run. Holding's representation
   stays 3.5's — a connection-scoped lock that dies with its worker, or a lease
   the holder renews — with a partial unique index over unfinished runs named
   as insufficient on its own because it encodes the wedging rule. Reaches:
   spec `processing-run` (requirement text; scenarios "A second run is started
   for a release already running", "A worker is gone before it recorded
   completion", "A retried worker resumes after the load committed", "Two
   retried workers race for one abandoned run", "A run is started after the
   previous one finished"); proposal D2o; design ("Who creates a run",
   "Retry, and the shape of the answer", the boundary diagram, two rejected
   alternatives, one risk, the 3.5 handoff); tasks 1.3 and 7.2. Pinned by task
   7.2: a run whose holder is gone is resumed with the same reference, two
   racing retries see one resume and one refusal, and the resumed run's
   completed load returns `already_complete=True`. Resolving commit: this
   commit.

   The alternative the finding offers first — returning the active run to any
   caller — is recorded as rejected: it recovers from a crash by letting two
   live workers share one run, which fails the overlap scenario and puts two
   workers' outcomes under one run.

## Out of scope

Nothing.

## Staleness sweep

Swept every authority for the value patterns `active run`, `no longer
active`, `previous run has finished`, `overlap`, and `start(` after the fix.
Remaining occurrences of "active" are the accepted contract's own phrase
"overlapping active runs", quoted where the requirement cites it. The
`design.md` "The order of the seams" and "From an acquisition to a run"
diagrams still show `start` yielding `ProcessingRunRef`; the reference is
what flows on, carried inside the start result, so they stand. The
cross-spec contract matrix row for `ProcessingRunRef`, `ProcessingRunRepository`
gains nothing: `ProcessingRunStart` is a value under the same owner.

## Reviewer's authoritative block (at review time)

```json
{
	"contract": "preimplementation-review-v2",
	"reviewed_commit": "e960fe6972ca6348e3b60312e56cae55d7f03d7f",
	"scope_id": "run-and-manifest",
	"verdict": "REVISE",
	"unresolved_p1_count": 1,
	"unassigned_p2_p3_count": 0
}
```
