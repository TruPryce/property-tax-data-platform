"""Run-bound quality values and the application-owned repository port.

Rules are configuration, evaluations are immutable facts about one processing
run, and a verdict is derived whenever it is requested. Missing or stale
coverage requires a new processing run; this boundary has no operation that
changes an evaluation already recorded for a run.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol, cast, runtime_checkable

from property_tax_application.runs import ProcessingRunRef

__all__ = [
    "QualityEvaluation",
    "QualityRepository",
    "QualityRule",
    "QualityVerdict",
    "RuleSeverity",
]

_RULE_IDENTIFIER: Final = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_RULE_FAMILIES: Final = frozenset(
    {
        "required_key_completeness",
        "logical_uniqueness",
        "child_relationship",
        "schema_compatibility",
        "record_count_drift",
        "value_validity",
        "archive_completeness",
        "source_specific",
    }
)


class RuleSeverity(StrEnum):
    """The complete quality severity vocabulary."""

    BLOCKING = "blocking"
    WARNING = "warning"


def _require_rule_identifier(value: object, field_name: str = "identifier") -> None:
    if not isinstance(value, str) or _RULE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} must match [a-z][a-z0-9_]{{0,63}}")


def _freeze_json(value: object, field_name: str) -> object:
    """Copy JSON-compatible configuration into immutable containers."""

    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must not contain a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, entry in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} object keys must be strings")
            frozen[key] = _freeze_json(entry, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(
            _freeze_json(entry, f"{field_name}[{index}]") for index, entry in enumerate(sequence)
        )
    raise ValueError(f"{field_name} must contain only JSON-compatible values")


@dataclass(frozen=True, slots=True)
class QualityRule:
    """One configured version of a quality rule.

    Thresholds are carried as configuration rather than embedded in application
    code. The top-level value is always an object, matching the accepted
    persistence model.
    """

    identifier: str
    version: int
    severity: RuleSeverity
    family: str
    configured_threshold: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_rule_identifier(self.identifier)
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise ValueError("version must be an int")
        if self.version < 1:
            raise ValueError("version must be positive")
        if not isinstance(self.severity, RuleSeverity):
            raise ValueError("severity must be a RuleSeverity")
        if not isinstance(self.family, str) or self.family not in _RULE_FAMILIES:
            raise ValueError("family must be one of the accepted quality rule families")
        if not isinstance(self.configured_threshold, Mapping):
            raise ValueError("configured_threshold must be an object mapping")
        object.__setattr__(
            self,
            "configured_threshold",
            _freeze_json(self.configured_threshold, "configured_threshold"),
        )


@dataclass(frozen=True, slots=True)
class QualityEvaluation:
    """One immutable rule result recorded against a processing run."""

    rule_identifier: str
    rule_version: int
    passed: bool
    subject: str | None = None
    measured_value: str | None = None
    expected_value: str | None = None

    def __post_init__(self) -> None:
        _require_rule_identifier(self.rule_identifier, "rule_identifier")
        if isinstance(self.rule_version, bool) or not isinstance(self.rule_version, int):
            raise ValueError("rule_version must be an int")
        if self.rule_version < 1:
            raise ValueError("rule_version must be positive")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        for field_name in ("subject", "measured_value", "expected_value"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field_name} must be a str or None")
        if not self.passed and (self.measured_value is None or self.expected_value is None):
            raise ValueError("a failing evaluation requires measured_value and expected_value")


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    """A computed answer for one run against the rules active when requested.

    Ambiguity is reported by rule identifier before severity is considered.
    Missing or stale blocking coverage makes the verdict incomplete. Warning
    failures remain visible but do not make an otherwise complete verdict
    unclean.
    """

    run: ProcessingRunRef
    missing_blocking_rules: tuple[QualityRule, ...] = ()
    stale_blocking_rules: tuple[QualityRule, ...] = ()
    ambiguous_rule_identifiers: tuple[str, ...] = ()
    blocking_failures: tuple[QualityEvaluation, ...] = ()
    warning_failures: tuple[QualityEvaluation, ...] = ()

    def __post_init__(self) -> None:
        if type(self.run) is not ProcessingRunRef:
            raise ValueError("run must be exactly a ProcessingRunRef")
        for field_name in ("missing_blocking_rules", "stale_blocking_rules"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                type(value) is QualityRule and value.severity is RuleSeverity.BLOCKING
                for value in values
            ):
                raise ValueError(f"{field_name} must contain blocking QualityRule values")
        if not isinstance(self.ambiguous_rule_identifiers, tuple):
            raise ValueError("ambiguous_rule_identifiers must be a tuple")
        for identifier in self.ambiguous_rule_identifiers:
            _require_rule_identifier(identifier, "ambiguous rule identifier")
        if len(set(self.ambiguous_rule_identifiers)) != len(self.ambiguous_rule_identifiers):
            raise ValueError("ambiguous_rule_identifiers must not contain duplicates")
        for field_name in ("blocking_failures", "warning_failures"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or not all(
                type(value) is QualityEvaluation and not value.passed for value in values
            ):
                raise ValueError(f"{field_name} must contain failing QualityEvaluation values")

    @property
    def complete(self) -> bool:
        """Whether every unambiguous active blocking rule has exact coverage."""

        return not (
            self.missing_blocking_rules
            or self.stale_blocking_rules
            or self.ambiguous_rule_identifiers
        )

    @property
    def clean(self) -> bool:
        """Whether this complete verdict records no blocking failure."""

        return self.complete and not self.blocking_failures


@runtime_checkable
class QualityRepository(Protocol):
    """Read configured rules and record or derive run-bound quality facts.

    ``verdict`` computes from the active rules and recorded evaluations every
    time it is called. Implementations do not persist the returned value.
    """

    def active_rules(self) -> tuple[QualityRule, ...]:
        """Return every rule version active when this method is called."""
        ...

    def record_evaluation(
        self,
        run: ProcessingRunRef,
        evaluation: QualityEvaluation,
    ) -> None:
        """Record one immutable result against a started processing run."""
        ...

    def verdict(self, run: ProcessingRunRef) -> QualityVerdict:
        """Compute this run's verdict against the rule set active now."""
        ...
