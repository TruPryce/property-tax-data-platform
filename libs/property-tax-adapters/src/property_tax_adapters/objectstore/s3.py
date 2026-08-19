"""Amazon S3 Bronze storage: a streaming sink and an immutable manifest store.

The sink implements the acquisition boundary's `ArtifactSink`, so bytes reach S3
the same way they reach any other sink — one bounded chunk at a time, never as a
whole object in memory.  Multipart upload is what makes that possible against
S3: parts are sent as they accumulate, and the object does not exist until the
upload is completed.

That maps onto the sink contract exactly.  `write` buffers to the part size and
flushes; `commit` completes the upload and returns the object URI; `abort` sends
`AbortMultipartUpload`, so a failed acquisition leaves no object *and* no
lingering parts accruing storage charges.  An acquisition that dies between the
two leaves an incomplete upload rather than a partial object, which is the
difference between something a lifecycle rule can clean up and something a
consumer can mistake for a complete artifact.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from property_tax_application.bronze import (
    BronzeConflict,
    ReleaseManifest,
    ReleasePartition,
)

__all__ = ["MINIMUM_PART_BYTES", "S3ArtifactSink", "S3BronzeStore", "manifest_key", "object_key"]

#: S3 requires every part except the last to be at least 5 MiB.  A smaller
#: buffer would be rejected at completion rather than at write, which is the
#: worst moment to discover it.
MINIMUM_PART_BYTES = 5 * 1024 * 1024


def object_key(partitions: tuple[ReleasePartition, ...], sha256: str) -> str:
    """Where an artifact's bytes live, keyed by content rather than by name.

    The checksum is in the key because Bronze is immutable and content-addressed:
    two acquisitions of the same bytes land on the same key and cannot diverge,
    while different bytes for the same release land beside each other rather than
    overwriting.  The mutable source slot a county publishes — Dallas reuses one
    `CURRENT` filename — has no bearing on where its contents are kept.
    """

    first = min(partitions, key=lambda p: (p.jurisdiction_code, p.tax_year, p.release_kind))
    return f"bronze/{first.jurisdiction_code}/{first.tax_year}/{first.release_kind}/{sha256}"


def manifest_key(partitions: tuple[ReleasePartition, ...], sha256: str) -> str:
    """The manifest sits beside the bytes it describes, under the same identity."""

    return f"{object_key(partitions, sha256)}.manifest.json"


class S3ArtifactSink:
    """Streams an artifact into S3 as a multipart upload.

    Implements the acquisition boundary's `ArtifactSink`.  Nothing here holds the
    complete object: a buffer is flushed as a part whenever it reaches the part
    size, so peak memory is one part regardless of artifact size.
    """

    __slots__ = ("_buffer", "_bucket", "_client", "_key", "_parts", "_part_bytes", "_upload_id")

    def __init__(
        self, client: Any, bucket: str, key: str, *, part_bytes: int = MINIMUM_PART_BYTES
    ) -> None:
        if part_bytes < MINIMUM_PART_BYTES:
            raise ValueError(
                f"part_bytes must be at least {MINIMUM_PART_BYTES}; S3 rejects a smaller "
                "non-final part at completion rather than at write"
            )
        self._client = client
        self._bucket = bucket
        self._key = key
        self._part_bytes = part_bytes
        self._buffer = bytearray()
        self._parts: list[dict[str, object]] = []
        self._upload_id: str | None = None

    def __enter__(self) -> S3ArtifactSink:
        created = self._client.create_multipart_upload(Bucket=self._bucket, Key=self._key)
        self._upload_id = created["UploadId"]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Raises nothing after a commit or an abort, and suppresses nothing:
        # both are the sink contract, and an exception here would arrive after
        # the object is already durable.
        self._buffer.clear()

    def write(self, chunk: bytes) -> None:
        self._buffer += chunk
        while len(self._buffer) >= self._part_bytes:
            self._flush(self._part_bytes)

    def _flush(self, size: int) -> None:
        body, self._buffer = bytes(self._buffer[:size]), bytearray(self._buffer[size:])
        number = len(self._parts) + 1
        response = self._client.upload_part(
            Bucket=self._bucket,
            Key=self._key,
            PartNumber=number,
            UploadId=self._upload_id,
            Body=body,
        )
        self._parts.append({"ETag": response["ETag"], "PartNumber": number})

    def commit(self) -> str:
        """Complete the upload and return where the bytes landed."""

        if self._buffer:
            # The final part may be smaller than the minimum; only earlier ones
            # may not.
            self._flush(len(self._buffer))
        if not self._parts:
            # S3 refuses a multipart upload with no parts, and a zero-byte
            # artifact is still an artifact.
            self._flush(0)
        self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=self._key,
            UploadId=self._upload_id,
            MultipartUpload={"Parts": self._parts},
        )
        return f"s3://{self._bucket}/{self._key}"

    def abort(self) -> None:
        """Discard the upload, so no object and no orphaned parts survive.

        Safe after a failed `__enter__`: with no upload to abort there is
        nothing to discard, and saying so is cheaper than making every caller
        remember which failures created one.
        """

        self._buffer.clear()
        if self._upload_id is None:
            return
        self._client.abort_multipart_upload(
            Bucket=self._bucket, Key=self._key, UploadId=self._upload_id
        )
        self._upload_id = None


class S3BronzeStore:
    """Records manifests in S3, and judges a repeat release identity.

    Implements the application's `BronzeStore`.  Writes are conditional: a
    manifest already recorded for an artifact version is never overwritten,
    because Bronze keeps what it was given and a correction is a new version.
    """

    __slots__ = ("_bucket", "_client")

    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def classify(self, partitions: tuple[ReleasePartition, ...], sha256: str) -> BronzeConflict:
        """Compare this identity and checksum against what is already stored.

        A prefix listing rather than a single lookup, because the interesting
        case is a *different* checksum under the same release identity — which
        by construction sits at a different key, so looking only where these
        bytes would land could never find it.
        """

        first = min(partitions, key=lambda p: (p.jurisdiction_code, p.tax_year, p.release_kind))
        prefix = f"bronze/{first.jurisdiction_code}/{first.tax_year}/{first.release_kind}/"
        stored = self._manifest_checksums(prefix)
        if sha256 in stored:
            return BronzeConflict.IDENTICAL
        if stored:
            return BronzeConflict.DIVERGED
        return BronzeConflict.NEW

    def _manifest_checksums(self, prefix: str) -> set[str]:
        seen: set[str] = set()
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self._client.list_objects_v2(**kwargs)
            for entry in page.get("Contents", ()):
                key = str(entry["Key"])
                if key.endswith(".manifest.json"):
                    seen.add(key.rsplit("/", 1)[-1].removesuffix(".manifest.json"))
            if not page.get("IsTruncated"):
                return seen
            token = page.get("NextContinuationToken")
            if not token:
                return seen

    def record(self, manifest: ReleaseManifest) -> str:
        """Write the manifest beside its artifact, refusing to replace one.

        `IfNoneMatch` makes the refusal the store's rather than the caller's: a
        second writer racing the first is rejected by S3 instead of silently
        replacing a record of what was acquired.
        """

        key = manifest_key(manifest.partitions, manifest.artifact.sha256)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=serialize_manifest(manifest).encode("utf-8"),
            ContentType="application/json",
            IfNoneMatch="*",
        )
        return f"s3://{self._bucket}/{key}"


def serialize_manifest(manifest: ReleaseManifest) -> str:
    """Render a manifest as sorted, stable JSON.

    Sorted and fixed-separator so two runs over one artifact produce identical
    bytes: a manifest that differs only by key order would look like a changed
    record to anything comparing them.
    """

    payload = {
        "manifest_version": manifest.manifest_version,
        "acquired_at": manifest.acquired_at.astimezone(UTC).isoformat(),
        "conflict": manifest.conflict.value,
        "source_url": manifest.source_url,
        "artifact": {
            "locator": manifest.artifact.locator,
            "sha256": manifest.artifact.sha256,
            "byte_count": manifest.artifact.byte_count,
            "media_type": manifest.artifact.media_type,
        },
        "partitions": [
            {
                "jurisdiction_code": partition.jurisdiction_code,
                "tax_year": partition.tax_year,
                "release_kind": partition.release_kind,
            }
            for partition in manifest.partitions
        ],
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
