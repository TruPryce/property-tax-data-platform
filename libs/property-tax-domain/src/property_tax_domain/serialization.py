"""The authoritative named-field JSON, and the compact renderings derived from it.

Named-field JSON is the contract. Identity values nest as objects rather than as
pre-rendered strings, so no reader parses a string to recover a field the writer
held. An absent optional is emitted as `null` rather than omitted, so a field's
absence and a reader's older schema stay distinguishable. Key order is declared
here rather than left to insertion or hashing, because equal values have to
serialize byte-identically.

The jurisdiction identity document carries identity only. `county_fips` has its
own document keyed by that identity, which is also the only shape in which a
disagreement with the registry is detectable: a document that omits the FIPS
cannot notice that the registry corrected it.

Compact renderings are conveniences for readability and adapter key composition.
They are not the contract, and nothing here derives the JSON from one.

Standard library only.
"""

from __future__ import annotations

import json
from typing import Any, Final

from property_tax_domain.artifact import ArtifactIdentity
from property_tax_domain.jurisdiction import Jurisdiction
from property_tax_domain.provenance import DomainProvenance
from property_tax_domain.release import ArtifactReleaseBinding, ReleaseIdentity
from property_tax_domain.release_kind import ReleaseKind

__all__ = [
    "COMPACT_RELEASE_SEPARATOR",
    "artifact_document",
    "binding_document",
    "jurisdiction_document",
    "jurisdiction_registry_document",
    "parse_artifact_document",
    "parse_binding_document",
    "parse_compact_release",
    "parse_jurisdiction_document",
    "parse_jurisdiction_registry_document",
    "parse_provenance_document",
    "parse_release_document",
    "provenance_document",
    "release_document",
    "to_json",
]

#: The compact release rendering joins on this. It needs no escaping, which is a
#: property of the accepted alphabets rather than of this renderer: the
#: identifier alphabet is `[A-Za-z0-9._-]` and a jurisdiction is lowercase
#: alphanumeric segments joined by hyphens, so no component can contain it. A
#: test proves that against the alphabet rather than restating this sentence.
COMPACT_RELEASE_SEPARATOR: Final = "/"

_STATE_CODE_CHARS: Final = 2


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def jurisdiction_document(jurisdiction: Jurisdiction) -> dict[str, Any]:
    """Identity only. Registry metadata has its own document."""

    return {"state_code": jurisdiction.state_code, "county_slug": jurisdiction.county_slug}


def jurisdiction_registry_document(jurisdiction: Jurisdiction) -> dict[str, Any]:
    """The auditable metadata shape, keyed by the identity rather than inside it."""

    return {
        "jurisdiction": jurisdiction_document(jurisdiction),
        "county_fips": jurisdiction.county_fips,
    }


def artifact_document(artifact: ArtifactIdentity) -> dict[str, Any]:
    return {"sha256": artifact.sha256}


def release_document(release: ReleaseIdentity) -> dict[str, Any]:
    return {
        "jurisdiction": jurisdiction_document(release.jurisdiction),
        "tax_year": release.tax_year,
        "release_kind": release.release_kind.value,
        "release_identifier": release.release_identifier,
    }


def binding_document(binding: ArtifactReleaseBinding) -> dict[str, Any]:
    return {
        "artifact": artifact_document(binding.artifact),
        "release": release_document(binding.release),
    }


def provenance_document(provenance: DomainProvenance) -> dict[str, Any]:
    """Absent optionals are `null`, never omitted."""

    return {
        "release": release_document(provenance.release),
        "artifact": artifact_document(provenance.artifact),
        "source_member_name": provenance.source_member_name,
        "source_row_number": provenance.source_row_number,
        "parser_contract_version": provenance.parser_contract_version,
        "layout_fingerprint": provenance.layout_fingerprint,
    }


def to_json(document: dict[str, Any]) -> str:
    """Serialize a document with its declared key order preserved."""

    return json.dumps(document, sort_keys=False, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_jurisdiction_document(document: dict[str, Any]) -> Jurisdiction:
    """Rebuild a jurisdiction, resolving its FIPS from the registry.

    The document does not carry a FIPS, so this cannot detect that the registry
    corrected one: a document written beforehand parses successfully with the
    new value. That is the cost of keeping metadata out of identity, and the
    registry document is where such a disagreement is visible.
    """

    state_code = _require_field(document, "state_code", str)
    county_slug = _require_field(document, "county_slug", str)
    from property_tax_domain.counties import county_by_slug

    try:
        county = county_by_slug(county_slug)
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"county_slug {county_slug!r} is not in the county registry, so its "
            "county_fips cannot be resolved"
        ) from error
    return Jurisdiction(state_code=state_code, county_slug=county_slug, county_fips=county.fips)


def parse_jurisdiction_registry_document(
    document: dict[str, Any],
) -> tuple[Jurisdiction, str]:
    """Rebuild a jurisdiction and return the FIPS the document recorded.

    The recorded value is returned alongside rather than discarded, so an audit
    reads what was written rather than what the registry says now. A recorded
    value the registry does not assign is refused rather than preferred over it,
    and this document is never used to reconstruct identity in the registry's
    place.
    """

    nested = _require_field(document, "jurisdiction", dict)
    recorded_fips = _require_field(document, "county_fips", str)
    jurisdiction = parse_jurisdiction_document(nested)
    if recorded_fips != jurisdiction.county_fips:
        raise ValueError(
            f"county_fips {recorded_fips!r} disagrees with the registry, which assigns "
            f"{jurisdiction.county_fips!r} to {jurisdiction.county_slug!r}"
        )
    return jurisdiction, recorded_fips


def parse_artifact_document(document: dict[str, Any]) -> ArtifactIdentity:
    return ArtifactIdentity(sha256=_require_field(document, "sha256", str))


def parse_release_document(document: dict[str, Any]) -> ReleaseIdentity:
    return ReleaseIdentity(
        jurisdiction=parse_jurisdiction_document(_require_field(document, "jurisdiction", dict)),
        tax_year=_require_field(document, "tax_year", int),
        release_kind=_require_release_kind(document),
        release_identifier=_require_field(document, "release_identifier", str),
    )


def parse_binding_document(document: dict[str, Any]) -> ArtifactReleaseBinding:
    return ArtifactReleaseBinding(
        artifact=parse_artifact_document(_require_field(document, "artifact", dict)),
        release=parse_release_document(_require_field(document, "release", dict)),
    )


def parse_provenance_document(document: dict[str, Any]) -> DomainProvenance:
    for key in ("source_row_number", "layout_fingerprint"):
        if key not in document:
            raise ValueError(f"{key} must be present, as null where absent")
    return DomainProvenance(
        release=parse_release_document(_require_field(document, "release", dict)),
        artifact=parse_artifact_document(_require_field(document, "artifact", dict)),
        source_member_name=_require_field(document, "source_member_name", str),
        parser_contract_version=_require_field(document, "parser_contract_version", int),
        source_row_number=document["source_row_number"],
        layout_fingerprint=document["layout_fingerprint"],
    )


# ---------------------------------------------------------------------------
# Compact renderings
# ---------------------------------------------------------------------------


def parse_compact_release(rendered: str) -> ReleaseIdentity:
    """Reverse `tx-collin/2025/certified/ID` into its four components.

    A plain four-way split suffices because the separator is outside every
    accepted component alphabet, so no component can contain one and no escaping
    is needed. Splitting with a bound rather than greedily keeps a separator
    smuggled into a future identifier from silently producing five parts that
    are then rejoined into something else.
    """

    if not isinstance(rendered, str):
        raise ValueError(f"rendered must be a str, got {type(rendered).__name__}")
    parts = rendered.split(COMPACT_RELEASE_SEPARATOR)
    if len(parts) != 4:
        raise ValueError(
            f"a compact release rendering has exactly four components, got {len(parts)}"
        )
    jurisdiction_code, tax_year, release_kind, release_identifier = parts
    if len(jurisdiction_code) <= _STATE_CODE_CHARS or jurisdiction_code[_STATE_CODE_CHARS] != "-":
        raise ValueError(f"jurisdiction code {jurisdiction_code!r} is not a state and a slug")
    if not tax_year.isdigit():
        raise ValueError(f"tax_year {tax_year!r} is not digits")
    return ReleaseIdentity(
        jurisdiction=parse_jurisdiction_document(
            {
                "state_code": jurisdiction_code[:_STATE_CODE_CHARS],
                "county_slug": jurisdiction_code[_STATE_CODE_CHARS + 1 :],
            }
        ),
        tax_year=int(tax_year),
        release_kind=ReleaseKind(release_kind),
        release_identifier=release_identifier,
    )


# ---------------------------------------------------------------------------


def _require_field(document: dict[str, Any], key: str, expected: type) -> Any:
    if not isinstance(document, dict):
        raise ValueError(f"expected an object, got {type(document).__name__}")
    if key not in document:
        raise ValueError(f"{key} is required")
    value = document[key]
    # `bool` subclasses `int`, and a flag is not a year or a version.
    if expected is int and isinstance(value, bool):
        raise ValueError(f"{key} must be an int, got bool")
    if not isinstance(value, expected):
        raise ValueError(f"{key} must be {expected.__name__}, got {type(value).__name__}")
    return value


def _require_release_kind(document: dict[str, Any]) -> ReleaseKind:
    value = _require_field(document, "release_kind", str)
    try:
        return ReleaseKind(value)
    except ValueError as error:
        raise ValueError(f"release_kind {value!r} is outside the closed vocabulary") from error
