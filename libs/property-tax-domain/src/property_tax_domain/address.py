"""Bounded address and legal-description value objects.

These values compose onto appraisal records. They carry no independent grain,
lineage, publication decision, or general-purpose payload.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

__all__ = ["LegalDescription", "MailingAddress", "SitusAddress"]


def _require_bounded_text(value: object, name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a str, got {type(value).__name__}")
    if not 1 <= len(value) <= max_chars:
        raise ValueError(f"{name} must be 1 through {max_chars} characters")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{name} must not contain a control character")
    if not any(not character.isspace() for character in value):
        raise ValueError(f"{name} must contain at least one non-whitespace character")
    return value


def _require_label(value: object, name: str) -> str:
    return _require_bounded_text(value, name, 256)


def _require_address_component(value: object, name: str) -> str:
    return _require_bounded_text(value, name, 128)


def _validate_optional_components(subject: object, names: tuple[str, ...]) -> None:
    present = False
    for name in names:
        value = getattr(subject, name)
        if value is None:
            continue
        present = True
        _require_address_component(value, name)
    if not present:
        raise ValueError("at least one address component must be present")


@dataclass(frozen=True, slots=True)
class SitusAddress:
    """One source-observed situs address, without publication permission."""

    street_address: str | None = None
    unit: str | None = None
    city: str | None = None
    state_code: str | None = None
    postal_code: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_components(
            self,
            ("street_address", "unit", "city", "state_code", "postal_code"),
        )


@dataclass(frozen=True, slots=True)
class MailingAddress:
    """One source-observed mailing address, without person identity."""

    addressee: str | None = None
    street_address: str | None = None
    unit: str | None = None
    city: str | None = None
    state_code: str | None = None
    postal_code: str | None = None
    country_code: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_components(
            self,
            (
                "addressee",
                "street_address",
                "unit",
                "city",
                "state_code",
                "postal_code",
                "country_code",
            ),
        )


@dataclass(frozen=True, slots=True)
class LegalDescription:
    """One bounded source legal description and its named components."""

    text: str
    subdivision: str | None = None
    block: str | None = None
    lot: str | None = None

    def __post_init__(self) -> None:
        _require_label(self.text, "text")
        for name in ("subdivision", "block", "lot"):
            value = getattr(self, name)
            if value is not None:
                _require_address_component(value, name)
