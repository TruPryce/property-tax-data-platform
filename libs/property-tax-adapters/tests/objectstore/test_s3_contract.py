"""Hold the adapter's calls to the real S3 service model.

The fake next door is a stand-in, and a stand-in can drift: it accepts whatever
signature it was written with, so a test suite built only on it proves the
adapter agrees with my idea of S3 rather than with S3. `botocore.stub.Stubber`
validates parameters against the shipped service model, so these tests fail if a
parameter is misspelled, missing, or not part of the operation at all.

No network and no credentials: the stubber intercepts before any request is
made.
"""

from __future__ import annotations

import hashlib

import pytest
from boto3.session import Session
from botocore.config import Config
from botocore.stub import ANY, Stubber
from property_tax_adapters.objectstore import S3ArtifactSink, S3BronzeStore, artifact_key
from property_tax_application.bronze import ReleasePartition

BUCKET = "bronze-contract"
PAYLOAD = b"contract bytes"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
PARTITION = ReleasePartition(jurisdiction_code="tx-dallas", tax_year=2026, release_kind="certified")


@pytest.fixture
def client():  # noqa: ANN201 - botocore's client type is dynamic
    """A real S3 client with no credentials and no network."""

    session = Session(
        aws_access_key_id="testing",
        aws_secret_access_key="testing",  # pragma: allowlist secret
        region_name="us-east-1",
    )
    return session.client("s3", config=Config(retries={"max_attempts": 1}))


def test_the_upload_sequence_matches_the_service_model(client) -> None:  # noqa: ANN001
    """Every parameter the sink sends is one the operation actually defines."""

    stubber = Stubber(client)
    stubber.add_response(
        "create_multipart_upload",
        {"UploadId": "upload-1"},
        {"Bucket": BUCKET, "Key": ANY},
    )
    stubber.add_response(
        "upload_part",
        {"ETag": '"etag-1"'},
        {"Bucket": BUCKET, "Key": ANY, "PartNumber": 1, "UploadId": "upload-1", "Body": PAYLOAD},
    )
    stubber.add_response(
        "complete_multipart_upload",
        {},
        {
            "Bucket": BUCKET,
            "Key": ANY,
            "UploadId": "upload-1",
            "MultipartUpload": {"Parts": [{"ETag": '"etag-1"', "PartNumber": 1}]},
        },
    )
    stubber.add_response(
        "copy_object",
        {},
        {"Bucket": BUCKET, "Key": artifact_key(DIGEST), "CopySource": ANY, "IfNoneMatch": "*"},
    )
    stubber.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": ANY})

    with stubber:
        with S3ArtifactSink(client, BUCKET) as sink:
            sink.write(PAYLOAD)
            locator = sink.commit()
        stubber.assert_no_pending_responses()

    assert locator == f"s3://{BUCKET}/{artifact_key(DIGEST)}"


def test_conditional_write_is_a_real_parameter_of_put_object(client) -> None:  # noqa: ANN001
    """`IfNoneMatch` is what makes a record immutable; the model must accept it."""

    stubber = Stubber(client)
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": ANY,
            "Body": ANY,
            "ContentType": "application/json",
            "IfNoneMatch": "*",
        },
    )
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": ANY,
            "Body": ANY,
            "ContentType": "application/json",
            "IfNoneMatch": "*",
        },
    )

    with stubber:
        S3BronzeStore(client, BUCKET).reference_partition(PARTITION, DIGEST)
        stubber.add_client_error("put_object", service_error_code="PreconditionFailed")
        # An already-present record is refused by S3 and tolerated here, which
        # is the behaviour immutability depends on.
        S3BronzeStore(client, BUCKET).reference_partition(PARTITION, DIGEST)


def test_the_listing_call_matches_the_service_model(client) -> None:  # noqa: ANN001
    stubber = Stubber(client)
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": f"bronze/releases/tx-dallas/2026/certified/{DIGEST}.ref.json"}]},
        {"Bucket": BUCKET, "Prefix": "bronze/releases/tx-dallas/2026/certified/"},
    )

    with stubber:
        found = S3BronzeStore(client, BUCKET).referenced_checksums(PARTITION)
        stubber.assert_no_pending_responses()

    assert found == {DIGEST}


def test_a_continuation_token_is_sent_on_the_second_page(client) -> None:  # noqa: ANN001
    """The paging parameter is `ContinuationToken`, and the model says so."""

    prefix = "bronze/releases/tx-dallas/2026/certified/"
    stubber = Stubber(client)
    stubber.add_response(
        "list_objects_v2",
        {
            "Contents": [{"Key": f"{prefix}{'0' * 64}.ref.json"}],
            "IsTruncated": True,
            "NextContinuationToken": "page-2",
        },
        {"Bucket": BUCKET, "Prefix": prefix},
    )
    stubber.add_response(
        "list_objects_v2",
        {"Contents": [{"Key": f"{prefix}{DIGEST}.ref.json"}]},
        {"Bucket": BUCKET, "Prefix": prefix, "ContinuationToken": "page-2"},
    )

    with stubber:
        found = S3BronzeStore(client, BUCKET).referenced_checksums(PARTITION)
        stubber.assert_no_pending_responses()

    assert found == {"0" * 64, DIGEST}


def test_the_abort_call_matches_the_service_model(client) -> None:  # noqa: ANN001
    stubber = Stubber(client)
    stubber.add_response(
        "create_multipart_upload", {"UploadId": "upload-1"}, {"Bucket": BUCKET, "Key": ANY}
    )
    stubber.add_response(
        "abort_multipart_upload", {}, {"Bucket": BUCKET, "Key": ANY, "UploadId": "upload-1"}
    )
    stubber.add_response("delete_object", {}, {"Bucket": BUCKET, "Key": ANY})

    with stubber:
        with S3ArtifactSink(client, BUCKET) as sink:
            sink.write(PAYLOAD)
            sink.abort()
        stubber.assert_no_pending_responses()


def test_a_real_client_error_is_recognised_as_a_precondition_failure(client) -> None:  # noqa: ANN001
    """The tolerated path keys off botocore's error shape, not a string match."""

    stubber = Stubber(client)
    stubber.add_client_error(
        "put_object", service_error_code="PreconditionFailed", http_status_code=412
    )

    with stubber:
        # Tolerated: the record already exists and describes the same artifact.
        S3BronzeStore(client, BUCKET).reference_partition(PARTITION, DIGEST)


def test_an_unrelated_client_error_still_propagates(client) -> None:  # noqa: ANN001
    """Only a precondition failure is tolerated; everything else is a real fault."""

    from botocore.exceptions import ClientError

    stubber = Stubber(client)
    stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)

    with stubber, pytest.raises(ClientError):
        S3BronzeStore(client, BUCKET).reference_partition(PARTITION, DIGEST)
