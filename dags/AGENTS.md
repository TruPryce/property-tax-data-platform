# DAG Agent Guide

## Rules

- Keep DAG import time fast and free of network or database calls.
- DAG files are inbound adapters; call application/service entry points instead of implementing source logic.
- Pass release IDs and object URIs through XCom, never county files or large record collections.
- Use mapped county tasks, deterministic backfill inputs, bounded concurrency, retries, timeouts, and same-release locking.
- Resolve credentials through Airflow Connections or a secrets backend.
- DAG tests must verify parse/import behavior without contacting official sources.

## Related

- [DAG overview](README.md)
- [Root agent guidance](../AGENTS.md)
