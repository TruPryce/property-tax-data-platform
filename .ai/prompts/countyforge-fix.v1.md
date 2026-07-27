# CountyForge Fix Profile v1

This is the reserved targeted-remediation contract for `TruPryce/property-tax-data-platform`.
`fix.targeted-write.v1` currently has no executor or built image, so CountyForge must fail closed
with `profile_not_implemented`; no model, command, credential, repository mutation, or provider call
is authorized by this file.

When a later accepted issue implements this profile, the agent must:

- Accept only explicitly selected review finding identifiers and one expected immutable 40-character
  head SHA. If the checked-out head, review packet, or finding set no longer matches, make no changes
  and return `status: "stale"` with `stale_review_disposition: "stale"`.
- Fix only the selected findings. Do not implement `NICE_TO_FIX` or unrelated cleanup, alter the
  branch objective, rewrite accepted OpenSpec behavior, change task checkboxes, or edit review
  output merely to hide a finding.
- Preserve `dags/services -> adapters -> application -> domain`; keep county/PACS mappings in
  `property_tax_adapters`, composition in services, and parsing/mapping/SQL out of `dags/`.
- Preserve immutable Bronze evidence, source-grain Silver lineage, prior Gold state on blocking
  quality failures, `(prop_id, owner_sequence)` owner rows, and owner/mailing default-deny.
- Never invent canonical semantics for unresolved fields such as Dallas `TOT_VAL` or Tarrant
  `Total_Value`, treat Rockwall GIS as a full appraisal roll, or present appraisal data as
  authoritative tax bills or payments.
- Never add secrets, credentials, `.env` values, county source releases, protected owner records, or
  oversized artifacts. Fixtures must remain small, synthetic or redistribution-safe.
- Use only future profile-declared paths and deterministic checks. Network, GitHub publication,
  production services, Docker/SSH/Tailscale access, and arbitrary commands remain prohibited.
- Return exactly the fields in `.ai/schemas/countyforge-fix-result.schema.json`: `status`,
  `targeted_finding_ids`, `expected_head_sha`, `applied_findings`, `unresolved_findings`,
  `changed_paths`, `validations`, and `stale_review_disposition`. Never fabricate validation
  evidence.
