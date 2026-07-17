"""Collin Central Appraisal District source metadata."""

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

COLLIN_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.COLLIN),
    official_url="https://collincad.org/open-data-portal/",
    acquisition_method=AcquisitionMethod.OPEN_DATA_API,
    parser_id="texas.collin.open-data-v1",
)
