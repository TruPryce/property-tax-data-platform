"""The S3 sink and store, driven through the real acquisition boundary.

The sink is exercised by `acquire_artifact` rather than called directly wherever
the point is a lifecycle guarantee: what matters is that a failed acquisition
leaves no object, and only the real boundary decides when abort runs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from acquisition.fixture_server import Route, base_url, serving
from property_tax_adapters.acquisition import acquire_artifact
from property_tax_adapters.objectstore import (
    MINIMUM_PART_BYTES,
    MissingArtifactError,
    S3ArtifactSink,
    S3BronzeStore,
    TruncatedListingError,
    artifact_key,
    manifest_key,
    partition_ref_key,
    serialize_manifest,
)
from property_tax_application.acquisition import (
    AcquisitionError,
    AcquisitionFailure,
    AcquisitionPolicy,
    RedirectHop,
    ResponseMetadata,
)
from property_tax_application.bronze import (
    BRONZE_MANIFEST_VERSION,
    BronzeConflict,
    BronzeStore,
    ReleaseManifest,
    ReleasePartition,
    StoredArtifact,
)

from objectstore.fake_s3 import FakeS3, S3Error

BUCKET = "bronze-test"
BODY = b"account|value\n" + b"".join(f"{n:08d}|{n * 3}\n".encode() for n in range(60_000))
DIGEST = hashlib.sha256(BODY).hexdigest()
DALLAS_PARTITION = ReleasePartition(
    jurisdiction_code="tx-dallas", tax_year=2026, release_kind="certified"
)
DALLAS = (DALLAS_PARTITION,)


def policy() -> AcquisitionPolicy:
    return AcquisitionPolicy(
        allowed_hosts=frozenset({"127.0.0.1"}),
        allowed_schemes=frozenset({"http"}),
        chunk_bytes=64 * 1024,
        timeout_seconds=10.0,
    )


def sink(client: FakeS3) -> S3ArtifactSink:
    """No destination is chosen here: the sink names the object by its content."""

    return S3ArtifactSink(client, BUCKET)


def artifact_bytes(client: FakeS3, digest: str) -> bytes:
    return client.objects[artifact_key(digest)]


# --------------------------------------------------------------------------
# Streaming, and the destination the sink chooses
# --------------------------------------------------------------------------


def test_an_artifact_streams_into_s3_and_commits_to_its_content_address() -> None:
    client = FakeS3()
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        acquired = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy()
        )

    assert acquired.sha256 == DIGEST
    assert acquired.locator == f"s3://{BUCKET}/{artifact_key(DIGEST)}"
    assert artifact_bytes(client, DIGEST) == BODY


def test_two_different_artifacts_cannot_overwrite_one_another() -> None:
    """The defect a caller-chosen key made possible, stated as its own case.

    An earlier design took the destination from the caller, so two acquisitions
    could name the same key and the second silently replaced bytes the first
    manifest still pointed at. Naming an object by its content makes that
    unrepresentable rather than merely discouraged.
    """

    client = FakeS3()
    payloads = (b"first release bytes", b"second release bytes")
    locators = []
    for payload in payloads:
        with sink(client) as opened:
            opened.write(payload)
            locators.append(opened.commit())

    assert len(set(locators)) == 2, "two different artifacts shared one locator"
    for payload in payloads:
        digest = hashlib.sha256(payload).hexdigest()
        assert artifact_bytes(client, digest) == payload, f"{payload!r} was overwritten"


def test_the_same_bytes_twice_land_on_one_object() -> None:
    """Content-addressing means a repeat acquisition is not a second artifact."""

    client = FakeS3()
    for _ in range(2):
        with sink(client) as opened:
            opened.write(b"identical")
            locator = opened.commit()

    digest = hashlib.sha256(b"identical").hexdigest()
    assert locator == f"s3://{BUCKET}/{artifact_key(digest)}"
    assert [k for k in client.objects if k.startswith("bronze/artifacts/")] == [
        artifact_key(digest)
    ]


def test_no_staging_object_survives_a_commit() -> None:
    client = FakeS3()
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    assert client.staging_objects == []


def test_the_object_arrives_in_parts_rather_than_one_body() -> None:
    """Multipart is what lets a large artifact stream; one part would not."""

    big = BODY * 12
    client = FakeS3()
    with serving({"/roll.txt": Route(body=big)}) as server:
        acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    upload = next(iter(client.uploads.values()))
    assert len(upload.parts) > 1, "the artifact was uploaded as a single part"
    assert artifact_bytes(client, hashlib.sha256(big).hexdigest()) == big


def test_no_part_below_the_minimum_is_sent_except_the_last() -> None:
    """S3 rejects an undersized non-final part at completion, not at write."""

    client = FakeS3()
    with serving({"/roll.txt": Route(body=BODY * 12)}) as server:
        acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    upload = next(iter(client.uploads.values()))
    numbers = sorted(upload.parts)
    for number in numbers[:-1]:
        assert len(upload.parts[number]) >= MINIMUM_PART_BYTES, f"part {number} is undersized"


def test_an_empty_artifact_still_becomes_an_object() -> None:
    """S3 refuses a multipart upload with no parts; a zero-byte artifact is real."""

    client = FakeS3()
    with serving({"/empty.txt": Route(body=b"")}) as server:
        acquired = acquire_artifact(
            url=f"{base_url(server)}/empty.txt", sink=sink(client), policy=policy()
        )

    assert acquired.byte_count == 0
    assert artifact_bytes(client, hashlib.sha256(b"").hexdigest()) == b""


def test_the_sink_hashes_what_it_writes() -> None:
    """It must, because only it can name the destination after the last byte."""

    client = FakeS3()
    with sink(client) as opened:
        opened.write(b"abc")
        opened.write(b"def")
        assert opened.sha256 == hashlib.sha256(b"abcdef").hexdigest()
        opened.commit()


def test_a_part_size_below_the_s3_minimum_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="at least"):
        S3ArtifactSink(FakeS3(), BUCKET, part_bytes=1024)


# --------------------------------------------------------------------------
# A failed acquisition leaves nothing behind
# --------------------------------------------------------------------------


def test_a_failed_transfer_leaves_no_object_and_no_orphaned_parts() -> None:
    client = FakeS3()
    route = Route(body=BODY, declared_length=len(BODY), send_bytes=len(BODY) // 3)
    with serving({"/roll.txt": route}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    assert raised.value.failure is AcquisitionFailure.TRUNCATED_ARTIFACT
    assert client.objects == {}, "a partial object was exposed"
    assert client.staging_objects == []
    assert client.orphaned_parts == 0
    assert all(upload.aborted for upload in client.uploads.values())


def test_a_rejected_status_leaves_no_upload_behind() -> None:
    client = FakeS3()
    with serving({"/roll.txt": Route(status=404)}) as server:
        with pytest.raises(AcquisitionError):
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    assert client.objects == {}
    assert client.orphaned_parts == 0


def test_a_checksum_mismatch_discards_the_upload() -> None:
    client = FakeS3()
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(
                url=f"{base_url(server)}/roll.txt",
                sink=sink(client),
                policy=policy(),
                expected_sha256="0" * 64,
            )

    assert raised.value.failure is AcquisitionFailure.CHECKSUM_MISMATCH
    assert client.objects == {}


def test_abort_is_safe_when_the_upload_never_started() -> None:
    """A caller should not have to know which failures created an upload."""

    S3ArtifactSink(FakeS3(), BUCKET).abort()


# --------------------------------------------------------------------------
# Artifact identity does not depend on any partition
# --------------------------------------------------------------------------


def test_the_artifact_key_names_the_checksum_and_nothing_else() -> None:
    """A key derived from a partition would make identity depend on which
    release happened to be noticed first."""

    assert artifact_key(DIGEST) == f"bronze/artifacts/{DIGEST}"
    for partition in DALLAS_PARTITION.jurisdiction_code, str(DALLAS_PARTITION.tax_year):
        assert partition not in artifact_key(DIGEST)


def test_one_artifact_serves_several_partitions_without_duplicating_bytes() -> None:
    """A measured Collin archive carries current and certified for two years."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    partitions = (
        ReleasePartition(jurisdiction_code="tx-collin", tax_year=2025, release_kind="certified"),
        ReleasePartition(jurisdiction_code="tx-collin", tax_year=2026, release_kind="current"),
    )
    acquired = acquired_artifact(client)
    store.record(
        ReleaseManifest.from_acquisition(
            acquired, partitions=partitions, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
        )
    )

    stored = [
        k for k in client.objects if k.startswith("bronze/artifacts/") and not k.endswith(".json")
    ]
    assert stored == [artifact_key(DIGEST)], "the bytes were duplicated per partition"
    for partition in partitions:
        assert partition_ref_key(partition, DIGEST) in client.objects


def test_a_partition_discovered_later_attaches_without_editing_the_manifest() -> None:
    """A release noticed afterwards does not change what was acquired."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)
    store.record(
        ReleaseManifest.from_acquisition(
            acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
        )
    )
    before = client.objects[manifest_key(DIGEST)]

    late = ReleasePartition(jurisdiction_code="tx-dallas", tax_year=2027, release_kind="current")
    store.reference_partition(late, DIGEST)

    assert client.objects[manifest_key(DIGEST)] == before, "the manifest was edited"
    assert partition_ref_key(late, DIGEST) in client.objects
    assert store.classify(late, DIGEST) is BronzeConflict.IDENTICAL


# --------------------------------------------------------------------------
# Manifests
# --------------------------------------------------------------------------


def acquired_artifact(client: FakeS3, body: bytes = BODY):  # noqa: ANN201 - the boundary's type
    with serving({"/roll.txt": Route(body=body, headers={"Content-Type": "text/plain"})}) as server:
        return acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy()
        )


def test_a_manifest_records_what_the_acquisition_established() -> None:
    client = FakeS3()
    acquired = acquired_artifact(client)
    stamp = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=stamp, tool_versions={"platform": "0.1.0"}
    )

    assert manifest.artifact.sha256 == DIGEST
    assert manifest.artifact.byte_count == len(BODY)
    assert manifest.artifact.media_type == "text/plain"
    assert manifest.artifact.locator == acquired.locator
    assert manifest.acquired_at == stamp
    assert manifest.manifest_version == BRONZE_MANIFEST_VERSION


def test_a_manifest_stores_no_conflict_verdict() -> None:
    """A stored verdict is a claim about what else existed when a writer looked."""

    assert "conflict" not in ReleaseManifest.__dataclass_fields__


def test_the_store_records_a_manifest_beside_its_artifact() -> None:
    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)

    locator = store.record(
        ReleaseManifest.from_acquisition(
            acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
        )
    )

    key = manifest_key(DIGEST)
    assert locator == f"s3://{BUCKET}/{key}"
    assert json.loads(client.objects[key])["artifact"]["sha256"] == DIGEST
    assert client.content_types[key] == "application/json"


def test_a_second_writer_does_not_replace_a_recorded_manifest() -> None:
    """Both writers succeed and the first record survives, because both describe
    the same artifact — but neither overwrote the other."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )
    store.record(manifest)
    first = client.objects[manifest_key(DIGEST)]

    store.record(
        ReleaseManifest.from_acquisition(
            acquired, partitions=DALLAS, acquired_at=datetime(2026, 9, 1, tzinfo=UTC)
        )
    )

    assert client.objects[manifest_key(DIGEST)] == first, "a recorded manifest was replaced"


def test_the_serialized_manifest_is_stable_across_runs() -> None:
    client = FakeS3()
    acquired = acquired_artifact(client)
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )

    assert serialize_manifest(manifest) == serialize_manifest(manifest)
    assert json.loads(serialize_manifest(manifest))["manifest_version"] == 1


def test_partition_order_does_not_change_the_serialized_bytes() -> None:
    """Two orderings of one set of partitions are one manifest, not two."""

    client = FakeS3()
    acquired = acquired_artifact(client)
    a = ReleasePartition(jurisdiction_code="tx-collin", tax_year=2025, release_kind="certified")
    b = ReleasePartition(jurisdiction_code="tx-collin", tax_year=2026, release_kind="current")
    stamp = datetime(2026, 8, 19, tzinfo=UTC)

    forward = ReleaseManifest.from_acquisition(acquired, partitions=(a, b), acquired_at=stamp)
    reverse = ReleaseManifest.from_acquisition(acquired, partitions=(b, a), acquired_at=stamp)

    assert serialize_manifest(forward) == serialize_manifest(reverse)


def test_a_manifest_carries_no_credential_from_a_signed_url() -> None:
    client = FakeS3()
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        acquired = acquire_artifact(
            url=f"{base_url(server)}/roll.txt?signature=SECRET-SIG",
            sink=sink(client),
            policy=policy(),
        )
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )

    rendered = serialize_manifest(manifest)
    assert "SECRET-SIG" not in rendered and "signature=" not in rendered


def test_a_manifest_refuses_an_unsanitized_source_url() -> None:
    """Restated here because a manifest may be built without the boundary."""

    with pytest.raises(ValueError, match="must be sanitized"):
        build_manifest(datetime(2026, 8, 19, tzinfo=UTC), source_url="https://c.gov/r.zip?t=SECRET")


def build_manifest(stamp: datetime, source_url: str = "https://cad.example.gov/roll.zip"):  # noqa: ANN201
    return ReleaseManifest(
        partitions=DALLAS,
        artifact=StoredArtifact(locator="s3://b/k", sha256="a" * 64, byte_count=1),
        acquired_at=stamp,
        source_url=source_url,
        response=ResponseMetadata(status=200),
    )


def test_a_naive_acquisition_instant_is_refused() -> None:
    """It cannot be reproduced, because it does not say when."""

    with pytest.raises(ValueError, match="timezone-aware"):
        build_manifest(datetime(2026, 8, 19))


def test_an_aware_instant_in_any_zone_is_accepted_and_normalized() -> None:
    """Awareness makes the instant unambiguous; the zone it is written in does not."""

    stamp = datetime(2026, 8, 19, 7, 0, tzinfo=timezone(timedelta(hours=-5)))

    manifest = build_manifest(stamp)

    assert manifest.acquired_at == stamp
    assert json.loads(serialize_manifest(manifest))["acquired_at"] == "2026-08-19T12:00:00+00:00"


def test_a_manifest_needs_at_least_one_partition() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ReleaseManifest(
            partitions=(),
            artifact=StoredArtifact(locator="s3://b/k", sha256="a" * 64, byte_count=1),
            acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
            source_url="https://cad.example.gov/roll.zip",
            response=ResponseMetadata(status=200),
        )


def test_repeated_partitions_are_refused() -> None:
    with pytest.raises(ValueError, match="distinct"):
        ReleaseManifest(
            partitions=DALLAS + DALLAS,
            artifact=StoredArtifact(locator="s3://b/k", sha256="a" * 64, byte_count=1),
            acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
            source_url="https://cad.example.gov/roll.zip",
            response=ResponseMetadata(status=200),
        )


def test_a_redirect_chain_reaches_the_manifest_sanitized() -> None:
    client = FakeS3()
    routes = {
        "/start": Route(status=302, location="/roll.txt?sig=SECRET"),
        "/roll.txt": Route(body=BODY),
    }
    with serving(routes) as server:
        acquired = acquire_artifact(
            url=f"{base_url(server)}/start", sink=sink(client), policy=policy()
        )
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )

    assert len(manifest.redirects) == 1
    assert all(isinstance(hop, RedirectHop) for hop in manifest.redirects)
    assert "SECRET" not in serialize_manifest(manifest)


# --------------------------------------------------------------------------
# Divergence, derived rather than stored
# --------------------------------------------------------------------------


def test_a_first_acquisition_is_new() -> None:
    assert S3BronzeStore(FakeS3(), BUCKET).classify(DALLAS_PARTITION, DIGEST) is BronzeConflict.NEW


def test_the_same_bytes_twice_are_identical_not_a_conflict() -> None:
    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    store.record(
        ReleaseManifest.from_acquisition(
            acquired_artifact(client),
            partitions=DALLAS,
            acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
        )
    )

    assert store.classify(DALLAS_PARTITION, DIGEST) is BronzeConflict.IDENTICAL


def test_different_bytes_under_one_identity_diverge_and_both_survive() -> None:
    """The mutable-source-slot case: Dallas republishes one CURRENT filename."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    store.record(
        ReleaseManifest.from_acquisition(
            acquired_artifact(client),
            partitions=DALLAS,
            acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
        )
    )

    other_body = BODY + b"99999999|1\n"
    other_digest = hashlib.sha256(other_body).hexdigest()
    assert store.classify(DALLAS_PARTITION, other_digest) is BronzeConflict.DIVERGED

    store.record(
        ReleaseManifest.from_acquisition(
            acquired_artifact(client, body=other_body),
            partitions=DALLAS,
            acquired_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
    )

    assert artifact_bytes(client, DIGEST) == BODY, "prior Bronze content was replaced"
    assert artifact_bytes(client, other_digest) == other_body
    assert manifest_key(DIGEST) in client.objects and manifest_key(other_digest) in client.objects


def test_two_writers_that_both_saw_nothing_do_not_contradict_each_other() -> None:
    """Both classify NEW, both write, and the durable state is still coherent.

    Nothing is overwritten, and asking afterwards reports divergence — which is
    the answer, rather than whichever verdict one writer happened to persist.
    """

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    other_body = BODY + b"racing\n"
    other_digest = hashlib.sha256(other_body).hexdigest()

    assert store.classify(DALLAS_PARTITION, DIGEST) is BronzeConflict.NEW
    assert store.classify(DALLAS_PARTITION, other_digest) is BronzeConflict.NEW

    for body in (BODY, other_body):
        store.record(
            ReleaseManifest.from_acquisition(
                acquired_artifact(client, body=body),
                partitions=DALLAS,
                acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
            )
        )

    assert store.classify(DALLAS_PARTITION, "f" * 64) is BronzeConflict.DIVERGED
    assert artifact_bytes(client, DIGEST) == BODY
    assert artifact_bytes(client, other_digest) == other_body


def test_classification_pages_through_a_long_listing() -> None:
    """A listing that stopped early would miss references beyond the first page.

    Seven references is already divergence, so what this checks is that every
    page is read: a caller that stopped after two would see one reference and
    report IDENTICAL for a release with seven different artifacts.
    """

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    for index in range(7):
        client.objects[partition_ref_key(DALLAS_PARTITION, f"{index:064x}")] = b"{}"

    assert store.referenced_checksums(DALLAS_PARTITION) == {f"{i:064x}" for i in range(7)}
    assert store.classify(DALLAS_PARTITION, f"{6:064x}") is BronzeConflict.DIVERGED


def test_a_known_checksum_stays_divergent_once_a_second_one_exists() -> None:
    """Divergence is a property of the release, not of the checksum being asked about.

    An earlier version asked whether *this* checksum was among those referenced,
    so with two artifacts recorded both sides of a known conflict reported
    IDENTICAL and the divergence vanished the moment it was stored.
    """

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    first, second = "a" * 64, "b" * 64
    for digest in (first, second):
        client.objects[partition_ref_key(DALLAS_PARTITION, digest)] = b"{}"

    assert store.classify(DALLAS_PARTITION, first) is BronzeConflict.DIVERGED
    assert store.classify(DALLAS_PARTITION, second) is BronzeConflict.DIVERGED
    assert store.classify(DALLAS_PARTITION, "c" * 64) is BronzeConflict.DIVERGED


def test_a_single_matching_reference_is_identical() -> None:
    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    client.objects[partition_ref_key(DALLAS_PARTITION, DIGEST)] = b"{}"

    assert store.classify(DALLAS_PARTITION, DIGEST) is BronzeConflict.IDENTICAL
    assert store.classify(DALLAS_PARTITION, "c" * 64) is BronzeConflict.DIVERGED


def test_a_reference_to_absent_bytes_is_refused() -> None:
    """A dangling reference makes a genuinely new checksum look already present."""

    store = S3BronzeStore(FakeS3(), BUCKET)

    with pytest.raises(MissingArtifactError):
        store.reference_partition(DALLAS_PARTITION, "c" * 64)


def test_both_entry_points_write_one_reference_body() -> None:
    """The key is immutable, so two renderings would let a race decide the shape."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)
    store.record(
        ReleaseManifest.from_acquisition(
            acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
        )
    )
    from_record = client.objects[partition_ref_key(DALLAS_PARTITION, DIGEST)]

    other = ReleasePartition(jurisdiction_code="tx-dallas", tax_year=2027, release_kind="certified")
    store.reference_partition(other, DIGEST)
    from_reference = client.objects[partition_ref_key(other, DIGEST)]

    assert set(json.loads(from_record)) == set(json.loads(from_reference))
    assert json.loads(from_reference)["artifact_locator"].endswith(artifact_key(DIGEST))


def test_a_large_artifact_is_finalized_with_a_ranged_copy() -> None:
    """CopyObject stops at 5 GB while acquisition permits more.

    Driven with a lowered threshold rather than five gigabytes of memory: the
    branch is what needs proving, and the byte count is what selects it.
    """

    import property_tax_adapters.objectstore.s3 as module

    client = FakeS3()
    payload = b"x" * 40_000
    original_max, original_part = module.MAX_SINGLE_COPY_BYTES, module.MULTIPART_COPY_PART_BYTES
    try:
        module.MAX_SINGLE_COPY_BYTES = 10_000
        module.MULTIPART_COPY_PART_BYTES = 15_000
        with S3ArtifactSink(client, BUCKET) as opened:
            opened.write(payload)
            locator = opened.commit()
    finally:
        module.MAX_SINGLE_COPY_BYTES, module.MULTIPART_COPY_PART_BYTES = original_max, original_part

    digest = hashlib.sha256(payload).hexdigest()
    assert locator.endswith(artifact_key(digest))
    assert client.objects[artifact_key(digest)] == payload, "the ranged copy lost bytes"
    copied = [u for u in client.uploads.values() if u.key == artifact_key(digest)]
    assert copied and len(copied[0].parts) == 3, "the copy was not ranged"


def test_a_failed_cleanup_is_not_swallowed() -> None:
    """The boundary reports a failed cleanup; suppressing it here would hide that."""

    class RefusesDelete(FakeS3):
        def delete_object(self, **kwargs: object) -> dict:  # type: ignore[override]
            raise S3Error("AccessDenied")

    client = RefusesDelete()
    with serving({"/roll.txt": Route(status=404)}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    assert raised.value.cleanup_failed is True
    assert any("partial artifact may remain" in note for note in raised.value.__notes__)


def test_a_truncated_listing_without_a_token_fails_closed() -> None:
    """Returning what arrived would report "nothing there" for "I could not look"."""

    client = FakeS3(truncate_without_token=True)
    store = S3BronzeStore(client, BUCKET)
    for index in range(7):
        client.objects[partition_ref_key(DALLAS_PARTITION, f"{index:064x}")] = b"{}"

    with pytest.raises(TruncatedListingError):
        store.classify(DALLAS_PARTITION, "f" * 64)


def test_the_store_conforms_to_the_application_port() -> None:
    assert isinstance(S3BronzeStore(FakeS3(), BUCKET), BronzeStore)
