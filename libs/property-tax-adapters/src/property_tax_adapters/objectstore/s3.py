"""Amazon S3 Bronze storage: a streaming sink and immutable manifest records.

Three rules shape this, and the first two were learned by getting them wrong.

**An artifact is named by its content, and the content is not known until it has
all arrived.** So bytes stream to a staging key unique to the attempt, and
`commit` finalizes them to `artifacts/<sha256>` with a conditional copy. A
caller-chosen destination cannot work: whoever picks the name picks it before
the checksum exists, and reusing one silently replaces the bytes an earlier
manifest still points at.

**An artifact's identity does not depend on the releases that reference it.**
One archive can carry current values for one tax year and certified for another,
and a partition can be discovered long after acquisition. Keying bytes by any
partition would make identity depend on which release happened to be noticed
first, so the artifact key is the checksum alone and partitions are index
entries beside it.

**No conflict verdict is stored as truth.** Two writers can both look, both see
nothing, and both write. Every write here is conditional, so nothing is ever
replaced; divergence is then computed from what durably exists rather than from
what some writer believed at the time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Protocol

from property_tax_application.bronze import (
    BronzeConflict,
    ReleaseManifest,
    ReleasePartition,
    StoredArtifact,
)

__all__ = [
    "ARTIFACT_PREFIX",
    "ArtifactMismatchError",
    "MAX_SINGLE_COPY_BYTES",
    "MissingArtifactError",
    "MINIMUM_PART_BYTES",
    "MULTIPART_COPY_PART_BYTES",
    "RELEASE_PREFIX",
    "STAGING_PREFIX",
    "S3ArtifactSink",
    "S3BronzeStore",
    "TruncatedListingError",
    "artifact_key",
    "manifest_key",
    "partition_prefix",
    "partition_ref_key",
    "serialize_manifest",
    "utc_now",
]

#: S3 requires every part except the last to be at least 5 MiB.  A smaller
#: buffer is rejected at completion rather than at write, which is the worst
#: moment to discover it.
MINIMUM_PART_BYTES = 5 * 1024 * 1024

#: `CopyObject` handles a single object up to 5 GB.  Acquisition permits more,
#: so anything past this is finalized with a ranged multipart copy instead —
#: the decimal reading of AWS's documented limit, which is the conservative one.
MAX_SINGLE_COPY_BYTES = 5 * 1000**3

#: Each ranged copy part.  Comfortably inside the 5 GB per-part ceiling and far
#: above the 5 MiB floor, so neither bound is close to a concern.
MULTIPART_COPY_PART_BYTES = 512 * 1024 * 1024

#: Bytes in flight, named by attempt.  Nothing durable is ever read from here.
STAGING_PREFIX = "bronze/staging"
#: Bytes at rest, named by their own checksum.
ARTIFACT_PREFIX = "bronze/artifacts"
#: Which releases reference which artifact.
RELEASE_PREFIX = "bronze/releases"

_PRECONDITION_CODES = frozenset({"PreconditionFailed", "ConditionalRequestConflict"})
#: What S3 says when an object genuinely is not there.  `HeadObject` answers
#: with a bare 404 and no code, which is why the status is checked too.
_ABSENT_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class ArtifactMismatchError(Exception):
    """A manifest describes an object other than the one it is keyed by.

    Refused rather than recorded: a manifest is immutable and durable, so one
    naming a different bucket, key, or length would be a permanent record
    pointing at something it does not describe.
    """


class MissingArtifactError(Exception):
    """A reference was asked for an artifact that is not stored.

    Refused rather than written, because a reference is what divergence counts:
    a dangling one reports bytes that cannot be fetched as stored, and makes a
    genuinely new checksum look already present.
    """


class TruncatedListingError(Exception):
    """A listing said there was more and did not say where to continue.

    Raised rather than returning what arrived.  A partial listing looks exactly
    like a complete one to the caller, so treating it as complete turns "I could
    not check" into "there is nothing there" — which for conflict detection is
    the difference between finding a divergent artifact and silently overwriting
    the question.
    """


class S3Client(Protocol):
    """The subset of the S3 API this module calls."""

    def create_multipart_upload(self, **kwargs: Any) -> Any: ...
    def upload_part_copy(self, **kwargs: Any) -> Any: ...
    def head_object(self, **kwargs: Any) -> Any: ...
    def upload_part(self, **kwargs: Any) -> Any: ...
    def complete_multipart_upload(self, **kwargs: Any) -> Any: ...
    def abort_multipart_upload(self, **kwargs: Any) -> Any: ...
    def copy_object(self, **kwargs: Any) -> Any: ...
    def delete_object(self, **kwargs: Any) -> Any: ...
    def put_object(self, **kwargs: Any) -> Any: ...
    def list_objects_v2(self, **kwargs: Any) -> Any: ...


def artifact_key(sha256: str) -> str:
    """Where the bytes live: the checksum, and nothing about any release."""

    return f"{ARTIFACT_PREFIX}/{sha256}"


def manifest_key(sha256: str) -> str:
    """The manifest describes an artifact, so it is keyed like one."""

    return f"{ARTIFACT_PREFIX}/{sha256}.manifest.json"


def partition_prefix(partition: ReleasePartition) -> str:
    return (
        f"{RELEASE_PREFIX}/{partition.jurisdiction_code}"
        f"/{partition.tax_year}/{partition.release_kind}/"
    )


def partition_ref_key(partition: ReleasePartition, sha256: str) -> str:
    """One reference per release partition, pointing at an artifact.

    Separate objects rather than a list inside the manifest, so a partition
    discovered after acquisition is a new object rather than an edit to an
    immutable record.
    """

    return f"{partition_prefix(partition)}{sha256}.ref.json"


def _error_code(error: BaseException) -> str | None:
    code = getattr(error, "code", None)
    if code is None:
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            code = response.get("Error", {}).get("Code")
    return None if code is None else str(code)


def _is_absent(error: BaseException) -> bool:
    """True only for a genuine absence, never for a denial or a throttle."""

    if _error_code(error) in _ABSENT_CODES:
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return bool(status == 404)
    return False


def _is_precondition_failure(error: BaseException) -> bool:
    return _error_code(error) in _PRECONDITION_CODES


class S3ArtifactSink:
    """Streams an artifact to S3 and finalizes it under its own checksum.

    Implements the acquisition boundary's `ArtifactSink`.  Nothing here holds the
    complete object: a buffer is flushed as a part whenever it reaches the part
    size, so peak memory is one part regardless of artifact size.

    It hashes what it writes.  The acquisition boundary hashes what it read, and
    the two see the same bytes — but only the sink can name the destination,
    because only `commit` happens after every byte has arrived.
    """

    __slots__ = (
        "_artifact_prefix",
        "_buffer",
        "_bucket",
        "_copy_upload",
        "_client",
        "_digest",
        "_parts",
        "_part_bytes",
        "_staging_key",
        "_upload_id",
        "_written",
    )

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        *,
        part_bytes: int = MINIMUM_PART_BYTES,
        artifact_prefix: str = ARTIFACT_PREFIX,
        staging_prefix: str = STAGING_PREFIX,
    ) -> None:
        if part_bytes < MINIMUM_PART_BYTES:
            raise ValueError(
                f"part_bytes must be at least {MINIMUM_PART_BYTES}; S3 rejects a smaller "
                "non-final part at completion rather than at write"
            )
        self._client = client
        self._bucket = bucket
        self._part_bytes = part_bytes
        self._artifact_prefix = artifact_prefix
        # Unique to this attempt, so two concurrent acquisitions of anything at
        # all cannot collide before either knows what it is carrying.
        self._staging_key = f"{staging_prefix}/{uuid.uuid4()}"
        self._buffer = bytearray()
        self._parts: list[dict[str, object]] = []
        self._upload_id: str | None = None
        self._digest = hashlib.sha256()
        self._written = 0
        self._copy_upload: tuple[str, str] | None = None

    @property
    def sha256(self) -> str:
        """The checksum of everything written so far."""

        return self._digest.hexdigest()

    def __enter__(self) -> S3ArtifactSink:
        created = self._client.create_multipart_upload(Bucket=self._bucket, Key=self._staging_key)
        self._upload_id = created["UploadId"]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Raises nothing after a commit or an abort, and suppresses nothing.
        self._buffer.clear()

    def write(self, chunk: bytes) -> None:
        self._digest.update(chunk)
        self._written += len(chunk)
        self._buffer += chunk
        while len(self._buffer) >= self._part_bytes:
            self._flush(self._part_bytes)

    def _flush(self, size: int) -> None:
        body, self._buffer = bytes(self._buffer[:size]), bytearray(self._buffer[size:])
        number = len(self._parts) + 1
        response = self._client.upload_part(
            Bucket=self._bucket,
            Key=self._staging_key,
            PartNumber=number,
            UploadId=self._upload_id,
            Body=body,
        )
        self._parts.append({"ETag": response["ETag"], "PartNumber": number})

    def commit(self) -> str:
        """Finalize the bytes under their checksum and return where they landed.

        The copy is conditional.  If an object already exists at the content key
        it holds these very bytes — that is what content-addressing means — so a
        refused copy is a success, not a collision to resolve.
        """

        if self._buffer or not self._parts:
            # The final part may be under the minimum; only earlier ones may not.
            # And S3 refuses an upload with no parts, while a zero-byte artifact
            # is still an artifact.
            self._flush(len(self._buffer))
        self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=self._staging_key,
            UploadId=self._upload_id,
            MultipartUpload={"Parts": self._parts},
        )
        self._upload_id = None

        final_key = f"{self._artifact_prefix}/{self.sha256}"
        try:
            if self._written <= MAX_SINGLE_COPY_BYTES:
                self._client.copy_object(
                    Bucket=self._bucket,
                    Key=final_key,
                    CopySource={"Bucket": self._bucket, "Key": self._staging_key},
                    IfNoneMatch="*",
                )
            else:
                self._copy_in_parts(final_key)
        except Exception as error:
            if not _is_precondition_failure(error):
                raise
        self._client.delete_object(Bucket=self._bucket, Key=self._staging_key)
        return f"s3://{self._bucket}/{final_key}"

    def _copy_in_parts(self, final_key: str) -> None:
        """Finalize an object too large for a single copy.

        `CopyObject` tops out at 5 GB while acquisition permits considerably
        more, so an artifact between the two limits would have failed at the
        last step of a successful transfer.  `UploadPartCopy` takes a byte range
        per part, and the source is already in S3, so nothing crosses the
        network twice either way.
        """

        created = self._client.create_multipart_upload(Bucket=self._bucket, Key=final_key)
        # Recorded on the sink before anything can fail.  Holding the id in a
        # local and aborting inside this method's own `except` loses it when
        # that abort itself fails: the parts stay, and `abort` has nothing left
        # to retry or to report.
        self._copy_upload = (final_key, created["UploadId"])
        upload_id = created["UploadId"]
        try:
            parts: list[dict[str, object]] = []
            start = 0
            while start < self._written:
                end = min(start + MULTIPART_COPY_PART_BYTES, self._written) - 1
                number = len(parts) + 1
                response = self._client.upload_part_copy(
                    Bucket=self._bucket,
                    Key=final_key,
                    UploadId=upload_id,
                    PartNumber=number,
                    CopySource={"Bucket": self._bucket, "Key": self._staging_key},
                    CopySourceRange=f"bytes={start}-{end}",
                )
                parts.append({"ETag": response["CopyPartResult"]["ETag"], "PartNumber": number})
                start = end + 1
            self._client.complete_multipart_upload(
                Bucket=self._bucket,
                Key=final_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
                IfNoneMatch="*",
            )
        except Exception:
            # A failed ranged copy must not leave its own upload behind, and if
            # this attempt at that also fails the state survives on the sink so
            # `abort` can try again and report a cleanup that did not happen.
            self._client.abort_multipart_upload(
                Bucket=self._bucket, Key=final_key, UploadId=upload_id
            )
            self._copy_upload = None
            raise
        self._copy_upload = None

    def abort(self) -> None:
        """Discard everything, so no object and no orphaned parts survive.

        Safe when the upload never started: a caller should not have to know
        which failures created one.
        """

        self._buffer.clear()
        if self._upload_id is not None:
            self._client.abort_multipart_upload(
                Bucket=self._bucket, Key=self._staging_key, UploadId=self._upload_id
            )
            self._upload_id = None
        if self._copy_upload is not None:
            # The destination upload of a ranged copy that neither completed nor
            # managed to abort itself.  Its id survives on the sink precisely so
            # this can reach it, and a failure here propagates like any other.
            key, upload_id = self._copy_upload
            self._copy_upload = None
            self._client.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)
        # The completed staging object survives a failure between commit's two
        # steps.  A delete that fails is not swallowed: the acquisition boundary
        # reports a failed cleanup as its own fact, and suppressing it here
        # would tell a caller the sink was clean when an object remains.
        # Deleting a key that never existed is not a failure in S3.
        self._client.delete_object(Bucket=self._bucket, Key=self._staging_key)


class S3BronzeStore:
    """Records manifests and release references, and judges what already exists.

    Every write is conditional, so nothing recorded is ever replaced.  That is
    what lets `classify` be honest: it reports what durably exists at the moment
    it looks, rather than a verdict some earlier writer reached and stored.
    """

    __slots__ = ("_bucket", "_client")

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def classify(self, partition: ReleasePartition, sha256: str) -> BronzeConflict:
        """Judge this checksum against every artifact this partition references.

        Derived from durable state at read time, and deliberately not stored.
        Two writers can both look, both see nothing, and both write; only the
        conditional writes below decide what survives, and this reports what did.
        """

        referenced = self.referenced_checksums(partition)
        if not referenced:
            return BronzeConflict.NEW
        # More than one artifact under one release identity is divergence, and
        # it stays divergence once recorded.  Asking whether *this* checksum is
        # among them answers a different question: an earlier version answered
        # that one and reported IDENTICAL for both sides of a known conflict,
        # so the divergence vanished the moment it was stored.
        if len(referenced) > 1:
            return BronzeConflict.DIVERGED
        return BronzeConflict.IDENTICAL if sha256 in referenced else BronzeConflict.DIVERGED

    def referenced_checksums(self, partition: ReleasePartition) -> set[str]:
        """Every artifact checksum this release partition points at."""

        seen: set[str] = set()
        token: str | None = None
        prefix = partition_prefix(partition)
        while True:
            kwargs: dict[str, object] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self._client.list_objects_v2(**kwargs)
            for entry in page.get("Contents", ()):
                key = str(entry["Key"])
                if key.endswith(".ref.json"):
                    seen.add(key.rsplit("/", 1)[-1].removesuffix(".ref.json"))
            if not page.get("IsTruncated"):
                return seen
            token = page.get("NextContinuationToken")
            if not token:
                # Fail closed: returning what arrived would report "nothing
                # there" for "I could not finish looking".
                raise TruncatedListingError(
                    f"listing of {prefix} was truncated without a continuation token"
                )

    def _reference_body(self, partition: ReleasePartition, sha256: str) -> bytes:
        """The one rendering of a reference, whichever entry point writes it.

        Two renderings would be worse than either: the key is immutable, so the
        first writer's body is the one that survives, and a reader would get a
        different shape depending on which call happened to win a race it cannot
        see.
        """

        return json.dumps(
            {
                "artifact_sha256": sha256,
                "artifact_locator": f"s3://{self._bucket}/{artifact_key(sha256)}",
                "jurisdiction_code": partition.jurisdiction_code,
                "tax_year": partition.tax_year,
                "release_kind": partition.release_kind,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _require_artifact(self, manifest_artifact: StoredArtifact | None, sha256: str) -> None:
        """Refuse to reference bytes that are not there, or that disagree.

        A reference is what `classify` counts, so a dangling one reports an
        artifact that cannot be fetched as though it were stored — and worse,
        makes a genuinely new checksum look already present.

        Only a genuine absence is a missing artifact.  An earlier version turned
        every `HeadObject` failure into one, so a denied permission or a
        throttled request said "these bytes do not exist" — which is a claim
        about the world made from a fact about this caller, and the caller would
        then have gone on to store something under it.
        """

        head = None
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=artifact_key(sha256))
        except Exception as error:
            if not _is_absent(error):
                raise
            raise MissingArtifactError(
                f"no artifact is stored for {sha256}, so it cannot be referenced"
            ) from error

        if manifest_artifact is None:
            return
        # The manifest describes an object; this is where the two are made to
        # agree.  A manifest naming a different bucket, key, or length would be
        # a durable record pointing at something other than what it describes.
        canonical = f"s3://{self._bucket}/{artifact_key(sha256)}"
        if manifest_artifact.locator != canonical:
            raise ArtifactMismatchError(
                f"the manifest names {manifest_artifact.locator} while the artifact for this "
                f"checksum is at {canonical}"
            )
        stored_length = head.get("ContentLength")
        if stored_length is not None and stored_length != manifest_artifact.byte_count:
            raise ArtifactMismatchError(
                f"the manifest records {manifest_artifact.byte_count} bytes while the stored "
                f"object holds {stored_length}"
            )

    def record(self, manifest: ReleaseManifest) -> str:
        """Persist the manifest and one reference per partition, immutably.

        Conditional on absence, so a second writer racing the first is refused
        by S3 rather than replacing a record of what was acquired.  An already
        present manifest is not an error: it describes the same artifact by
        construction, since both are keyed by the same checksum.
        """

        sha256 = manifest.artifact.sha256
        self._require_artifact(manifest.artifact, sha256)
        self._put_if_absent(
            manifest_key(sha256), serialize_manifest(manifest).encode("utf-8"), "application/json"
        )
        for partition in manifest.partitions:
            self._put_if_absent(
                partition_ref_key(partition, sha256),
                self._reference_body(partition, sha256),
                "application/json",
            )
        return f"s3://{self._bucket}/{manifest_key(sha256)}"

    def reference_partition(self, partition: ReleasePartition, sha256: str) -> str:
        """Attach a partition discovered after acquisition to an existing artifact.

        A new object rather than an edit: the manifest is immutable, and a
        release noticed later does not change what was acquired.
        """

        self._require_artifact(None, sha256)
        key = partition_ref_key(partition, sha256)
        self._put_if_absent(key, self._reference_body(partition, sha256), "application/json")
        return f"s3://{self._bucket}/{key}"

    def _put_if_absent(self, key: str, body: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except Exception as error:
            if not _is_precondition_failure(error):
                raise


def serialize_manifest(manifest: ReleaseManifest) -> str:
    """Render a manifest as sorted, stable JSON.

    Sorted and fixed-separator so two runs over one artifact produce identical
    bytes: a manifest differing only by key order would look like a changed
    record to anything comparing them.
    """

    payload = {
        "manifest_version": manifest.manifest_version,
        "acquired_at": manifest.acquired_at.astimezone(UTC).isoformat(),
        "source_url": manifest.source_url,
        "artifact": {
            "locator": manifest.artifact.locator,
            "sha256": manifest.artifact.sha256,
            "byte_count": manifest.artifact.byte_count,
            "media_type": manifest.artifact.media_type,
        },
        "partitions": sorted(
            (
                {
                    "jurisdiction_code": partition.jurisdiction_code,
                    "tax_year": partition.tax_year,
                    "release_kind": partition.release_kind,
                }
                for partition in manifest.partitions
            ),
            key=lambda entry: (
                entry["jurisdiction_code"],
                entry["tax_year"],
                entry["release_kind"],
            ),
        ),
        "response": {
            "status": manifest.response.status,
            "headers": dict(manifest.response.headers),
        },
        "redirects": [
            {"from_url": hop.from_url, "to_url": hop.to_url, "status": hop.status}
            for hop in manifest.redirects
        ],
        "tool_versions": dict(manifest.tool_versions),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def utc_now() -> datetime:
    """The acquisition instant, recorded exactly rather than approximated."""

    return datetime.now(UTC)
