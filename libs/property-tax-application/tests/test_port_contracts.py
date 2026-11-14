"""Complete application-port falsification matrix from the accepted design."""

from __future__ import annotations

import ast
import copy
import inspect
import subprocess
import sys
import typing
from collections import defaultdict
from dataclasses import MISSING, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _fake_load import FakeRepository as FakeCanonicalRepository
from _fake_load import outcome as load_outcome
from property_tax_application.acquisition import RedirectHop, ResponseMetadata
from property_tax_application.bronze import (
    ManifestAttachmentConflictError,
    ManifestIndex,
    ManifestRef,
    ReleaseManifest,
    ReleasePartition,
    StoredArtifact,
)
from property_tax_application.canonical import CanonicalReleaseRepository, ReleaseLoadCompletion
from property_tax_application.clock import Clock
from property_tax_application.discovery import (
    IncompleteReleaseIdentity,
    LogicalReleaseEvidence,
    PageEvidence,
    ReleaseDiscovery,
    SourceCandidate,
    UnchangedRelease,
    promote,
)
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
    QualityRepository,
    QualityRule,
    QualityVerdict,
    RuleSeverity,
)
from property_tax_application.runs import (
    ProcessingRunHeldError,
    ProcessingRunRef,
    ProcessingRunRepository,
    ProcessingRunStart,
    ReleaseDisposition,
    ReleaseProcessingOutcome,
    UnknownProcessingRunError,
)
from property_tax_application.sources import (
    AcquisitionMethod,
    CountySourceDefinition,
    SourceRegistry,
    UnsupportedSource,
)
from property_tax_domain import (
    INITIAL_COUNTIES,
    ArtifactIdentity,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
    county_by_slug,
)

ROOT = Path(__file__).resolve().parents[3]
OBSERVED_AT = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
ACQUIRED_AT = datetime(2026, 11, 11, 13, 0, tzinfo=UTC)
SOURCE_AS_OF = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)
CLOCK_NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

MATRIX_CASES: dict[str, dict[str, str]] = {
    "registry-and-discovery": {
        "R01": "test_page_evidence_bounds_refuse_instead_of_truncate",
        "R02": "test_page_evidence_requires_a_locating_fact_and_preserves_absence",
        "R03": "test_discovery_is_one_jurisdiction_and_failures_are_independent",
        "R04": "test_unknown_jurisdiction_fails_before_network",
        "R05": "test_registered_jurisdiction_resolves_without_kind",
        "R06": "test_unsupported_caller_kind_fails_before_network",
        "R07": "test_content_kind_is_validated_after_parsing_before_promotion",
        "R08": "test_all_counties_have_explicit_expected_media",
        "R09": "test_candidate_and_unchanged_are_distinct_without_download",
        "R10": "test_candidate_with_no_logical_releases_is_valid",
        "R11": "test_three_identity_components_remain_three",
        "R12": "test_promotion_names_missing_components_and_promotes_complete_evidence",
        "R13": "test_parser_evidence_uses_one_promotion_and_two_runs_share_one_manifest",
    },
    "run-and-manifest": {
        "M01": "test_zero_partition_manifest_and_jurisdiction_agreement",
        "M02": "test_each_included_acquisition_component_changes_equivalence",
        "M03": "test_each_excluded_artifact_or_partition_field_preserves_equivalence",
        "M04": "test_equal_acquisition_evidence_compares_equal",
        "M05": "test_manifest_index_registration_and_later_attachment",
        "M06": "test_manifest_value_carries_partition_freshness_without_substitution",
        "M07": "test_partition_freshness_is_not_acquisition_identity",
        "M08": "test_one_acquisition_reference_can_bind_two_releases",
        "M09": "test_run_ports_require_typed_references_and_refuse_unknown_runs",
        "M10": "test_run_lifecycle_resume_race_completion_and_reference_semantics",
    },
    "quality-publication-clock": {
        "Q01": "test_failing_quality_evaluation_requires_explanatory_values",
        "Q02": "test_quality_verdict_distinguishes_missing_stale_clean_and_warning",
        "Q03": "test_quality_ambiguity_precedes_severity",
        "Q04": "test_publication_admission_and_nonretroactivity",
        "Q05": "test_activation_rederives_quality_after_advisory_read",
        "Q06": "test_activation_refuses_when_atomic_quality_admission_is_unavailable",
        "Q07": "test_new_run_recovers_after_stale_quality",
        "Q08": "test_failed_attempt_preserves_current_publication",
        "Q09": "test_manifest_lookup_distinguishes_absence_and_does_not_write",
        "Q10": "test_later_process_publication_uses_recorded_freshness",
        "Q11": "test_publication_freshness_preserves_absence_and_release_grain",
        "Q12": "test_fixed_clock_returns_the_exact_aware_instant",
    },
    "surface-and-proof": {
        "S01": "test_suite_stays_application_contract_only",
        "S02": "test_port_contract_suite_is_collected_by_default",
    },
}


def jurisdiction(slug: str = "dallas") -> Jurisdiction:
    county = county_by_slug(slug)
    return Jurisdiction(
        state_code=county.state_code.casefold(),
        county_slug=county.slug.value,
        county_fips=county.fips,
    )


def release(
    *,
    year: int = 2026,
    kind: ReleaseKind = ReleaseKind.CERTIFIED,
    identifier: str = "release-2026",
) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=jurisdiction(),
        tax_year=year,
        release_kind=kind,
        release_identifier=identifier,
    )


def page(**changes: object) -> PageEvidence:
    values: dict[str, object] = {
        "observed_at": OBSERVED_AT,
        "page_url": "https://example.gov/releases",
        "rendered": False,
        "link_label": "Release archive",
    }
    values.update(changes)
    return PageEvidence(**values)  # type: ignore[arg-type]


def logical(**changes: object) -> LogicalReleaseEvidence:
    values: dict[str, object] = {
        "jurisdiction": jurisdiction(),
        "tax_year": 2026,
        "release_kind": ReleaseKind.CERTIFIED,
        "release_identifier": "release-2026",
        "source_as_of": SOURCE_AS_OF,
    }
    values.update(changes)
    return LogicalReleaseEvidence(**values)  # type: ignore[arg-type]


def candidate(**changes: object) -> SourceCandidate:
    values: dict[str, object] = {
        "jurisdiction": jurisdiction(),
        "source_locator": "https://example.gov/releases/export.zip",
        "remote_metadata": ResponseMetadata(
            status=200,
            headers={"content-type": "application/zip", "etag": '"v1"'},
        ),
        "source_as_of": None,
        "page_evidence": page(),
        "logical_releases": (),
    }
    values.update(changes)
    return SourceCandidate(**values)  # type: ignore[arg-type]


def fake_source_definitions() -> tuple[CountySourceDefinition, ...]:
    return tuple(
        CountySourceDefinition(
            county=county,
            official_url=f"https://example.gov/{county.slug.value}/releases",
            acquisition_method=AcquisitionMethod.BULK_ZIP,
            parser_id=f"test.{county.slug.value}.archive-v1",
            expected_media_types=("application/zip",),
        )
        for county in INITIAL_COUNTIES
    )


class FakeSourceRegistry:
    def __init__(self) -> None:
        self.definitions = {
            jurisdiction(source.county.slug.value): source for source in fake_source_definitions()
        }
        self.supported = {
            requested: frozenset({ReleaseKind.CURRENT, ReleaseKind.CERTIFIED})
            for requested in self.definitions
        }

    def resolve(
        self,
        requested: Jurisdiction,
        release_kind: ReleaseKind | None = None,
    ) -> CountySourceDefinition:
        definition = self.definitions.get(requested)
        if definition is None:
            raise UnsupportedSource(requested, release_kind)
        if release_kind is not None:
            self.validate_release_kind(requested, release_kind)
        return definition

    def validate_release_kind(
        self,
        requested: Jurisdiction,
        release_kind: ReleaseKind,
    ) -> None:
        if requested not in self.definitions or release_kind not in self.supported[requested]:
            raise UnsupportedSource(requested, release_kind)


class FailingNetwork:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self, definition: CountySourceDefinition) -> None:
        self.calls += 1
        raise AssertionError(f"network was reached for {definition.parser_id}")


def resolve_then_acquire(
    registry: SourceRegistry,
    network: FailingNetwork,
    requested: Jurisdiction,
    kind: ReleaseKind | None = None,
) -> None:
    definition = registry.resolve(requested, kind)
    network.acquire(definition)


class FakeDiscovery:
    def __init__(self, results: dict[Jurisdiction, SourceCandidate | UnchangedRelease | Exception]):
        self.results = results
        self.download_calls = 0

    def discover(self, requested: Jurisdiction) -> SourceCandidate | UnchangedRelease:
        result = self.results[requested]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize(
    ("field_name", "maximum", "prefix"),
    [
        ("page_url", 2_048, "https://example.gov/"),
        ("section_heading", 256, ""),
        ("link_label", 256, ""),
        ("directory_path", 256, ""),
        ("published_label", 256, ""),
    ],
)
def test_page_evidence_bounds_refuse_instead_of_truncate(
    field_name: str,
    maximum: int,
    prefix: str,
) -> None:
    accepted = prefix + "a" * (maximum - len(prefix))
    refused = accepted + "a"

    assert getattr(page(**{field_name: accepted}), field_name) == accepted
    with pytest.raises(ValueError, match="at most"):
        page(**{field_name: refused})


def test_page_evidence_requires_a_locating_fact_and_preserves_absence() -> None:
    with pytest.raises(ValueError, match="locating fact"):
        PageEvidence(
            observed_at=OBSERVED_AT,
            page_url="https://example.gov/releases",
            rendered=False,
        )

    evidence = PageEvidence(
        observed_at=OBSERVED_AT,
        page_url="https://example.gov/releases",
        rendered=False,
        directory_path="exports/",
    )
    assert evidence.directory_path == "exports/"
    assert evidence.section_heading is None
    assert evidence.link_label is None
    assert evidence.published_label is None


def test_discovery_is_one_jurisdiction_and_failures_are_independent() -> None:
    first = jurisdiction("dallas")
    second = jurisdiction("collin")
    other = replace(candidate(), jurisdiction=second)
    discovery = FakeDiscovery({first: TimeoutError("publisher timeout"), second: other})

    assert tuple(inspect.signature(ReleaseDiscovery.discover).parameters) == (
        "self",
        "jurisdiction",
    )
    assert not hasattr(discovery, "discover_many")
    with pytest.raises(TimeoutError):
        discovery.discover(first)
    assert discovery.discover(second) is other
    assert isinstance(discovery, ReleaseDiscovery)


def test_unknown_jurisdiction_fails_before_network() -> None:
    registry = FakeSourceRegistry()
    network = FailingNetwork()
    registry.definitions.pop(jurisdiction("rockwall"))
    registry.supported.pop(jurisdiction("rockwall"))

    with pytest.raises(UnsupportedSource, match="tx-rockwall"):
        resolve_then_acquire(registry, network, jurisdiction("rockwall"))

    assert network.calls == 0


def test_registered_jurisdiction_resolves_without_kind() -> None:
    registry = FakeSourceRegistry()

    resolved = registry.resolve(jurisdiction("dallas"))

    assert resolved.county.slug.value == "dallas"
    assert isinstance(registry, SourceRegistry)


def test_unsupported_caller_kind_fails_before_network() -> None:
    registry = FakeSourceRegistry()
    network = FailingNetwork()

    with pytest.raises(UnsupportedSource, match="tx-dallas/supplemental"):
        resolve_then_acquire(
            registry,
            network,
            jurisdiction("dallas"),
            ReleaseKind.SUPPLEMENTAL,
        )

    assert network.calls == 0


def test_content_kind_is_validated_after_parsing_before_promotion() -> None:
    registry = FakeSourceRegistry()
    requested = jurisdiction("dallas")
    parsed = LogicalReleaseEvidence(
        jurisdiction=requested,
        tax_year=2026,
        release_kind=ReleaseKind.CERTIFIED,
        release_identifier="parsed-release",
    )

    assert registry.resolve(requested) is not None
    registry.validate_release_kind(requested, parsed.release_kind)  # type: ignore[arg-type]
    assert promote(parsed).release_kind is ReleaseKind.CERTIFIED


def test_all_counties_have_explicit_expected_media() -> None:
    sources = fake_source_definitions()
    field_names = {field.name for field in CountySourceDefinition.__dataclass_fields__.values()}

    assert len(sources) == 6
    assert all(source.expected_media_types for source in sources)
    assert all(type(source.expected_media_types) is tuple for source in sources)
    assert all(source.expected_media_types == ("application/zip",) for source in sources)
    assert CountySourceDefinition.__dataclass_fields__["expected_media_types"].default is MISSING
    assert not field_names & {"credential", "credentials", "password", "secret", "token"}


def test_candidate_and_unchanged_are_distinct_without_download() -> None:
    requested = jurisdiction()
    unchanged = UnchangedRelease(
        jurisdiction=requested,
        source_locator="https://example.gov/releases/export.zip",
        remote_metadata=ResponseMetadata(status=304),
        source_as_of=None,
        page_evidence=page(),
        artifact=ArtifactIdentity("a" * 64),
    )
    discovery = FakeDiscovery({requested: unchanged})

    result = discovery.discover(requested)

    assert type(result) is UnchangedRelease
    assert type(result) is not SourceCandidate
    assert discovery.download_calls == 0


def test_candidate_with_no_logical_releases_is_valid() -> None:
    assert candidate().logical_releases == ()


def test_three_identity_components_remain_three() -> None:
    evidence = LogicalReleaseEvidence(
        jurisdiction=jurisdiction(),
        tax_year=2026,
        release_kind=ReleaseKind.CERTIFIED,
    )

    assert evidence.release_identifier is None
    with pytest.raises(IncompleteReleaseIdentity) as caught:
        promote(evidence)
    assert caught.value.missing_components == ("release_identifier",)


def test_promotion_names_missing_components_and_promotes_complete_evidence() -> None:
    incomplete = LogicalReleaseEvidence(jurisdiction=jurisdiction())

    with pytest.raises(IncompleteReleaseIdentity) as caught:
        promote(incomplete)

    assert caught.value.missing_components == (
        "tax_year",
        "release_kind",
        "release_identifier",
    )
    assert promote(logical()) == release()


def manifest(
    *,
    jurisdiction_code: str = "tx-dallas",
    sha256: str = "a" * 64,
    acquired_at: datetime = ACQUIRED_AT,
    source_url: str = "https://example.gov/releases/export.zip",
    response: ResponseMetadata | None = None,
    redirects: tuple[RedirectHop, ...] = (),
    partitions: tuple[ReleasePartition, ...] = (),
    locator: str = "artifact-a",
    byte_count: int = 10,
    media_type: str | None = "application/zip",
    tool_versions: dict[str, str] | None = None,
) -> ReleaseManifest:
    return ReleaseManifest(
        jurisdiction=jurisdiction_code,
        artifact=StoredArtifact(
            locator=locator,
            sha256=sha256,
            byte_count=byte_count,
            media_type=media_type,
        ),
        acquired_at=acquired_at,
        source_url=source_url,
        response=response
        if response is not None
        else ResponseMetadata(status=200, headers={"etag": '"v1"'}),
        redirects=redirects,
        partitions=partitions,
        tool_versions=tool_versions if tool_versions is not None else {"platform": "1.0"},
    )


def partition(
    *,
    year: int = 2026,
    kind: str = "certified",
    source_as_of: datetime | None = SOURCE_AS_OF,
) -> ReleasePartition:
    return ReleasePartition(
        jurisdiction_code="tx-dallas",
        tax_year=year,
        release_kind=kind,
        source_as_of=source_as_of,
    )


class FakeManifestIndex:
    def __init__(self) -> None:
        self.by_evidence: dict[tuple[object, ...], ManifestRef] = {}
        self.manifests: dict[ManifestRef, ReleaseManifest] = {}
        self.partitions: dict[tuple[ManifestRef, ReleaseIdentity], ReleasePartition] = {}
        self.write_count = 0
        self.read_count = 0

    def register(self, recorded: ReleaseManifest) -> ManifestRef:
        existing = self.by_evidence.get(recorded.acquisition_evidence)
        if existing is not None:
            return existing
        reference = ManifestRef(len(self.manifests) + 1)
        self.by_evidence[recorded.acquisition_evidence] = reference
        self.manifests[reference] = recorded
        self.write_count += 1
        return reference

    def attach_partition(
        self,
        reference: ManifestRef,
        release: ReleaseIdentity,
        attached: ReleasePartition,
    ) -> None:
        recorded = self.manifests.get(reference)
        if recorded is None:
            raise KeyError(reference)
        if attached.jurisdiction_code != recorded.jurisdiction:
            raise ValueError("partition jurisdiction disagrees with acquisition")
        if attached.jurisdiction_code != release.jurisdiction.rendered:
            raise ValueError("partition jurisdiction disagrees with release identity")
        if attached.tax_year != release.tax_year:
            raise ValueError("partition tax year disagrees with release identity")
        if attached.release_kind != release.release_kind.value:
            raise ValueError("partition release kind disagrees with release identity")
        key = (reference, release)
        existing = self.partitions.get(key)
        if existing is not None:
            if existing != attached:
                raise ManifestAttachmentConflictError(
                    "partition evidence disagrees with the immutable attachment"
                )
            return
        self.partitions[key] = attached
        self.write_count += 1

    def partition_for(
        self,
        reference: ManifestRef,
        requested_release: ReleaseIdentity,
    ) -> ReleasePartition | None:
        if reference not in self.manifests:
            raise KeyError(reference)
        self.read_count += 1
        return self.partitions.get((reference, requested_release))


@dataclass
class RunState:
    release: ReleaseIdentity
    manifest: ManifestRef
    finished: bool = False


class FakeRunRepository:
    def __init__(self) -> None:
        self.runs: dict[ProcessingRunRef, RunState] = {}
        self.held: set[ProcessingRunRef] = set()

    def start(
        self,
        requested_release: ReleaseIdentity,
        manifest_reference: ManifestRef,
    ) -> ProcessingRunStart:
        unfinished = next(
            (
                reference
                for reference, state in reversed(tuple(self.runs.items()))
                if state.release == requested_release and not state.finished
            ),
            None,
        )
        if unfinished is not None:
            if unfinished in self.held:
                raise ProcessingRunHeldError(requested_release.rendered)
            self.held.add(unfinished)
            return ProcessingRunStart(reference=unfinished, resumed=True)
        reference = ProcessingRunRef(len(self.runs) + 1)
        self.runs[reference] = RunState(requested_release, manifest_reference)
        self.held.add(reference)
        return ProcessingRunStart(reference=reference, resumed=False)

    def finish(
        self,
        reference: ProcessingRunRef,
        outcome: ReleaseProcessingOutcome,
    ) -> None:
        if type(reference) is not ProcessingRunRef or reference not in self.runs:
            raise UnknownProcessingRunError(reference)
        self.runs[reference].finished = True
        self.held.discard(reference)

    def abandon(self, reference: ProcessingRunRef) -> None:
        if reference not in self.runs:
            raise UnknownProcessingRunError(reference)
        self.held.discard(reference)


def test_parser_evidence_uses_one_promotion_and_two_runs_share_one_manifest() -> None:
    observed = candidate(
        logical_releases=(
            logical(tax_year=2026, release_identifier="certified-2026"),
            logical(
                tax_year=2025,
                release_kind=ReleaseKind.CURRENT,
                release_identifier="current-2025",
            ),
        ),
    )
    identities = tuple(promote(evidence) for evidence in observed.logical_releases)
    index = FakeManifestIndex()
    reference = index.register(manifest())
    runs = FakeRunRepository()

    started = tuple(runs.start(identity, reference) for identity in identities)

    assert identities[0] != identities[1]
    assert started[0].reference != started[1].reference
    assert {state.manifest for state in runs.runs.values()} == {reference}


def test_zero_partition_manifest_and_jurisdiction_agreement() -> None:
    empty = manifest()

    assert empty.jurisdiction == "tx-dallas"
    assert empty.partitions == ()
    with pytest.raises(ValueError, match="manifest jurisdiction"):
        manifest(
            partitions=(
                ReleasePartition(
                    jurisdiction_code="tx-collin",
                    tax_year=2026,
                    release_kind="certified",
                ),
            )
        )


def _different_manifest_component(base: ReleaseManifest, component: str) -> ReleaseManifest:
    if component == "jurisdiction":
        return replace(base, jurisdiction="tx-collin")
    if component == "sha256":
        return replace(base, artifact=replace(base.artifact, sha256="b" * 64))
    if component == "acquired_at":
        return replace(base, acquired_at=base.acquired_at + timedelta(seconds=1))
    if component == "source_url":
        return replace(base, source_url="https://example.gov/releases/other.zip")
    if component == "response":
        return replace(base, response=ResponseMetadata(status=206, headers={"etag": '"v1"'}))
    if component == "redirects":
        return replace(
            base,
            redirects=(
                RedirectHop(
                    from_url="https://example.gov/releases",
                    to_url=base.source_url,
                    status=302,
                ),
            ),
        )
    if component == "manifest_version":
        changed = copy.copy(base)
        object.__setattr__(changed, "manifest_version", base.manifest_version - 1)
        return changed
    if component == "tool_versions":
        return replace(base, tool_versions={"platform": "2.0"})
    raise AssertionError(component)


@pytest.mark.parametrize(
    "component",
    [
        "jurisdiction",
        "sha256",
        "acquired_at",
        "source_url",
        "response",
        "redirects",
        "manifest_version",
        "tool_versions",
    ],
)
def test_each_included_acquisition_component_changes_equivalence(component: str) -> None:
    base = manifest()
    changed = _different_manifest_component(base, component)

    assert not base.same_acquisition_as(changed)


@pytest.mark.parametrize(
    "component",
    ["partitions", "locator", "byte_count", "media_type"],
)
def test_each_excluded_artifact_or_partition_field_preserves_equivalence(component: str) -> None:
    base = manifest()
    if component == "partitions":
        changed = replace(base, partitions=(partition(),))
    else:
        artifact_changes: dict[str, object] = {
            "locator": "artifact-b",
            "byte_count": 99,
            "media_type": "application/octet-stream",
        }
        changed = replace(
            base,
            artifact=replace(base.artifact, **{component: artifact_changes[component]}),
        )

    assert base.same_acquisition_as(changed)


def test_equal_acquisition_evidence_compares_equal() -> None:
    first = manifest()
    second = manifest()

    assert first is not second
    assert first.same_acquisition_as(second)
    assert first.acquisition_evidence == second.acquisition_evidence


def test_manifest_index_registration_and_later_attachment() -> None:
    index = FakeManifestIndex()
    recorded = manifest()
    same = index.register(recorded)
    duplicate = index.register(
        replace(recorded, artifact=replace(recorded.artifact, locator="artifact-other"))
    )
    distinct = index.register(replace(recorded, acquired_at=ACQUIRED_AT + timedelta(seconds=1)))
    before = index.manifests[same]

    index.attach_partition(same, release(), partition())

    assert same == duplicate
    assert distinct != same
    assert index.manifests[same] is before
    assert index.manifests[same].partitions == ()
    assert index.partition_for(same, release()) == partition()
    assert isinstance(index, ManifestIndex)


def test_manifest_value_carries_partition_freshness_without_substitution() -> None:
    current = SOURCE_AS_OF
    certified = SOURCE_AS_OF - timedelta(days=30)
    recorded = manifest(
        partitions=(
            partition(year=2025, kind="certified", source_as_of=certified),
            partition(kind="current", source_as_of=current),
        )
    )
    absent = manifest(partitions=(partition(source_as_of=None),))

    assert tuple(entry.source_as_of for entry in recorded.partitions) == (certified, current)
    assert all(entry.source_as_of.tzinfo is not None for entry in recorded.partitions)  # type: ignore[union-attr]
    assert absent.partitions[0].source_as_of is None
    assert absent.partitions[0].source_as_of != absent.acquired_at


def test_partition_freshness_is_not_acquisition_identity() -> None:
    first = manifest(partitions=(partition(source_as_of=SOURCE_AS_OF),))
    second = manifest(partitions=(partition(source_as_of=SOURCE_AS_OF + timedelta(days=1)),))

    assert first.same_acquisition_as(second)


def test_one_acquisition_reference_can_bind_two_releases() -> None:
    index = FakeManifestIndex()
    reference = index.register(manifest())
    assert index.register(manifest()) == reference
    certified = partition()
    current = partition(year=2025, kind="current")

    certified_release = release()
    current_release = release(year=2025, kind=ReleaseKind.CURRENT, identifier="current-2025")
    index.attach_partition(reference, certified_release, certified)
    index.attach_partition(reference, current_release, current)

    assert index.partition_for(reference, certified_release) == certified
    assert index.partition_for(reference, current_release) == current


def test_run_ports_require_typed_references_and_refuse_unknown_runs() -> None:
    methods = (
        (CanonicalReleaseRepository.open_load, "run"),
        (QualityRepository.record_evaluation, "run"),
        (QualityRepository.verdict, "run"),
        (PublicationRepository.open, "run"),
        (ProcessingRunRepository.finish, "reference"),
    )
    for method, parameter in methods:
        assert typing.get_type_hints(method)[parameter] is ProcessingRunRef

    runs = FakeRunRepository()
    with pytest.raises(UnknownProcessingRunError):
        runs.finish(
            ProcessingRunRef("unknown"),
            ReleaseProcessingOutcome(ReleaseDisposition.ACCEPTED),
        )


def test_run_lifecycle_resume_race_completion_and_reference_semantics() -> None:
    runs = FakeRunRepository()
    reference = ManifestRef("manifest-1")
    started = runs.start(release(), reference)
    with pytest.raises(ProcessingRunHeldError):
        runs.start(release(), reference)
    runs.abandon(started.reference)
    resumed = runs.start(release(), reference)
    with pytest.raises(ProcessingRunHeldError):
        runs.start(release(), reference)

    canonical = FakeCanonicalRepository()
    first = canonical.open_load(release(), resumed.reference, load_outcome()).commit()
    second = canonical.open_load(release(), resumed.reference, load_outcome()).commit()

    assert resumed.reference == started.reference
    assert resumed.resumed is True
    assert first == ReleaseLoadCompletion(resumed.reference, False)
    assert second == ReleaseLoadCompletion(resumed.reference, True)
    assert ProcessingRunRef("same") == ProcessingRunRef("same")
    with pytest.raises(TypeError, match="no ordering"):
        _ = ProcessingRunRef(1) < ProcessingRunRef(2)

    runs.finish(resumed.reference, ReleaseProcessingOutcome(ReleaseDisposition.ACCEPTED))
    next_run = runs.start(release(), reference)
    assert next_run.resumed is False
    assert next_run.reference != resumed.reference


def quality_rule(
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
    )


def quality_evaluation(
    configured: QualityRule,
    *,
    passed: bool = True,
) -> QualityEvaluation:
    return QualityEvaluation(
        rule_identifier=configured.identifier,
        rule_version=configured.version,
        passed=passed,
        measured_value=None if passed else "0.9",
        expected_value=None if passed else "1.0",
    )


class FakeQualityRepository:
    def __init__(self, active: tuple[QualityRule, ...] = ()) -> None:
        self.active = active
        self.evaluations: dict[ProcessingRunRef, list[QualityEvaluation]] = defaultdict(list)
        self.verdict_calls = 0

    def active_rules(self) -> tuple[QualityRule, ...]:
        return self.active

    def record_evaluation(
        self,
        run: ProcessingRunRef,
        evaluation: QualityEvaluation,
    ) -> None:
        key = (evaluation.rule_identifier, evaluation.subject)
        if any((stored.rule_identifier, stored.subject) == key for stored in self.evaluations[run]):
            raise ValueError("one immutable evaluation per rule, subject, and run")
        self.evaluations[run].append(evaluation)

    def verdict(self, run: ProcessingRunRef) -> QualityVerdict:
        self.verdict_calls += 1
        active_by_identifier: dict[str, list[QualityRule]] = defaultdict(list)
        for configured in self.active:
            active_by_identifier[configured.identifier].append(configured)
        ambiguous = tuple(
            sorted(
                identifier
                for identifier, versions in active_by_identifier.items()
                if len(versions) > 1
            )
        )
        recorded_by_identifier: dict[str, list[QualityEvaluation]] = defaultdict(list)
        for evaluation in self.evaluations[run]:
            recorded_by_identifier[evaluation.rule_identifier].append(evaluation)

        missing: list[QualityRule] = []
        stale: list[QualityRule] = []
        blocking_failures: list[QualityEvaluation] = []
        warning_failures: list[QualityEvaluation] = []
        for identifier, versions in active_by_identifier.items():
            if identifier in ambiguous:
                continue
            configured = versions[0]
            recorded = recorded_by_identifier[identifier]
            exact = [entry for entry in recorded if entry.rule_version == configured.version]
            if configured.severity is RuleSeverity.BLOCKING:
                if not recorded:
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
class PublicationState:
    reference: PublicationRef
    product: PublicationProduct
    release: ReleaseIdentity
    run: ProcessingRunRef
    source_as_of: datetime | None
    status: str = "building"
    supersedes: PublicationRef | None = None
    superseded_by: PublicationRef | None = None


class FakePublicationAttempt:
    def __init__(self, repository: FakePublicationRepository, reference: PublicationRef) -> None:
        self.repository = repository
        self._reference = reference

    @property
    def reference(self) -> PublicationRef:
        return self._reference

    def activate(self) -> None:
        self.repository.activate(self._reference)

    def fail(self) -> None:
        self.repository.fail(self._reference)


class FakePublicationRepository:
    def __init__(
        self,
        quality: FakeQualityRepository,
        *,
        can_serialize: bool = True,
    ) -> None:
        self.quality = quality
        self.can_serialize = can_serialize
        self.attempts: dict[PublicationRef, PublicationState] = {}
        self.current: dict[tuple[PublicationProduct, str], PublicationRef] = {}

    def open(
        self,
        product: PublicationProduct,
        requested_release: ReleaseIdentity,
        run: ProcessingRunRef,
        source_as_of: datetime | None,
    ) -> FakePublicationAttempt:
        reference = PublicationRef(len(self.attempts) + 1)
        self.attempts[reference] = PublicationState(
            reference,
            product,
            requested_release,
            run,
            source_as_of,
        )
        return FakePublicationAttempt(self, reference)

    def activate(self, reference: PublicationRef) -> None:
        state = self.attempts[reference]
        if state.status != "building":
            raise PublicationAttemptClosedError(reference)
        if not self.can_serialize:
            raise PublicationQualityUnavailableError(
                "quality and current-state change cannot share one atomic boundary"
            )
        verdict = self.quality.verdict(state.run)
        if not verdict.clean:
            raise PublicationQualityError(verdict)
        key = (state.product, state.release.jurisdiction.rendered)
        previous_reference = self.current.get(key)
        if previous_reference is not None:
            previous = self.attempts[previous_reference]
            previous.status = "superseded"
            previous.superseded_by = reference
        state.status = "current"
        state.supersedes = previous_reference
        self.current[key] = reference

    def fail(self, reference: PublicationRef) -> None:
        state = self.attempts[reference]
        if state.status != "building":
            raise PublicationAttemptClosedError(reference)
        state.status = "failed"

    def current_for(
        self,
        product: PublicationProduct,
        requested_jurisdiction: Jurisdiction,
    ) -> PublicationRef | None:
        return self.current.get((product, requested_jurisdiction.rendered))


def open_attempt(
    repository: FakePublicationRepository,
    run: ProcessingRunRef,
    *,
    requested_release: ReleaseIdentity | None = None,
    source_as_of: datetime | None = SOURCE_AS_OF,
) -> FakePublicationAttempt:
    return repository.open(
        PublicationProduct.LATEST_AVAILABLE,
        requested_release if requested_release is not None else release(),
        run,
        source_as_of,
    )


def activate_clean_current(
    repository: FakePublicationRepository,
    run: ProcessingRunRef,
) -> FakePublicationAttempt:
    attempt = open_attempt(repository, run)
    attempt.activate()
    return attempt


@pytest.mark.parametrize(
    ("measured", "expected"),
    [(None, "1.0"), ("0.9", None), (None, None)],
)
def test_failing_quality_evaluation_requires_explanatory_values(
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


def test_quality_verdict_distinguishes_missing_stale_clean_and_warning() -> None:
    run = ProcessingRunRef("run-a")
    version_one = quality_rule(version=1)
    version_two = quality_rule(version=2)
    warning = quality_rule("record_count_drift", severity=RuleSeverity.WARNING)
    repository = FakeQualityRepository((version_two, warning))

    missing = repository.verdict(run)
    repository.record_evaluation(run, quality_evaluation(version_one))
    repository.record_evaluation(run, quality_evaluation(warning, passed=False))
    stale = repository.verdict(run)

    clean_run = ProcessingRunRef("run-b")
    repository.record_evaluation(clean_run, quality_evaluation(version_two))
    repository.record_evaluation(clean_run, quality_evaluation(warning, passed=False))
    clean = repository.verdict(clean_run)

    assert missing.missing_blocking_rules == (version_two,)
    assert missing.complete is False
    assert stale.stale_blocking_rules == (version_two,)
    assert stale.complete is False
    assert clean.complete is True
    assert clean.clean is True
    assert clean.warning_failures == (quality_evaluation(warning, passed=False),)


@pytest.mark.parametrize(
    "severities",
    [
        (RuleSeverity.BLOCKING, RuleSeverity.BLOCKING),
        (RuleSeverity.WARNING, RuleSeverity.WARNING),
        (RuleSeverity.BLOCKING, RuleSeverity.WARNING),
    ],
)
def test_quality_ambiguity_precedes_severity(
    severities: tuple[RuleSeverity, RuleSeverity],
) -> None:
    repository = FakeQualityRepository(
        (
            quality_rule(version=1, severity=severities[0]),
            quality_rule(version=2, severity=severities[1]),
        )
    )

    verdict = repository.verdict(ProcessingRunRef("run-a"))

    assert verdict.ambiguous_rule_identifiers == ("required_account_key",)
    assert verdict.missing_blocking_rules == ()
    assert verdict.stale_blocking_rules == ()
    assert verdict.complete is False


@pytest.mark.parametrize("quality_case", ["missing", "stale", "ambiguous", "failed"])
def test_publication_admission_and_nonretroactivity(quality_case: str) -> None:
    quality = FakeQualityRepository()
    repository = FakePublicationRepository(quality)
    previous = activate_clean_current(repository, ProcessingRunRef("run-previous"))
    current = open_attempt(
        repository,
        ProcessingRunRef("run-current"),
        requested_release=release(identifier="release-2026-r1"),
    )
    current.activate()
    assert repository.attempts[current.reference].supersedes == previous.reference
    assert repository.attempts[previous.reference].superseded_by == current.reference
    run = ProcessingRunRef("run-next")
    version_one = quality_rule(version=1)
    version_two = quality_rule(version=2)
    if quality_case == "missing":
        quality.active = (version_two,)
    elif quality_case == "stale":
        quality.active = (version_two,)
        quality.record_evaluation(run, quality_evaluation(version_one))
    elif quality_case == "ambiguous":
        quality.active = (version_one, version_two)
    else:
        quality.active = (version_two,)
        quality.record_evaluation(run, quality_evaluation(version_two, passed=False))
    attempted = open_attempt(
        repository,
        run,
        requested_release=release(identifier="release-2026-r2"),
    )

    with pytest.raises(PublicationQualityError):
        attempted.activate()

    assert repository.current_for(PublicationProduct.LATEST_AVAILABLE, jurisdiction()) == (
        current.reference
    )
    assert repository.attempts[current.reference].status == "current"
    assert repository.attempts[attempted.reference].status == "building"

    quality.active = (quality_rule(version=99),)
    assert repository.attempts[current.reference].status == "current"


def test_activation_rederives_quality_after_advisory_read() -> None:
    run = ProcessingRunRef("run-a")
    version_one = quality_rule(version=1)
    version_two = quality_rule(version=2)
    quality = FakeQualityRepository((version_one,))
    quality.record_evaluation(run, quality_evaluation(version_one))
    repository = FakePublicationRepository(quality)
    attempt = open_attempt(repository, run)
    advisory = quality.verdict(run)
    calls_before = quality.verdict_calls

    quality.active = (version_two,)
    with pytest.raises(PublicationQualityError) as caught:
        attempt.activate()

    assert advisory.clean is True
    assert quality.verdict_calls == calls_before + 1
    assert caught.value.verdict.stale_blocking_rules == (version_two,)
    assert repository.current_for(PublicationProduct.LATEST_AVAILABLE, jurisdiction()) is None


def test_activation_refuses_when_atomic_quality_admission_is_unavailable() -> None:
    quality = FakeQualityRepository()
    repository = FakePublicationRepository(quality)
    current = activate_clean_current(repository, ProcessingRunRef("run-current"))
    repository.can_serialize = False
    attempted = open_attempt(
        repository,
        ProcessingRunRef("run-next"),
        requested_release=release(identifier="release-2026-r2"),
    )

    with pytest.raises(PublicationQualityUnavailableError):
        attempted.activate()

    assert repository.attempts[current.reference].status == "current"
    assert repository.attempts[attempted.reference].status == "building"


def test_new_run_recovers_after_stale_quality() -> None:
    run_a = ProcessingRunRef("run-a")
    run_b = ProcessingRunRef("run-b")
    version_one = quality_rule(version=1)
    version_two = quality_rule(version=2)
    quality = FakeQualityRepository((version_one,))
    quality.record_evaluation(run_a, quality_evaluation(version_one))
    repository = FakePublicationRepository(quality)
    stale_attempt = open_attempt(repository, run_a)
    quality.active = (version_two,)

    with pytest.raises(PublicationQualityError):
        stale_attempt.activate()

    quality.record_evaluation(run_b, quality_evaluation(version_two))
    recovered = open_attempt(repository, run_b)
    recovered.activate()

    assert quality.verdict(run_a).stale_blocking_rules == (version_two,)
    assert quality.verdict(run_b).clean is True
    assert repository.attempts[recovered.reference].status == "current"


def test_failed_attempt_preserves_current_publication() -> None:
    quality = FakeQualityRepository()
    repository = FakePublicationRepository(quality)
    current = activate_clean_current(repository, ProcessingRunRef("run-current"))
    failed = open_attempt(
        repository,
        ProcessingRunRef("run-next"),
        requested_release=release(identifier="release-2026-r2"),
    )

    failed.fail()

    assert repository.attempts[failed.reference].status == "failed"
    assert repository.attempts[current.reference].status == "current"
    assert repository.current_for(PublicationProduct.LATEST_AVAILABLE, jurisdiction()) == (
        current.reference
    )


def open_from_recorded_partition(
    repository: PublicationRepository,
    index: ManifestIndex,
    run_manifests: dict[ProcessingRunRef, ManifestRef],
    product: PublicationProduct,
    requested_release: ReleaseIdentity,
    run: ProcessingRunRef,
) -> PublicationAttempt:
    recorded = index.partition_for(run_manifests[run], requested_release)
    if recorded is None:
        raise LookupError("the run's acquisition has no partition for this release")
    return repository.open(product, requested_release, run, recorded.source_as_of)


def test_manifest_lookup_distinguishes_absence_and_does_not_write() -> None:
    index = FakeManifestIndex()
    reference = index.register(manifest())
    writes_after_register = index.write_count

    assert index.partition_for(reference, release()) is None
    assert index.write_count == writes_after_register

    requested_release = release()
    index.attach_partition(reference, requested_release, partition(source_as_of=None))
    writes_after_attach = index.write_count
    first = index.partition_for(reference, requested_release)
    second = index.partition_for(reference, requested_release)

    assert first is not None
    assert first.source_as_of is None
    assert second == first
    assert index.write_count == writes_after_attach


def test_later_process_publication_uses_recorded_freshness() -> None:
    quality = FakeQualityRepository()
    publications = FakePublicationRepository(quality)
    index = FakeManifestIndex()
    reference = index.register(manifest())
    requested_release = release()
    index.attach_partition(reference, requested_release, partition())
    run = ProcessingRunRef("run-a")

    class MutablePage:
        def __init__(self) -> None:
            self.value = SOURCE_AS_OF
            self.reads = 0

        def read(self) -> datetime:
            self.reads += 1
            return self.value

    publisher_page = MutablePage()
    assert publisher_page.read() == SOURCE_AS_OF
    publisher_page.value = SOURCE_AS_OF + timedelta(days=10)

    first = open_from_recorded_partition(
        publications,
        index,
        {run: reference},
        PublicationProduct.LATEST_AVAILABLE,
        requested_release,
        run,
    )
    retry = open_from_recorded_partition(
        publications,
        index,
        {run: reference},
        PublicationProduct.LATEST_AVAILABLE,
        requested_release,
        run,
    )

    assert publications.attempts[first.reference].source_as_of == SOURCE_AS_OF
    assert publications.attempts[retry.reference].source_as_of == SOURCE_AS_OF
    assert publications.attempts[retry.reference].source_as_of != publisher_page.value
    assert publisher_page.reads == 1


def test_publication_freshness_preserves_absence_and_release_grain() -> None:
    page_instant = SOURCE_AS_OF - timedelta(days=1)
    content_instant = SOURCE_AS_OF
    page_only = candidate(
        source_as_of=page_instant,
        logical_releases=(
            logical(source_as_of=None),
            logical(
                tax_year=2025,
                release_kind=ReleaseKind.CURRENT,
                release_identifier="current-2025",
                source_as_of=None,
            ),
        ),
    )
    assert {entry.source_as_of for entry in page_only.logical_releases} == {page_instant}

    observed = candidate(
        source_as_of=page_instant,
        logical_releases=(
            logical(source_as_of=content_instant),
            logical(
                tax_year=2025,
                release_kind=ReleaseKind.CURRENT,
                release_identifier="current-2025",
                source_as_of=None,
            ),
        ),
    )
    first_release, second_release = tuple(promote(entry) for entry in observed.logical_releases)
    index = FakeManifestIndex()
    reference = index.register(manifest())
    for identity, evidence in zip(
        (first_release, second_release), observed.logical_releases, strict=True
    ):
        index.attach_partition(
            reference,
            identity,
            ReleasePartition(
                jurisdiction_code=evidence.jurisdiction.rendered,  # type: ignore[union-attr]
                tax_year=evidence.tax_year,  # type: ignore[arg-type]
                release_kind=evidence.release_kind.value,  # type: ignore[union-attr]
                source_as_of=evidence.source_as_of,
            ),
        )
    absent_release = release(year=2024, identifier="certified-2024")
    index.attach_partition(
        reference,
        absent_release,
        partition(year=2024, source_as_of=None),
    )
    quality = FakeQualityRepository()
    publications = FakePublicationRepository(quality)
    first_run = ProcessingRunRef("run-first")
    second_run = ProcessingRunRef("run-second")
    absent_run = ProcessingRunRef("run-absent")
    run_manifests = {
        first_run: reference,
        second_run: reference,
        absent_run: reference,
    }

    first = open_from_recorded_partition(
        publications,
        index,
        run_manifests,
        PublicationProduct.LATEST_CERTIFIED,
        first_release,
        first_run,
    )
    second = open_from_recorded_partition(
        publications,
        index,
        run_manifests,
        PublicationProduct.LATEST_AVAILABLE,
        second_release,
        second_run,
    )
    absent = open_from_recorded_partition(
        publications,
        index,
        run_manifests,
        PublicationProduct.HISTORY,
        absent_release,
        absent_run,
    )

    assert publications.attempts[first.reference].source_as_of == content_instant
    assert publications.attempts[second.reference].source_as_of == page_instant
    assert publications.attempts[absent.reference].source_as_of is None
    assert publications.attempts[absent.reference].source_as_of != ACQUIRED_AT
    assert publications.attempts[absent.reference].source_as_of != CLOCK_NOW


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("instant must be timezone-aware")
        self.instant = instant
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.instant


def test_fixed_clock_returns_the_exact_aware_instant() -> None:
    clock = FixedClock(CLOCK_NOW)

    observed = clock.now()

    assert observed is CLOCK_NOW
    assert observed.tzinfo is not None
    assert observed.utcoffset() is not None
    assert clock.calls == 1
    assert isinstance(clock, Clock)


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", maxsplit=1)[0])
    return imports


def test_suite_stays_application_contract_only() -> None:
    """Keys, payload layout, concrete registries, and persistence stay adapter-owned."""

    source_path = Path(__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imports = _top_level_imports(source_path)

    assert not imports & {"boto3", "botocore", "property_tax_adapters", "psycopg"}
    forbidden_identifiers = {
        "artifact_" + "key",
        "manifest_" + "key",
        "copy_" + "object",
        "upload_" + "part",
    }
    forbidden_literals = {
        "s3" + "://",
        "select " + "* from",
        "insert " + "into",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id.casefold() not in forbidden_identifiers
        elif isinstance(node, ast.Attribute):
            assert node.attr.casefold() not in forbidden_identifiers
            assert not (
                isinstance(node.value, ast.Name)
                and node.value.id == "json"
                and node.attr == "loads"
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.casefold()
            assert not any(fragment in lowered for fragment in forbidden_literals)


def test_port_contract_suite_is_collected_by_default() -> None:
    relative = "libs/property-tax-application/tests/test_port_contracts.py"
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    assert relative in completed.stdout


def test_every_falsification_matrix_entry_maps_to_a_collected_test() -> None:
    assert {scope: len(cases) for scope, cases in MATRIX_CASES.items()} == {
        "registry-and-discovery": 13,
        "run-and-manifest": 10,
        "quality-publication-clock": 12,
        "surface-and-proof": 2,
    }
    assert sum(len(cases) for cases in MATRIX_CASES.values()) == 37
    missing = [
        f"{scope}/{case}: {test_name}"
        for scope, cases in MATRIX_CASES.items()
        for case, test_name in cases.items()
        if not callable(globals().get(test_name))
    ]
    assert not missing, "Matrix entries without tests:\n" + "\n".join(missing)
