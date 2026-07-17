"""Tarrant Appraisal District source metadata."""

from property_tax_application import AcquisitionMethod, CountySourceDefinition
from property_tax_domain import CountySlug, county_by_slug

TARRANT_SOURCE = CountySourceDefinition(
    county=county_by_slug(CountySlug.TARRANT),
    official_url="https://www.tad.org/",
    acquisition_method=AcquisitionMethod.FIXED_WIDTH,
    parser_id="texas.tarrant.fixed-width-v1",
)
