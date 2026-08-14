"""Vendor-neutral source contracts shared by every county adapter.

Issue #43 decision D7 specifies these three types field by field.  They hold
what a county observed and where it came from, and nothing about what any of it
means: no market, appraised, assessed, taxable, tax-amount, exemption, or
replacement semantics live here, and a value keeps its county's meaning until a
later canonical layer assigns one.

Two absences are deliberate and load-bearing.

`source_account_id` is optional because one accepted county contract forbids
declaring either of its candidate identifiers an account key.  A required field
would have forced that county either to violate its contract or to stay off the
shared record entirely.

`lexical_text` is optional because one county decodes values from a fixed-width
binary wrapper, where there is no original text to preserve.  An empty observed
text is *not* that case: `""` is a text, and it stays `""`.

Everything raised here is a `ValueError` at construction, because every caller
is trusted repository code.  A malformed record is an authoring defect, not
source data, so it produces no diagnostic.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal

__all__ = [
    "SOURCE_NATIVE_CLASSIFICATION",
    "AppraisalSourceRecord",
    "SourceNativeValue",
    "SourceProvenance",
]

SOURCE_NATIVE_CLASSIFICATION: Final[Literal["source-native"]] = "source-native"

#: A lowercase two-letter jurisdiction prefix, a hyphen, and a slug.  The shape
#: is fixed here rather than left to each county so that a record and its
#: provenance can be compared for agreement at all.
_JURISDICTION_PATTERN: Final = re.compile(r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require_text(value: str, field_name: str) -> None:
    """Reject a string that is absent while pretending not to be.

    `""` and `"   "` are the same fact wearing different clothes.  Absence is
    `None`; anything else is a value someone must be able to trace.
    """

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a str, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank or whitespace-only")


def _require_optional_text(value: str | None, field_name: str) -> None:
    """The same rule, for a field where `None` is the way to say nothing."""

    if value is None:
        return
    _require_text(value, field_name)


def _require_jurisdiction(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if not _JURISDICTION_PATTERN.fullmatch(value):
        raise ValueError(
            f"{field_name} must be a lowercase state prefix, a hyphen, and a county slug"
        )


def _require_positive_int(value: int, field_name: str) -> None:
    # `bool` subclasses `int`, and `True` is not a row number.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{field_name} must be positive, got {value}")


def _freeze[Value](values: Mapping[str, Value], field_name: str) -> Mapping[str, Value]:
    """Copy first, then wrap.

    The copy is what stops a caller mutating a constructed record through the
    dict it passed in; the proxy is what stops anyone mutating it through the
    record.  Either alone leaves a hole.
    """

    if not isinstance(values, Mapping):
        raise ValueError(f"{field_name} must be a mapping, got {type(values).__name__}")
    return MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class SourceNativeValue:
    """One value exactly as a county observed it, and where it came from."""

    source_field: str
    value: str | int | Decimal
    lexical_text: str | None = None
    precision: int | None = None
    scale: int | None = None
    classification: Literal["source-native"] = field(
        default=SOURCE_NATIVE_CLASSIFICATION,
        init=False,
    )

    def __post_init__(self) -> None:
        _require_text(self.source_field, "source_field")
        if self.value is None:
            raise ValueError("value must not be None; omit the entry to express absence")
        if not isinstance(self.value, str | int | Decimal) or isinstance(self.value, bool):
            raise ValueError(f"value must be str, int, or Decimal, got {type(self.value).__name__}")
        # Exempt from the blank rule on purpose: an observed empty text is a
        # fact about the source, and one county emits it today.
        if self.lexical_text is not None and not isinstance(self.lexical_text, str):
            raise ValueError("lexical_text must be a str or None")
        if (self.precision is None) != (self.scale is None):
            raise ValueError("precision and scale must be supplied together or not at all")


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Where a record came from, in the terms every county already agreed on.

    The six optional fields are the ones issue #43 D7 approves for counties that
    have them.  A county that records no field vector leaves it `None`; a county
    that recorded an empty one passes `()`.  Those are different facts.
    """

    jurisdiction_code: str
    release_identifier: str
    source_member_name: str
    source_row_number: int
    parser_contract_version: int
    layout_fingerprint: str
    table_name: str | None = None
    source_family: str | None = None
    source_year: int | None = None
    source_status: str | None = None
    observed_fields: tuple[str, ...] | None = None
    normalized_fields: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _require_jurisdiction(self.jurisdiction_code, "jurisdiction_code")
        _require_text(self.release_identifier, "release_identifier")
        _require_text(self.source_member_name, "source_member_name")
        _require_positive_int(self.source_row_number, "source_row_number")
        _require_positive_int(self.parser_contract_version, "parser_contract_version")
        _require_text(self.layout_fingerprint, "layout_fingerprint")
        _require_optional_text(self.table_name, "table_name")
        _require_optional_text(self.source_family, "source_family")
        _require_optional_text(self.source_status, "source_status")
        if self.source_year is not None:
            _require_positive_int(self.source_year, "source_year")
        for name in ("observed_fields", "normalized_fields"):
            vector = getattr(self, name)
            if vector is None:
                continue
            if not isinstance(vector, tuple) or not all(isinstance(item, str) for item in vector):
                raise ValueError(f"{name} must be a tuple of str or None")


@dataclass(frozen=True, slots=True)
class AppraisalSourceRecord:
    """One county row, vendor-neutral, with its origin attached.

    `provenance` is required and has no default: a source-native record whose
    origin is unknown is not evidence of anything.
    """

    jurisdiction_code: str
    appraisal_year: int
    provenance: SourceProvenance
    source_account_id: str | None = None
    source_family: str | None = None
    source_status: str | None = None
    parcel_reference: str | None = None
    source_native_identifiers: Mapping[str, str] = field(default_factory=dict)
    source_native_values: Mapping[str, SourceNativeValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_jurisdiction(self.jurisdiction_code, "jurisdiction_code")
        _require_positive_int(self.appraisal_year, "appraisal_year")
        if not isinstance(self.provenance, SourceProvenance):
            raise ValueError("provenance must be a SourceProvenance")
        if self.provenance.jurisdiction_code != self.jurisdiction_code:
            raise ValueError(
                "jurisdiction_code must equal the provenance jurisdiction_code, "
                f"got {self.jurisdiction_code!r} and {self.provenance.jurisdiction_code!r}"
            )
        _require_optional_text(self.source_account_id, "source_account_id")
        _require_optional_text(self.source_family, "source_family")
        _require_optional_text(self.source_status, "source_status")
        _require_optional_text(self.parcel_reference, "parcel_reference")

        identifiers = _freeze(self.source_native_identifiers, "source_native_identifiers")
        for name, identifier in identifiers.items():
            _require_text(name, "source_native_identifiers key")
            _require_text(identifier, f"source_native_identifiers[{name!r}]")
        object.__setattr__(self, "source_native_identifiers", identifiers)

        values = _freeze(self.source_native_values, "source_native_values")
        for name, native in values.items():
            if not isinstance(native, SourceNativeValue):
                raise ValueError(f"source_native_values[{name!r}] must be a SourceNativeValue")
            # The key is how a caller looks a value up; the source_field is how
            # the value says where it came from.  If those disagree, one of them
            # is lying and there is no way to tell which.
            if native.source_field != name:
                raise ValueError(
                    f"source_native_values key {name!r} does not equal its "
                    f"source_field {native.source_field!r}"
                )
        object.__setattr__(self, "source_native_values", values)
