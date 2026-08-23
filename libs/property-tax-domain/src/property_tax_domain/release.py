"""Which logical release a fact came from, and which bytes carried it.

A release identity is the jurisdiction, the tax year, the kind, and the
identifier the source supplied. The identifier is in the identity because a
county can issue two distinct releases in one year under one kind; leaving it
out would collapse those into one identity with two artifacts, which is the
shape Bronze already treats as divergence.

The identifier is opaque. It is namespaced by its jurisdiction, so two counties
may reuse one label without either being renamed, and it is never inferred from
a filename, never assumed globally unique, and never rewritten to be accepted.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from property_tax_domain.artifact import ArtifactIdentity
from property_tax_domain.jurisdiction import Jurisdiction
from property_tax_domain.release_kind import ReleaseKind

__all__ = [
    "IDENTIFIER_MAX_CHARS",
    "TAX_YEAR_MAX",
    "TAX_YEAR_MIN",
    "ArtifactReleaseBinding",
    "ReleaseIdentity",
    "require_identifier",
]

#: The identifier alphabet already accepted across this repository. It admits
#: no `/`, `\`, `:`, whitespace, or control character, so an absolute path, a
#: UNC path, and a traversal are unrepresentable rather than discouraged.
IDENTIFIER_MAX_CHARS: Final = 128
_IDENTIFIER: Final = re.compile(rf"[A-Za-z0-9._-]{{1,{IDENTIFIER_MAX_CHARS}}}\Z")

#: The bound `ReleasePartition` and the merged `partition_tax_year_plausible`
#: constraint already enforce. The narrower parser bound applies to a source
#: year, which is a different value.
TAX_YEAR_MIN: Final = 1900
TAX_YEAR_MAX: Final = 2200


def require_identifier(value: object, name: str) -> str:
    """Accept a bounded opaque identifier, preserving its case exactly.

    Both letter cases are inside the alphabet, so `ABC` and `abc` are each
    valid and denote different things. Refusing one for differing only in case
    would invalidate half the alphabet or impose a canonical case nobody
    declared. Whitespace is refused because it is outside the grammar, which is
    a separate rule and not the same one.
    """

    if not isinstance(value, str):
        raise ValueError(f"{name} must be a str, got {type(value).__name__}")
    if _IDENTIFIER.fullmatch(value) is None or value[:1] in {".", "-"}:
        raise ValueError(
            f"{name} must be 1 to {IDENTIFIER_MAX_CHARS} characters of [A-Za-z0-9._-] "
            f"not beginning with '.' or '-', got {value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """One logical release, identified by four components and carrying no artifact.

    No artifact identity is stored here on purpose: binding a second artifact to
    a release must not change the identity of a release that has not changed.
    """

    jurisdiction: Jurisdiction
    tax_year: int
    release_kind: ReleaseKind
    release_identifier: str

    def __post_init__(self) -> None:
        if not isinstance(self.jurisdiction, Jurisdiction):
            raise ValueError(
                f"jurisdiction must be a Jurisdiction, got {type(self.jurisdiction).__name__}"
            )
        _require_tax_year(self.tax_year)
        if not isinstance(self.release_kind, ReleaseKind):
            raise ValueError(
                f"release_kind must be a ReleaseKind, got {type(self.release_kind).__name__}"
            )
        require_identifier(self.release_identifier, "release_identifier")

    @property
    def rendered(self) -> str:
        """The compact `tx-collin/2025/certified/ID` form.

        A derived convenience for readability and adapter key composition. The
        named-field JSON in the serialization module is the contract.
        """

        return (
            f"{self.jurisdiction.rendered}/{self.tax_year}/"
            f"{self.release_kind.value}/{self.release_identifier}"
        )


def _require_tax_year(value: object) -> None:
    # `bool` subclasses `int`, and `True` is not a tax year.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"tax_year must be an int, got {type(value).__name__}")
    if not TAX_YEAR_MIN <= value <= TAX_YEAR_MAX:
        raise ValueError(f"tax_year must be {TAX_YEAR_MIN} through {TAX_YEAR_MAX}, got {value}")


@dataclass(frozen=True, slots=True)
class ArtifactReleaseBinding:
    """That one artifact carried one logical release.

    An association rather than a field on either identity, which is what lets
    the relationship be many-to-many in both directions: one archive carrying a
    current release for one tax year and a certified release for another, and
    one release observed in several artifacts when a source diverges. Recording
    another binding changes neither identity.
    """

    artifact: ArtifactIdentity
    release: ReleaseIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactIdentity):
            raise ValueError(
                f"artifact must be an ArtifactIdentity, got {type(self.artifact).__name__}"
            )
        if not isinstance(self.release, ReleaseIdentity):
            raise ValueError(
                f"release must be a ReleaseIdentity, got {type(self.release).__name__}"
            )
