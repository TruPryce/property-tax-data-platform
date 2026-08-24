"""Where a domain fact came from, in bounded lineage and nothing else.

Provenance composes the identities rather than restating them: jurisdiction,
tax year, release kind, and release identifier are reachable through the release
identity, and a second copy of any of them would be two things that must agree.

What this shape guarantees is worth stating precisely. It has no generic payload,
detail, extra, metadata, or annotation field, no mapping, and no sequence of
arbitrary values — so there is nowhere whose *purpose* is to accept whatever a
caller has. It does not make an address or a name unrepresentable: a bounded
string called `source_member_name` can still be handed `JOHN_DOE`. Keeping
sensitive values out of what reaches provenance remains the adapter's obligation
under the accepted county contracts.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass

from property_tax_domain.artifact import ArtifactIdentity, require_hex_digest
from property_tax_domain.release import ReleaseIdentity, require_identifier

__all__ = ["DomainProvenance"]


@dataclass(frozen=True, slots=True)
class DomainProvenance:
    """The bounded lineage of one domain fact.

    Six fields and no seventh. Absence is `None`, never a placeholder: an empty
    member name, a zero row number, and a zero-filled fingerprint are all values
    that read as data while meaning "we did not have this".
    """

    release: ReleaseIdentity
    artifact: ArtifactIdentity
    source_member_name: str
    parser_contract_version: int
    source_row_number: int | None = None
    layout_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.release, ReleaseIdentity):
            raise ValueError(
                f"release must be a ReleaseIdentity, got {type(self.release).__name__}"
            )
        if not isinstance(self.artifact, ArtifactIdentity):
            raise ValueError(
                f"artifact must be an ArtifactIdentity, got {type(self.artifact).__name__}"
            )
        require_identifier(self.source_member_name, "source_member_name")
        _require_positive_int(self.parser_contract_version, "parser_contract_version")
        if self.source_row_number is not None:
            _require_positive_int(self.source_row_number, "source_row_number")
        if self.layout_fingerprint is not None:
            require_hex_digest(self.layout_fingerprint, "layout_fingerprint")


def _require_positive_int(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{name} must be one-based and at least 1, got {value}")
