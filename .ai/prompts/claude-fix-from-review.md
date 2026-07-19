# Claude Fix From Review Prompt

Apply only the `BLOCKER` and `MUST_FIX` findings from the Codex pre-PR review file provided by the caller.

Rules:

* Do not expand scope beyond the current branch objective and its referenced GitHub Issue / OpenSpec change.
* Do not implement `NICE_TO_FIX` items unless they are necessary for a blocker/must-fix.
* Preserve the dependency direction `dags/services -> adapters -> application -> domain`; never move county parsing, mapping, or SQL into `dags/`, or vendor (PACS) vocabulary into the domain.
* Do not collapse `(prop_id, owner_sequence)` owner rows, invent canonical value semantics for unresolved source fields (e.g. Dallas `TOT_VAL`), or enable owner/mailing-address publication as part of a fix.
* Never introduce secrets, county source records, or oversized artifacts; fixtures stay small, synthetic or redistribution-safe.
* Keep OpenSpec artifacts valid; check off tasks only for work actually completed and verified.
* Run the smallest relevant deterministic checks after editing: `make lint`, `make typecheck`, `make test`, plus `make docs`, `make spec`, `make secrets`, or `make artifacts` when those areas changed.
* Summarize files changed, checks run, and any remaining risks.
