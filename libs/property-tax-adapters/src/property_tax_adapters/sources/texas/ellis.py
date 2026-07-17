"""Ellis Appraisal District certified-roll source metadata."""

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

ELLIS_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.ELLIS),
    official_url="https://www.elliscad.com/appraisal-data-export",
    acquisition_method=AcquisitionMethod.FIXED_WIDTH,
    parser_id="texas.ellis.pacs-fixed-width-v1",
)
