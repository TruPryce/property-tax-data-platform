"""Bounded discovery evidence and the one release-identity promotion seam.

Discovery observes one jurisdiction and preserves only the facts needed to
decide whether an artifact should be acquired. County parsing remains outside
this module; parsed content produces the same ``LogicalReleaseEvidence`` as a
publisher page and passes it through the same ``promote`` function.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from property_tax_domain import (
    ArtifactIdentity,
    Jurisdiction,
    ReleaseIdentity,
    ReleaseKind,
)
from property_tax_domain.release import (
    TAX_YEAR_MAX,
    TAX_YEAR_MIN,
    require_identifier,
)

from property_tax_application.acquisition import (
    MAX_LOCATOR_CHARS,
    ResponseMetadata,
    sanitize_url,
)
from property_tax_application.runs import MAX_FIELD_CHARS

__all__ = [
    "MAX_LOGICAL_RELEASES",
    "IncompleteReleaseIdentity",
    "LogicalReleaseEvidence",
    "PageEvidence",
    "ReleaseDiscovery",
    "SourceCandidate",
    "UnchangedRelease",
    "promote",
]

MAX_LOGICAL_RELEASES: Final = 256


def _require_aware(value: datetime | None, field_name: str, *, optional: bool) -> None:
    if value is None:
        if optional:
            return
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _require_sanitized_locator(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty str")
    if len(value) > MAX_LOCATOR_CHARS:
        raise ValueError(f"{field_name} must be at most {MAX_LOCATOR_CHARS} characters")
    if value != sanitize_url(value):
        raise ValueError(
            f"{field_name} must be sanitized and carry no userinfo, query, or fragment"
        )


def _require_optional_page_fact(value: object, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank str or None")
    if len(value) > MAX_FIELD_CHARS:
        raise ValueError(f"{field_name} must be at most {MAX_FIELD_CHARS} characters")


@dataclass(frozen=True, slots=True)
class PageEvidence:
    """The bounded facts that located an artifact on one publisher page."""

    observed_at: datetime
    page_url: str
    rendered: bool
    section_heading: str | None = None
    link_label: str | None = None
    directory_path: str | None = None
    published_label: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at", optional=False)
        _require_sanitized_locator(self.page_url, "page_url")
        if not isinstance(self.rendered, bool):
            raise ValueError("rendered must be a bool")
        for field_name in (
            "section_heading",
            "link_label",
            "directory_path",
            "published_label",
        ):
            _require_optional_page_fact(getattr(self, field_name), field_name)
        if all(
            getattr(self, field_name) is None
            for field_name in (
                "section_heading",
                "link_label",
                "directory_path",
                "published_label",
            )
        ):
            raise ValueError(
                "page evidence must carry at least one locating fact beyond "
                "observed_at and page_url"
            )


@dataclass(frozen=True, slots=True)
class LogicalReleaseEvidence:
    """The canonical identity facts established for one logical release."""

    jurisdiction: Jurisdiction | None = None
    tax_year: int | None = None
    release_kind: ReleaseKind | None = None
    release_identifier: str | None = None
    source_as_of: datetime | None = None

    def __post_init__(self) -> None:
        if self.jurisdiction is not None and not isinstance(self.jurisdiction, Jurisdiction):
            raise ValueError(
                "jurisdiction must be a Jurisdiction or None, got "
                f"{type(self.jurisdiction).__name__}"
            )
        if self.tax_year is not None:
            if isinstance(self.tax_year, bool) or not isinstance(self.tax_year, int):
                raise ValueError("tax_year must be an int or None")
            if not TAX_YEAR_MIN <= self.tax_year <= TAX_YEAR_MAX:
                raise ValueError(f"tax_year must be {TAX_YEAR_MIN} through {TAX_YEAR_MAX} or None")
        if self.release_kind is not None and not isinstance(self.release_kind, ReleaseKind):
            raise ValueError(
                "release_kind must be a ReleaseKind or None, got "
                f"{type(self.release_kind).__name__}"
            )
        if self.release_identifier is not None:
            require_identifier(self.release_identifier, "release_identifier")
        _require_aware(self.source_as_of, "source_as_of", optional=True)


class IncompleteReleaseIdentity(ValueError):  # noqa: N818 - contract name
    """Promotion was attempted before every canonical component was established."""

    def __init__(self, missing_components: tuple[str, ...]) -> None:
        self.missing_components = missing_components
        super().__init__(
            "release identity is incomplete; missing: " + ", ".join(missing_components)
        )


def promote(evidence: LogicalReleaseEvidence) -> ReleaseIdentity:
    """Promote complete page- or parser-established evidence without inference."""

    if not isinstance(evidence, LogicalReleaseEvidence):
        raise ValueError(f"evidence must be LogicalReleaseEvidence, got {type(evidence).__name__}")
    missing = tuple(
        field_name
        for field_name in (
            "jurisdiction",
            "tax_year",
            "release_kind",
            "release_identifier",
        )
        if getattr(evidence, field_name) is None
    )
    if missing:
        raise IncompleteReleaseIdentity(missing)
    return ReleaseIdentity(
        jurisdiction=evidence.jurisdiction,  # type: ignore[arg-type]
        tax_year=evidence.tax_year,  # type: ignore[arg-type]
        release_kind=evidence.release_kind,  # type: ignore[arg-type]
        release_identifier=evidence.release_identifier,  # type: ignore[arg-type]
    )


def _require_candidate_fields(
    jurisdiction: object,
    source_locator: object,
    remote_metadata: object,
    source_as_of: datetime | None,
    page_evidence: object,
) -> None:
    if not isinstance(jurisdiction, Jurisdiction):
        raise ValueError(f"jurisdiction must be a Jurisdiction, got {type(jurisdiction).__name__}")
    _require_sanitized_locator(source_locator, "source_locator")
    if not isinstance(remote_metadata, ResponseMetadata):
        raise ValueError(
            f"remote_metadata must be ResponseMetadata, got {type(remote_metadata).__name__}"
        )
    _require_aware(source_as_of, "source_as_of", optional=True)
    if not isinstance(page_evidence, PageEvidence):
        raise ValueError(f"page_evidence must be PageEvidence, got {type(page_evidence).__name__}")


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    """One observed source that should be acquired."""

    jurisdiction: Jurisdiction
    source_locator: str
    remote_metadata: ResponseMetadata
    source_as_of: datetime | None
    page_evidence: PageEvidence
    logical_releases: tuple[LogicalReleaseEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_candidate_fields(
            self.jurisdiction,
            self.source_locator,
            self.remote_metadata,
            self.source_as_of,
            self.page_evidence,
        )
        if not isinstance(self.logical_releases, tuple) or not all(
            isinstance(evidence, LogicalReleaseEvidence) for evidence in self.logical_releases
        ):
            raise ValueError("logical_releases must be a tuple of LogicalReleaseEvidence")
        if len(self.logical_releases) > MAX_LOGICAL_RELEASES:
            raise ValueError(
                f"logical_releases must contain no more than {MAX_LOGICAL_RELEASES} entries"
            )
        normalized: list[LogicalReleaseEvidence] = []
        for evidence in self.logical_releases:
            if evidence.jurisdiction != self.jurisdiction:
                raise ValueError("logical release jurisdiction disagrees with the candidate")
            if evidence.source_as_of is None and self.source_as_of is not None:
                evidence = replace(evidence, source_as_of=self.source_as_of)
            normalized.append(evidence)
        object.__setattr__(self, "logical_releases", tuple(normalized))


@dataclass(frozen=True, slots=True)
class UnchangedRelease:
    """An already-acquired artifact whose remote representation is unchanged."""

    jurisdiction: Jurisdiction
    source_locator: str
    remote_metadata: ResponseMetadata
    source_as_of: datetime | None
    page_evidence: PageEvidence
    artifact: ArtifactIdentity

    def __post_init__(self) -> None:
        _require_candidate_fields(
            self.jurisdiction,
            self.source_locator,
            self.remote_metadata,
            self.source_as_of,
            self.page_evidence,
        )
        if not isinstance(self.artifact, ArtifactIdentity):
            raise ValueError(
                f"artifact must be an ArtifactIdentity, got {type(self.artifact).__name__}"
            )


@runtime_checkable
class ReleaseDiscovery(Protocol):
    """Observe one jurisdiction and decide whether it needs acquisition."""

    def discover(self, jurisdiction: Jurisdiction) -> SourceCandidate | UnchangedRelease:
        """Return one result for one publisher; never fan out to a cohort."""
        ...
