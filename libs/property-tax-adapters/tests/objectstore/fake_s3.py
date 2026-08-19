"""A fake S3 client: enough of the API to hold the adapter to its contract.

Not a mock that records calls. It keeps objects and in-flight uploads, so a
test can ask what actually exists rather than what was requested — the
difference between asserting that `abort` was called and asserting that nothing
survived it.
"""

# ruff: noqa: N803 - boto3's S3 API takes PascalCase keywords, and a fake that
# renamed them would not stand in for the client the adapter actually calls.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class S3Error(Exception):
    """Stands in for botocore's ClientError, with the code tests branch on."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class Upload:
    key: str
    parts: dict[int, bytes] = field(default_factory=dict)
    aborted: bool = False
    completed: bool = False


@dataclass
class FakeS3:
    """Objects that exist, and uploads that have not become objects yet."""

    objects: dict[str, bytes] = field(default_factory=dict)
    content_types: dict[str, str] = field(default_factory=dict)
    uploads: dict[str, Upload] = field(default_factory=dict)
    _next_upload: int = 0
    fail_on_part: int | None = None
    fail_on_complete: bool = False

    # -- multipart ---------------------------------------------------------

    def create_multipart_upload(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self._next_upload += 1
        upload_id = f"upload-{self._next_upload}"
        self.uploads[upload_id] = Upload(key=Key)
        return {"UploadId": upload_id}

    def upload_part(
        self,
        *,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> dict[str, Any]:
        if self.fail_on_part == PartNumber:
            raise S3Error("InternalError")
        self.uploads[UploadId].parts[PartNumber] = Body
        return {"ETag": f'"etag-{PartNumber}"'}

    def complete_multipart_upload(
        self,
        *,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.fail_on_complete:
            raise S3Error("InternalError")
        upload = self.uploads[UploadId]
        ordered = sorted(part["PartNumber"] for part in MultipartUpload["Parts"])
        self.objects[Key] = b"".join(upload.parts[number] for number in ordered)
        upload.completed = True
        return {"ETag": '"final"'}

    def abort_multipart_upload(self, *, Bucket: str, Key: str, UploadId: str) -> dict[str, Any]:
        self.uploads[UploadId].aborted = True
        self.uploads[UploadId].parts.clear()
        return {}

    # -- objects -----------------------------------------------------------

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str | None = None,
        IfNoneMatch: str | None = None,
    ) -> dict[str, Any]:
        if IfNoneMatch == "*" and Key in self.objects:
            raise S3Error("PreconditionFailed")
        self.objects[Key] = Body
        if ContentType:
            self.content_types[Key] = ContentType
        return {}

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str = "",
        ContinuationToken: str | None = None,
    ) -> dict[str, Any]:
        keys = sorted(key for key in self.objects if key.startswith(Prefix))
        # Paginate at two, so the continuation path is exercised rather than
        # assumed: a listing that never truncates hides a whole branch.
        start = int(ContinuationToken or 0)
        window = keys[start : start + 2]
        truncated = start + 2 < len(keys)
        page: dict[str, Any] = {"Contents": [{"Key": key} for key in window]}
        if truncated:
            page["IsTruncated"] = True
            page["NextContinuationToken"] = str(start + 2)
        return page

    # -- what a test asks about -------------------------------------------

    @property
    def orphaned_parts(self) -> int:
        return sum(len(u.parts) for u in self.uploads.values() if not u.completed)
