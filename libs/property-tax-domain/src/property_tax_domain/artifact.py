"""Which bytes a fact came from.

An artifact is identified by its content and nothing else. Two acquisitions of
the same bytes are one artifact however they were named or wherever they were
stored; the same name carrying different bytes is two. That is the property the
whole Bronze divergence rule rests on, so no location, name, entity tag,
surrogate key, or timestamp is admitted here.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["ARTIFACT_IDENTITY_HEX_LENGTH", "ArtifactIdentity", "require_hex_digest"]

#: Characters in a SHA-256 hexdigest. Published so a consumer asserting the
#: bound reads it from the vocabulary rather than repeating the literal.
ARTIFACT_IDENTITY_HEX_LENGTH: Final = 64

#: Built from the constant, so the published length and the enforced one cannot
#: drift apart by someone editing one of them.
_HEX_DIGEST: Final = re.compile(rf"[0-9a-f]{{{ARTIFACT_IDENTITY_HEX_LENGTH}}}\Z")


def require_hex_digest(value: object, name: str) -> str:
    """Accept exactly a lowercase SHA-256 hexdigest, or refuse it unchanged."""

    if not isinstance(value, str):
        raise ValueError(f"{name} must be a str, got {type(value).__name__}")
    if _HEX_DIGEST.fullmatch(value) is None:
        raise ValueError(
            f"{name} must be exactly {ARTIFACT_IDENTITY_HEX_LENGTH} lowercase "
            f"hexadecimal characters, got {value!r}"
        )
    return value


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """One set of bytes, named by their digest and by nothing else."""

    sha256: str

    def __post_init__(self) -> None:
        require_hex_digest(self.sha256, "sha256")

    @property
    def rendered(self) -> str:
        """The bare digest. A convenience, not the identity contract."""

        return self.sha256
