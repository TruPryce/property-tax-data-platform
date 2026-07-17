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
| GitHub Issue intake and OpenSpec planning | Scaffolded |
| Pre-commit and CI secret and source-artifact scanning | Scaffolded |
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
| [`docs/`](docs/README.md) | Architecture, source, decision, and operations reference |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/config.yml) | Structured work intake |

## Development

Start with [CONTRIBUTING.md](CONTRIBUTING.md). The active foundation change is [bootstrap-six-county-appraisal-platform](openspec/changes/bootstrap-six-county-appraisal-platform/README.md).
