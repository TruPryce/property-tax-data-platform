"""Source definitions and the application-owned source registry port."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from property_tax_domain import County, Jurisdiction, ReleaseKind

__all__ = [
    "MAX_EXPECTED_MEDIA_TYPES",
    "MAX_MEDIA_TYPE_CHARS",
    "AcquisitionMethod",
    "CountySourceDefinition",
    "SourceRegistry",
    "UnsupportedSource",
]

MAX_EXPECTED_MEDIA_TYPES: Final = 16
MAX_MEDIA_TYPE_CHARS: Final = 256

_MEDIA_TYPE: Final = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z")


class AcquisitionMethod(StrEnum):
    """Supported high-level acquisition strategies."""

    BULK_ZIP = "bulk_zip"
    OPEN_DATA_API = "open_data_api"
    FIXED_WIDTH = "fixed_width"
    DATA_EXTRACT = "data_extract"
    ARCGIS = "arcgis"
    GIS_SHAPEFILE = "gis_shapefile"
    OWNERSHIP_EXPORT = "ownership_export"


class UnsupportedSource(LookupError):  # noqa: N818 - contract name
    """A jurisdiction or caller-supplied release kind is not registered."""

    def __init__(
        self,
        jurisdiction: Jurisdiction,
        release_kind: ReleaseKind | None = None,
    ) -> None:
        if not isinstance(jurisdiction, Jurisdiction):
            raise ValueError(
                f"jurisdiction must be a Jurisdiction, got {type(jurisdiction).__name__}"
            )
        if release_kind is not None and not isinstance(release_kind, ReleaseKind):
            raise ValueError(
                f"release_kind must be a ReleaseKind or None, got {type(release_kind).__name__}"
            )
        self.jurisdiction = jurisdiction
        self.release_kind = release_kind
        requested = jurisdiction.rendered
        if release_kind is not None:
            requested = f"{requested}/{release_kind.value}"
        super().__init__(f"no source is registered for {requested}")


@dataclass(frozen=True, slots=True)
class CountySourceDefinition:
    """Non-secret metadata used to select and profile a county source."""

    county: County
    official_url: str
    acquisition_method: AcquisitionMethod
    parser_id: str
    expected_media_types: tuple[str, ...]
    production_ready: bool = False

    def __post_init__(self) -> None:
        if not self.official_url.startswith("https://"):
            raise ValueError("Official source URLs must use HTTPS")
        if not self.parser_id:
            raise ValueError("A parser identifier is required")
        if not isinstance(self.expected_media_types, tuple):
            raise ValueError("expected_media_types must be a tuple")
        if not 1 <= len(self.expected_media_types) <= MAX_EXPECTED_MEDIA_TYPES:
            raise ValueError(
                f"expected_media_types must contain 1 to {MAX_EXPECTED_MEDIA_TYPES} media types"
            )
        if len(set(self.expected_media_types)) != len(self.expected_media_types):
            raise ValueError("expected_media_types must not contain duplicates")
        for media_type in self.expected_media_types:
            if not isinstance(media_type, str):
                raise ValueError("each expected media type must be a str")
            if len(media_type) > MAX_MEDIA_TYPE_CHARS:
                raise ValueError(
                    f"an expected media type exceeds {MAX_MEDIA_TYPE_CHARS} characters"
                )
            if _MEDIA_TYPE.fullmatch(media_type) is None:
                raise ValueError(
                    "expected media types must be lowercase type/subtype values without parameters"
                )


@runtime_checkable
class SourceRegistry(Protocol):
    """Resolve county source metadata without performing acquisition."""

    def resolve(
        self,
        jurisdiction: Jurisdiction,
        release_kind: ReleaseKind | None = None,
    ) -> CountySourceDefinition:
        """Return one definition or refuse an unsupported request."""
        ...

    def validate_release_kind(
        self,
        jurisdiction: Jurisdiction,
        release_kind: ReleaseKind,
    ) -> None:
        """Validate a release kind established after source content was parsed."""
        ...
