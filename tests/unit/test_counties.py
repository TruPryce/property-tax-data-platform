"""Tests for the initial county cohort and source registry."""

import json

from property_tax_adapters.sources.texas import all_sources, source_for_county
from property_tax_domain import INITIAL_COUNTIES, CountySlug
from property_tax_ingestion.cli import main


def test_initial_counties_have_unique_slugs_and_fips() -> None:
    assert len(INITIAL_COUNTIES) == 6
    assert len({county.slug for county in INITIAL_COUNTIES}) == 6
    assert len({county.fips for county in INITIAL_COUNTIES}) == 6


def test_registry_covers_every_initial_county() -> None:
    sources = all_sources()

    assert tuple(source.county for source in sources) == INITIAL_COUNTIES
    assert all(
        source_for_county(county.slug) is source
        for county, source in zip(INITIAL_COUNTIES, sources, strict=True)
    )
    assert all(not source.production_ready for source in sources)


def test_counties_command_reports_the_registry(capsys: object) -> None:
    assert main(["counties"]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert [item["slug"] for item in payload] == [slug.value for slug in CountySlug]
    assert {item["fips"] for item in payload} == {county.fips for county in INITIAL_COUNTIES}
