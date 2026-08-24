"""What kind of release a county published.

Four values, closed. A county-native label reaches one of these only where an
accepted county contract establishes equivalence, and that mapping lives at the
county-aware boundary rather than here — this module declares no county name and
no county-native label, so the canonical vocabulary cannot grow one county at a
time.

Standard library only.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ReleaseKind"]


class ReleaseKind(StrEnum):
    """The canonical release kinds, with no fallback member.

    There is deliberately no `UNKNOWN`, no `_missing_` hook, and no open-string
    constructor: an unrecognized label must fail where it is presented rather
    than become a value that travels.
    """

    PROPOSED = "proposed"
    CERTIFIED = "certified"
    SUPPLEMENTAL = "supplemental"
    CURRENT = "current"
