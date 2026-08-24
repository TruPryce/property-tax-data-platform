"""Which appraisal jurisdiction a fact came from.

Identity is the state and the county slug — the `tx-collin` form every storage
and provenance layer in this platform already holds. `county_fips` is required
registry metadata carried alongside it, not a second identity: a platform that
identified a county by slug in five places and by FIPS in a sixth would have two
identifiers for one concept, which is the defect this vocabulary exists to
remove.

Caller-supplied identity is never rewritten. An uppercase state code is refused
rather than folded, so a caller cannot receive an identity other than the one
they asked for. The registry stores `TX`, and the fold happens on that side,
where the uppercase datum legitimately lives.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from property_tax_domain.counties import County, county_by_slug

__all__ = ["Jurisdiction"]

_STATE_CODE: Final = re.compile(r"[a-z]{2}\Z")
_COUNTY_SLUG: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_COUNTY_FIPS: Final = re.compile(r"[0-9]{5}\Z")


@dataclass(frozen=True, slots=True)
class Jurisdiction:
    """A county-qualified appraisal jurisdiction, identified by state and slug.

    `county_fips` is declared `compare=False`, which keeps it out of equality
    and out of the generated hash. That exclusion is enumerable — a caller can
    read which fields participate — rather than asserted in prose, because a
    jurisdiction whose FIPS disagrees with its slug cannot be constructed and so
    the exclusion has no reachable counterexample to demonstrate.
    """

    state_code: str
    county_slug: str
    county_fips: str = field(compare=False)

    def __post_init__(self) -> None:
        _require_match(self.state_code, _STATE_CODE, "state_code", "two lowercase ASCII letters")
        _require_match(
            self.county_slug,
            _COUNTY_SLUG,
            "county_slug",
            "lowercase alphanumeric segments joined by single hyphens",
        )
        _require_match(self.county_fips, _COUNTY_FIPS, "county_fips", "exactly five digits")
        self._require_registry_agreement()

    def _require_registry_agreement(self) -> None:
        """Refuse metadata the registry contradicts.

        The registry is `counties.py` and is not duplicated here. A slug it does
        not describe is refused rather than admitted with an unverifiable FIPS,
        because the whole point of carrying the FIPS is that something checked it.
        """

        try:
            county: County = county_by_slug(self.county_slug)
        except (KeyError, ValueError) as error:
            raise ValueError(
                f"county_slug {self.county_slug!r} is not in the county registry"
            ) from error
        # Folded on the registry side: the registry's `TX` stays valid where it
        # lives, and the caller's `tx` is compared rather than rewritten.
        if county.state_code.casefold() != self.state_code:
            raise ValueError(
                f"county_slug {self.county_slug!r} is registered under state "
                f"{county.state_code.casefold()!r}, not {self.state_code!r}"
            )
        if county.fips != self.county_fips:
            raise ValueError(
                f"county_fips {self.county_fips!r} contradicts the registry, which "
                f"assigns {county.fips!r} to {self.county_slug!r}"
            )

    @property
    def rendered(self) -> str:
        """The `tx-collin` form. A convenience, not the identity contract."""

        return f"{self.state_code}-{self.county_slug}"


def _require_match(value: object, pattern: re.Pattern[str], name: str, expected: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a str, got {type(value).__name__}")
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must be {expected}, got {value!r}")
