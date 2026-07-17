## Why

Data consumers need repeatable, traceable appraisal data for six North Texas counties, but county publishers expose large, versioned releases through inconsistent file and API formats. A dedicated platform is needed so source acquisition, normalization, validation, and publication can evolve independently without coupling the data contract to one consumer or confusing appraisal values with authoritative tax bills or payment records.

## What Changes

- Create a Python 3.12 uv workspace organized around hexagonal architecture, with thin Airflow DAGs, reusable domain and application libraries, outbound adapters, and an ingestion worker.
- Add source adapters for Dallas, Collin, Tarrant, Denton, Rockwall, and Ellis that discover and acquire official appraisal releases without embedding county logic in orchestration code.
- Preserve immutable source artifacts and release manifests in Amazon S3 before parsing or normalization.
- Normalize county-specific records into a provenance-rich PostgreSQL Silver model keyed by county and source account, then publish validated current and historical Gold datasets.
- Add schema-drift, archive-safety, row-count, key, relationship, and publication-gate controls with quarantine behavior.
- Make GitHub Issues the work-intake system and OpenSpec the accepted-requirements and implementation-planning system.
- Require all six initial county adapters to pass their source-contract and normalization tests before the first six-county Gold release.
- Treat parcel geometry as optional enrichment and defer authoritative tax bills, payments, delinquency, penalties, and interest until tax assessor-collector sources are separately specified.
- Deploy the platform on an independent Akamai Cloud VPS in Dallas with its own Airflow and PostgreSQL services, and make the VPS and attached volume rebuildable from S3-backed evidence and PostgreSQL point-in-time recovery.
- Expose approved Gold data through a lightweight, consumer-neutral Python `appraisal-api`; downstream products integrate through the API or versioned bulk exports rather than direct database access.
- Use the hosted Bitwarden vault as the off-host recovery store for environment secrets while keeping runtime secret injection and rotation separately controlled.

## Capabilities

### New Capabilities

- `source-release-ingestion`: Discovery, immutable acquisition, manifests, idempotency, archive safety, and Airflow orchestration for external releases.
- `county-appraisal-normalization`: County adapter contracts and canonical appraisal normalization for Dallas, Collin, Tarrant, Denton, Rockwall, and Ellis.
- `dallas-cad-source-contract`: Evidence-backed Dallas release discovery, mutable-artifact, schema, identity, privacy, and replacement-snapshot behavior.
- `collin-cad-source-contract`: Evidence-backed Collin PACS Access export discovery, remote-probe, dual-roll, numeric-decoding, identity, and privacy behavior.
- `denton-cad-source-contract`: Evidence-backed Denton PACS fixed-width release discovery, layout-version, grain, value, privacy, and roll-correction behavior.
- `ellis-cad-source-contract`: Evidence-backed Ellis PACS fixed-width certified-roll discovery, scenario-roll exclusion, ODS layout, grain, value, and privacy behavior.
- `rockwall-cad-source-contract`: Evidence-backed Rockwall public GIS source boundaries and the full-appraisal-roll acquisition gate.
- `tarrant-cad-source-contract`: Evidence-backed Tarrant certified pipe-delimited roll behavior, companion-source gates, identity, values, privacy, and replacement semantics.
- `validated-data-publication`: Silver persistence, data-quality gates, quarantine, lineage, and current/history Gold publication.
- `appraisal-query-api`: Versioned read-only access to approved Gold products, provenance, matching evidence, privacy defaults, and bulk-export boundaries.
- `platform-runtime-operations`: Independent Akamai runtime topology, S3 and PostgreSQL recovery, Bitwarden secret recovery, access control, and restore validation.
- `delivery-governance`: GitHub Issue intake, OpenSpec traceability, repository navigation, and required delivery checks.

### Modified Capabilities

None. This is the first change in a new repository.

## Impact

- Introduces a new independent Git repository and deployment boundary.
- Adds Python workspace packages, Airflow DAGs, PostgreSQL migrations, Amazon S3 conventions, a lightweight Python API, deployment automation, tests, documentation, and GitHub Issue forms.
- Requires externalized runtime secrets and an operator-maintained recovery copy in the hosted Bitwarden vault; secret values remain outside Git, images, S3 data buckets, and logs.
- Creates a versioned, consumer-neutral API and bulk-export contract; it does not modify downstream consumer application code in this change.
