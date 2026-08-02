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

**Budget roughly 1 GiB peak RSS per task.** If a task needs more, reduce parallelism deliberately and
say so in the pull request; do not discover the limit in production.

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

**Measure before claiming.** For any code that processes a county release, include the numbers in the
pull request:

```python
import tracemalloc
tracemalloc.start()
consume(parse(source))
current, peak = tracemalloc.get_traced_memory()
```

Run it against a synthetic input at least as large as the real release, not a fixture.

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

Adapters are required to quarantine incompatible drift rather than guess. For a release of hundreds
of thousands of rows, aborting the whole file on the first bad row means one malformed record costs
the entire ingestion. Separate the two cases explicitly:

- **layout drift** — header changes, encoding failures, width mismatches — fails the release closed;
- **row-level rejection** — a single unparseable row — quarantines that row with a bounded diagnostic
  and lets the release continue.

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
