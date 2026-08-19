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
    S3ArtifactSink,
    S3BronzeStore,
    manifest_key,
    object_key,
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
DALLAS = (ReleasePartition(jurisdiction_code="tx-dallas", tax_year=2026, release_kind="certified"),)


def policy() -> AcquisitionPolicy:
    return AcquisitionPolicy(
        allowed_hosts=frozenset({"127.0.0.1"}),
        allowed_schemes=frozenset({"http"}),
        chunk_bytes=64 * 1024,
        timeout_seconds=10.0,
    )


def sink(client: FakeS3, key: str = "bronze/artifact") -> S3ArtifactSink:
    return S3ArtifactSink(client, BUCKET, key)


# --------------------------------------------------------------------------
# Streaming into S3
# --------------------------------------------------------------------------


def test_an_artifact_streams_into_s3_and_commits_to_a_locator() -> None:
    client = FakeS3()
    with serving({"/roll.txt": Route(body=BODY)}) as server:
        acquired = acquire_artifact(
            url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy()
        )

    assert acquired.sha256 == DIGEST
    assert acquired.locator == f"s3://{BUCKET}/bronze/artifact"
    assert client.objects["bronze/artifact"] == BODY


def test_the_object_arrives_in_parts_rather_than_one_body() -> None:
    """Multipart is what lets a large artifact stream; one part would not."""

    big = BODY * 12
    client = FakeS3()
    with serving({"/roll.txt": Route(body=big)}) as server:
        acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    upload = next(iter(client.uploads.values()))
    assert len(upload.parts) > 1, "the artifact was uploaded as a single part"
    assert client.objects["bronze/artifact"] == big


def test_no_part_below_the_minimum_is_sent_except_the_last() -> None:
    """S3 rejects an undersized non-final part at completion, not at write."""

    big = BODY * 12
    client = FakeS3()
    with serving({"/roll.txt": Route(body=big)}) as server:
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
    assert client.objects["bronze/artifact"] == b""


def test_a_part_size_below_the_s3_minimum_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="at least"):
        S3ArtifactSink(FakeS3(), BUCKET, "k", part_bytes=1024)


# --------------------------------------------------------------------------
# A failed acquisition leaves nothing behind
# --------------------------------------------------------------------------


def test_a_failed_transfer_leaves_no_object_and_no_orphaned_parts() -> None:
    """The upload is aborted, so nothing accrues storage and nothing is visible."""

    client = FakeS3()
    route = Route(body=BODY, declared_length=len(BODY), send_bytes=len(BODY) // 3)
    with serving({"/roll.txt": route}) as server:
        with pytest.raises(AcquisitionError) as raised:
            acquire_artifact(url=f"{base_url(server)}/roll.txt", sink=sink(client), policy=policy())

    assert raised.value.failure is AcquisitionFailure.TRUNCATED_ARTIFACT
    assert client.objects == {}, "a partial object was exposed"
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

    S3ArtifactSink(FakeS3(), BUCKET, "k").abort()


# --------------------------------------------------------------------------
# Manifests
# --------------------------------------------------------------------------


def acquired_artifact(client: FakeS3, body: bytes = BODY) -> object:
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
    assert manifest.artifact.locator == acquired.locator  # type: ignore[attr-defined]
    assert manifest.acquired_at == stamp
    assert manifest.manifest_version == BRONZE_MANIFEST_VERSION


def test_the_store_records_a_manifest_beside_its_artifact() -> None:
    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )

    locator = store.record(manifest)

    key = manifest_key(DALLAS, DIGEST)
    assert locator == f"s3://{BUCKET}/{key}"
    assert key.startswith(object_key(DALLAS, DIGEST))
    payload = json.loads(client.objects[key])
    assert payload["artifact"]["sha256"] == DIGEST
    assert client.content_types[key] == "application/json"


def test_a_recorded_manifest_is_never_overwritten() -> None:
    """Bronze keeps what it was given; a correction is a new version."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )
    store.record(manifest)

    with pytest.raises(S3Error) as raised:
        store.record(manifest)

    assert raised.value.code == "PreconditionFailed"


def test_the_serialized_manifest_is_stable_across_runs() -> None:
    """Two renderings of one manifest must not differ by key order."""

    client = FakeS3()
    acquired = acquired_artifact(client)
    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )

    assert serialize_manifest(manifest) == serialize_manifest(manifest)
    assert json.loads(serialize_manifest(manifest))["manifest_version"] == 1


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
    assert "SECRET-SIG" not in rendered
    assert "signature=" not in rendered


def test_a_manifest_refuses_an_unsanitized_source_url() -> None:
    """Restated here because a manifest may be built without the boundary."""

    with pytest.raises(ValueError, match="must be sanitized"):
        ReleaseManifest(
            partitions=DALLAS,
            artifact=StoredArtifact(locator="s3://b/k", sha256="a" * 64, byte_count=1),
            acquired_at=datetime(2026, 8, 19, tzinfo=UTC),
            source_url="https://cad.example.gov/roll.zip?token=SECRET",
            response=ResponseMetadata(status=200),
        )


def build_manifest(stamp: datetime) -> ReleaseManifest:
    return ReleaseManifest(
        partitions=DALLAS,
        artifact=StoredArtifact(locator="s3://b/k", sha256="a" * 64, byte_count=1),
        acquired_at=stamp,
        source_url="https://cad.example.gov/roll.zip",
        response=ResponseMetadata(status=200),
    )


def test_a_naive_acquisition_instant_is_refused() -> None:
    """It cannot be reproduced, because it does not say when."""

    with pytest.raises(ValueError, match="timezone-aware"):
        build_manifest(datetime(2026, 8, 19))


def test_an_aware_instant_in_any_zone_is_accepted_and_normalized() -> None:
    """Awareness makes the instant unambiguous; the zone it is written in does not.

    Rejecting a well-defined time for being expressed in the wrong words would
    be strictness without a reason, and serialization normalizes to UTC.
    """

    elsewhere = timezone(timedelta(hours=-5))
    stamp = datetime(2026, 8, 19, 7, 0, tzinfo=elsewhere)

    manifest = build_manifest(stamp)

    assert manifest.acquired_at == stamp
    assert json.loads(serialize_manifest(manifest))["acquired_at"] == "2026-08-19T12:00:00+00:00"


# --------------------------------------------------------------------------
# Conflicting content
# --------------------------------------------------------------------------


def test_a_first_acquisition_is_new() -> None:
    store = S3BronzeStore(FakeS3(), BUCKET)

    assert store.classify(DALLAS, DIGEST) is BronzeConflict.NEW


def test_the_same_bytes_twice_are_identical_not_a_conflict() -> None:
    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    acquired = acquired_artifact(client)
    store.record(
        ReleaseManifest.from_acquisition(
            acquired, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
        )
    )

    assert store.classify(DALLAS, DIGEST) is BronzeConflict.IDENTICAL


def test_different_bytes_under_one_identity_diverge_and_both_survive() -> None:
    """The mutable-source-slot case: Dallas republishes one CURRENT filename."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    first = acquired_artifact(client)
    store.record(
        ReleaseManifest.from_acquisition(
            first, partitions=DALLAS, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
        )
    )

    other_body = BODY + b"99999999|1\n"
    other_digest = hashlib.sha256(other_body).hexdigest()

    assert store.classify(DALLAS, other_digest) is BronzeConflict.DIVERGED

    second = acquired_artifact(client, body=other_body)
    store.record(
        ReleaseManifest.from_acquisition(
            second,
            partitions=DALLAS,
            acquired_at=datetime(2026, 8, 20, tzinfo=UTC),
            conflict=BronzeConflict.DIVERGED,
        )
    )

    assert manifest_key(DALLAS, DIGEST) in client.objects
    assert manifest_key(DALLAS, other_digest) in client.objects, "prior Bronze content was replaced"


def test_classification_pages_through_a_long_listing() -> None:
    """A truncated listing that stopped early would miss the divergent version."""

    client = FakeS3()
    store = S3BronzeStore(client, BUCKET)
    for index in range(7):
        client.objects[manifest_key(DALLAS, f"{index:064x}")] = b"{}"

    assert store.classify(DALLAS, f"{6:064x}") is BronzeConflict.IDENTICAL
    assert store.classify(DALLAS, "f" * 64) is BronzeConflict.DIVERGED


# --------------------------------------------------------------------------
# One artifact, several logical releases
# --------------------------------------------------------------------------


def test_one_artifact_supports_several_release_partitions() -> None:
    """A measured Collin archive carries current and certified for two years."""

    client = FakeS3()
    acquired = acquired_artifact(client)
    partitions = (
        ReleasePartition(jurisdiction_code="tx-collin", tax_year=2025, release_kind="certified"),
        ReleasePartition(jurisdiction_code="tx-collin", tax_year=2026, release_kind="current"),
    )

    manifest = ReleaseManifest.from_acquisition(
        acquired, partitions=partitions, acquired_at=datetime(2026, 8, 19, tzinfo=UTC)
    )

    assert len(manifest.partitions) == 2
    assert manifest.artifact.sha256 == DIGEST, "the bytes were duplicated per partition"
    payload = json.loads(serialize_manifest(manifest))
    assert len(payload["partitions"]) == 2


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


def test_the_store_conforms_to_the_application_port() -> None:
    assert isinstance(S3BronzeStore(FakeS3(), BUCKET), BronzeStore)


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
