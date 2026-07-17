"""Rockwall public partial-GIS source metadata."""

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

ROCKWALL_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.ROCKWALL),
    official_url="https://www.rockwallcad.com/gis-data",
    acquisition_method=AcquisitionMethod.GIS_SHAPEFILE,
    parser_id="texas.rockwall.gis-shapefile-partial-v1",
)
