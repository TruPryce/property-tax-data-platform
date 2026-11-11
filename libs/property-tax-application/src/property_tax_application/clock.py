"""The application-owned current-time port."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

__all__ = ["Clock"]


@runtime_checkable
class Clock(Protocol):
    """Return the current application time as a timezone-aware instant.

    Use cases depend on this port instead of reading a system wall clock, so a
    test can supply one exact instant. Source freshness is publisher evidence
    and never comes from this clock. The existing object-store time helper is
    intentionally unchanged; its later wiring has a separate owner.
    """

    def now(self) -> datetime:
        """Return the current timezone-aware instant."""
        ...
