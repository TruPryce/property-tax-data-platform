"""Task-local falsification for run-bound quality values and verdicts."""

from __future__ import annotations

from collections import defaultdict

import pytest
from property_tax_application.quality import (
    QualityEvaluation,
    QualityRepository,
    QualityRule,
    QualityVerdict,
    RuleSeverity,
)
from property_tax_application.runs import ProcessingRunRef


def rule(
    identifier: str = "required_account_key",
    *,
    version: int = 1,
    severity: RuleSeverity = RuleSeverity.BLOCKING,
) -> QualityRule:
    return QualityRule(
        identifier=identifier,
        version=version,
        severity=severity,
        family="required_key_completeness",
        configured_threshold={"minimum_fraction": 1.0},
    )


def evaluation(
    configured_rule: QualityRule,
    *,
    passed: bool = True,
    subject: str | None = None,
) -> QualityEvaluation:
    return QualityEvaluation(
        rule_identifier=configured_rule.identifier,
        rule_version=configured_rule.version,
        passed=passed,
        subject=subject,
        measured_value=None if passed else "0.97",
        expected_value=None if passed else "1.0",
    )


class FakeQualityRepository:
    """A deterministic computation fake, not a persistence proof."""

    def __init__(self, active: tuple[QualityRule, ...] = ()) -> None:
        self.active = active
        self.evaluations: dict[ProcessingRunRef, list[QualityEvaluation]] = defaultdict(list)

    def active_rules(self) -> tuple[QualityRule, ...]:
        return self.active

    def record_evaluation(
        self,
        run: ProcessingRunRef,
        result: QualityEvaluation,
    ) -> None:
        key = (result.rule_identifier, result.subject)
        if any((stored.rule_identifier, stored.subject) == key for stored in self.evaluations[run]):
            raise ValueError("one immutable evaluation per rule, subject, and run")
        self.evaluations[run].append(result)

    def verdict(self, run: ProcessingRunRef) -> QualityVerdict:
        active_by_identifier: dict[str, list[QualityRule]] = defaultdict(list)
        for configured_rule in self.active:
            active_by_identifier[configured_rule.identifier].append(configured_rule)

        ambiguous = tuple(
            sorted(
                identifier
                for identifier, versions in active_by_identifier.items()
                if len(versions) > 1
            )
        )
        recorded_by_identifier: dict[str, list[QualityEvaluation]] = defaultdict(list)
        for result in self.evaluations[run]:
            recorded_by_identifier[result.rule_identifier].append(result)

        missing: list[QualityRule] = []
        stale: list[QualityRule] = []
        blocking_failures: list[QualityEvaluation] = []
        warning_failures: list[QualityEvaluation] = []
        for identifier, versions in active_by_identifier.items():
            if identifier in ambiguous:
                continue
            configured_rule = versions[0]
            results = recorded_by_identifier[identifier]
            exact = [result for result in results if result.rule_version == configured_rule.version]
            if configured_rule.severity is RuleSeverity.BLOCKING:
                if not results:
                    missing.append(configured_rule)
                elif not exact:
                    stale.append(configured_rule)
                blocking_failures.extend(result for result in exact if not result.passed)
            else:
                warning_failures.extend(result for result in exact if not result.passed)

        return QualityVerdict(
            run=run,
            missing_blocking_rules=tuple(missing),
            stale_blocking_rules=tuple(stale),
            ambiguous_rule_identifiers=ambiguous,
            blocking_failures=tuple(blocking_failures),
            warning_failures=tuple(warning_failures),
        )


def test_rule_severity_is_exactly_blocking_or_warning() -> None:
    assert tuple(RuleSeverity) == (RuleSeverity.BLOCKING, RuleSeverity.WARNING)
    assert RuleSeverity("blocking") is RuleSeverity.BLOCKING
    assert RuleSeverity("warning") is RuleSeverity.WARNING

    with pytest.raises(ValueError):
        RuleSeverity("advisory")
    with pytest.raises(ValueError, match="RuleSeverity"):
        QualityRule(
            identifier="required_account_key",
            version=1,
            severity="blocking",  # type: ignore[arg-type]
            family="required_key_completeness",
        )


def test_rule_carries_configuration_without_an_embedded_threshold() -> None:
    configured = rule()

    assert configured.configured_threshold == {"minimum_fraction": 1.0}
    with pytest.raises(TypeError):
        configured.configured_threshold["minimum_fraction"] = 0.5


@pytest.mark.parametrize(("measured", "expected"), [(None, "1"), ("0", None), (None, None)])
def test_failing_evaluation_requires_measured_and_expected_values(
    measured: str | None,
    expected: str | None,
) -> None:
    with pytest.raises(ValueError, match="requires measured_value and expected_value"):
        QualityEvaluation(
            rule_identifier="required_account_key",
            rule_version=1,
            passed=False,
            measured_value=measured,
            expected_value=expected,
        )


def test_missing_active_blocking_rule_is_incomplete_and_not_clean() -> None:
    configured = rule()
    repository = FakeQualityRepository((configured,))

    verdict = repository.verdict(ProcessingRunRef(1))

    assert verdict.missing_blocking_rules == (configured,)
    assert verdict.stale_blocking_rules == ()
    assert verdict.complete is False
    assert verdict.clean is False


def test_newly_activated_blocking_rule_is_missing_for_an_earlier_run() -> None:
    run = ProcessingRunRef(1)
    original = rule("required_account_key")
    added = rule("valid_values", severity=RuleSeverity.BLOCKING)
    repository = FakeQualityRepository((original,))
    repository.record_evaluation(run, evaluation(original))
    assert repository.verdict(run).clean is True

    repository.active = (original, added)
    verdict = repository.verdict(run)

    assert verdict.missing_blocking_rules == (added,)
    assert verdict.complete is False


def test_only_an_old_rule_version_is_reported_as_stale() -> None:
    run = ProcessingRunRef(1)
    version_one = rule(version=1)
    version_two = rule(version=2)
    repository = FakeQualityRepository((version_two,))
    repository.record_evaluation(run, evaluation(version_one))

    verdict = repository.verdict(run)

    assert verdict.missing_blocking_rules == ()
    assert verdict.stale_blocking_rules == (version_two,)
    assert verdict.complete is False


@pytest.mark.parametrize(
    "severities",
    [
        (RuleSeverity.BLOCKING, RuleSeverity.BLOCKING),
        (RuleSeverity.WARNING, RuleSeverity.WARNING),
        (RuleSeverity.BLOCKING, RuleSeverity.WARNING),
    ],
)
def test_two_active_versions_are_ambiguous_before_severity_is_considered(
    severities: tuple[RuleSeverity, RuleSeverity],
) -> None:
    repository = FakeQualityRepository(
        (
            rule(version=1, severity=severities[0]),
            rule(version=2, severity=severities[1]),
        )
    )

    verdict = repository.verdict(ProcessingRunRef(1))

    assert verdict.ambiguous_rule_identifiers == ("required_account_key",)
    assert verdict.complete is False


def test_exact_blocking_passes_are_clean_and_warning_failures_stay_visible() -> None:
    run = ProcessingRunRef(1)
    blocking = rule()
    warning = rule(
        "record_count_drift",
        severity=RuleSeverity.WARNING,
    )
    repository = FakeQualityRepository((blocking, warning))
    repository.record_evaluation(run, evaluation(blocking))
    warning_failure = evaluation(warning, passed=False)
    repository.record_evaluation(run, warning_failure)

    verdict = repository.verdict(run)

    assert verdict.complete is True
    assert verdict.clean is True
    assert verdict.warning_failures == (warning_failure,)
    assert verdict.blocking_failures == ()


def test_blocking_failure_makes_a_complete_verdict_unclean() -> None:
    run = ProcessingRunRef(1)
    blocking = rule()
    repository = FakeQualityRepository((blocking,))
    failure = evaluation(blocking, passed=False)
    repository.record_evaluation(run, failure)

    verdict = repository.verdict(run)

    assert verdict.complete is True
    assert verdict.clean is False
    assert verdict.blocking_failures == (failure,)


def test_verdict_is_computed_and_never_persisted() -> None:
    run = ProcessingRunRef(1)
    configured = rule()
    repository = FakeQualityRepository((configured,))
    first = repository.verdict(run)
    repository.record_evaluation(run, evaluation(configured))
    second = repository.verdict(run)

    assert first.clean is False
    assert second.clean is True
    assert "verdicts" not in vars(repository)
    assert isinstance(repository, QualityRepository)


def test_missing_or_stale_coverage_is_recovered_only_by_a_new_run() -> None:
    run_a = ProcessingRunRef("run-a")
    run_b = ProcessingRunRef("run-b")
    version_one = rule(version=1)
    version_two = rule(version=2)
    repository = FakeQualityRepository((version_one,))
    repository.record_evaluation(run_a, evaluation(version_one))
    repository.active = (version_two,)

    assert repository.verdict(run_a).stale_blocking_rules == (version_two,)
    with pytest.raises(ValueError, match="immutable"):
        repository.record_evaluation(run_a, evaluation(version_two))

    repository.record_evaluation(run_b, evaluation(version_two))
    assert repository.verdict(run_b).clean is True


def test_a_new_run_recovers_a_rule_missing_from_the_earlier_run() -> None:
    run_a = ProcessingRunRef("run-a")
    run_b = ProcessingRunRef("run-b")
    original = rule("required_account_key")
    added = rule("valid_values")
    repository = FakeQualityRepository((original,))
    repository.record_evaluation(run_a, evaluation(original))
    repository.active = (original, added)

    assert repository.verdict(run_a).missing_blocking_rules == (added,)

    repository.record_evaluation(run_b, evaluation(original))
    repository.record_evaluation(run_b, evaluation(added))
    assert repository.verdict(run_b).clean is True
