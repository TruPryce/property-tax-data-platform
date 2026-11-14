"""Task-local falsification for the application-owned manifest index port."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime

import pytest
from property_tax_application.acquisition import ResponseMetadata
from property_tax_application.bronze import (
    ManifestAttachmentConflictError,
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
        self._partitions: dict[tuple[ManifestRef, ReleaseIdentity], ReleasePartition] = {}

    def register(self, manifest: ReleaseManifest) -> ManifestRef:
        existing = self._by_evidence.get(manifest.acquisition_evidence)
        if existing is not None:
            return existing
        reference = ManifestRef(len(self._manifests) + 1)
        self._by_evidence[manifest.acquisition_evidence] = reference
        self._manifests[reference] = manifest
        return reference

    def attach_partition(
        self,
        reference: ManifestRef,
        release: ReleaseIdentity,
        partition: ReleasePartition,
    ) -> None:
        manifest = self._manifests.get(reference)
        if manifest is None:
            raise KeyError(reference)
        if partition.jurisdiction_code != manifest.jurisdiction:
            raise ValueError("partition jurisdiction disagrees with its acquisition")
        if release.jurisdiction.rendered != partition.jurisdiction_code:
            raise ValueError("partition jurisdiction disagrees with release identity")
        if release.tax_year != partition.tax_year:
            raise ValueError("partition tax year disagrees with release identity")
        if release.release_kind.value != partition.release_kind:
            raise ValueError("partition release kind disagrees with release identity")
        key = (reference, release)
        existing = self._partitions.get(key)
        if existing is not None:
            if existing != partition:
                raise ManifestAttachmentConflictError(
                    "partition evidence disagrees with the immutable attachment"
                )
            return
        self._partitions[key] = partition

    def partition_for(
        self, reference: ManifestRef, release: ReleaseIdentity
    ) -> ReleasePartition | None:
        if reference not in self._manifests:
            raise KeyError(reference)
        return self._partitions.get((reference, release))


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


def release(
    *,
    tax_year: int = 2026,
    kind: ReleaseKind = ReleaseKind.CERTIFIED,
    identifier: str = "release-1",
    jurisdiction: Jurisdiction | None = None,
) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=jurisdiction
        or Jurisdiction(state_code="tx", county_slug="dallas", county_fips="48113"),
        tax_year=tax_year,
        release_kind=kind,
        release_identifier=identifier,
    )


def partition(
    *,
    tax_year: int = 2026,
    kind: str = "certified",
    source_as_of: datetime | None = None,
    jurisdiction: str = "tx-dallas",
) -> ReleasePartition:
    return ReleasePartition(
        jurisdiction_code=jurisdiction,
        tax_year=tax_year,
        release_kind=kind,
        source_as_of=source_as_of,
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
    attached_partition = partition(source_as_of=source_as_of)
    identity = release()

    index.attach_partition(reference, identity, attached_partition)

    assert index.partition_for(reference, identity) == attached_partition
    assert index.partition_for(reference, identity).source_as_of == source_as_of  # type: ignore[union-attr]


def test_no_partition_and_partition_with_no_source_as_of_are_distinct() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))

    attached_identity = release(identifier="A")
    missing_identity = release(identifier="B")
    assert index.partition_for(reference, attached_identity) is None

    attached_partition = partition(source_as_of=None)
    index.attach_partition(reference, attached_identity, attached_partition)

    attached = index.partition_for(reference, attached_identity)
    assert attached is not None
    assert attached.source_as_of is None
    assert index.partition_for(reference, missing_identity) is None


def test_partitions_do_not_change_registration_identity() -> None:
    index = InMemoryManifestIndex()
    acquisition = manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC))
    attached_partition = partition(source_as_of=datetime(2026, 7, 25, tzinfo=UTC))
    identity = release()

    first = index.register(acquisition)
    index.attach_partition(first, identity, attached_partition)
    second = index.register(replace(acquisition, partitions=(attached_partition,)))

    assert first == second
    assert index.partition_for(first, identity) == attached_partition


def test_release_identifiers_select_distinct_attachments_and_freshness() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))
    first_identity = release(identifier="A")
    second_identity = release(identifier="B")
    first_partition = partition(source_as_of=datetime(2026, 7, 25, tzinfo=UTC))
    second_partition = partition(source_as_of=datetime(2026, 7, 26, tzinfo=UTC))

    assert first_identity != second_identity
    index.attach_partition(reference, first_identity, first_partition)
    index.attach_partition(reference, second_identity, second_partition)

    assert index.partition_for(reference, first_identity) == first_partition
    assert index.partition_for(reference, second_identity) == second_partition
    assert len(index._partitions) == 2


def test_a_wrong_release_identifier_does_not_alias_an_attachment() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))
    first_identity = release(identifier="A")
    second_identity = release(identifier="B")

    index.attach_partition(reference, first_identity, partition())

    assert index.partition_for(reference, second_identity) is None


def test_registration_does_not_invent_full_release_identity() -> None:
    index = InMemoryManifestIndex()
    bronze_partition = partition(source_as_of=datetime(2026, 7, 25, tzinfo=UTC))

    reference = index.register(
        manifest(
            acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
            partitions=(bronze_partition,),
        )
    )

    assert index.partition_for(reference, release()) is None
    assert index._partitions == {}


@pytest.mark.parametrize(
    ("mismatched_release", "mismatched_partition"),
    [
        (
            release(
                jurisdiction=Jurisdiction(state_code="tx", county_slug="ellis", county_fips="48139")
            ),
            partition(),
        ),
        (release(), partition(tax_year=2025)),
        (release(), partition(kind="current")),
    ],
    ids=("jurisdiction", "tax-year", "release-kind"),
)
def test_overlap_mismatch_is_refused_before_state_changes(
    mismatched_release: ReleaseIdentity,
    mismatched_partition: ReleasePartition,
) -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))
    before = dict(index._partitions)

    with pytest.raises(ValueError, match="disagrees"):
        index.attach_partition(reference, mismatched_release, mismatched_partition)

    assert index._partitions == before


def test_an_exact_attachment_retry_is_a_no_op() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))
    identity = release()
    attached_partition = partition(source_as_of=datetime(2026, 7, 25, tzinfo=UTC))

    index.attach_partition(reference, identity, attached_partition)
    before = dict(index._partitions)
    index.attach_partition(reference, identity, attached_partition)

    assert index._partitions == before
    assert len(index._partitions) == 1


def test_conflicting_attachment_preserves_the_first_evidence() -> None:
    index = InMemoryManifestIndex()
    reference = index.register(manifest(acquired_at=datetime(2026, 8, 19, tzinfo=UTC)))
    identity = release()
    original = partition(source_as_of=datetime(2026, 7, 25, tzinfo=UTC))
    conflict = replace(original, source_as_of=datetime(2026, 7, 26, tzinfo=UTC))

    index.attach_partition(reference, identity, original)
    before = dict(index._partitions)

    with pytest.raises(ManifestAttachmentConflictError, match="immutable attachment"):
        index.attach_partition(reference, identity, conflict)

    assert index._partitions == before
    assert index.partition_for(reference, identity) == original


def test_release_partition_remains_three_part_bronze_evidence_plus_freshness() -> None:
    assert tuple(field.name for field in fields(ReleasePartition)) == (
        "jurisdiction_code",
        "tax_year",
        "release_kind",
        "source_as_of",
    )
