## ADDED Requirements

<!-- Owns: the rule that no port names infrastructure vocabulary, and the
     opaque-locator rule for every persistence-generated handle that crosses a
     port (`ProcessingRunRef`, `ManifestRef`, `PublicationRef`).
     Cites: nothing. Every other spec in this change cites this one. -->

### Requirement: The application owns the port boundary and depends on no infrastructure
The application package SHALL own every port the ingestion, persistence, quality, publication, and time responsibilities are coordinated through, expressed as Protocols together with the value types that cross them. No public port contract SHALL name an object-store SDK type, a database driver type, a connection, a cursor, a SQL transaction, a database schema or table name, a bulk-load mechanism, a conflict clause, an orchestrator type, or a county implementation.

The application package SHALL remain importable and its ports constructible without any of those dependencies installed.

#### Scenario: A port contract is inspected for infrastructure vocabulary
- **WHEN** the public surface of any application port is examined
- **THEN** it names only domain types, application-owned value types, and standard-library types

#### Scenario: The application is imported in isolation
- **WHEN** the application package is imported with no object-store SDK, database driver, or orchestrator available
- **THEN** the import succeeds and every port remains usable as a type

### Requirement: Persistence-generated handles are explicitly opaque locators
Where a persistence-generated handle crosses a port, the contract SHALL state that it is an opaque locator. Such a handle SHALL NOT be presented as canonical identity, SHALL NOT carry an ordering guarantee, and SHALL NOT be interpreted as a business fact.

#### Scenario: A run reference crosses a port
- **WHEN** a processing-run reference is passed between ports
- **THEN** its contract identifies it as an opaque locator rather than as identity

#### Scenario: Two run references are compared
- **WHEN** two run references are compared
- **THEN** the contract offers equality and no ordering, freshness, or precedence meaning
