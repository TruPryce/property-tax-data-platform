UV_CACHE_DIR ?= .cache/uv
UV := UV_CACHE_DIR=$(UV_CACHE_DIR) uv
.PHONY: sync hooks format lint typecheck test docs spec secrets artifacts precommit check counties \
	codex-image review-packet prepr prepr-no-ai codex-smoke \
	codex-observability-fixtures codex-observability-validate codex-observability-qa \
	runner-contract-tests countyforge-runner-check countyforge-profile-tests \
	countyforge-request-fixtures countyforge-github-check countyforge-command-fixtures \
	countyforge-workflow-policy-tests countyforge-plan-check countyforge-plan-fixtures \
	countyforge-plan-policy-tests countyforge-plan-image countyforge-implement-check \
	countyforge-implement-fixtures countyforge-implement-policy-tests codex-image-openai codex-smoke-openai


RUNNER_SHELL_SCRIPTS := \
	scripts/dev-loop/build-review-packet.sh \
	scripts/dev-loop/check-runner-identity.sh \
	scripts/dev-loop/prepr.sh \
	scripts/dev-loop/prepare-countyforge-target.sh \
	scripts/dev-loop/test-countyforge-target-preparation.sh \
	scripts/dev-loop/test-build-review-packet.sh \
	scripts/dev-loop/test-review-output-paths.sh \
	scripts/dev-loop/test-run-directory-guard.sh \
	scripts/dev-loop/test-runner-identity.sh \
	.ai/codex/01-build-codex-image.sh \
	.ai/codex/02-run-prepr-review-docker.sh \
	.ai/codex/03-smoke-test.sh \
	.ai/codex/04-validate-observability-export.sh \
	.ai/codex/05-test-observability-export-fixtures.sh \
	.ai/codex/06-qa-observability.sh \
	.ai/codex/07-build-countyforge-plan-image.sh \
	.ai/codex/08-run-countyforge-plan-docker.sh \
	.ai/codex/09-run-countyforge-implement-docker.sh \
	.ai/codex/10-build-countyforge-implement-image.sh

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

countyforge-github-check:
	$(UV) run ruff format --check tools/countyforge-github
	$(UV) run ruff check tools/countyforge-github
	$(UV) run mypy -p countyforge_github
	$(UV) run pytest tools/countyforge-github/tests -q
	$(UV) run --package countyforge-github countyforge-github check >/dev/null

countyforge-command-fixtures:
	$(UV) run pytest \
		tools/countyforge-github/tests/test_commands.py \
		tools/countyforge-github/tests/test_authorization_identity.py \
		tools/countyforge-github/tests/test_orchestrator.py -q

countyforge-workflow-policy-tests:
	$(UV) run pytest tools/countyforge-github/tests/test_workflow_policy.py -q
	./scripts/dev-loop/test-countyforge-target-preparation.sh

countyforge-plan-check:
	$(UV) run ruff format --check tools/countyforge-github/src/countyforge_github/planning.py tools/countyforge-github/tests/test_planning.py
	$(UV) run ruff check tools/countyforge-github/src/countyforge_github/planning.py tools/countyforge-github/tests/test_planning.py
	$(UV) run mypy tools/countyforge-github/src/countyforge_github/planning.py
	$(UV) run python3 -m json.tool .ai/schemas/countyforge-plan-result.schema.json >/dev/null

countyforge-plan-fixtures:
	$(UV) run pytest tools/countyforge-github/tests/test_planning.py tools/countyforge-runner/tests/test_execution.py -q

countyforge-plan-policy-tests:
	$(UV) run pytest tools/countyforge-github/tests/test_workflow_policy.py tools/countyforge-github/tests/test_requests.py -q

countyforge-plan-image:
	./.ai/codex/07-build-countyforge-plan-image.sh

countyforge-implement-check:
	$(UV) run ruff format --check tools/countyforge-github/src/countyforge_github/implementation.py tools/countyforge-github/tests/test_implementation.py tools/countyforge-runner/src/countyforge_runner/command_broker.py tools/countyforge-runner/tests/test_command_broker.py
	$(UV) run ruff check tools/countyforge-github/src/countyforge_github/implementation.py tools/countyforge-github/tests/test_implementation.py tools/countyforge-runner/src/countyforge_runner/command_broker.py tools/countyforge-runner/tests/test_command_broker.py
	$(UV) run mypy tools/countyforge-github/src/countyforge_github/implementation.py tools/countyforge-runner/src/countyforge_runner/command_broker.py
	$(UV) run python -m json.tool .ai/schemas/countyforge-implementation-result.schema.json >/dev/null
	$(UV) run python -m json.tool .ai/schemas/countyforge-implementation-packet.schema.json >/dev/null

countyforge-implement-fixtures:
	$(UV) run pytest tools/countyforge-github/tests/test_implementation.py tools/countyforge-runner/tests/test_execution.py tools/countyforge-runner/tests/test_command_broker.py -q

countyforge-implement-policy-tests:
	$(UV) run pytest tools/countyforge-github/tests/test_workflow_policy.py tools/countyforge-github/tests/test_requests.py -q

# Free and deterministic: no Docker, provider, secret-manager, or collector call.
runner-contract-tests: countyforge-runner-check countyforge-github-check \
	countyforge-command-fixtures countyforge-workflow-policy-tests countyforge-plan-check \
	countyforge-plan-fixtures countyforge-plan-policy-tests countyforge-implement-check \
	countyforge-implement-fixtures countyforge-implement-policy-tests
	bash -n $(RUNNER_SHELL_SCRIPTS)
	@for schema in .ai/schemas/*.json .ai/profiles/*.json .ai/providers/*.json .ai/policies/*.json; do \
		python3 -m json.tool "$$schema" >/dev/null || exit 1; \
	done
	./scripts/dev-loop/test-build-review-packet.sh
	./scripts/dev-loop/test-review-output-paths.sh
	./scripts/dev-loop/test-run-directory-guard.sh
	./scripts/dev-loop/test-runner-identity.sh
	./.ai/codex/05-test-observability-export-fixtures.sh
	./scripts/dev-loop/check-runner-identity.sh .ai
