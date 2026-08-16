"""The bounded release-processing boundary.

A single-pass county reader plus a caller-supplied atomic stage, with a
processor that stages records which stay invisible until exactly one commit.

Issue #43 decisions D1, D2, D3, D4, D6, D8, and the diagnostic half of D5. The
resource target, its measurement, and the acceptance benchmark are a separate
change; this one declares the `ResourceGuard` seam they plug into.
"""

from property_tax_adapters.release.outcome import (
    BOUNDARY_CONTRACT_VERSION,
    DIAGNOSTIC_RETENTION_LIMIT,
    DuplicateRecordKey,
    ReleaseDiagnostic,
    ReleaseDiagnosticCode,
    ReleaseDisposition,
    ReleaseNotice,
    ReleaseOutcome,
)
from property_tax_adapters.release.processor import process_release
from property_tax_adapters.release.progress import (
    PROGRESS_CONTRACT_VERSION,
    PROGRESS_ROW_INTERVAL,
    ReleaseProgressEvent,
)
from property_tax_adapters.release.protocols import (
    PreparedReader,
    ProgressCallback,
    ReleaseStage,
    ResourceGuard,
)
from property_tax_adapters.release.records import (
    MAX_CARRIER_NOTICES,
    NoticeSet,
    PreparedRelease,
    SourceRowEnvelope,
    record_disagreement,
)

__all__ = [
    "BOUNDARY_CONTRACT_VERSION",
    "DIAGNOSTIC_RETENTION_LIMIT",
    "MAX_CARRIER_NOTICES",
    "PROGRESS_CONTRACT_VERSION",
    "PROGRESS_ROW_INTERVAL",
    "DuplicateRecordKey",
    "NoticeSet",
    "PreparedReader",
    "PreparedRelease",
    "ProgressCallback",
    "ReleaseDiagnostic",
    "ReleaseDiagnosticCode",
    "ReleaseDisposition",
    "ReleaseNotice",
    "ReleaseOutcome",
    "ReleaseProgressEvent",
    "ReleaseStage",
    "ResourceGuard",
    "SourceRowEnvelope",
    "process_release",
    "record_disagreement",
]
