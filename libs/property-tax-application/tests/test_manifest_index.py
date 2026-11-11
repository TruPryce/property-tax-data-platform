"""Task-local falsification for the application-owned manifest index port."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from property_tax_application.acquisition import ResponseMetadata
from property_tax_application.bronze import (
    ManifestIndex,
    ManifestRef,
    ReleaseManifest,
    ReleasePartition,
    StoredArtifact,
)
from property_tax_domain import Jurisdiction, ReleaseIdentity, ReleaseKind


class InMemoryManifestIndex:
    """A deterministic contract fake, not evidence of database locking."""

    def __init__(self) -> None:
        self._by_evidence: dict[tuple[object, ...], ManifestRef] = {}
        self._manifests: dict[ManifestRef, ReleaseManifest] = {}
        self._partitions: dict[tuple[ManifestRef, str, int, ReleaseKind], ReleasePartition] = {}

    def register(self, manifest: ReleaseManifest) -> ManifestRef:
        existing = self._by_evidence.get(manifest.acquisition_evidence)
        if existing is not None:
            return existing
        reference = ManifestRef(len(self._manifests) + 1)
        self._by_evidence[manifest.acquisition_evidence] = reference
        self._manifests[reference] = manifest
        for partition in manifest.partitions:
            self.attach_partition(reference, partition)
        return reference

    def attach_partition(self, reference: ManifestRef, partition: ReleasePartition) -> None:
        manifest = self._manifests.get(reference)
        if manifest is None:
            raise KeyError(reference)
        if partition.jurisdiction_code != manifest.jurisdiction:
            raise ValueError("partition jurisdiction disagrees with its acquisition")
        key = (
            reference,
            partition.jurisdiction_code,
            partition.tax_year,
            ReleaseKind(partition.release_kind),
        )
        self._partitions[key] = partition

    def partition_for(
        self, reference: ManifestRef, release: ReleaseIdentity
    ) -> ReleasePartition | None:
        if reference not in self._manifests:
            raise KeyError(reference)
        return self._partitions.get(
            (reference, release.jurisdiction.rendered, release.tax_year, release.release_kind)
        )


def manifest(
    *, acquired_at: datetime, partitions: tuple[ReleasePartition, ...] = ()
) -> ReleaseManifest:
    return ReleaseManifest(
        jurisdiction="tx-dallas",
        artifact=StoredArtifact(
            locator="s3://bronze/artifacts/" + "a" * 64,
            sha256="a" * 64,
            byte_count=10,
            media_type="application/zip",
        ),
        acquired_at=acquired_at,
        source_url="https://example.gov/releases/current.zip",
        response=ResponseMetadata(status=200, headers={"etag": '"one"'}),
        partitions=partitions,
        tool_versions={"platform": "1.0"},
    )


def release(*, tax_year: int = 2026, kind: ReleaseKind = ReleaseKind.CERTIFIED) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113"),
        tax_year=tax_year,
        release_kind=kind,
        release_identifier="release-1",
    )


def test_the_same_acquisition_returns_the_same_opaque_reference() -> None:
    index = InMemoryManifestIndex()
    acquisition = manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC))

    first = index.register(acquisition)
    second = index.register(replace(acquisition, partitions=()))

    assert first == second
    assert isinstance(index, ManifestIndex)
    with pytest.raises(TypeError, match="no ordering"):
        _ = first < second


def test_distinct_acquisitions_of_one_artifact_return_distinct_references() -> None:
    index = InMemoryManifestIndex()
    first = manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC))
    second = replace(first, acquired_at=datetime(2026, 8, 20, tzinfo=UTC))

    assert index.register(first) != index.register(second)
    assert first.artifact.sha256 == second.artifact.sha256


def test_a_later_partition_is_queryable_with_its_source_as_of() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))
    source_as_of = datetime(2026, 7, 25, tzinfo=UTC)
    partition = ReleasePartition(
        jurisdiction_code="tx-dallas",
        tax_year=2026,
        release_kind="certified",
        source_as_of=source_as_of,
    )

    index.attach_partition(reference, partition)

    assert index.partition_for(reference, release()) == partition
    assert index.partition_for(reference, release()).source_as_of == source_as_of  # type: ignore[union-attr]


def test_no_partition_and_partition_with_no_source_as_of_are_distinct() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))

    assert index.partition_for(reference, release()) is None

    partition = ReleasePartition(
        jurisdiction_code="tx-dallas",
        tax_year=2026,
        release_kind="certified",
        source_as_of=None,
    )
    index.attach_partition(reference, partition)

    attached = index.partition_for(reference, release())
    assert attached is not None
    assert attached.source_as_of is None


def test_partitions_do_not_change_registration_identity() -> None:
    index = InMemoryManifestIndex()
    acquisition = manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC))
    partition = ReleasePartition(
        jurisdiction_code="tx-dallas",
        tax_year=2026,
        release_kind="certified",
        source_as_of=datetime(2026, 7, 25, tzinfo=UTC),
    )

    first = index.register(acquisition)
    index.attach_partition(first, partition)
    second = index.register(replace(acquisition, partitions=(partition,)))

    assert first == second
    assert index.partition_for(first, release()) == partition
