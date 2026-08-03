# Airflow Implementation Ways of Working

How an agent implements work that will run on the Airflow runtime. It assumes the runtime described
in [Runtime infrastructure](../../infra/README.md) and the DAG boundary in
[DAG agent guidance](../../dags/AGENTS.md), and it exists because that runtime imposes limits that
are not visible from the repository alone.

## The Runtime You Are Targeting

A single 15 GB host running `LocalExecutor`. There is no Celery worker: **task processes are children
of the scheduler container and are bounded by its memory limit**, currently 4 GiB. A task that
exceeds it is OOM-killed, and the scheduler dies with it.

| Setting | Value | Consequence |
|---|---|---|
| `AIRFLOW__CORE__EXECUTOR` | `LocalExecutor` | tasks run inside the scheduler container |
| `mem_limit` (scheduler) | 4 GiB | the ceiling for all concurrent tasks combined |
| `AIRFLOW__CORE__PARALLELISM` | 4 | up to four task processes share that ceiling |
| `AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG` | 2 | two concurrent tasks per DAG |
| `AIRFLOW__CORE__MAX_ACTIVE_RUNS_PER_DAG` | 1 | no overlapping runs of the same DAG |

**The scheduler's own footprint comes out of that same 4 GiB before any task runs.** Measured on the
deployed runtime it sits at 288 MiB idle with a 400 MiB peak, so the budget is not `4096 / 4`:

```text
(4096 MiB limit - 400 MiB scheduler) / 4 concurrent tasks ≈ 900 MiB peak RSS per task
```

**Budget 900 MiB peak RSS per task at the current parallelism of 4.** Four tasks each sitting on a
full 1 GiB would exceed the container limit and take the scheduler down with them, which is the
failure mode where every task passes its own benchmark and the runtime still dies.

A task that genuinely needs more memory buys it by lowering `AIRFLOW__CORE__PARALLELISM` — at 3 the
same arithmetic allows about 1.2 GiB each. Make that trade deliberately in the pull request rather
than discovering the ceiling in production, and re-measure the scheduler baseline if it grows.

`dags/` is mounted read-only at `/opt/airflow/dags`. DAG code cannot write beside itself. Remote
logging is off, so task logs land in a named volume and are not durable — do not treat them as
evidence that survives the host.

## Memory Is Part of the Interface

`libs/property-tax-adapters/AGENTS.md` requires streaming and forbids materializing a county release.
That rule has a measurable cost behind it. A parser that accepts whole-file `bytes` and returns a
`tuple` of records retains roughly **18x the input size**, with process RSS around **58x**, scaling
linearly. A 160 MiB county release becomes about 3 GiB retained and considerably more resident —
well past the 4 GiB ceiling, before any other task runs.

So an API shape is a runtime decision:

```python
# Cannot run on this runtime for a real release.
def parse(content: bytes, ...) -> tuple[Record, ...]: ...

# Bounded regardless of release size.
def parse(lines: Iterable[str], ...) -> Iterator[Record]: ...
```

Prefer returning one representation. Returning both a source-native and a vendor-neutral record for
every row doubles peak memory for a conversion the caller may not need.

**Measure peak RSS, not traced allocations.** The OOM killer reads resident set size, so that is what
the budget is denominated in. `tracemalloc` counts only allocations the Python allocator made and
still tracks: it misses native extension buffers, memory-mapped files, child processes such as
Access tooling, and freed-but-unreturned arena memory. The gap is not marginal — the measurement
behind the numbers above reported 663 MiB traced against 2,079 MiB resident for the same run, a
factor of three. Evidence gathered with `tracemalloc` alone can sit comfortably under 1 GiB while the
task is killed at 2 GiB.

```python
import resource

def peak_rss_bytes() -> int:
    """Peak RSS of this process and any child it waited on, in bytes."""
    this = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return max(this, children) * 1024  # ru_maxrss is KiB on Linux
```

`ru_maxrss` is a high-water mark, so read it after the work rather than around it, and note that
`RUSAGE_CHILDREN` only accounts for children that have been reaped.

Inside a container the cgroup is the authority, because it is what the limit is enforced against:

```bash
cat /sys/fs/cgroup/memory.peak      # cgroup v2, bytes
```

Run against a synthetic input at least as large as the real release, not a fixture, and report the
number in the pull request.

## Where Code Lives

DAG files stay thin inbound adapters, per `dags/AGENTS.md`. The practical test: **the function a task
calls must be importable and unit-testable without Airflow installed.** If a behaviour can only be
tested by running a DAG, it is in the wrong place.

Keep county parsing, SQL, and business rules in `libs/` and `services/`. XCom carries release
identifiers and object URIs, never records.

## Tests Only Count If CI Collects Them

The root `pyproject.toml` sets `testpaths = ["tests"]`, and CI runs `uv run pytest`. **Tests under
`libs/*/tests` are not collected.** A suite that passes only under an explicit `uv run --package …`
invocation is unprotected: nothing will fail when someone breaks it.

Adding tests is not done until the gate runs them. Either place them where CI collects them or extend
the collected paths in the same change, and show the collected count in the pull request.

Every Airflow-touching change needs, at minimum:

- a DAG import test asserting the file parses with no import errors and no network or database access
  at import time;
- unit tests for the callable the task invokes, independent of Airflow;
- for release-processing code, the memory measurement above.

## Secrets and Connections

Runtime secrets come from Bitwarden through `infra/scripts/compose-with-bitwarden.sh` into the
container environment. In DAG and task code:

- never read a secret from a file in the repository, and never add one to `infra/.env`, which is the
  Compose interpolation namespace rather than a secret store;
- never write a secret into an Airflow Variable — Variables are visible in the UI and in exports;
- resolve database and object-store credentials through Airflow Connections.

Rotating a secret in Bitwarden does not reach a running system on its own. If a change introduces a
new credential, it also owns the runbook step that applies a rotation.

## Failure Behaviour

**The county source contracts are normative here, and this document is not.** Quarantine in the
accepted specs is release-level, not row-level. A malformed non-null Collin NUMERIC value quarantines
the affected logical release rather than the row
([`collin-cad-source-contract`](../../openspec/changes/bootstrap-six-county-appraisal-platform/specs/collin-cad-source-contract/spec.md)),
and Dallas, Tarrant, Denton, Ellis, `source-release-ingestion`, and `validated-data-publication` all
quarantine the release or artifact. No accepted spec permits dropping a row and continuing.

So the default is: **a release is loaded whole or not at all.** Diagnostics record which rows failed
and why; they do not license loading the rest. Converting a malformed source value to null is
specifically prohibited.

Where a contract carves out an exception it says so — Denton marks a field absent or incompatible
according to the approved mapping and quarantines the release only when the field is required. Read
the relevant county contract before choosing behaviour, and if a release genuinely should survive
partial failure, that is a change to the contract rather than a decision to make in the adapter.

Set retries, task timeouts, and same-release locking explicitly. Diagnostics carry stable codes,
normalized field names, and row numbers, never source values.

## Exercising Work on the Runtime

Static review does not catch what only appears at runtime. A merged change in this repository shipped
three healthchecks that could never pass and an initialization gate that could never fail, all of
which read correctly and none of which had been run.

DAG changes are picked up by the DAG processor from the read-only mount. From the repository root on
the runtime host:

```bash
./infra/scripts/compose-with-bitwarden.sh exec airflow-scheduler airflow dags list
./infra/scripts/compose-with-bitwarden.sh exec airflow-scheduler airflow dags list-import-errors
./infra/scripts/compose-with-bitwarden.sh exec airflow-scheduler airflow dags test <dag_id> <logical_date>
```

`airflow dags test` executes a full run in-process without scheduling it, which is the cheapest way to
prove a DAG actually runs. The `airflow-cli` service exists under the `debug` profile for ad-hoc
commands.

New DAGs are paused at creation (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION`), so merging one does
not start it. Unpausing is a deliberate operator step.

## Definition of Done

A pull request that touches Airflow-executed code states, with evidence rather than assertion:

1. the commands run and their actual output, including the collected test count;
2. peak memory for the largest realistic input, if it processes a release;
3. what was exercised on the runtime and what was not, named specifically;
4. which OpenSpec tasks the change completes, checked off in `tasks.md`;
5. any operator action the change depends on that is not in the repository.

"Not run" is an acceptable answer. An unlabelled gap is not.

## Related

- [Runtime infrastructure](../../infra/README.md)
- [DAG agent guidance](../../dags/AGENTS.md)
- [Adapter agent guidance](../../libs/property-tax-adapters/AGENTS.md)
- [Operations](../operations/README.md)
