## ADDED Requirements

### Requirement: GitHub Issue intake
The repository SHALL provide structured GitHub Issue forms for source onboarding, defects, feature work, and architecture decisions and SHALL disable unstructured blank issues.

#### Scenario: Submit county source work
- **WHEN** a contributor opens the source-onboarding form
- **THEN** the intake captures source authority, county, release kinds, access method, sample/layout availability, expected cadence, acceptance criteria, and data-sensitivity concerns

#### Scenario: Submit implementation work
- **WHEN** a contributor opens a feature or defect form
- **THEN** the intake captures problem, impact, scope, evidence, and verifiable acceptance criteria

### Requirement: OpenSpec traceability
The repository SHALL use OpenSpec changes to define accepted behavior and implementation tasks for non-trivial work, and each non-bootstrap change SHALL reference its originating GitHub Issue before implementation begins.

#### Scenario: Begin accepted feature work
- **WHEN** a GitHub Issue is accepted for implementation
- **THEN** a kebab-case OpenSpec change records the behavior, design decisions, and tasks and references the issue

#### Scenario: Complete a change
- **WHEN** all OpenSpec tasks and required checks pass
- **THEN** the change is eligible for archival and the pull request can close the originating issue

### Requirement: Navigable repository guidance
The repository SHALL provide concise README files for human navigation and scoped AGENTS.md files at architectural boundaries for agent navigation and constraints.

#### Scenario: Enter a repository area
- **WHEN** a human or agent enters the root, OpenSpec, DAG, library, adapter, service, or documentation area
- **THEN** nearby guidance identifies the area's purpose, dependency rules, authoritative documents, and validation commands without duplicating detailed requirements

### Requirement: Enforced dependency direction
The repository SHALL enforce the dependency direction `adapters -> application -> domain`; domain code MUST NOT import orchestration, network, object-store, database, or county-adapter implementations.

#### Scenario: Introduce a prohibited import
- **WHEN** a change adds an import that reverses the allowed dependency direction
- **THEN** an automated architecture test or static check fails

### Requirement: Required repository checks
The repository SHALL provide repeatable commands and continuous-integration checks for formatting, linting, type checking, unit tests, architecture tests, OpenSpec validation, and documentation links.

#### Scenario: Validate a pull request
- **WHEN** continuous integration runs for a pull request
- **THEN** the same documented checks available to local contributors execute in a clean environment

### Requirement: Secret-safe repository
The repository SHALL provide example configuration containing names and non-secret defaults only, SHALL ignore local environment files, credentials, downloaded county artifacts, and generated runtime state, and SHALL scan repository content for potential secrets before commit and in continuous integration.

#### Scenario: Configure a local environment
- **WHEN** a contributor follows developer setup documentation
- **THEN** secrets remain outside tracked files and logs redact credential values

#### Scenario: Stage a potential secret
- **WHEN** a contributor stages a text file containing a potential secret that is not an explicitly reviewed false positive
- **THEN** the pre-commit hook fails and identifies the affected file before a commit is created

#### Scenario: Validate repository contents in continuous integration
- **WHEN** continuous integration validates a pull request or the main branch
- **THEN** all tracked text files are scanned using the version-controlled detector configuration and reviewed baseline

#### Scenario: Change the secret baseline
- **WHEN** a contributor adds a detector finding to the secret baseline
- **THEN** the pull request documents why the finding is a false positive and reviewers can identify the baseline change

### Requirement: Source-artifact-free repository
The repository SHALL prohibit tracked county source releases, extracted source members, spatial sidecars, source databases, record-bearing spreadsheets, and unknown large binary artifacts regardless of filename or directory. Pre-commit and continuous integration SHALL enforce this rule using content, size, path, and extension checks with a narrowly reviewed allowlist for synthetic or redistribution-safe fixtures.

#### Scenario: Stage a county source artifact
- **WHEN** a contributor stages a ZIP, Access database, spreadsheet, shapefile component, SQLite file, extracted source member, or other record-bearing county artifact
- **THEN** the repository check fails before commit and identifies the prohibited path

#### Scenario: Stage an unknown large binary
- **WHEN** a staged file exceeds the configured repository-artifact threshold and is not on the reviewed fixture allowlist
- **THEN** the repository check fails even when the extension is absent or not in the known-artifact list

#### Scenario: Add a safe fixture exception
- **WHEN** a contributor needs a synthetic or redistribution-safe binary fixture
- **THEN** the fixture remains below the configured size limit or receives a documented narrow allowlist entry reviewed in the pull request
