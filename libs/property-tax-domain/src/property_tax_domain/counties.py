"""County identities included in the initial platform cohort."""

from dataclasses import dataclass
from enum import StrEnum


class CountySlug(StrEnum):
    """Stable slugs used in configuration, object keys, and task mapping."""

    DALLAS = "dallas"
    COLLIN = "collin"
    TARRANT = "tarrant"
    DENTON = "denton"
    ROCKWALL = "rockwall"
    ELLIS = "ellis"


@dataclass(frozen=True, slots=True)
class County:
    """A county-qualified appraisal jurisdiction."""

    slug: CountySlug
    name: str
    state_code: str
    fips: str

    def __post_init__(self) -> None:
        if self.state_code != "TX":
            raise ValueError("The initial cohort only supports Texas counties")
        if len(self.fips) != 5 or not self.fips.isdigit():
            raise ValueError("County FIPS must contain exactly five digits")


INITIAL_COUNTIES: tuple[County, ...] = (
    County(CountySlug.DALLAS, "Dallas", "TX", "48113"),
    County(CountySlug.COLLIN, "Collin", "TX", "48085"),
    County(CountySlug.TARRANT, "Tarrant", "TX", "48439"),
    County(CountySlug.DENTON, "Denton", "TX", "48121"),
    County(CountySlug.ROCKWALL, "Rockwall", "TX", "48397"),
    County(CountySlug.ELLIS, "Ellis", "TX", "48139"),
)

_COUNTIES_BY_SLUG = {county.slug: county for county in INITIAL_COUNTIES}


def county_by_slug(slug: CountySlug | str) -> County:
    """Return one initial county by its stable slug."""

    return _COUNTIES_BY_SLUG[CountySlug(slug)]
