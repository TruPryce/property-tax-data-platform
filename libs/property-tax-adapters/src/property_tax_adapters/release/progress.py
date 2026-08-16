"""Deterministic progress for a long release.

A DAG that silently loses progress cannot tell a stalled release from a slow
one, so progress is part of the contract rather than a best-effort
notification: a callback that raises rejects the release.

Every field here is a count, an identifier, or a contract version.  There is no
row, no source value, and no host-local path, and the release identity is bounded
so a path cannot be represented as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from property_tax_adapters.release.records import (
    require_identifier,
    require_jurisdiction_code,
)

__all__ = ["PROGRESS_CONTRACT_VERSION", "ReleaseProgressEvent"]

#: Pinned, for the same reason the boundary version is.
PROGRESS_CONTRACT_VERSION: Final = 1

#: A non-final event is emitted after every this many physical rows.
PROGRESS_ROW_INTERVAL: Final = 100_000


@dataclass(frozen=True, slots=True)
class ReleaseProgressEvent:
    """One progress observation, carrying counts and identity and nothing else.

    Identity comes from the reader's `PreparedRelease` rather than from any
    record, which is what lets an empty release emit a complete final event.
    """

    jurisdiction_code: str
    release_identifier: str
    source_member_name: str
    parser_contract_version: int
    layout_fingerprint: str
    physical_rows_processed: int
    staged_record_count: int
    sequence_number: int
    final: bool
    progress_contract_version: int = PROGRESS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.progress_contract_version != PROGRESS_CONTRACT_VERSION:
            raise ValueError(f"progress_contract_version must be {PROGRESS_CONTRACT_VERSION}")
        # The same bound `PreparedRelease` applies, not a weaker one.  A
        # non-blank string would have admitted an absolute path as a member
        # name, and a progress stream is precisely where that would be logged.
        require_jurisdiction_code(self.jurisdiction_code)
        require_identifier(self.release_identifier, "release_identifier")
        require_identifier(self.source_member_name, "source_member_name")
        if not isinstance(self.layout_fingerprint, str) or not self.layout_fingerprint.strip():
            raise ValueError("layout_fingerprint must be a non-blank str")
        for name in (
            "physical_rows_processed",
            "staged_record_count",
            "sequence_number",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if isinstance(self.parser_contract_version, bool) or not isinstance(
            self.parser_contract_version, int
        ):
            raise ValueError("parser_contract_version must be an int")
        if not isinstance(self.final, bool):
            raise ValueError("final must be a bool")
