"""Task-local falsification for the application clock port."""

from __future__ import annotations

from datetime import UTC, datetime

from property_tax_application.clock import Clock


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("instant must be timezone-aware")
        self.instant = instant
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.instant


def observe_current_time(clock: Clock) -> datetime:
    return clock.now()


def test_an_aware_fixed_instant_is_observed_exactly_without_a_wall_clock() -> None:
    fixed = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    clock = FixedClock(fixed)

    observed = observe_current_time(clock)

    assert observed is fixed
    assert observed.tzinfo is not None
    assert observed.utcoffset() is not None
    assert clock.calls == 1
    assert isinstance(clock, Clock)


def test_a_naive_fixed_instant_is_refused() -> None:
    naive = datetime(2026, 11, 11, 9, 30)

    try:
        FixedClock(naive)
    except ValueError as error:
        assert "timezone-aware" in str(error)
    else:
        raise AssertionError("a naive clock instant was accepted")
