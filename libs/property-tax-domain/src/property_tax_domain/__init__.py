"""Domain types for the Property Tax Data Platform."""

from property_tax_domain.counties import INITIAL_COUNTIES, County, CountySlug, county_by_slug

__all__ = ["INITIAL_COUNTIES", "County", "CountySlug", "county_by_slug"]
