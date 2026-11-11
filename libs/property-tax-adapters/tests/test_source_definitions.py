"""The production source registry carries explicit, non-secret media contracts."""

from dataclasses import fields

from property_tax_adapters.sources.texas.collin import COLLIN_SOURCE
from property_tax_adapters.sources.texas.dallas import DALLAS_SOURCE
from property_tax_adapters.sources.texas.denton import DENTON_SOURCE
from property_tax_adapters.sources.texas.ellis import ELLIS_SOURCE
from property_tax_adapters.sources.texas.rockwall import ROCKWALL_SOURCE
from property_tax_adapters.sources.texas.tarrant import TARRANT_SOURCE

SOURCES = (
    COLLIN_SOURCE,
    DALLAS_SOURCE,
    DENTON_SOURCE,
    ELLIS_SOURCE,
    ROCKWALL_SOURCE,
    TARRANT_SOURCE,
)


def test_all_six_counties_explicitly_expect_their_archive_media_type() -> None:
    expected = {
        "collin": ("application/zip",),
        "dallas": ("application/zip",),
        "denton": ("application/zip",),
        "ellis": ("application/zip",),
        "rockwall": ("application/zip",),
        "tarrant": ("application/zip",),
    }

    assert {source.county.slug.value: source.expected_media_types for source in SOURCES} == expected


def test_source_definitions_have_no_place_for_credentials() -> None:
    names = {field.name for field in fields(COLLIN_SOURCE)}

    assert names == {
        "county",
        "official_url",
        "acquisition_method",
        "parser_id",
        "expected_media_types",
        "production_ready",
    }
    assert all("@" not in source.official_url for source in SOURCES)
