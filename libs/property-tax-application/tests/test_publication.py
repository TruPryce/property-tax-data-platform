"""Task-local falsification for publication admission and freshness lineage."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from property_tax_application.bronze import ManifestIndex, ManifestRef, ReleasePartition
from property_tax_application.publication import (
    PublicationAttempt,
    PublicationAttemptClosedError,
    PublicationProduct,
    PublicationQualityError,
    PublicationQualityUnavailableError,
    PublicationRef,
    PublicationRepository,
)
from property_tax_application.quality import (
    QualityEvaluation,
    QualityRule,
    QualityVerdict,
    RuleSeverity,
)
from property_tax_application.runs import ProcessingRunRef
from property_tax_domain import Jurisdiction, ReleaseIdentity, ReleaseKind

SOURCE_AS_OF = datetime(2026, 8, 18, 17, 0, tzinfo=UTC)
ACQUIRED_AT = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
CLOCK_NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def release(
    *,
    year: int = 2026,
    kind: ReleaseKind = ReleaseKind.CERTIFIED,
    identifier: str = "certified-2026",
) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=Jurisdiction(
            state_code="tx",
            county_slug="dallas",
            county_fips="48113",
        ),
        tax_year=year,
        release_kind=kind,
        release_identifier=identifier,
    )


def rule(
    *,
    version: int = 1,
    severity: RuleSeverity = RuleSeverity.BLOCKING,
) -> QualityRule:
    return QualityRule(
        identifier="required_account_key",
        version=version,
        severity=severity,
        family="required_key_completeness",
    )


def result(configured: QualityRule, *, passed: bool = True) -> QualityEvaluation:
    return QualityEvaluation(
        rule_identifier=configured.identifier,
        rule_version=configured.version,
        passed=passed,
        measured_value=None if passed else "0.9",
        expected_value=None if passed else "1.0",
    )


class QualityEngine:
    def __init__(self) -> None:
        self.active: tuple[QualityRule, ...] = ()
        self.evaluations: dict[ProcessingRunRef, list[QualityEvaluation]] = defaultdict(list)
        self.verdict_calls = 0

    def record(self, run: ProcessingRunRef, evaluation: QualityEvaluation) -> None:
        self.evaluations[run].append(evaluation)

    def verdict(self, run: ProcessingRunRef) -> QualityVerdict:
        self.verdict_calls += 1
        by_identifier: dict[str, list[QualityRule]] = defaultdict(list)
        for configured in self.active:
            by_identifier[configured.identifier].append(configured)
        ambiguous = tuple(
            identifier for identifier, versions in by_identifier.items() if len(versions) > 1
        )
        missing: list[QualityRule] = []
        stale: list[QualityRule] = []
        blocking_failures: list[QualityEvaluation] = []
        warning_failures: list[QualityEvaluation] = []
        recorded = self.evaluations[run]
        for identifier, versions in by_identifier.items():
            if identifier in ambiguous:
                continue
            configured = versions[0]
            candidates = [entry for entry in recorded if entry.rule_identifier == identifier]
            exact = [entry for entry in candidates if entry.rule_version == configured.version]
            if configured.severity is RuleSeverity.BLOCKING:
                if not candidates:
                    missing.append(configured)
                elif not exact:
                    stale.append(configured)
                blocking_failures.extend(entry for entry in exact if not entry.passed)
            else:
                warning_failures.extend(entry for entry in exact if not entry.passed)
        return QualityVerdict(
            run=run,
            missing_blocking_rules=tuple(missing),
            stale_blocking_rules=tuple(stale),
            ambiguous_rule_identifiers=ambiguous,
            blocking_failures=tuple(blocking_failures),
            warning_failures=tuple(warning_failures),
        )


@dataclass
class AttemptState:
    reference: PublicationRef
    product: PublicationProduct
    release: ReleaseIdentity
    run: ProcessingRunRef
    source_as_of: datetime | None
    state: str = "building"
    supersedes: PublicationRef | None = None
    superseded_by: PublicationRef | None = None


class FakePublicationAttempt:
    def __init__(self, store: FakePublicationRepository, reference: PublicationRef) -> None:
        self.store = store
        self._reference = reference

    @property
    def reference(self) -> PublicationRef:
        return self._reference

    def activate(self) -> None:
        self.store.activate(self._reference)

    def fail(self) -> None:
        self.store.fail(self._reference)


class FakePublicationRepository:
    """A deterministic state fake, not proof of a particular persistence mechanism."""

    def __init__(self, quality: QualityEngine, *, can_serialize: bool = True) -> None:
        self.quality = quality
        self.can_serialize = can_serialize
        self.attempts: dict[PublicationRef, AttemptState] = {}
        self.current: dict[tuple[PublicationProduct, str], PublicationRef] = {}
        self.next_reference = 1

    def open(
        self,
        product: PublicationProduct,
        release: ReleaseIdentity,
        run: ProcessingRunRef,
        source_as_of: datetime | None,
    ) -> FakePublicationAttempt:
        if not isinstance(product, PublicationProduct):
            raise ValueError("product must be a PublicationProduct")
        if type(release) is not ReleaseIdentity:
            raise ValueError("release must be exactly a ReleaseIdentity")
        if type(run) is not ProcessingRunRef:
            raise ValueError("run must be exactly a ProcessingRunRef")
        if source_as_of is not None and (
            not isinstance(source_as_of, datetime)
            or source_as_of.tzinfo is None
            or source_as_of.utcoffset() is None
        ):
            raise ValueError("source_as_of must be timezone-aware or None")
        reference = PublicationRef(self.next_reference)
        self.next_reference += 1
        self.attempts[reference] = AttemptState(
            reference=reference,
            product=product,
            release=release,
            run=run,
            source_as_of=source_as_of,
        )
        return FakePublicationAttempt(self, reference)

    def activate(self, reference: PublicationRef) -> None:
        state = self.attempts[reference]
        if state.state != "building":
            raise PublicationAttemptClosedError("publication attempt is already terminal")
        if not self.can_serialize:
            raise PublicationQualityUnavailableError(
                "quality cannot be derived inside the activation boundary"
            )
        verdict = self.quality.verdict(state.run)
        if not verdict.clean:
            raise PublicationQualityError(verdict)
        key = (state.product, state.release.jurisdiction.rendered)
        previous_reference = self.current.get(key)
        if previous_reference is not None:
            previous = self.attempts[previous_reference]
            previous.state = "superseded"
            previous.superseded_by = reference
        state.state = "current"
        state.supersedes = previous_reference
        self.current[key] = reference

    def fail(self, reference: PublicationRef) -> None:
        state = self.attempts[reference]
        if state.state != "building":
            raise PublicationAttemptClosedError("publication attempt is already terminal")
        state.state = "failed"

    def current_for(
        self,
        product: PublicationProduct,
        jurisdiction: Jurisdiction,
    ) -> PublicationRef | None:
        return self.current.get((product, jurisdiction.rendered))


def activated_attempt(
    repository: FakePublicationRepository,
    run: ProcessingRunRef,
) -> FakePublicationAttempt:
    attempt = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(),
        run,
        SOURCE_AS_OF,
    )
    attempt.activate()
    return attempt


def test_publication_product_and_reference_are_closed_and_opaque() -> None:
    assert tuple(PublicationProduct) == (
        PublicationProduct.LATEST_AVAILABLE,
        PublicationProduct.LATEST_CERTIFIED,
        PublicationProduct.HISTORY,
    )
    assert PublicationRef(1) == PublicationRef(1)
    with pytest.raises(TypeError, match="no ordering"):
        assert PublicationRef(1) < PublicationRef(2)


def test_failed_attempt_leaves_the_previous_publication_current() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    current = activated_attempt(repository, ProcessingRunRef("run-a"))
    failed = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(identifier="certified-2026-r2"),
        ProcessingRunRef("run-b"),
        SOURCE_AS_OF,
    )

    failed.fail()

    assert (
        repository.current_for(
            PublicationProduct.LATEST_AVAILABLE,
            release().jurisdiction,
        )
        == current.reference
    )
    assert repository.attempts[failed.reference].state == "failed"


def test_clean_activation_becomes_current_and_records_supersession() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    first = activated_attempt(repository, ProcessingRunRef("run-a"))
    second = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(identifier="certified-2026-r2"),
        ProcessingRunRef("run-b"),
        SOURCE_AS_OF,
    )

    second.activate()

    assert (
        repository.current_for(
            PublicationProduct.LATEST_AVAILABLE,
            release().jurisdiction,
        )
        == second.reference
    )
    assert repository.attempts[second.reference].supersedes == first.reference
    assert repository.attempts[first.reference].superseded_by == second.reference


@pytest.mark.parametrize("quality_case", ["missing", "stale", "ambiguous", "failed"])
def test_every_quality_refusal_preserves_the_previous_current_publication(
    quality_case: str,
) -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    first = activated_attempt(repository, ProcessingRunRef("run-a"))
    run = ProcessingRunRef("run-b")
    version_one = rule(version=1)
    version_two = rule(version=2)
    if quality_case == "missing":
        quality.active = (version_two,)
    elif quality_case == "stale":
        quality.active = (version_two,)
        quality.record(run, result(version_one))
    elif quality_case == "ambiguous":
        quality.active = (version_one, version_two)
    else:
        quality.active = (version_two,)
        quality.record(run, result(version_two, passed=False))
    attempted = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(identifier="certified-2026-r2"),
        run,
        SOURCE_AS_OF,
    )

    with pytest.raises(PublicationQualityError):
        attempted.activate()

    assert (
        repository.current_for(
            PublicationProduct.LATEST_AVAILABLE,
            release().jurisdiction,
        )
        == first.reference
    )
    assert repository.attempts[first.reference].state == "current"
    assert repository.attempts[attempted.reference].state == "building"


def test_activation_recomputes_after_an_advisory_verdict_and_closes_the_race() -> None:
    run = ProcessingRunRef("run-a")
    version_one = rule(version=1)
    version_two = rule(version=2)
    quality = QualityEngine()
    quality.active = (version_one,)
    quality.record(run, result(version_one))
    repository = FakePublicationRepository(quality)
    attempt = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(),
        run,
        SOURCE_AS_OF,
    )
    advisory = quality.verdict(run)
    assert advisory.clean is True
    calls_before_activation = quality.verdict_calls

    quality.active = (version_two,)
    with pytest.raises(PublicationQualityError) as error:
        attempt.activate()

    assert quality.verdict_calls == calls_before_activation + 1
    assert error.value.verdict.stale_blocking_rules == (version_two,)
    assert (
        repository.current_for(
            PublicationProduct.LATEST_AVAILABLE,
            release().jurisdiction,
        )
        is None
    )


def test_activation_refuses_when_quality_and_state_cannot_be_serialized() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    current = activated_attempt(repository, ProcessingRunRef("run-current"))
    repository.can_serialize = False
    attempt = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(identifier="certified-2026-r2"),
        ProcessingRunRef("run-a"),
        SOURCE_AS_OF,
    )

    with pytest.raises(PublicationQualityUnavailableError):
        attempt.activate()

    assert repository.attempts[attempt.reference].state == "building"
    assert repository.attempts[current.reference].state == "current"
    assert (
        repository.current_for(
            PublicationProduct.LATEST_AVAILABLE,
            release().jurisdiction,
        )
        == current.reference
    )


def test_current_publication_is_not_rejudged_when_rules_change_later() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    attempt = activated_attempt(repository, ProcessingRunRef("run-a"))

    quality.active = (rule(version=2),)

    assert repository.attempts[attempt.reference].state == "current"
    assert (
        repository.current_for(
            PublicationProduct.LATEST_AVAILABLE,
            release().jurisdiction,
        )
        == attempt.reference
    )
    assert quality.verdict_calls == 1


def test_a_new_run_recovers_after_the_old_run_becomes_stale() -> None:
    run_a = ProcessingRunRef("run-a")
    run_b = ProcessingRunRef("run-b")
    version_one = rule(version=1)
    version_two = rule(version=2)
    quality = QualityEngine()
    quality.active = (version_one,)
    quality.record(run_a, result(version_one))
    repository = FakePublicationRepository(quality)
    old_attempt = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(),
        run_a,
        SOURCE_AS_OF,
    )
    quality.active = (version_two,)

    with pytest.raises(PublicationQualityError):
        old_attempt.activate()

    quality.record(run_b, result(version_two))
    new_attempt = repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        release(),
        run_b,
        SOURCE_AS_OF,
    )
    new_attempt.activate()

    assert quality.verdict(run_b).clean is True
    assert repository.attempts[new_attempt.reference].state == "current"


class FakeManifestIndex:
    def __init__(self) -> None:
        self.partitions: dict[
            tuple[ManifestRef, ReleaseIdentity],
            ReleasePartition,
        ] = {}

    def register(self, manifest: object) -> ManifestRef:
        raise AssertionError("publication retry must not register an acquisition")

    def attach_partition(self, reference: ManifestRef, partition: ReleasePartition) -> None:
        raise AssertionError("publication retry must not attach new evidence")

    def partition_for(
        self,
        reference: ManifestRef,
        requested_release: ReleaseIdentity,
    ) -> ReleasePartition | None:
        return self.partitions.get((reference, requested_release))


def open_retry_from_recorded_partition(
    repository: PublicationRepository,
    manifest_index: ManifestIndex,
    run_manifests: dict[ProcessingRunRef, ManifestRef],
    product: PublicationProduct,
    requested_release: ReleaseIdentity,
    run: ProcessingRunRef,
) -> PublicationAttempt:
    partition = manifest_index.partition_for(run_manifests[run], requested_release)
    if partition is None:
        raise LookupError("the run's manifest has no evidence for this release")
    return repository.open(product, requested_release, run, partition.source_as_of)


def record_partition(
    index: FakeManifestIndex,
    reference: ManifestRef,
    requested_release: ReleaseIdentity,
    source_as_of: datetime | None,
) -> None:
    index.partitions[(reference, requested_release)] = ReleasePartition(
        jurisdiction_code=requested_release.jurisdiction.rendered,
        tax_year=requested_release.tax_year,
        release_kind=requested_release.release_kind.value,
        source_as_of=source_as_of,
    )


def test_retry_reads_durable_source_as_of_and_ignores_a_mutated_page() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    index = FakeManifestIndex()
    manifest = ManifestRef(1)
    run = ProcessingRunRef("run-a")
    requested_release = release()
    record_partition(index, manifest, requested_release, SOURCE_AS_OF)
    page_now_says = SOURCE_AS_OF + timedelta(days=10)

    attempt = open_retry_from_recorded_partition(
        repository,
        index,
        {run: manifest},
        PublicationProduct.LATEST_AVAILABLE,
        requested_release,
        run,
    )

    assert repository.attempts[attempt.reference].source_as_of == SOURCE_AS_OF
    assert repository.attempts[attempt.reference].source_as_of != page_now_says


def test_recorded_absence_is_not_replaced_by_acquisition_or_clock_time() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    index = FakeManifestIndex()
    manifest = ManifestRef(1)
    run = ProcessingRunRef("run-a")
    requested_release = release()
    record_partition(index, manifest, requested_release, None)

    attempt = open_retry_from_recorded_partition(
        repository,
        index,
        {run: manifest},
        PublicationProduct.LATEST_AVAILABLE,
        requested_release,
        run,
    )

    observed = repository.attempts[attempt.reference].source_as_of
    assert observed is None
    assert observed != ACQUIRED_AT
    assert observed != CLOCK_NOW


def test_two_releases_on_one_manifest_retain_distinct_freshness() -> None:
    quality = QualityEngine()
    repository = FakePublicationRepository(quality)
    index = FakeManifestIndex()
    manifest = ManifestRef(1)
    certified_run = ProcessingRunRef("run-certified")
    current_run = ProcessingRunRef("run-current")
    certified = release()
    current = release(
        year=2025,
        kind=ReleaseKind.CURRENT,
        identifier="current-2025",
    )
    current_as_of = SOURCE_AS_OF - timedelta(days=30)
    record_partition(index, manifest, certified, SOURCE_AS_OF)
    record_partition(index, manifest, current, current_as_of)
    run_manifests = {certified_run: manifest, current_run: manifest}

    certified_attempt = open_retry_from_recorded_partition(
        repository,
        index,
        run_manifests,
        PublicationProduct.LATEST_CERTIFIED,
        certified,
        certified_run,
    )
    current_attempt = open_retry_from_recorded_partition(
        repository,
        index,
        run_manifests,
        PublicationProduct.LATEST_AVAILABLE,
        current,
        current_run,
    )

    assert repository.attempts[certified_attempt.reference].source_as_of == SOURCE_AS_OF
    assert repository.attempts[current_attempt.reference].source_as_of == current_as_of
    assert isinstance(repository, PublicationRepository)
    assert isinstance(certified_attempt, PublicationAttempt)
