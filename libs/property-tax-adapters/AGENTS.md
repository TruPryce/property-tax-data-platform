# Adapter Agent Guide

## County Sources

- Use only verified official bulk, API, or GIS endpoints.
- Preserve original artifacts and source provenance before normalization.
- Keep format mappings in the county module or versioned mapping assets, never `.env` aliases.
- Stream downloads and records; do not materialize county releases as lists or whole-file dataframes.
- Paginate deterministically and reconcile authoritative counts when available.
- Fingerprint layouts and quarantine incompatible drift instead of guessing.
- Keep all six county adapters behind the same application port and contract-test suite.
- Mark `production_ready` only after the corresponding OpenSpec tasks are verified.

## Fixtures

Commit only small synthetic or redistribution-safe fixtures. Document their source layout and checksum; never commit full county releases or protected owner data.

## Related

- [Adapter overview](README.md)
- [Source reference](../../docs/sources/README.md)
- [Root agent guidance](../../AGENTS.md)
