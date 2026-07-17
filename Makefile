UV_CACHE_DIR ?= .cache/uv
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
.PHONY: sync hooks format lint typecheck test docs spec secrets artifacts precommit check counties

sync:
	$(UV) sync --all-packages --group dev

hooks: sync
	$(UV) run pre-commit install

format:
	$(UV) run ruff format .

lint:
	$(UV) run ruff format --check .
	$(UV) run ruff check .

typecheck:
	$(UV) run mypy

test:
	$(UV) run pytest

docs:
	$(UV) run python scripts/check_doc_links.py

spec:
	openspec validate --all --strict --no-interactive
	openspec doctor

secrets:
	@UV_CACHE_DIR=$(UV_CACHE_DIR); export UV_CACHE_DIR; git ls-files --cached --others --exclude-standard -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline --exclude-files '^\.secrets\.baseline$$' # pragma: allowlist secret

artifacts:
	$(UV) run python scripts/check_repository_artifacts.py

precommit:
	$(UV) run pre-commit run --all-files --show-diff-on-failure

check: lint typecheck test docs spec secrets artifacts

counties:
	$(UV) run --package property-tax-ingestion-worker property-tax-ingestion counties
