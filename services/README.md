# Services

Services are deployable composition roots and inbound interfaces. They assemble application ports with concrete adapters but do not own reusable domain behavior.

| Service | Purpose |
|---|---|
| [`ingestion-worker`](ingestion-worker/README.md) | CLI/task runtime for source discovery and ingestion use cases |

## Related

- [Service agent guidance](AGENTS.md)
- [Shared libraries](../libs/README.md)
- [DAGs](../dags/README.md)
