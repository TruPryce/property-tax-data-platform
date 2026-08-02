# DAG Agent Guide

## Rules

- Keep DAG import time fast and free of network or database calls.
- DAG files are inbound adapters; call application/service entry points instead of implementing source logic.
- Pass release IDs and object URIs through XCom, never county files or large record collections.
- Use mapped county tasks, deterministic backfill inputs, bounded concurrency, retries, timeouts, and same-release locking.
- Resolve credentials through Airflow Connections or a secrets backend.
- DAG tests must verify parse/import behavior without contacting official sources.

- Budget about 1 GiB peak RSS per task: `LocalExecutor` runs tasks inside the scheduler container, under its memory limit.
- Prove a DAG runs with `airflow dags test` before publishing, and report what was not exercised.

## Related

- [DAG overview](README.md)
- [Airflow implementation ways of working](../docs/engineering/airflow-implementation.md)
- [Root agent guidance](../AGENTS.md)
