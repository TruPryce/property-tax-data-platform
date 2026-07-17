"""Dallas Central Appraisal District source metadata."""

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

DALLAS_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.DALLAS),
    official_url="https://www.dallascad.org/DataProducts.aspx",
    acquisition_method=AcquisitionMethod.BULK_ZIP,
    parser_id="texas.dallas.dcad-delimited-v1",
)
