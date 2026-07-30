## Why

Accepted Dallas behavior establishes a distinct delimited source, preserves `ACCOUNT_NUM` as a 17-character zero-padded account identifier distinct from `GIS_PARCEL_ID`, uses `(ACCOUNT_NUM, APPRAISAL_YR)` as the source row join key, and leaves `TOT_VAL` without approved canonical value semantics. Issue #17 requests typed source records, observed-header parsing, neutral translation, duplicate rejection, extras retention, and deterministic failures, but the packet does not approve the exact layout grammar, record contracts, duplicate-detection scope, or privacy treatment for unknown extras. Selecting those details would invent source behavior from untrusted issue prose. Sources: a8d0164e015d086c00140812, ca0df171cabe5f246f2a4fe5, 37b0be1db5c2ff2ef21f3eae.

## Outcome

Create one issue-linked OpenSpec delta for `dallas-cad-source-contract` that records the blocking decisions and, after human approval, governs adapter-local Dallas source records, deterministic header-name parsing, provenance, privacy-safe source extras, translation into an approved vendor-neutral contract, fail-closed validation, synthetic fixtures, contract tests, and documentation. The change must not imply that the Dallas adapter is production-ready or add acquisition, persistence, publication, orchestration, or deployment behavior. Sources: fc02f32a50f16c9ec430bd1b, ca0df171cabe5f246f2a4fe5, 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0.

## Scope

- Originating issue: #17
- CountyForge planning run: `gh-2ce3b2689100ce2b0b00d2c8-a1`
- Affected capabilities: MODIFIED `dallas-cad-source-contract` — add only the eventually approved parser-foundation requirements for typed records, observed-header handling, provenance, source extras, deterministic failures, privacy, fixtures, and testing while preserving existing Dallas identity and unresolved-value semantics. Sources: fc02f32a50f16c9ec430bd1b, a8d0164e015d086c00140812.

## Constraints

- The planned implementation adds no source download, network access, credentials, authentication, provider, workflow, infrastructure, or production-configuration behavior. Source: ca0df171cabe5f246f2a4fe5.
- Owner names and mailing addresses remain default-deny for publication, protected identities are never reconstructed, and diagnostics must not echo raw sensitive row values. Sources: b34baeeecb2d6f95937ce5a1, a8d0164e015d086c00140812.
- Only small synthetic or redistribution-safe fixtures may be committed; secret scanning and county-source artifact checks remain blocking gates. Sources: 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f.
- Appraisal facts must not be represented as authoritative tax bills, balances, payments, delinquencies, penalties, or interest. Sources: c83b55e968e3981f0030935d, b34baeeecb2d6f95937ce5a1.

## Non-goals

- Live Dallas discovery, HTTP probing, download, or archive acquisition. Source: ca0df171cabe5f246f2a4fe5.
- Bronze persistence, source-release state transitions, or full-release ingestion. Source: ca0df171cabe5f246f2a4fe5.
- PostgreSQL loading, schema migrations, Silver persistence, Gold publication, or backfill. Source: ca0df171cabe5f246f2a4fe5.
- Airflow orchestration or service-composition work. Sources: ca0df171cabe5f246f2a4fe5, c83b55e968e3981f0030935d.
- Owner or mailing-address publication or protected-identity reconstruction. Sources: ca0df171cabe5f246f2a4fe5, b34baeeecb2d6f95937ce5a1.
- Canonical child publication before natural child keys are approved. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812.
- Cross-county normalization or a shared Dallas/PACS base abstraction. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812.
- Authoritative tax-bill, payment, balance, delinquency, penalty, or interest behavior. Sources: c83b55e968e3981f0030935d, b34baeeecb2d6f95937ce5a1.
- Production deployment or a `production_ready` designation for Dallas. Sources: ca0df171cabe5f246f2a4fe5, 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0.

## Unresolved decisions

- D1 — Approve the exact Dallas member and delimited-layout contract: member selection, encoding and BOM behavior, delimiter, quoting and escaping, line endings, header normalization, required observed headers, permitted aliases, null representation, row-width behavior, and accepted numeric and date forms. The supplied authoritative context does not establish this complete grammar. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 37b0be1db5c2ff2ef21f3eae.
- D2 — Approve the exact typed Dallas source-record and vendor-neutral record fields, types, semantics, provenance representation, and owning packages, including whether an existing accepted neutral type is reused or a separate shared-capability change is required. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac.
- D3 — Approve whether `(ACCOUNT_NUM, APPRAISAL_YR)` uniqueness is enforced per member or per logical release and select a state strategy compatible with bounded record streaming. An unbounded key set and batch-only duplicate checking have materially different correctness and resource behavior. Sources: ca0df171cabe5f246f2a4fe5, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0.
- D4 — Approve the classification, retention, suppression, and diagnostic-redaction policy for unknown source extras, especially owner, mailing-address, and protected-identity fields. The issue requests extras retention, while accepted privacy behavior is default-deny for owner and mailing-address publication. Sources: ca0df171cabe5f246f2a4fe5, b34baeeecb2d6f95937ce5a1, a8d0164e015d086c00140812, 7676ed46a8bb877ba7fdaac0.

This draft requires human maintainer approval before implementation.
