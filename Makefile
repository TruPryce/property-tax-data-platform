UV_CACHE_DIR ?= .cache/uv
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
.PHONY: sync hooks format lint typecheck test docs spec secrets artifacts precommit check counties \
	codex-image review-packet prepr prepr-no-ai codex-smoke \
	codex-observability-fixtures codex-observability-validate codex-observability-qa \
	runner-contract-tests

RUNNER_SHELL_SCRIPTS := \
	scripts/dev-loop/build-review-packet.sh \
	scripts/dev-loop/check-runner-identity.sh \
	scripts/dev-loop/prepr.sh \
	scripts/dev-loop/test-build-review-packet.sh \
	scripts/dev-loop/test-review-output-paths.sh \
	scripts/dev-loop/test-run-directory-guard.sh \
	scripts/dev-loop/test-runner-identity.sh \
	.ai/codex/01-build-codex-image.sh \
	.ai/codex/02-run-prepr-review-docker.sh \
	.ai/codex/03-smoke-test.sh \
	.ai/codex/04-validate-observability-export.sh \
	.ai/codex/05-test-observability-export-fixtures.sh \
	.ai/codex/06-qa-observability.sh

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

codex-image:
	./.ai/codex/01-build-codex-image.sh

review-packet:
	@mkdir -p .ai/reviews
	@packet_tmp="$$(mktemp .ai/reviews/.review-packet.XXXXXX)"; \
		trap 'rm -f "$$packet_tmp"' EXIT; \
		./scripts/dev-loop/build-review-packet.sh "$${BASE:-origin/main}" > "$$packet_tmp"; \
		mv "$$packet_tmp" .ai/reviews/review-packet.md; \
		trap - EXIT

prepr:
	./scripts/dev-loop/prepr.sh

prepr-no-ai:
	RUN_CODEX_REVIEW=0 ./scripts/dev-loop/prepr.sh

# Paid live-provider probe. The opt-in variable is required even though the
# target is invoked explicitly, so CI and copied commands cannot spend by accident.
codex-smoke:
	@test "$${RUN_LIVE_PROVIDER_SMOKE:-0}" = "1" || { \
		echo "error: set RUN_LIVE_PROVIDER_SMOKE=1 to authorize the paid smoke test" >&2; \
		exit 2; \
	}
	RUN_LIVE_PROVIDER_SMOKE=1 ./.ai/codex/03-smoke-test.sh

codex-observability-fixtures:
	./.ai/codex/05-test-observability-export-fixtures.sh

codex-observability-validate:
	./.ai/codex/04-validate-observability-export.sh

codex-observability-qa:
	./.ai/codex/06-qa-observability.sh

# Free and deterministic: no Docker, provider, secret-manager, or collector call.
runner-contract-tests:
	bash -n $(RUNNER_SHELL_SCRIPTS)
	python3 -m json.tool .ai/schemas/codex-prepr-review.schema.json >/dev/null
	python3 -m json.tool .ai/schemas/codex-runner-event.schema.json >/dev/null
	./scripts/dev-loop/test-build-review-packet.sh
	./scripts/dev-loop/test-review-output-paths.sh
	./scripts/dev-loop/test-run-directory-guard.sh
	./scripts/dev-loop/test-runner-identity.sh
	./.ai/codex/05-test-observability-export-fixtures.sh
	./scripts/dev-loop/check-runner-identity.sh .ai
