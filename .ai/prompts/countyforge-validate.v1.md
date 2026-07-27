# CountyForge Validate Profile v1

This is the reserved no-model validation contract for
`TruPryce/property-tax-data-platform`. `validate.deterministic.v1` currently has no executor, so
CountyForge must fail closed with `profile_not_implemented`. This prompt never authorizes a provider
call, shell exposed to a model, repository write, network access, credential selection, GitHub
publication, or production connection.

When a later accepted issue implements the deterministic executor:

- Mount the candidate repository read-only and write only declared run artifacts under `/out`.
- Execute only the profile-declared commands: `make check`, `make runner-contract-tests`,
  `make countyforge-runner-check`, and `make prepr-no-ai`. Do not run `make prepr`,
  `make codex-smoke`, `make codex-smoke-openai`, or any `RUN_LIVE_PROVIDER_SMOKE=1` command.
- Treat `make check` as the repository gate for Ruff, strict mypy, pytest, documentation links,
  strict OpenSpec validation/doctor, secret scanning, and repository artifact policy.
- Treat `make runner-contract-tests` as the free CountyForge profile, request, GitHub-control-plane,
  planning, implementation, shell, schema, observability, and sandbox fixture suite.
- Keep the candidate repository read-only. If a declared command such as `make prepr-no-ai` cannot
  run without writing its normal `.ai/reviews` packet files, record validation as blocked; this
  prompt cannot authorize a writable candidate mount, undeclared artifact, or profile expansion.
- Never contact official Dallas, Collin, Tarrant, Denton, Rockwall, or Ellis sources, Airflow,
  PostgreSQL, S3, Bitwarden, Docker services, or a model provider.
- Return exactly the fields in `.ai/schemas/countyforge-validation-result.schema.json`. Record exact
  commands and check outcomes from trusted process evidence, put failures and warnings in their
  matching arrays, reference only declared artifacts, and mark `merge_eligibility` ineligible
  unless every required check passed for the same immutable candidate.
