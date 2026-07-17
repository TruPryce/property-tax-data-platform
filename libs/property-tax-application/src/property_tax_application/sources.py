"""Source definitions shared by county adapter implementations."""

from dataclasses import dataclass
from enum import StrEnum

from property_tax_domain import County


class AcquisitionMethod(StrEnum):
    """Supported high-level acquisition strategies."""

    BULK_ZIP = "bulk_zip"
    OPEN_DATA_API = "open_data_api"
    FIXED_WIDTH = "fixed_width"
    DATA_EXTRACT = "data_extract"
    ARCGIS = "arcgis"
    GIS_SHAPEFILE = "gis_shapefile"
    OWNERSHIP_EXPORT = "ownership_export"


@dataclass(frozen=True, slots=True)
class CountySourceDefinition:
    """Non-secret metadata used to select and profile a county source."""

    county: County
    official_url: str
    acquisition_method: AcquisitionMethod
    parser_id: str
    production_ready: bool = False

    def __post_init__(self) -> None:
        if not self.official_url.startswith("https://"):
            raise ValueError("Official source URLs must use HTTPS")
        if not self.parser_id:
            raise ValueError("A parser identifier is required")
