# Property Tax Data Platform

Spec-driven ingestion, normalization, validation, and publication of county appraisal and property-tax data.

> Status: repository scaffold and initial OpenSpec are complete; no county adapter is production-ready yet.

## Quick Start

1. **Choose:** Use the local developer profile; it exposes source metadata without external services.
2. **Install:** Run `make sync` to create the Python 3.12 uv workspace environment.
3. **Authenticate:** No credentials are required for the scaffold command. Runtime credentials will use Airflow Connections or a secrets backend.
4. **Try:** Run `make counties` to inspect the six registered county sources.

## Capabilities

| Capability | Current state |
|---|---|
| GitHub Issue intake and OpenSpec planning | Structured intake and accepted OpenSpec workflow |
| Pre-commit and CI secret and source-artifact scanning | Scaffolded |
| CountyForge mode-aware runner kernel | Review executable; plan/implement/fix/validate fail closed |
| CountyForge GitHub control plane | Authorized comment commands, canonical status, cancel/retry, and packet-only review dispatch |
| Dallas, Collin, Tarrant, Denton, Rockwall, and Ellis source registry | Scaffolded |
| Hexagonal Python package boundaries | Scaffolded |
| Immutable Bronze acquisition | Specified, not implemented |
| Canonical Silver normalization | Specified, not implemented |
| Validated Gold publication | Specified, not implemented |
| Authoritative tax bills and payments | Out of scope for the initial change |

## Repository Map

| Area | Responsibility |
|---|---|
| [`openspec/`](openspec/README.md) | Accepted requirements, designs, and implementation tasks |
| [`dags/`](dags/README.md) | Thin Airflow inbound adapters |
| [`libs/`](libs/README.md) | Reusable domain, application, and outbound-adapter packages |
| [`services/`](services/README.md) | Runtime composition and deployable process entry points |
| [`tools/`](tools/README.md) | Repository developer-platform packages, including CountyForge |
| [`docs/`](docs/README.md) | Architecture, source, decision, and operations reference |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/config.yml) | Structured work intake |

## Development

Start with [CONTRIBUTING.md](CONTRIBUTING.md). Accepted behavior lives in [OpenSpec](openspec/README.md); CountyForge architecture and operations are indexed from the [documentation hub](docs/README.md).

## Licensing

Project software and documentation are licensed under the [Apache License 2.0](LICENSE); see
[NOTICE](NOTICE) for attribution. Synthetic fixtures and generated demo datasets are released
under CC0 1.0 Universal. Third-party county data retains its publisher's terms and is not granted
under the project software license. See [Data Licensing](DATA_LICENSE.md) for the complete data
boundary.
