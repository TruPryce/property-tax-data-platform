## ADDED Requirements

### Requirement: Separate trusted contract and immutable target roots
The CountyForge kernel SHALL resolve profiles, schemas, provider catalogs, prompts, adapters, container policy, and run evidence only from an explicit trusted `contract_root`, while validating repository identity, immutable `HEAD`, base ancestry, and packet provenance against an explicit `target_root`. The roots MAY be equal for a local developer invocation, but a GitHub-dispatched run MUST keep them distinct. An executable review MUST revalidate the target and packet binding immediately before selecting a provider credential, and neither a target file nor target configuration may replace a contract-root resource.

#### Scenario: Preserve local single-root compatibility
- **WHEN** a developer invokes the existing local pre-PR path without separate root options
- **THEN** the kernel treats the current repository as both roots and preserves the existing request, security posture, and evidence contract

#### Scenario: Resolve trusted resources separately
- **WHEN** a GitHub run supplies a trusted default-branch tooling checkout as `contract_root` and an immutable target repository as `target_root`
- **THEN** the kernel loads all executable policy from the contract root and validates repository/packet facts against only the target root

#### Scenario: Reject target-root replacement of policy
- **WHEN** the target revision contains modified profiles, schemas, prompts, provider catalogs, adapters, workflow files, package hooks, or runner source
- **THEN** no target version of those files is loaded or executed and the trusted contract-root versions remain authoritative

#### Scenario: Validate a bare immutable target repository
- **WHEN** the provider-execution phase supplies a bare Git repository containing the bound base and head commits without a checked-out worktree
- **THEN** repository identity, exact head, base existence, ancestry, and packet provenance validation succeeds without executing or checking out target content

#### Scenario: Fail closed on root or binding drift
- **WHEN** either root is absent, the trusted resource hash differs, the target repository identity or head differs, the base commit is invalid, or packet provenance disagrees with the target facts
- **THEN** the kernel returns a sanitized structured failure before provider credential selection or executor dispatch
