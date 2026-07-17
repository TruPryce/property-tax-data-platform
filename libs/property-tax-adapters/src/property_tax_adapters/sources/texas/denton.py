"""Denton Central Appraisal District source metadata."""

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

DENTON_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.DENTON),
    official_url="https://dentoncad.net/data/_uploaded/files/datafiles/",
    acquisition_method=AcquisitionMethod.FIXED_WIDTH,
    parser_id="texas.denton.pacs-fixed-width-v1",
)
