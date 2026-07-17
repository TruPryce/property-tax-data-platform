"""Registry for the initial Texas county source cohort."""

from property_tax_application import CountySourceDefinition
from property_tax_domain import CountySlug

from property_tax_adapters.sources.texas.collin import COLLIN_SOURCE
from property_tax_adapters.sources.texas.dallas import DALLAS_SOURCE
from property_tax_adapters.sources.texas.denton import DENTON_SOURCE
from property_tax_adapters.sources.texas.ellis import ELLIS_SOURCE
from property_tax_adapters.sources.texas.rockwall import ROCKWALL_SOURCE
from property_tax_adapters.sources.texas.tarrant import TARRANT_SOURCE

_SOURCES: tuple[CountySourceDefinition, ...] = (
    DALLAS_SOURCE,
    COLLIN_SOURCE,
    TARRANT_SOURCE,
    DENTON_SOURCE,
    ROCKWALL_SOURCE,
    ELLIS_SOURCE,
)

_SOURCES_BY_COUNTY = {source.county.slug: source for source in _SOURCES}
if len(_SOURCES_BY_COUNTY) != len(_SOURCES):
    raise RuntimeError("County source registry contains duplicate county slugs")


def all_sources() -> tuple[CountySourceDefinition, ...]:
    """Return every source definition in deterministic cohort order."""

    return _SOURCES


def source_for_county(county: CountySlug | str) -> CountySourceDefinition:
    """Resolve a county source definition by stable slug."""

    return _SOURCES_BY_COUNTY[CountySlug(county)]
