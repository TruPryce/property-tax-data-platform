"""Publication attempt, lineage, and activation contracts.

This boundary records one attempt and its transition to current or failed. It
does not build the published product, grant canonical read access, or confer
permission to publish any field. An implementation admits activation only when
it can derive quality and change current state within one atomic boundary; a
verdict read earlier is advisory and is never an activation credential.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from property_tax_domain import ReleaseIdentity

from property_tax_application.quality import QualityVerdict
from property_tax_application.runs import ProcessingRunRef, require_locator_value

__all__ = [
    "PublicationActivationError",
    "PublicationAttempt",
    "PublicationAttemptClosedError",
    "PublicationProduct",
    "PublicationQualityError",
    "PublicationQualityUnavailableError",
    "PublicationRef",
    "PublicationRepository",
]


class PublicationProduct(StrEnum):
    """The complete published-product vocabulary."""

    LATEST_AVAILABLE = "latest_available"
    LATEST_CERTIFIED = "latest_certified"
    HISTORY = "history"


@dataclass(frozen=True, slots=True)
class PublicationRef:
    """An equality-capable opaque locator for one publication attempt."""

    value: str | int | tuple[str | int, ...]

    def __post_init__(self) -> None:
        require_locator_value(self.value)

    def _no_ordering(self, other: object) -> bool:
        raise TypeError(
            "PublicationRef carries no ordering: it is an opaque locator, not freshness"
        )

    __lt__ = _no_ordering
    __le__ = _no_ordering
    __gt__ = _no_ordering
    __ge__ = _no_ordering


class PublicationActivationError(RuntimeError):
    """Base class for a named refusal to make an attempt current."""


class PublicationQualityError(PublicationActivationError):
    """The run is missing, stale, ambiguous, or failing quality admission."""

    def __init__(self, verdict: QualityVerdict) -> None:
        if type(verdict) is not QualityVerdict:
            raise ValueError("verdict must be exactly a QualityVerdict")
        if verdict.clean:
            raise ValueError("a clean verdict cannot explain a quality refusal")
        self.verdict = verdict
        reasons: list[str] = []
        if verdict.missing_blocking_rules:
            reasons.append("missing blocking evaluations")
        if verdict.stale_blocking_rules:
            reasons.append("stale blocking evaluations")
        if verdict.ambiguous_rule_identifiers:
            reasons.append("ambiguous active rule versions")
        if verdict.blocking_failures:
            reasons.append("blocking failures")
        super().__init__("publication quality refused: " + ", ".join(reasons))


class PublicationQualityUnavailableError(PublicationActivationError):
    """Quality derivation cannot be serialized with the current-state change."""


class PublicationAttemptClosedError(PublicationActivationError):
    """A terminal publication attempt was asked to transition again."""


@runtime_checkable
class PublicationAttempt(Protocol):
    """One open attempt whose implementation owns atomic quality admission."""

    @property
    def reference(self) -> PublicationRef:
        """The persistence-generated locator for this attempt."""
        ...

    def activate(self) -> None:
        """Derive quality inside activation, then become current or refuse."""
        ...

    def fail(self) -> None:
        """Mark this attempt failed without disturbing the current publication."""
        ...


@runtime_checkable
class PublicationRepository(Protocol):
    """Open publication attempts with release, run, and freshness lineage.

    A retried caller obtains ``source_as_of`` from the run's indexed manifest
    partition before opening the attempt. ``None`` records established absence;
    neither application time nor acquisition time is substituted.
    """

    def open(
        self,
        product: PublicationProduct,
        release: ReleaseIdentity,
        run: ProcessingRunRef,
        source_as_of: datetime | None,
    ) -> PublicationAttempt:
        """Record and return one building publication attempt."""
        ...
