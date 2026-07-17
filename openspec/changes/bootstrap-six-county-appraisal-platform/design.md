## Context

The platform begins as an independent, consumer-neutral repository. The initial sources publish large ZIP, delimited, fixed-width, API, and GIS-oriented datasets with county-specific layouts and release semantics. The system must preserve raw evidence, normalize without losing one-to-many relationships, and distinguish appraisal information from tax collection information.

The primary stakeholders are platform maintainers, data engineering, operations, and downstream data consumers. GitHub Issues provide intake and prioritization; OpenSpec provides the accepted behavioral contract and implementation plan.

A Dallas source-contract spike completed on 2026-07-16 and was reviewed at commit `50ab86e`. It acquired a 2026 proposed current archive, a 2025 certified-with-supplemental current archive, and the dated 2025 certified archive. This design treats the spike as evidence, not as production code to copy unchanged.

A Collin source-contract spike completed on 2026-07-16 and was reviewed at commit `e776260`. Its measured source conclusions and official export documentation are reflected here. The spike branch is immutable evidence, not a delivery branch: its exploratory code will not be repaired, promoted, imported, or used as the base of the production implementation. Manifest reproduction and source-record verification in this repository remain production-readiness gates.

Denton, Ellis, and Rockwall evidence was reviewed at commits `dc323e2` and `4df25e2`. Denton and Ellis expose full PACS relational fixed-width exports through different discovery and layout-container mechanisms. Rockwall's public source is a PACS-derived GIS shapefile subset, not a full appraisal roll. The review verified 206 spike tests and clean Ruff formatting/lint, found no committed source artifacts or detector findings in those commits, and treats all reported aggregates as provisional until reproduced in record-free production evidence manifests.

The Denton and Ellis review corrections at commit `798e966` and the Tarrant evidence at commits `89584f7` and `ac356ee` were reviewed on 2026-07-16. The correction evidence establishes PACS `prop_id` as an account identifier with physical owner-row grain, including undivided-interest allocations that may vary by owner, and classifies a measured Denton roll correction as a full replacement snapshot. Tarrant exposes a large, header-driven pipe-delimited certified roll. The spike remains requirements evidence only: several published aggregates are not reproducible from its committed profiler and its manifests use a date-shaped placeholder retrieval timestamp, so production must regenerate exact evidence rather than import the spike implementation.

## Goals / Non-Goals

**Goals:**

- Establish an independently deployable Python 3.12 repository with a single uv workspace and lockfile.
- Keep domain and application behavior reusable from Airflow, a CLI worker, tests, and future services.
- Deliver all six county adapters through a common contract and a coordinated publication gate.
- Preserve immutable source artifacts and end-to-end lineage.
- Publish explicit latest-available, latest-certified, and historical appraisal products.
- Make source drift, partial data, retries, and failures observable and recoverable.
- Convert source-spike evidence into county-specific contracts without duplicating shared ingestion and canonical requirements.
- Operate independently on a rebuildable Akamai Cloud runtime with durable source and database recovery outside the VPS.
- Serve approved Gold records through a small consumer-neutral Python API and versioned bulk exports.

**Non-Goals:**

- Scraping individual property-search web pages when an official bulk/API source exists.
- Publishing authoritative bills, payments, delinquency, penalties, or interest from appraisal-only sources.
- Building a consumer UI or modifying downstream consumer application code in this change.
- Requiring Spark, Delta Lake, Kafka, or TimescaleDB for the initial batch workload.
- Requiring parcel geometry for the first appraisal publication.
- Promoting exploratory spike scripts directly into production adapters without resolving their documented gaps.
- Giving consumer applications direct database credentials or coupling the platform API to TruPryce-specific domain behavior.
- Treating VPS snapshots as the durable system of record or exposing the administrative plane publicly.

## Decisions

### 1. Use one uv workspace with explicit package boundaries

The repository will use Python 3.12 and one uv lockfile with these initial workspace members:

```text
libs/property-tax-domain
libs/property-tax-application
libs/property-tax-adapters
services/ingestion-worker
services/appraisal-api
```

The root project owns development tooling. Every member uses a `src/` layout. A single workspace keeps interdependent packages and CI reproducible; separate repositories would add release coordination before the boundaries are stable. uv workspaces are preferred over untracked path manipulation or a shared `PYTHONPATH`.

### 2. Apply hexagonal dependency direction

`property_tax_domain` contains value objects, entities, release states, canonical records, and domain errors without infrastructure dependencies. `property_tax_application` contains use cases and Protocol-based ports. `property_tax_adapters` implements outbound HTTP, county source, Bronze object-store, PostgreSQL, and clock/checksum ports. `property_tax_ingestion` is a composition root and inbound CLI/task interface. Airflow DAG files remain declarative inbound adapters and contain no county parsing or SQL.

Alternatives rejected: a single package would make dependency violations invisible; one package per county would duplicate infrastructure and complicate coordinated releases.

### 3. Use a lightweight medallion architecture

Bronze is immutable Amazon S3 object storage containing original bytes and manifests. Silver is normalized PostgreSQL data at source grain with release lineage. Gold is versioned PostgreSQL tables or views for latest available, latest certified, and history. Parquet may be used as a derived batch interchange format but is not the system of record for original source evidence. The object-store port remains S3-compatible so recovery is not coupled to the initial cloud provider.

PostgreSQL regular tables are selected over TimescaleDB because release snapshots are not high-frequency time series. PostGIS remains optional for geometry. Spark and Delta Lake are deferred until measured volume or distributed-compute requirements justify them.

### 4. Make source observations, artifacts, and logical releases first-class

A source observation identifies county FIPS, source locator, discovery time, page evidence, and remote metadata. An artifact version is identified by SHA-256. Parsing can assign multiple logical release partitions, each identified by county FIPS, tax year, release kind, source as-of evidence, and artifact identity. This separation is required because one Collin artifact contains current values for one tax year and certified values for another. Conflicting content under the same source locator is retained and flagged. The release state machine is `DISCOVERED -> ACQUIRING -> BRONZED -> PARSED -> LOADED -> VALIDATED -> PUBLISHED`, with terminal or review states `FAILED` and `QUARANTINED`.

This model supports retries without using filenames as identity and makes silent publisher replacement observable.

### 5. Separate generic acquisition from county normalization

Each county adapter implements the same application port but owns its pagination, archive members, delimiters, fixed-width layouts, source fingerprints, and field mappings. The registry is data-driven and version-controlled. County formats never appear in DAG branches or domain entities.

The evidence-backed acquisition strategies are Dallas ZIP/delimited, Collin ZIP/PACS Access, Denton ZIP/PACS fixed-width with XLSX layout, Ellis ZIP/PACS fixed-width with ODS layout, and Tarrant ZIP/pipe-delimited with a header row. Rockwall's public shapefiles are optional partial enrichment and do not satisfy the full-appraisal adapter. Collin's Texas Open Data offering, Tarrant's mutable current and companion exemption archives, and any future Rockwall full-roll delivery are separately versioned source mappings, not transparent substitutes. Source fixtures will be small, synthetic or redistribution-safe slices with checksums and documented provenance.

### 6. Stream files and bulk-load batches

Downloads stream directly to temporary object keys while hashing. Archives are inspected before extraction. Parsers emit bounded batches. PostgreSQL adapters use `COPY` into run-scoped staging tables followed by set-based merge operations. Large record collections do not cross Airflow XCom; tasks exchange release IDs and object URIs only.

Alternatives rejected: whole-file pandas dataframes and per-row inserts do not provide acceptable memory bounds or throughput for county-scale files.

### 7. Preserve source grain in the canonical model

The account key is `(county_fips, source_account_id)`, where `source_account_id` is approved by the county contract after measured null and account-group checks. Physical row uniqueness is separate: PACS repeats one account for multiple owners, with row grain `(prop_id, owner_sequence)`. Most repeated rows share property facts, but undivided-interest accounts can carry owner-scoped ownership percentages, value allocations, and exemptions. Production preserves those allocations at owner-association grain and does not deduplicate, sum, or choose an arbitrary owner row until a verified account roll-up rule is approved. Unexplained conflicts still block publication. Snapshots add logical release ID, tax year, and source as-of value. Owners, owner allocations, exemptions, jurisdiction values, land segments, improvements, and geometry remain child records. Raw source extras may be retained in JSONB, but query-critical values receive typed columns.

System ingestion time and source as-of time are both retained. This provides bitemporal evidence without forcing the entire model into generic SCD2 tables.

### 8. Publish explicit products instead of one ambiguous current row

Gold exposes `latest_available`, `latest_certified`, and `history`. Deterministic precedence selects supplemental certified records over their earlier certified baseline for the same tax year while retaining both in history. A proposed newer year never replaces the certified product.

The consumer property bridge records match method and confidence. County-qualified account matches are exact; normalized-address matches are candidates. Unqualified APN joins are prohibited because account values can collide across counties.

### 9. Treat quality as a publication gate

Quality results are persisted per release. Blocking rules prevent publication and preserve prior Gold state; warning rules remain visible without blocking. Initial rules cover schema compatibility, required keys, logical uniqueness, child relationships, archive completeness, record-count drift, non-negative values, and source-specific invariants. Thresholds are configuration, not hard-coded DAG constants.

### 10. Use Airflow 3.3 for orchestration and a worker composition root

Airflow 3.3 TaskFlow DAGs schedule discovery and map work across counties. The ingestion worker exposes the same application use cases through CLI/task entry points for local execution and isolated task runtimes. Runtime credentials are injected through Airflow Connections or a reviewed secrets mechanism; the hosted Bitwarden vault is the off-host recovery copy, not an implicit runtime integration. Catchup is disabled for discovery; explicit release IDs and tax-year ranges drive backfills.

### 11. Use GitHub Issues for intake and OpenSpec for accepted work

Issue forms capture source onboarding, feature, defect, and decision context. Non-trivial accepted issues create an OpenSpec change before implementation. The initial bootstrap change is the only exception to the issue-reference rule because it creates the repository and its intake system. Pull requests reference both the issue and OpenSpec change.

### 12. Keep documentation layered and agent guidance local

The root README is a landing page, `docs/README.md` is the documentation hub, and `CONTRIBUTING.md` owns developer workflow. Area READMEs explain purpose and navigation. Scoped AGENTS.md files state local constraints and commands, with requirements linked back to OpenSpec rather than copied.

### 13. Layer shared capabilities with one thin source contract per county

Shared behavior remains in `source-release-ingestion` and `county-appraisal-normalization`. Each county receives a separate source-contract capability after its spike establishes source authority, release semantics, format and schema behavior, identity and grain, privacy handling, quality gates, and publication blockers. Spike reports are evidence; the county spec is the normative production contract.

Alternatives rejected: one monolithic six-county spec would make independent review and change history difficult, while duplicating acquisition, lineage, and canonical requirements in six specs would create conflicting contracts. Placeholder county specs based only on page reconnaissance are also rejected; a county contract is added when measured evidence exists.

The shared application port and common acquisition primitives do not imply a shared county base adapter. Denton and Ellis now provide the repeated evidence needed for a reusable PACS fixed-width layout and record-streaming component: the same field positions and parser behavior were observed across both exports, with XLSX versus ODS as layout-container adapters. County discovery, expected fingerprints, release semantics, privacy policy, and quality thresholds remain in thin county adapters. Collin's PACS Access product and Rockwall's PACS-derived shapefile remain separate serialization front ends.

The canonical domain remains vendor-neutral. PACS market, appraised, and assessed fields provide strong source evidence for Texas appraisal concepts, but PACS field names, table names, and product variants do not become domain types. Alternatives rejected: copying the spike package would retain exploratory assumptions; a PACS base county adapter would conflate vendor serialization with county policy; making Dallas the canonical template would privilege the one observed bespoke source.

### 14. Apply the Dallas spike findings to production boundaries

The reviewed Dallas evidence is:

| Artifact | Bytes | SHA-256 | Observed release state |
|---|---:|---|---|
| `DCAD2026_CURRENT.ZIP` | 205,621,950 | `b0bd0938e0e3d54fb171b4c56bb1f40a0c7b1a7ee0299f9e238ce21d81b0858c` | Proposed |
| `DCAD2025_CURRENT.ZIP` | 206,011,012 | `e86cfc800cf17dd8959c55c9940c2e6fed11e258c293c9192c37de088851820d` | Certified with supplemental changes |
| `DCAD2025_CERTIFIED_07242025.zip` | 191,596,710 | `57695ef8fd8c2a6c6e1472e34d1c577d3c2958bfc9788ed8b9a7a8705128560d` | Certified at certification |

All three contained 14 data members and four reference documents. The 2025 candidate carried 107.28 percent of baseline row volume, retained 99.88 percent of baseline account-level keys across the compared members, restated 86.51 percent of shared account-level groups byte-identically, and removed 830 parent accounts. Production therefore treats the supplemental package as a full replacement snapshot while retaining the dated certification separately.

Dallas provides no `ETag`, `Last-Modified`, or usable range support on the measured endpoints. `Content-Length` is an early positive change signal only; equal length cannot prove unchanged content. The stable `CURRENT` filename is a mutable source slot, while immutable Bronze identity is the acquired SHA-256. A scheduled mutable-slot observation must never overwrite an earlier proposed or supplemental capture.

`ACCOUNT_NUM` is the stable source account identifier and remains a 17-character, zero-padded string. It is not a parcel identifier; `GIS_PARCEL_ID` differs or is blank for a material share of accounts. The source row join key is `(ACCOUNT_NUM, APPRAISAL_YR)`, while canonical identity remains county-qualified. Child records remain at source grain until their component keys are measured.

The Dallas `TOT_VAL` field has unresolved semantics and is not approved as canonical market, appraised, assessed, or taxable value. The six jurisdiction-specific taxable-value families also cannot be collapsed into one unlabeled taxable value. Production may preserve these fields as source-native facts but cannot publish a fabricated canonical interpretation.

### 15. Apply the reported Collin spike findings to production boundaries

The Collin handoff reports one mutable ZIP containing a roughly 955 MB Microsoft Access database with 503,811 rows and 90 columns. The compressed transfer is roughly 87 MB. Collin's official page identifies this as a PACS-style Access export containing current property and ownership information with certified and preliminary values, and warns that the export will be retired in favor of Texas Open Data. Production must therefore version the measured Access source and treat any open-data replacement as new onboarding.

The source path has distinct probe semantics. HEAD describes a 7,256-byte HTML intermediary rather than the archive. The file response advertises `ETag` and `Last-Modified`, but conditional requests return status 200 with the full representation instead of 304. A one-byte range request returns partial content with total length and validators. Review of the exploratory code exposed implementation traps without invalidating those measured HTTP observations: automatic redirects and invalid-probe comparison must not be carried forward. The new production implementation validates every hop before contact, requires exact range-response semantics, records invalid observations as indeterminate, binds valid observations to a fully acquired artifact checksum, and periodically verifies complete content rather than trusting an unmeasured negative signal indefinitely.

The artifact contains current and certified field families in the same row. Reported 2026 current and 2025 certified values therefore become separate logical release partitions backed by one immutable artifact. The documented market, appraised, and assessed fields provide a reference vocabulary: the spike reports zero cases where `curr_appraised_val` exceeded `curr_market` across 501,537 comparable rows. This informs the canonical vocabulary but does not resolve Dallas `TOT_VAL` semantics.

The handoff reports that documented `prop_id` values contain 106 duplicate rows and remain duplicated when paired with `geo_id`. The duplicate pattern must be classified before identity is approved: if required account facts agree and only owner-association fields differ, `prop_id` may identify one account while the physical rows produce owner children; conflicting account facts remain blocking. It also reports that `file_as_name` is populated on every row and that no Dallas-like protected-owner marker was observed. Owner and mailing-address publication remains default-deny pending a reviewed Collin field policy.

The exploratory Python Access parser reportedly required about 13 minutes and 4 GB of memory for the measured database and did not decode 17-byte Access NUMERIC values. A custom decoder was required after an initial incorrect implementation produced implausible billion-dollar medians. Review found that scaled values are returned as binary floating point and most tests construct buffers with an encoder that mirrors the decoder, so they do not independently prove signed, scaled, or multiword behavior. These are requirements-discovery findings, not requests to repair the spike. Production will select and benchmark `mdbtools`, ODBC, or another reviewed runtime and require exact decimal results, independently derived golden vectors, and value-plausibility gates without importing the exploratory decoder.

The Collin commit contains narrative measurements but no record-free evidence manifest carrying the archive SHA-256, sanitized response metadata, member checksums, database-schema fingerprint, aggregate profile, and tool versions. Those data are required to make the reported 503,811-row baseline reproducible without committing the source database or record values.

### 16. Apply the reported Denton spike findings to production boundaries

Denton's official `dentoncad.net` directory exposes per-year `PreliminaryDataAllProperty`, `CertifiedDataAllProperty`, `RollCorrections`, and `AppraisalExportLayout` directories. Folder paths, not portal labels or source columns, establish roll status. The measured 2025 certified ZIP was about 413 MB compressed and 11.5 GB expanded, with 21 members, 20 layout tables, a 5.3 GB entity member, and a 485-field, 9,247-character property record. Production therefore streams members directly from the ZIP and performs uniqueness and relationship checks with bounded or external state.

The same official server now exposes nightly appraisal CSV/text and geodatabase artifacts plus a GIS schema. Those are potentially useful for freshness but are not established as equivalent to the annual relational PACS roll. They become a separate source mapping and cannot silently replace preliminary, certified, or roll-correction sources.

The server honored `ETag`, `Last-Modified`, ranges, and conditional requests in the spike. A valid 304 bound to a completed prior artifact is a cheap no-change observation; SHA-256 remains content identity. This behavior is Denton-specific and cannot be generalized to Dallas or Collin.

The data header reports PACS `8.1.33.23`, while the available layout reports `8.0.32`. Three wide tables have record widths that do not match the layout. The corrected spike distinguishes absent from truncated fields and measured no field crossing the 9,247-character property boundary. Production still maps only a matching or explicitly verified layout region, validates every required field end, preserves structural evidence for unknown trailing bytes, and quarantines partial required fields.

The 2025 certified release reports 461,827 property rows with 26 duplicate `prop_id` rows; the 2026 preliminary release reports 1,117 duplicates. The measured duplicate groups and documentation establish `prop_id` as account identity and `(prop_id, owner_sequence)` as physical owner-row grain. Undivided-interest accounts are the important exception to naive collapsing: ownership percentage, values, and exemptions can be allocated per owner. Production preserves those allocations and requires a verified account roll-up rather than deduplicating or summing them. Core land, improvement, and mobile-home relationships reported zero orphans, while legal records had measured nonzero orphan rates; thresholds remain relationship-specific.

The reported value hierarchy is strong evidence: market, appraised, and assessed fields are explicit, and appraised did not exceed market in 399,901 measured certified comparisons. This informs canonical semantics without making PACS vocabulary the domain model. `ten_percent_cap` remains a cap amount, not a capped value. The measured 2025 certified-to-correction comparison retained 461,510 accounts, removed 291, added 13, and changed values on 3,260 shared accounts. The correction is therefore a full replacement snapshot and must never be merged as a delta. Same-year preliminary-to-certified behavior remains unclassified.

Denton's official GIS schema states that confidential ownership and over-65 exemption data are excluded from public downloads. Production preserves those omissions and never reconstructs them. Applicability to the full PACS roll and the field-level redistribution policy still require confirmation; the absence of a row-level flag is not evidence that every owner value is safe to publish.

### 17. Apply the reported Ellis spike findings to production boundaries

Ellis's official Appraisal Data Export page is a JavaScript-rendered TrueProdigy SPA. Production discovery renders only the public page or uses an approved direct artifact URL with periodic page revalidation; it does not extract bundle keys or automate an undocumented backend API. The plain `2025 Certified Appraisal Roll` is authoritative for the measured spike. The separately labeled `RC2 Potential $140k HS and $60k OV65-DP` artifact is a hypothetical scenario and must never be selected as certified current state. The page reportedly exposes certified history from 2015 through 2025.

The measured archive is a full PACS fixed-width export with 21 members, 109,772 property rows, and about 2.9 GB expanded. It reports the same PACS export version, 485-field property layout, 9,247-character property record, and required positions as Denton. The Denton parser ran unchanged, which justifies a shared PACS fixed-width component, but production independently fingerprints Ellis before reuse. Ellis publishes an ODS layout with a misleading `.xlsx.ods` suffix, so parser selection is based on package content rather than filename.

Ellis reports 496 duplicate `prop_id` rows and the same PACS account/owner grain: `prop_id` identifies the account while owner sequence identifies the physical owner row. Production preserves possible undivided-interest owner allocations and requires an approved account roll-up. The spike reports zero core appraisal orphans, nonzero legal-table orphans, and zero appraised-over-market violations across 109,772 comparisons. Same-year preliminary and correction behavior remain unmeasured. Inline ownership data and the absence of a verified confidentiality marker keep owner publication default-deny.

### 18. Treat Rockwall public GIS as enrichment and obtain the full roll

Rockwall's official GIS page is a TrueProdigy SPA whose public link resolves to shapefile layers. The observed ownership layer contains 55,210 rows and partial 2026 market, land, improvement, owner, situs, legal, and jurisdiction-code attributes; parcel, road, and subdivision layers are also available. It lacks appraised, assessed, capped, agricultural, exemption, jurisdiction-value, land-detail, improvement-detail, and other facts required by the appraisal contract. It is therefore optional geometry and partial-value enrichment, not a complete county source.

The initial platform does not require geometry, so building a Rockwall shapefile reader now would not unblock the six-county goal. The recommended next action is an official open-records request or authorized bulk-feed agreement for the full appraisal roll. Any resulting source gets its own measured contract even if it resembles Denton or Ellis. A later GIS change can add strict shapefile bundle, CRS, encoding, record-alignment, and truncated-DBF-field controls.

The ownership layer reports 337 duplicate `pid` rows and contains owner PII. As with the other PACS-derived sources, production measures account-fact consistency rather than conflating row uniqueness with account identity, and owner publication remains disabled pending a Rockwall policy.

### 19. Apply the measured Tarrant contract without overstating completeness

Tarrant's official static data page exposes a measured 2025 certified archive containing one 779,172,533-byte pipe-delimited text member with a header, 56 columns, 1,996,478 non-ragged account rows, and a verified unique, nonblank `Account_Num`. The archive SHA-256 is `609e05fa3f6b82157c80a1131fcd1a3f3f0f6e4531abdea591f80f2bd4166dcd`. The measured division distribution is material to drift monitoring because mineral accounts comprise about 60 percent of the file. Production fingerprints the exact header and requires unambiguous member resolution rather than selecting the first text file.

The certified core file carries land, improvement, agricultural, total, appraised, and physical-characteristic fields. The reported inequality `Appraised_Value <= Total_Value` is a useful invariant, but the spike does not contain code that reproduces its stated 1,632,896 comparisons. Neither the inequality nor field names alone establish that `Total_Value` is canonical market value. Production regenerates the aggregate and obtains official semantic evidence before mapping those types.

Tarrant's conditional and range behavior was favorable in the measured request, but SHA-256 remains immutable identity. The mutable current archive, companion certified exemption archive, same-year replacement behavior, longitudinal account stability, and confidentiality handling are not yet profiled. The certified core parser can be implemented independently, but Tarrant does not pass the complete county publication gate until those contracts are resolved.

### 20. Operate on an independent, rebuildable Akamai runtime

The first runtime is an Akamai Cloud VPS in Dallas (`us-central`) using Ubuntu 24.04 LTS, 16 GB shared CPU memory, and a 250 GB attached volume. It hosts the platform's own PostgreSQL, Airflow, ingestion workers, and API with separate databases or schemas and least-privilege roles. Tailscale is the administrative path. Database ports, Airflow administration, and host management are not public consumer interfaces.

The VPS and volume are replaceable compute, not the durable recovery boundary. Amazon S3 retains Bronze artifacts, manifests, derived exports, Airflow remote logs, PostgreSQL physical backups, and archived WAL. The initial target is continuous WAL archiving with at most a five-minute archive timeout, daily differential backups, weekly full backups, and three recoverable cycles, subject to measured storage and restore results. The Linode backup add-on is disabled only after a point-in-time restore and clean-host rebuild are automated and exercised successfully.

The hosted Bitwarden vault at `https://vault.bitwarden.com` stores the operator-controlled recovery copy of environment secrets. Git, images, logs, source manifests, and S3 data buckets do not store plaintext secrets. Runtime injection, least-privilege access, rotation, and break-glass procedures remain explicit implementation concerns rather than being implied by the recovery vault.

### 21. Serve Gold through a consumer-neutral appraisal API

A lightweight Python `appraisal-api` runs on the platform VPS and reads approved Gold data through a read-only database role. It exposes versioned OpenAPI contracts for county-qualified account lookup, latest available, latest certified, history, provenance, freshness, and match evidence. Sensitive ownership and mailing fields are absent by default and require an explicitly approved policy and authorization path.

Interactive consumers, including TruPryce, call the API through typed clients and compose the results in their own services. They do not receive platform database credentials. Large extracts use versioned S3 exports rather than row-by-row API traversal. External TLS termination, service authentication, rate limiting, and exposure topology must be selected before production access.

## Risks / Trade-offs

- [Official endpoints or layouts change without versioning] -> Fingerprint schemas, retain Bronze artifacts, quarantine incompatible releases, and version adapters and fixtures.
- [Rockwall has only a partial public GIS source] -> Request the full official appraisal roll and keep the shapefile source separately labeled as optional enrichment; do not count it toward complete-cohort readiness.
- [A county republishes content under the same filename] -> Use content hashes and retain conflicting versions.
- [Six-county atomic readiness delays partial value] -> Permit county-level Silver validation while reserving the “complete six-county” Gold label until all adapters pass.
- [One uv lockfile makes Airflow resolution heavier] -> Keep domain libraries dependency-light and use workspace dependency groups; split runtime locking only if a demonstrated conflict occurs.
- [Address matching creates false positives] -> Publish address matches as candidates with evidence and confidence, never as exact silent merges.
- [Public records contain sensitive or suppressed ownership] -> Preserve publisher redactions, avoid reconstructing protected identities, and review redistribution terms per source.
- [A spike downloader reuses a mutable locator after only a same-length HEAD response] -> Production acquisition requires a remote content identity or a scheduled full download and SHA-256; local file validity alone cannot prove remote content is unchanged.
- [A redirect reaches an unapproved host before final-host validation] -> Disable automatic redirects and validate the scheme and host before issuing every redirected request.
- [Dallas `EXCLUDE_OWNER` is interpreted more broadly than the governing confidentiality rules] -> Treat it as a sensitive-record marker, default-deny owner and address publication, and obtain a reviewed field-level policy before production; do not infer that all non-identifying appraisal facts must be removed.
- [Spike comparison aggregates duplicate-key rows in source order] -> Validate natural child keys or use deterministic order-independent multiset comparison before using child-level change rates as a production assertion.
- [Collin's retiring Access export disappears or changes to Texas Open Data] -> Preserve acquired artifacts, monitor the official page, and require a new source contract and measured equivalence before switching adapters.
- [Collin HEAD and conditional responses appear standards-compatible but transfer the wrong representation or full file] -> Use a contract-tested one-byte range strategy, validate exact response semantics, and bind probe metadata to verified artifact checksums.
- [A custom Access NUMERIC decoder silently emits plausible but wrong values] -> Test independent signed and scaled golden vectors, enforce year and value invariants, and benchmark the complete runtime before enabling the adapter.
- [A failed or malformed Collin probe is persisted as an unchanged baseline] -> Model probe validity explicitly, reject invalid observations from comparison state, and require exact status, range, length, and media-type checks.
- [Scaled Access values are converted through binary floating point] -> Use exact decimal types from decoding through canonical persistence and test precision at configured boundaries.
- [Collin ownership lacks an observable protected-owner marker] -> Default-deny owner and mailing-address publication, request source clarification, and approve a field-level policy before Gold publication.
- [A reusable PACS parser becomes a PACS-shaped domain model] -> Share only serialization and layout mechanics; keep canonical Texas appraisal concepts and county policy outside vendor-specific packages.
- [Denton and Ellis layouts are older than their export headers] -> Require matching or verified layout regions, reject partial required fields, fingerprint unknown trailing data, and quarantine incompatible drift.
- [PACS duplicate property rows are mistaken for duplicate accounts] -> Measure account-fact consistency by candidate key and model owners as children before approving or rejecting account identity.
- [Denton correction archives are merged as deltas] -> Treat the measured correction family as full replacement snapshots, apply removals atomically, and retain each release in history; keep preliminary-to-certified behavior separately gated.
- [Denton's nightly GIS extract silently replaces the fuller annual PACS roll] -> Version it as a separate source and measure coverage, identity, release status, and field equivalence before use.
- [SPA discovery is implemented by extracting a client-bundle key] -> Render the official public page or revalidate an approved direct URL; never depend on undocumented credential-bearing content APIs.
- [A source artifact bypasses an extension-only ignore rule] -> Enforce path-, size-, content-, and extension-aware tracked-artifact checks in pre-commit and CI.
- [PACS owner-row allocations are collapsed as duplicate account facts] -> Preserve `(prop_id, owner_sequence)` rows and their ownership percentage, value, and exemption allocations until a verified account roll-up is approved.
- [Tarrant's simple core file is mistaken for a complete source] -> Keep its current, exemption, confidentiality, value-semantic, and replacement gates explicit and independently version each source family.
- [Tarrant member selection accepts an ambiguous archive] -> Require exactly one member matching the approved contract and quarantine zero or multiple matches.
- [A record-free manifest carries a synthetic timestamp or unreproducible aggregate] -> Record the exact acquisition instant, tool and schema versions, and only aggregates regenerated by committed tooling.
- [The single VPS or attached volume is lost] -> Treat it as replaceable, retain source and database recovery material in S3, and exercise both point-in-time restore and clean-host rebuild before disabling provider snapshots.
- [Self-managed WAL archiving silently fails] -> Alert on archive lag, backup age, restore-test age, and S3 access failures; keep the provider backup add-on until recovery objectives are proven.
- [Bitwarden recovery values drift from deployed credentials] -> Assign owners, rotation dates, and a tested break-glass procedure without making the vault an undocumented runtime dependency.
- [The appraisal API exposes Silver, owner data, or direct database access] -> Use a read-only Gold role, default-deny sensitive fields, version OpenAPI, and publish bulk data through controlled S3 exports.

## Migration Plan

1. Land the repository, OpenSpec workflow, package boundaries, issue forms, and CI without production connections.
2. Add manifest and Silver schemas plus local object-store/PostgreSQL integration tests.
3. Reproduce the Dallas, Collin, Denton, Ellis, and Tarrant evidence in isolated non-production storage and create complete record-free evidence manifests without importing spike code or source data.
4. Implement shared acquisition primitives plus a reusable PACS fixed-width parser behind thin Denton and Ellis adapters; keep Collin Access and all county policies separate.
5. Request and contract the full Rockwall appraisal roll; defer its public shapefile reader to an optional GIS-enrichment change unless the product scope changes.
6. Complete the Tarrant current, exemption, value-semantic, replacement, and confidentiality contracts; resolve every county's remaining owner-allocation, release, value, and publication policies.
7. Backfill a selected certified tax year into isolated Bronze and Silver environments.
8. Validate each county, reconcile counts against official summaries where available, and resolve quarantines.
9. Provision the independent Akamai runtime, configure S3-backed Bronze and PostgreSQL WAL/physical backups, and prove point-in-time restore plus clean-host rebuild before disabling provider backups.
10. Publish versioned Gold products, the property bridge, S3 bulk exports, and the read-only `appraisal-api` in a non-production environment.
11. Promote after API consumer acceptance and recovery exercises; rollback data by repointing the Gold publication pointer and recover infrastructure from versioned automation and S3.

## Open Questions

- Which historical tax years are required for the initial backfill?
- What freshness target is required for current/supplemental releases by county?
- Is parcel geometry required in the initial published data contract or a later enrichment change?
- What official process, delivery format, redistribution terms, and cadence will provide Rockwall's full appraisal roll?
- Which portable property identifiers and match evidence must the consumer bridge expose?
- What official Dallas meaning and arithmetic relationship apply to `TOT_VAL`, `IMPR_VAL`, `LAND_VAL`, and `HMSTD_CAP_VAL`?
- Which source component keys uniquely identify each Dallas child record?
- What reviewed field-level suppression policy applies when Dallas sets `EXCLUDE_OWNER`?
- Does a second Dallas certification/supplemental year confirm the measured full-replacement behavior?
- Will the first Collin production adapter use the retiring Access export, Texas Open Data after a separate spike, or both during a measured transition?
- What official roll-up rule converts PACS undivided-interest owner allocations into account-level values and exemptions without double counting?
- Which Access runtime meets exact-decimal correctness, portability, memory, and throughput requirements in the Airflow worker image?
- What complete-download verification cadence is required behind Collin's cheap range probe?
- How does Collin exclude or redact records protected under Texas confidentiality requirements, and which owner or address fields may the platform publish?
- Which Denton and Ellis layout version exactly matches each PACS `8.1.33.23` export, and which verified field prefix is safe until that layout is obtained?
- Are Denton same-year preliminary and certified archives full replacement snapshots?
- What coverage, release status, and freshness relationship does Denton's nightly appraisal extract have to the annual PACS and roll-correction sources?
- Does Ellis publish a preliminary or correction roll, and what official rule identifies hypothetical RC2 artifacts over time?
- Does Denton's published confidentiality statement govern the full PACS export, how do Ellis and Rockwall suppress protected records, and which non-identifying appraisal and situs fields may be published?
- What official Tarrant semantics distinguish `Total_Value`, `Appraised_Value`, taxable values, and companion exemption facts?
- Is Tarrant's mutable current archive a full replacement, how stable is `Account_Num` across years, and how does TAD suppress records protected under Texas confidentiality rules?
- Which external TLS, service-authentication, rate-limit, and network-exposure controls protect `appraisal-api`?
- What measured RPO, RTO, retention, S3 lifecycle, encryption-key ownership, and restore-test cadence will be accepted before the Linode backup add-on is disabled?
- Which reviewed mechanism injects Bitwarden-recovered secrets into Airflow, PostgreSQL, and `appraisal-api`, and how are rotation and break-glass access audited?
