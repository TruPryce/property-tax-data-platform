## 1. Repository Foundation

- [x] 1.1 Create the Python 3.12 uv workspace with domain, application, adapter, and ingestion-worker src-layout packages
- [x] 1.2 Add root and area README.md and AGENTS.md navigation with hexagonal dependency rules
- [x] 1.3 Add GitHub Issue forms, pull-request traceability, and the documented OpenSpec delivery workflow
- [x] 1.4 Add Ruff, mypy, pytest, architecture, OpenSpec, and documentation-link validation commands
- [x] 1.5 Add continuous integration that runs the documented validation commands from a clean uv environment
- [x] 1.6 Add uv-managed pre-commit hooks and CI-enforced secret scanning with a reviewed baseline
- [x] 1.7 Add pre-commit and CI checks that reject tracked county source artifacts and unknown large binaries using path, size, content, and extension rules with a reviewed safe-fixture allowlist
- [x] 1.8 Add the strict packet-only pre-PR reviewer profile with deterministic packet generation, read-only container boundaries, versioned evidence and observability contracts, no-cost CI contract tests, and an explicitly opt-in paid-provider smoke test

## 2. Domain and Application Core

- [ ] 2.1 Implement county, release identity, artifact identity, release status, and provenance domain types
- [ ] 2.2 Implement canonical account, owner, value, exemption, jurisdiction, land, improvement, and geometry record types
- [ ] 2.3 Define source discovery, artifact storage, manifest, canonical repository, quality, publication, and clock ports
- [ ] 2.4 Implement discover, acquire, parse, normalize, validate, and publish use cases with idempotent stage boundaries
- [ ] 2.5 Add state-machine, identity, canonical-grain, and dependency-direction tests

## 3. Bronze and Silver Infrastructure

- [ ] 3.1 Implement streaming HTTP acquisition with remote metadata, SHA-256 calculation, and partial-object cleanup
- [ ] 3.2 Implement the Amazon S3 Bronze adapter behind the S3-compatible port and persist immutable release manifests
- [ ] 3.3 Implement archive inspection and extraction limits for traversal, expansion, compression ratio, members, and media types
- [ ] 3.4 Create PostgreSQL release-manifest, Silver canonical, diagnostic, quality-result, and publication metadata migrations
- [ ] 3.5 Implement bounded batch parsing and PostgreSQL COPY-to-staging plus set-based idempotent merges
- [ ] 3.6 Add containerized object-store and PostgreSQL integration tests for retry, conflict, quarantine, and rollback behavior

## 4. County Source Contracts and Adapters

- [ ] 4.1 Capture the currently available Tarrant release and preserve current official page metadata for all six counties in non-production storage before mutable publications are replaced
- [ ] 4.2 Reproduce the Dallas spike manifest in isolated Bronze storage, capture redistribution-safe fixtures, resolve the reviewed downloader findings, and implement the ZIP/delimited adapter against the Dallas source contract
- [ ] 4.3 Reproduce the Collin evidence from commit `e776260` in this repository, create a record-free evidence manifest, and capture independently derived redistribution-safe Access schema and NUMERIC fixtures without importing or modifying the exploratory spike code
- [ ] 4.4 Select and benchmark the Collin Access runtime, resolve the account key and ownership policy, and implement the PACS Access adapter without silently switching to Texas Open Data
- [ ] 4.5 Reproduce the corrected Denton evidence from `798e966`, create an exact-time record-free archive/layout manifest, verify layout compatibility and strict truncation handling, preserve owner-sequence and undivided-interest allocations, confirm preliminary-to-certified semantics, profile the nightly source and confidentiality scope, and implement the fixed-width adapter
- [ ] 4.6 Reproduce the corrected Ellis evidence from `798e966`, independently fingerprint its PACS and ODS compatibility, contract-test plain-roll versus RC2 discovery, preserve owner-sequence and undivided-interest allocations, and implement a thin Ellis adapter over the shared fixed-width component
- [ ] 4.7 Submit an official Rockwall full-appraisal-roll request, record terms and delivery provenance, profile the resulting source under a contract update, and keep the public shapefile source optional and separately labeled
- [ ] 4.8 Reproduce Tarrant evidence from `89584f7` and `ac356ee`; record the exact retrieval instant, full header fingerprint, tool versions, and committed key/division/value aggregates; enforce exactly-one-member resolution; profile current and exemption archives, replacement behavior, identity stability, value semantics, and confidentiality; then implement the pipe-delimited adapter
- [ ] 4.9 Resolve Dallas `TOT_VAL` and related component semantics through official clarification and measured arithmetic before approving canonical value mapping
- [ ] 4.10 Statistically validate required Dallas child keys, confirm a second Dallas certification/supplemental year, approve PACS undivided-interest account roll-up rules, and approve field-level owner, mailing-address, and situs publication policies for all six counties
- [ ] 4.11 Add contract, normalization, provenance, member-resolution, field-boundary, schema-drift, redirect-safety, scenario-roll, immutable-artifact, numeric-decoder, resource-bound, and idempotency tests for all six adapters
- [ ] 4.12 Add a cohort-readiness check that requires every initial adapter before a complete six-county publication

## 5. Orchestration and Operations

- [ ] 5.1 Implement ingestion-worker CLI entry points and dependency composition using externalized configuration
- [ ] 5.2 Implement thin Airflow 3.3 TaskFlow DAGs for scheduled discovery, mapped county processing, and explicit backfills
- [ ] 5.3 Configure concurrency, retries, task timeouts, release-level locking, and XCom-safe identifiers
- [ ] 5.4 Add structured logs, run metrics, freshness metrics, failure diagnostics, and secret redaction
- [ ] 5.5 Document environment connection names, deployment prerequisites, runbooks, and release recovery procedures
- [ ] 5.6 Provision the Akamai Dallas Ubuntu 24.04 runtime with Tailscale administration and isolated PostgreSQL, Airflow, worker, and API roles
- [ ] 5.7 Configure encrypted S3 locations for Bronze, exports, remote logs, PostgreSQL physical backups, and WAL with least-privilege policies and lifecycle rules
- [ ] 5.8 Implement backup and WAL schedules, lag and age alerts, integrity checks, and recorded point-in-time restore exercises
- [ ] 5.9 Automate and exercise a clean-host rebuild, accept RPO/RTO and retention, and only then disable the Linode backup add-on
- [ ] 5.10 Document the Bitwarden recovery inventory, owners, rotation, runtime injection, and audited break-glass procedure without storing secret values in the repository

## 6. Quality, Gold, and Consumer Contract

- [ ] 6.1 Implement configurable blocking and warning quality rules with persisted measurements and quarantine decisions
- [ ] 6.2 Implement atomic latest-available, latest-certified, and history Gold publications with deterministic precedence
- [ ] 6.3 Implement county-qualified consumer property bridge output with match method, confidence, and evidence
- [ ] 6.4 Implement explicitly labeled estimated-tax output only when validated rate inputs exist
- [ ] 6.5 Backfill the agreed historical years and reconcile county counts and values against official summaries
- [ ] 6.6 Run consumer acceptance, publish the versioned data contract, and record production promotion or rollback evidence
- [ ] 6.7 Implement `appraisal-api` with a read-only Gold role, versioned OpenAPI, county-qualified account lookup, explicit latest/certified/history selectors, lineage, freshness, health, and stable errors
- [ ] 6.8 Enforce default-deny sensitive fields, service authentication, TLS, rate limits, request correlation, and bounded interactive queries
- [ ] 6.9 Publish versioned S3 bulk exports and a typed consumer client contract; validate TruPryce integration without direct database access
