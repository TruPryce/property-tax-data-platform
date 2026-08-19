"""What Bronze records about an artifact, and what a store owes.

Bronze is immutable: the original bytes and a manifest describing them, written
once and never rewritten.  The manifest is the durable half — an object without
one cannot be found, verified, or attributed, and an object whose manifest was
written before the bytes were verified would claim a completeness the transfer
never reached.

Nothing here performs I/O.  It is the port the S3 adapter implements and the
contract a caller reads, so the immutability rules live where both can see them
rather than inside one storage backend's control flow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from property_tax_application.acquisition import (
    MAX_LOCATOR_CHARS,
    AcquiredArtifact,
    RedirectHop,
    ResponseMetadata,
)

__all__ = [
    "BRONZE_MANIFEST_VERSION",
    "BronzeConflict",
    "BronzeStore",
    "ReleaseManifest",
    "ReleasePartition",
    "StoredArtifact",
]

#: The manifest schema this contract writes.  Pinned, so a consumer can tell
#: which shape it is reading rather than inferring it from the fields present.
BRONZE_MANIFEST_VERSION: int = 1

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_JURISDICTION_PATTERN = re.compile(r"[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class BronzeConflict(StrEnum):
    """What a store found when asked to record an artifact.

    Three outcomes and no fourth, because the interesting case is the middle
    one: the same release identity arriving with different bytes is not an
    error to retry and not a duplicate to ignore.
    """

    #: No artifact was stored for this release identity before.
    NEW = "new"
    #: The same identity and the same checksum: already recorded, nothing to do.
    IDENTICAL = "identical"
    #: The same identity with a *different* checksum. Both versions are kept and
    #: the release is flagged, never overwritten.
    DIVERGED = "diverged"


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a str")
    if _IDENTIFIER_PATTERN.fullmatch(value) is None or value[0] in {".", "-"}:
        raise ValueError(
            f"{field_name} must be 1 to 128 characters of [A-Za-z0-9._-] not beginning "
            "with '.' or '-', so a host-local path cannot be represented"
        )


@dataclass(frozen=True, slots=True)
class ReleasePartition:
    """One logical release backed by an artifact.

    Separate from the artifact because they are different counts: one measured
    Collin archive carries current values for one tax year and certified values
    for another, and both are releases sharing one set of bytes, one checksum,
    and one acquisition event.
    """

    jurisdiction_code: str
    tax_year: int
    release_kind: str

    def __post_init__(self) -> None:
        if _JURISDICTION_PATTERN.fullmatch(self.jurisdiction_code) is None:
            raise ValueError(
                "jurisdiction_code must be a lowercase state prefix, a hyphen, and a county slug"
            )
        if isinstance(self.tax_year, bool) or not isinstance(self.tax_year, int):
            raise ValueError("tax_year must be an int")
        if not 1900 <= self.tax_year <= 2200:
            raise ValueError(f"tax_year must be a plausible appraisal year, got {self.tax_year}")
        _require_identifier(self.release_kind, "release_kind")


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Where the bytes landed, and what they are.

    Constructed only after a store has committed: holding one is the evidence
    that the object is durable, which is why there is no partial form of it.
    """

    locator: str
    sha256: str
    byte_count: int
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.locator, str) or not self.locator.strip():
            raise ValueError("locator must be a non-blank str")
        if len(self.locator) > MAX_LOCATOR_CHARS:
            raise ValueError(f"locator exceeds {MAX_LOCATOR_CHARS} characters")
        if _CONTROL_CHARACTERS.search(self.locator) is not None:
            raise ValueError("locator carries a control character")
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if isinstance(self.byte_count, bool) or not isinstance(self.byte_count, int):
            raise ValueError("byte_count must be an int")
        if self.byte_count < 0:
            raise ValueError("byte_count must not be negative")
        if self.media_type is not None and (
            not isinstance(self.media_type, str) or not self.media_type.strip()
        ):
            raise ValueError("media_type must be a non-blank str or None")


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """The immutable record of one acquisition.

    Every field is either evidence about the bytes or sanitized provenance about
    where they came from.  There is no field for a credential, a host path, or a
    signed query: the acquisition boundary already refused those, and repeating
    the rule here is what stops a manifest built by some other caller from
    carrying one.
    """

    partitions: tuple[ReleasePartition, ...]
    artifact: StoredArtifact
    acquired_at: datetime
    source_url: str
    response: ResponseMetadata
    redirects: tuple[RedirectHop, ...] = ()
    conflict: BronzeConflict = BronzeConflict.NEW
    manifest_version: int = BRONZE_MANIFEST_VERSION
    tool_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.partitions, tuple) or not self.partitions:
            raise ValueError("partitions must be a non-empty tuple")
        if not all(isinstance(entry, ReleasePartition) for entry in self.partitions):
            raise ValueError("partitions must be a tuple of ReleasePartition")
        if len(set(self.partitions)) != len(self.partitions):
            raise ValueError("partitions must be distinct")
        if not isinstance(self.artifact, StoredArtifact):
            raise ValueError("artifact must be a StoredArtifact")
        if not isinstance(self.acquired_at, datetime):
            raise ValueError("acquired_at must be a datetime")
        # Timezone-aware, in any zone.  Awareness is what makes the instant
        # unambiguous; requiring UTC specifically would reject a perfectly
        # well-defined time for being written down in the wrong words, and
        # serialization normalizes to UTC anyway.  A naive instant is the real
        # defect: it cannot be reproduced, because it does not say when.
        if self.acquired_at.tzinfo is None or self.acquired_at.utcoffset() is None:
            raise ValueError("acquired_at must be timezone-aware, so the instant is unambiguous")
        if not isinstance(self.response, ResponseMetadata):
            raise ValueError("response must be a ResponseMetadata")
        if not isinstance(self.redirects, tuple) or not all(
            isinstance(hop, RedirectHop) for hop in self.redirects
        ):
            raise ValueError("redirects must be a tuple of RedirectHop")
        if not isinstance(self.conflict, BronzeConflict):
            raise ValueError("conflict must be a BronzeConflict")
        if (
            isinstance(self.manifest_version, bool)
            or not isinstance(self.manifest_version, int)
            or self.manifest_version != BRONZE_MANIFEST_VERSION
        ):
            raise ValueError(f"manifest_version must be the int {BRONZE_MANIFEST_VERSION}")
        # Provenance obeys the acquisition boundary's rule, restated because a
        # manifest may be built by a caller that never used that boundary.
        from property_tax_application.acquisition import sanitize_url

        if self.source_url != sanitize_url(self.source_url):
            raise ValueError(
                "source_url must be sanitized: userinfo, query, and fragment are removed, "
                "because a manifest outlives any credential a request URL carried"
            )
        if not isinstance(self.tool_versions, Mapping):
            raise ValueError("tool_versions must be a mapping")
        for name, version in self.tool_versions.items():
            if not isinstance(name, str) or not isinstance(version, str):
                raise ValueError("tool_versions must map str to str")
            _require_identifier(name, f"tool_versions key {name!r}")
        object.__setattr__(self, "tool_versions", MappingProxyType(dict(self.tool_versions)))

    @classmethod
    def from_acquisition(
        cls,
        acquired: AcquiredArtifact,
        *,
        partitions: tuple[ReleasePartition, ...],
        acquired_at: datetime,
        conflict: BronzeConflict = BronzeConflict.NEW,
        tool_versions: Mapping[str, str] | None = None,
    ) -> ReleaseManifest:
        """Build a manifest from what the acquisition boundary established.

        The checksum, byte count, locator, and provenance all come from the
        `AcquiredArtifact` rather than being recomputed: recomputing would
        introduce a second answer to a question already settled, and the two
        could disagree.
        """

        return cls(
            partitions=partitions,
            artifact=StoredArtifact(
                locator=acquired.locator,
                sha256=acquired.sha256,
                byte_count=acquired.byte_count,
                media_type=acquired.media_type,
            ),
            acquired_at=acquired_at,
            source_url=acquired.final_url,
            response=acquired.response,
            redirects=acquired.redirects,
            conflict=conflict,
            tool_versions=dict(tool_versions or {}),
        )


@runtime_checkable
class BronzeStore(Protocol):
    """Where manifests are recorded, and how a repeat identity is judged.

    Distinct from `ArtifactSink`, which takes the bytes.  The sink makes an
    object durable; the store decides what that object *is* relative to what
    was stored before, and records it.
    """

    def classify(self, partitions: tuple[ReleasePartition, ...], sha256: str) -> BronzeConflict:
        """Judge this identity and checksum against what is already stored.

        Called before the manifest is written, so a diverged release can be
        flagged rather than discovered afterwards.
        """
        ...

    def record(self, manifest: ReleaseManifest) -> str:
        """Persist the manifest immutably and return its locator.

        SHALL NOT overwrite a manifest already recorded for this artifact
        version.  Bronze keeps what it was given; a correction is a new version,
        not an edit.
        """
        ...
