## Why

Accepted Dallas evidence establishes ACCOUNT_NUM as a 17-character zero-padded account identifier, keeps GIS_PARCEL_ID distinct, uses ACCOUNT_NUM with APPRAISAL_YR as the source row key, and leaves TOT_VAL without approved canonical value semantics. Issue 17 requests a synthetic observed-header parser and typed conversion, but the supplied authoritative evidence does not settle the complete required-header set, delimiter and encoding contract, header-normalization collision behavior, accepted lexical forms, compatible layout fingerprints, or exact vendor-neutral target record. Those choices must not be invented from untrusted issue prose. [source_ids: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5, c83b55e968e3981f0030935d, d253d5455b500dc5f5a9bca6]

## Outcome

Create a draft OpenSpec delta for dallas-cad-source-contract that records the blocking decisions and, once maintainers resolve them, specifies typed Dallas adapter records, deterministic header-name binding, fail-closed layout and row validation, source extras and provenance preservation, approved vendor-neutral conversion, synthetic-fixture coverage, and boundary documentation. The delta must not make the adapter production-ready or add acquisition, persistence, publication, orchestration, infrastructure, or deployment behavior. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0, 05e1317dff1c2a0b0cdc4827]

## Scope

- Originating issue: #17
- CountyForge planning run: `gh-d60959871886b8c59984868c-a2`
- Affected capabilities: dallas-cad-source-contract

## Constraints

- Network and credential boundary: the parser foundation requires no live Dallas endpoint, external retrieval, provider credential, runtime secret, or production connection. [source_ids: ca0df171cabe5f246f2a4fe5, c83b55e968e3981f0030935d]
- Privacy boundary: owner and mailing-address publication remains default-deny, protected identities are never reconstructed, and fixtures and diagnostics must contain no protected identity. [source_ids: ca0df171cabe5f246f2a4fe5, 1f68cbd53a026079a9b30f8d]
- Artifact boundary: no county archive, CSV, appraisal record, owner record, mailing-address data, full release, credential, or secret may be committed. [source_ids: ca0df171cabe5f246f2a4fe5, 12eb90de41980a9b5226022f, 1f68cbd53a026079a9b30f8d]
- Source-license boundary: project-controlled synthetic fixtures and generated demo data are CC0, while third-party county data retains its publisher's terms and receives no redistribution grant from the project license. [source_id: 05e1317dff1c2a0b0cdc4827]
- Semantic safety boundary: appraisal facts must not be represented as authoritative tax bills, payments, delinquencies, penalties, or interest records. [source_ids: c83b55e968e3981f0030935d, a8d0164e015d086c00140812]

## Non-goals

- Live Dallas discovery, download, HTTP probing, or source contact. [source_id: ca0df171cabe5f246f2a4fe5]
- ZIP or archive acquisition, Bronze persistence, immutable source storage, or source-release ingestion. [source_id: ca0df171cabe5f246f2a4fe5]
- PostgreSQL loading, database migration, production backfill, Silver persistence, Gold publication, or release promotion. [source_id: ca0df171cabe5f246f2a4fe5]
- Airflow DAG or ingestion-service orchestration. [source_ids: ca0df171cabe5f246f2a4fe5, c83b55e968e3981f0030935d]
- Owner or mailing-address publication, protected-identity reconstruction, or owner-bearing fixtures and diagnostics. [source_ids: ca0df171cabe5f246f2a4fe5, 1f68cbd53a026079a9b30f8d]
- Canonical child-member publication before natural child keys are approved. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812]
- Cross-county normalization, a shared Dallas-derived base adapter, or a PACS domain abstraction. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812]
- Production deployment or marking the Dallas adapter production-ready. [source_ids: ca0df171cabe5f246f2a4fe5, 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0]
- Authoritative tax-bill, payment, delinquency, penalty, or interest behavior. [source_ids: c83b55e968e3981f0030935d, a8d0164e015d086c00140812]

## Unresolved decisions

- BLOCKING: Maintainers must approve the authoritative required observed headers, delimiter and encoding, header-normalization and collision rules, supported layout fingerprints, quoting behavior, and accepted row-width forms. The issue requests these behaviors but the accepted Dallas evidence supplied here does not define their complete contract. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 37b0be1db5c2ff2ef21f3eae]
- BLOCKING: Maintainers must identify the exact approved vendor-neutral target record and field types, including whether an existing domain type is sufficient and which Dallas facts must remain adapter-only. [source_ids: ca0df171cabe5f246f2a4fe5, 76e21fb4c68b6f87724edaac, a8d0164e015d086c00140812]
- BLOCKING: Maintainers must approve lexical and typed representations for Dallas numeric and date fields, the retained representation of unresolved values such as TOT_VAL, and the exact source-member, header, release, extras, and diagnostic provenance carried by parser output. [source_ids: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0]

This draft requires human maintainer approval before implementation.
