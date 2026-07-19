UV_CACHE_DIR ?= .cache/uv
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
.PHONY: sync hooks format lint typecheck test docs spec secrets artifacts precommit check counties \
	codex-image review-packet prepr prepr-no-ai codex-smoke \
	codex-observability-fixtures codex-observability-validate codex-observability-qa \
	runner-contract-tests countyforge-runner-check countyforge-profile-tests \
	countyforge-request-fixtures codex-image-openai codex-smoke-openai

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

codex-image-openai:
	CODEX_PROVIDER=openai ./.ai/codex/01-build-codex-image.sh

review-packet:
	@mkdir -p .ai/reviews
	@packet_tmp="$$(mktemp .ai/reviews/.review-packet.XXXXXX)"; \
		provenance_tmp="$$(mktemp .ai/reviews/.review-packet-provenance.XXXXXX)"; \
		trap 'rm -f "$$packet_tmp" "$$provenance_tmp"' EXIT; \
		./scripts/dev-loop/build-review-packet.sh "$${BASE:-origin/main}" > "$$packet_tmp"; \
		python3 scripts/dev-loop/build-review-packet-provenance.py \
			--repo-root "$$PWD" \
			--packet "$$packet_tmp" \
			--repository TruPryce/property-tax-data-platform \
			> "$$provenance_tmp"; \
		mv "$$packet_tmp" .ai/reviews/review-packet.md; \
		mv "$$provenance_tmp" .ai/reviews/review-packet.provenance.json; \
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

codex-smoke-openai:
	@test "$${RUN_LIVE_PROVIDER_SMOKE:-0}" = "1" || { \
		echo "error: set RUN_LIVE_PROVIDER_SMOKE=1 to authorize the paid OpenAI smoke test" >&2; \
		exit 2; \
	}
	CODEX_PROVIDER=openai RUN_LIVE_PROVIDER_SMOKE=1 ./.ai/codex/03-smoke-test.sh

codex-observability-fixtures:
	./.ai/codex/05-test-observability-export-fixtures.sh

codex-observability-validate:
	./.ai/codex/04-validate-observability-export.sh

codex-observability-qa:
	./.ai/codex/06-qa-observability.sh

countyforge-request-fixtures:
	$(UV) run pytest tools/countyforge-runner/tests/test_resolution.py -q

countyforge-profile-tests:
	$(UV) run pytest \
		tools/countyforge-runner/tests/test_execution.py \
		tools/countyforge-runner/tests/test_compatibility.py -q

countyforge-runner-check:
	$(UV) run ruff format --check tools/countyforge-runner scripts/dev-loop/build-countyforge-review-request.py scripts/dev-loop/build-review-packet-provenance.py
	$(UV) run ruff check tools/countyforge-runner scripts/dev-loop/build-countyforge-review-request.py scripts/dev-loop/build-review-packet-provenance.py
	$(UV) run mypy -p countyforge_runner
	$(UV) run pytest tools/countyforge-runner/tests -q
	$(UV) run --package countyforge-runner countyforge-runner list-profiles --json >/dev/null

# Free and deterministic: no Docker, provider, secret-manager, or collector call.
runner-contract-tests: countyforge-runner-check
	bash -n $(RUNNER_SHELL_SCRIPTS)
	@for schema in .ai/schemas/*.json .ai/profiles/*.json .ai/providers/*.json; do \
		python3 -m json.tool "$$schema" >/dev/null || exit 1; \
	done
	./scripts/dev-loop/test-build-review-packet.sh
	./scripts/dev-loop/test-review-output-paths.sh
	./scripts/dev-loop/test-run-directory-guard.sh
	./scripts/dev-loop/test-runner-identity.sh
	./.ai/codex/05-test-observability-export-fixtures.sh
	./scripts/dev-loop/check-runner-identity.sh .ai
