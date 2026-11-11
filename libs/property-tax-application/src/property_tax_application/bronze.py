"""What Bronze records about an artifact, and what a store owes.

Bronze is immutable: the original bytes and a manifest describing them, written
once and never rewritten.  The manifest is the durable half — an object without
one cannot be found, verified, or attributed, and an object whose manifest was
written before the bytes were verified would claim a completeness the transfer
never reached.

Nothing here performs I/O. `BronzeStore` is the port the S3 adapter implements;
`ManifestIndex` is the separate queryable index a run binds to. The contracts
live where callers and both implementations can see them rather than inside one
storage backend's control flow.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from property_tax_domain import ReleaseIdentity

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
    "ManifestIndex",
    "ManifestRef",
    "ReleaseManifest",
    "ReleasePartition",
    "StoredArtifact",
]

#: The manifest schema this contract writes.  Pinned, so a consumer can tell
#: which shape it is reading rather than inferring it from the fields present.
BRONZE_MANIFEST_VERSION: int = 2

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_JURISDICTION_PATTERN = re.compile(r"[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class BronzeConflict(StrEnum):
    """What a store finds when asked about a release identity and a checksum.

    Three outcomes and no fourth, because the interesting case is the last one:
    the same release identity arriving with different bytes is not an error to
    retry and not a duplicate to ignore.

    Derived at read time and never stored on a manifest.  A stored verdict is a
    claim about what else existed when some writer looked, and two writers can
    both look, both see nothing, and both write — so the only honest answer is
    computed from what durably exists when the question is asked.
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
    source_as_of: datetime | None = None

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
        if self.source_as_of is not None:
            if not isinstance(self.source_as_of, datetime):
                raise ValueError("source_as_of must be a datetime or None")
            if self.source_as_of.tzinfo is None or self.source_as_of.utcoffset() is None:
                raise ValueError("source_as_of must be timezone-aware when present")


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

    jurisdiction: str
    artifact: StoredArtifact
    acquired_at: datetime
    source_url: str
    response: ResponseMetadata
    partitions: tuple[ReleasePartition, ...] = ()
    redirects: tuple[RedirectHop, ...] = ()
    manifest_version: int = BRONZE_MANIFEST_VERSION
    tool_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _JURISDICTION_PATTERN.fullmatch(self.jurisdiction) is None:
            raise ValueError(
                "jurisdiction must be a lowercase state prefix, a hyphen, and a county slug"
            )
        if not isinstance(self.partitions, tuple):
            raise ValueError("partitions must be a tuple")
        if not all(isinstance(entry, ReleasePartition) for entry in self.partitions):
            raise ValueError("partitions must be a tuple of ReleasePartition")
        partition_grains = {
            (entry.jurisdiction_code, entry.tax_year, entry.release_kind)
            for entry in self.partitions
        }
        if len(partition_grains) != len(self.partitions):
            raise ValueError("partitions must be distinct by logical release")
        if any(entry.jurisdiction_code != self.jurisdiction for entry in self.partitions):
            raise ValueError("every partition must name the manifest jurisdiction")
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

    @property
    def acquisition_evidence(self) -> tuple[object, ...]:
        """The retained evidence that decides acquisition equivalence.

        Partitions are deliberately absent because they attach after acquisition.
        The artifact contributes only its content identity; locator, byte count,
        and media type are artifact-grain consistency evidence rather than facts
        identifying another acquisition.
        """

        return (
            self.jurisdiction,
            self.artifact.sha256,
            self.acquired_at.astimezone(UTC).isoformat(),
            self.source_url,
            self.response.status,
            tuple(sorted(self.response.headers.items())),
            tuple((hop.from_url, hop.to_url, hop.status) for hop in self.redirects),
            self.manifest_version,
            tuple(sorted(self.tool_versions.items())),
        )

    def same_acquisition_as(self, other: object) -> bool:
        """Whether two recordings retain indistinguishable acquisition evidence."""

        return isinstance(other, ReleaseManifest) and (
            self.acquisition_evidence == other.acquisition_evidence
        )

    @classmethod
    def from_acquisition(
        cls,
        acquired: AcquiredArtifact,
        *,
        jurisdiction: str,
        acquired_at: datetime,
        partitions: tuple[ReleasePartition, ...] = (),
        tool_versions: Mapping[str, str] | None = None,
    ) -> ReleaseManifest:
        """Build a manifest from what the acquisition boundary established.

        The checksum, byte count, locator, and provenance all come from the
        `AcquiredArtifact` rather than being recomputed: recomputing would
        introduce a second answer to a question already settled, and the two
        could disagree.
        """

        return cls(
            jurisdiction=jurisdiction,
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
            tool_versions=dict(tool_versions or {}),
        )


@dataclass(frozen=True, slots=True)
class ManifestRef:
    """An opaque locator for one acquisition manifest in the queryable index.

    Comparable for equality and carrying no ordering or business-identity
    meaning. The value is generated where the manifest is indexed; callers do
    not derive it from an object-store locator, key, or checksum.
    """

    value: str | int | tuple[str | int, ...]

    def __post_init__(self) -> None:
        from property_tax_application.runs import require_locator_value

        require_locator_value(self.value)

    def _no_ordering(self, other: object) -> bool:
        raise TypeError(
            "ManifestRef carries no ordering: it is an opaque locator, not business identity"
        )

    __lt__ = _no_ordering
    __le__ = _no_ordering
    __gt__ = _no_ordering
    __ge__ = _no_ordering


@runtime_checkable
class ManifestIndex(Protocol):
    """Queryable acquisition records and their later release partitions.

    This is separate from `BronzeStore`: that port writes immutable evidence to
    object storage and returns a storage locator, while this one returns the
    persistence-generated reference a run binds to. The reference is derivable
    from neither the storage locator nor the artifact checksum.
    """

    def register(self, manifest: ReleaseManifest) -> ManifestRef:
        """Record one acquisition idempotently by its acquisition evidence."""
        ...

    def attach_partition(self, reference: ManifestRef, partition: ReleasePartition) -> None:
        """Associate a later-established partition with one acquisition."""
        ...

    def partition_for(
        self, reference: ManifestRef, release: ReleaseIdentity
    ) -> ReleasePartition | None:
        """Return recorded evidence, or `None` when that release was not attached.

        A returned partition whose `source_as_of` is `None` is distinct from no
        returned partition: the first records absence, while the second says the
        release is not part of this acquisition. Reading changes nothing.
        """
        ...


@runtime_checkable
class BronzeStore(Protocol):
    """Where manifests are recorded, and how a repeat identity is judged.

    Distinct from `ArtifactSink`, which takes the bytes.  The sink makes an
    object durable; the store decides what that object *is* relative to what
    was stored before, and records it.
    """

    def classify(self, partition: ReleasePartition, sha256: str) -> BronzeConflict:
        """Judge this checksum against every artifact the partition references.

        A read-time query over durable state, not a verdict to be persisted.
        One partition rather than a tuple, because divergence is a property of a
        single release identity and an artifact may serve several.
        """
        ...

    def record(self, manifest: ReleaseManifest) -> str:
        """Persist the manifest and its partition references, and return its locator.

        SHALL NOT overwrite anything already recorded.  Bronze keeps what it was
        given; a correction is a new artifact version, not an edit.
        """
        ...

    def reference_partition(self, partition: ReleasePartition, sha256: str) -> str:
        """Attach a partition discovered after acquisition to an existing artifact.

        This association is artifact-grain because the checksum identifies
        content. `ManifestIndex.attach_partition` separately associates the
        same evidence with the acquisition a run binds to.
        """
        ...
