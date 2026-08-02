## Current-state evidence

- `515a41057d446a949cae5adc`: Untrusted issue evidence requests exact Access NUMERIC decoding, typed Collin adapter-layer source records, and deterministic current/certified logical-value normalization.
- `a8d0164e015d086c00140812`: The artifact contains current and certified field families in the same row. The handoff reports duplicate prop_id/geo_id rows, and review found that mirrored decoder tests did not independently prove signed, scaled, or multiword behavior.
- `37b0be1db5c2ff2ef21f3eae`: Before implementation, source onboarding must verify layouts, schema fingerprints, authoritative counts, stable identifiers, and one-to-many relationships.
- `c83b55e968e3981f0030935d`: Allowed dependency direction: dags/services -> adapters -> application -> domain.
- `76e21fb4c68b6f87724edaac`: Adapters translate external formats and implement ports; source-specific fields stop at this boundary.
- `7676ed46a8bb877ba7fdaac0`: Fingerprint layouts and quarantine incompatible drift instead of guessing. Commit only small synthetic or redistribution-safe fixtures.
- `1f68cbd53a026079a9b30f8d`: Physical owner-row grain (prop_id, owner_sequence) is preserved without an approved account roll-up rule; owner and mailing-address publication is default-deny.
- `12eb90de41980a9b5226022f`: The repository supports make check as the aggregate gate and requires source fixtures rather than full county releases.
- `05e1317dff1c2a0b0cdc4827`: No county adapter is production-ready yet. Synthetic fixtures use CC0, while third-party county data retains its publisher's terms.
- `2e0a24560feb74d4881dab53`: Whenever blocking unresolved decisions remain, implementation eligibility is false.
- `84e1270fa46d7eebbcd2d3c3`: Implementation requires a valid accepted change with no unresolved blocking decision and a planning PR merged by an authorized human maintainer.
- `d253d5455b500dc5f5a9bca6`: Trusted code renders only .openspec.yaml, proposal.md, design.md, tasks.md, and one capability spec.md beneath the proposed change.
- `714534bcff3cb21530465c55`: Use one spec directory per capability named in the proposal.
- `fc02f32a50f16c9ec430bd1b`: collin-cad-source-contract covers evidence-backed Collin PACS Access dual-roll, numeric-decoding, identity, and privacy behavior.

## Proposed architecture

Create a draft OpenSpec delta for collin-cad-source-contract that records the missing decisions as blocking. Once maintainers approve those decisions and merge the planning change, the contingent implementation can add adapter-local exact-decimal decoding, typed Collin records, fail-closed schema checks, separate current and certified observations, repeated-row preservation, and identity-free synthetic tests without persistence, publication, runtime acquisition, or a production-ready designation [sources: 2e0a24560feb74d4881dab53, 84e1270fa46d7eebbcd2d3c3, a8d0164e015d086c00140812].

## Dependency direction

The implementation must preserve the repository dependency direction and keep planning tooling outside production domain, application, adapter, and DAG packages.

## Trust boundaries

Issue and comment text is untrusted evidence. The planning model receives only the frozen packet and schema, has no repository-write mount or Git credentials, and cannot approve its own plan. Trusted publication code validates and materializes the bounded result.

## Data and contract changes

The planning packet, context manifest, strict planning result, publication manifest, and revision metadata are the governing contracts for this change.

## Alternatives considered

No alternative is finalized by the planning agent when the packet lacks evidence. Unresolved alternatives remain explicit decisions for human review rather than being silently selected.

## Decisions and assumptions

- Only collin-cad-source-contract is modified; Collin, PACS, and Access representations remain inside property_tax_adapters, while property_tax_application and property_tax_domain remain unchanged [sources: c83b55e968e3981f0030935d, 76e21fb4c68b6f87724edaac].
- Fixtures are independently authored, small, synthetic, identity-free, and redistribution-safe; no county database, archive, row, owner value, mailing address, or production record is included [sources: 7676ed46a8bb877ba7fdaac0, 12eb90de41980a9b5226022f].
- Current and certified value families from one Collin artifact remain distinct logical observations rather than one ambiguous current record [source: a8d0164e015d086c00140812].
- prop_id and geo_id remain source fields rather than an approved canonical account key, and repeated physical rows are preserved without deduplication or owner roll-up [sources: a8d0164e015d086c00140812, 1f68cbd53a026079a9b30f8d].
- No new dependency or Access runtime is authorized. If the approved decoding contract cannot be implemented with existing facilities, dependency selection becomes another blocking human decision [sources: 515a41057d446a949cae5adc, a8d0164e015d086c00140812].
- Completing this foundation will not make Collin or another county adapter production-ready; live-source compatibility, resource behavior, acquisition, persistence, and publication remain separate gates [sources: 05e1317dff1c2a0b0cdc4827, 7676ed46a8bb877ba7fdaac0].

## Unresolved decisions

- D1 — Approve the exact Access NUMERIC physical contract, including supported buffer width, required metadata, sign representation, precision/scale interpretation, byte and word order, zero encoding, boundaries, and malformed or unsupported forms. Existing evidence identifies decoder failures but does not define these rules [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].
- D2 — Approve the exact Collin structural contract: required table names, required columns, duplicate-column behavior, physical type descriptors, widths, precision/scale metadata, nullability, ordering policy, and canonical fingerprint input. Source onboarding requires measured fingerprints rather than inference from issue prose [sources: 37b0be1db5c2ff2ef21f3eae, 7676ed46a8bb877ba7fdaac0].
- D3 — Approve the complete current/certified field mapping and observation shape, including supported value families, the roles of curr_val_yr, cert_val_yr, and property_status, classification rules, and mandatory provenance. The accepted context establishes dual releases but not the complete mapping [sources: a8d0164e015d086c00140812, 515a41057d446a949cae5adc].
- D4 — Approve deterministic lexical, null, and range rules for prop_id, geo_id, years, monetary values, and stable diagnostics. The issue requests fail-closed validation, but authoritative context does not define the accepted forms or bounds [sources: 515a41057d446a949cae5adc, 37b0be1db5c2ff2ef21f3eae].

## Risks and compatibility

- A guessed NUMERIC layout could decode malformed bytes into plausible but materially incorrect appraisal values. Mitigation: block implementation until D1 is approved and require independent vectors rather than an encoder mirroring the decoder [source: a8d0164e015d086c00140812].
- An incomplete fingerprint could accept silent Access schema drift or bind values to the wrong columns. Mitigation: approve and validate the complete D2 table/column/physical-type contract before row conversion [sources: 37b0be1db5c2ff2ef21f3eae, 7676ed46a8bb877ba7fdaac0].
- Combining current and certified fields could create an ambiguous release and corrupt precedence. Mitigation: emit separate observations with explicit year, status, field-family, row, and artifact provenance [source: a8d0164e015d086c00140812].
- Treating prop_id or prop_id plus geo_id as unique could erase legitimate repeated owner-row evidence. Mitigation: preserve every physical row and prohibit identity approval, deduplication, aggregation, or owner roll-up in this slice [sources: a8d0164e015d086c00140812, 1f68cbd53a026079a9b30f8d].
- Synthetic-only validation cannot prove compatibility, throughput, or memory behavior against a live Collin release. Mitigation: retain non-production-ready status and require separate live-source onboarding and benchmarking [sources: a8d0164e015d086c00140812, 05e1317dff1c2a0b0cdc4827].
- No data migration or backfill is authorized because this is an additive, pre-production adapter foundation with no Bronze, Silver, Gold, database, API, or release state to transform [sources: 515a41057d446a949cae5adc, 05e1317dff1c2a0b0cdc4827].
- Before later persistence integration, rollback is removal or reversion of the adapter-local decoder, records, tests, and documentation; no persisted or published release requires repair [sources: 05e1317dff1c2a0b0cdc4827, c83b55e968e3981f0030935d].
- Only independently authored synthetic fixtures are proposed. Project synthetic fixtures use CC0, while third-party county data retains publisher terms and is not introduced by this change [source: 05e1317dff1c2a0b0cdc4827].
- property_tax_domain and property_tax_application remain unchanged, and no shared PACS or Collin abstraction is introduced [sources: 76e21fb4c68b6f87724edaac, c83b55e968e3981f0030935d].
- Texas Open Data or another future source representation requires separate onboarding and cannot silently replace the measured Access contract [source: a8d0164e015d086c00140812].

## Rollout and failure recovery

Validation commands: make check. Failures remain blocked and do not authorize implementation. Repeated context creates a deduplicated result; changed context creates a linked superseding draft without overwriting prior evidence or human edits.

## Testing strategy

Run the trusted deterministic validation commands recorded in the plan, plus the repository OpenSpec, documentation-link, and artifact-policy gates before publication.
