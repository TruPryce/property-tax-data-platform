"""Task-local falsification for source registry contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from property_tax_adapters.sources.texas.collin import COLLIN_SOURCE
from property_tax_adapters.sources.texas.dallas import DALLAS_SOURCE
from property_tax_application.sources import (
    CountySourceDefinition,
    SourceRegistry,
    UnsupportedSource,
)
from property_tax_domain import Jurisdiction, ReleaseKind


def jurisdiction(county: str) -> Jurisdiction:
    fips = {"collin": "48085", "dallas": "48113"}[county]
    return Jurisdiction(state_code="tx", county_slug=county, county_fips=fips)


@dataclass
class InMemorySourceRegistry:
    definitions: dict[Jurisdiction, CountySourceDefinition]
    supported_kinds: dict[Jurisdiction, frozenset[ReleaseKind]]
    network_calls: int = 0

    def resolve(
        self,
        requested: Jurisdiction,
        release_kind: ReleaseKind | None = None,
    ) -> CountySourceDefinition:
        definition = self.definitions.get(requested)
        if definition is None:
            raise UnsupportedSource(requested, release_kind)
        if release_kind is not None:
            self.validate_release_kind(requested, release_kind)
        return definition

    def validate_release_kind(
        self,
        requested: Jurisdiction,
        release_kind: ReleaseKind,
    ) -> None:
        if requested not in self.definitions or release_kind not in self.supported_kinds[requested]:
            raise UnsupportedSource(requested, release_kind)


def registry() -> InMemorySourceRegistry:
    collin = jurisdiction("collin")
    return InMemorySourceRegistry(
        definitions={collin: COLLIN_SOURCE},
        supported_kinds={collin: frozenset({ReleaseKind.CURRENT, ReleaseKind.CERTIFIED})},
    )


def test_a_registered_jurisdiction_resolves_without_a_release_kind_or_network() -> None:
    sources = registry()

    resolved = sources.resolve(jurisdiction("collin"))

    assert resolved is COLLIN_SOURCE
    assert sources.network_calls == 0
    assert isinstance(sources, SourceRegistry)


def test_an_unregistered_jurisdiction_is_refused_by_name() -> None:
    sources = registry()
    requested = jurisdiction("dallas")

    with pytest.raises(UnsupportedSource, match="tx-dallas") as caught:
        sources.resolve(requested)

    assert caught.value.jurisdiction == requested
    assert caught.value.release_kind is None
    assert sources.network_calls == 0


def test_a_caller_supplied_unsupported_kind_is_refused_before_network() -> None:
    sources = registry()

    with pytest.raises(UnsupportedSource, match="tx-collin/supplemental") as caught:
        sources.resolve(jurisdiction("collin"), ReleaseKind.SUPPLEMENTAL)

    assert caught.value.release_kind is ReleaseKind.SUPPLEMENTAL
    assert sources.network_calls == 0


def test_a_kind_learned_from_content_is_validated_after_resolution() -> None:
    sources = registry()
    requested = jurisdiction("collin")

    assert sources.resolve(requested) is COLLIN_SOURCE
    sources.validate_release_kind(requested, ReleaseKind.CERTIFIED)
    with pytest.raises(UnsupportedSource):
        sources.validate_release_kind(requested, ReleaseKind.PROPOSED)

    assert sources.network_calls == 0


def test_expected_media_types_are_bounded_and_required() -> None:
    with pytest.raises(ValueError, match="1 to"):
        CountySourceDefinition(
            county=DALLAS_SOURCE.county,
            official_url=DALLAS_SOURCE.official_url,
            acquisition_method=DALLAS_SOURCE.acquisition_method,
            parser_id=DALLAS_SOURCE.parser_id,
            expected_media_types=(),
        )
    with pytest.raises(ValueError, match="lowercase"):
        CountySourceDefinition(
            county=DALLAS_SOURCE.county,
            official_url=DALLAS_SOURCE.official_url,
            acquisition_method=DALLAS_SOURCE.acquisition_method,
            parser_id=DALLAS_SOURCE.parser_id,
            expected_media_types=("Application/ZIP",),
        )
