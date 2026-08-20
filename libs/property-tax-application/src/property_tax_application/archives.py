"""What an archive must satisfy before anything is extracted from it.

Inspection precedes extraction, and that ordering is the whole design. An
archive that is going to be refused should be refused while it is still a
listing — before a single byte lands anywhere, before a parser is handed a
member, and before a release is marked as anything but quarantined.

The limits are stated as data rather than as code so a county whose export
legitimately expands to eleven gigabytes can be admitted by policy rather than
by weakening a rule for everyone.

Nothing here reads an archive. It is the vocabulary a refusal is expressed in
and the policy an adapter enforces, so both live where a caller can see them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "ARCHIVE_POLICY_VERSION",
    "ArchiveInspection",
    "ArchivePolicy",
    "ArchiveViolation",
    "MemberSummary",
    "UnsafeArchiveError",
]

#: Pinned, so a recorded refusal can say which policy shape judged it.
ARCHIVE_POLICY_VERSION: int = 1


class ArchiveViolation(StrEnum):
    """Why an archive was refused, named rather than described.

    A refusal has to say which rule it broke: the requirement is that the
    release is quarantined *and* the violated rule recorded, and an operator
    deciding whether a county changed its export or someone sent a bomb needs
    to know which.
    """

    #: A member path escapes the extraction root — absolute, rooted, or `..`.
    PATH_TRAVERSAL = "path_traversal"
    #: A member is a link, a device, or anything that is not a regular file.
    UNSUPPORTED_MEMBER_TYPE = "unsupported_member_type"
    #: A member's suffix is not on the allowlist.
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    #: More members than the policy admits.
    TOO_MANY_MEMBERS = "too_many_members"
    #: One member expands beyond the per-member ceiling.
    MEMBER_TOO_LARGE = "member_too_large"
    #: The archive expands beyond the total ceiling.
    EXPANSION_TOO_LARGE = "expansion_too_large"
    #: Expanded bytes divided by compressed bytes exceeds the ceiling.
    COMPRESSION_RATIO_TOO_HIGH = "compression_ratio_too_high"
    #: A member's bytes did not match its own checksum, which is how a
    #: rewritten size or a truncated transfer surfaces while reading.
    CORRUPT_MEMBER = "corrupt_member"
    #: The container could not be read as an archive at all.
    UNREADABLE_ARCHIVE = "unreadable_archive"


class UnsafeArchiveError(Exception):
    """An archive was refused, and this says which rule refused it.

    Carries the violation and the member it was found on, and never the
    member's contents: a refusal is a fact about structure, and quoting bytes
    from something judged hostile is how an inspector becomes an amplifier.
    """

    def __init__(self, violation: ArchiveViolation, member: str = "", detail: str = "") -> None:
        self.violation = violation
        self.member = member
        self.detail = detail
        described = f"{violation.value}"
        if member:
            described += f" at {member!r}"
        if detail:
            described += f": {detail}"
        super().__init__(described)


@dataclass(frozen=True, slots=True)
class ArchivePolicy:
    """The limits an archive is judged against.

    Defaults come from what the six counties actually publish, with room above
    it rather than at it. Measured: Denton's 2025 certified export is roughly
    413 MB compressed and 11.5 GB expanded across 21 members, one of them
    5.3 GB — a ratio near 28. Collin's is about 87 MB compressed and 955 MB
    expanded, near 11. A ratio ceiling of 100 admits both with margin and still
    refuses the thousand-fold expansions that make a bomb a bomb.
    """

    max_members: int = 256
    max_member_bytes: int = 16 * 1024**3
    max_expanded_bytes: int = 32 * 1024**3
    max_compression_ratio: float = 100.0
    allowed_suffixes: frozenset[str] = frozenset(
        {".txt", ".csv", ".dat", ".tsv", ".mdb", ".accdb", ".xlsx", ".ods", ".xml", ".json"}
    )
    policy_version: int = ARCHIVE_POLICY_VERSION

    def __post_init__(self) -> None:
        for name in ("max_members", "max_member_bytes", "max_expanded_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        if (
            isinstance(self.max_compression_ratio, bool)
            or not isinstance(self.max_compression_ratio, int | float)
            or self.max_compression_ratio <= 1
        ):
            raise ValueError("max_compression_ratio must be greater than 1")
        if not self.allowed_suffixes:
            raise ValueError("allowed_suffixes must name at least one suffix")
        if any(not s.startswith(".") or s != s.lower() for s in self.allowed_suffixes):
            raise ValueError("allowed_suffixes must be lowercase and begin with a dot")
        if self.policy_version != ARCHIVE_POLICY_VERSION:
            raise ValueError(f"policy_version must be {ARCHIVE_POLICY_VERSION}")


@dataclass(frozen=True, slots=True)
class MemberSummary:
    """One member as the archive's own directory describes it.

    Declared, not verified. The sizes here are the container's claims about
    itself, written by whoever built it.

    What that does and does not permit is worth stating, because it decides
    which rules can be enforced where. A reader bounds a member to its declared
    size and checks the member's checksum, so a header understating what follows
    yields a checksum failure rather than an over-delivery — the danger of a
    *lying* header is bounded for us. A header *overstating* is the live risk,
    and that is what inspection refuses before anything is opened.
    """

    name: str
    declared_bytes: int
    compressed_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty str")
        for field_name in ("declared_bytes", "compressed_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative int")


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    """What inspection found, for an archive that passed.

    Only constructed for an archive that satisfied every rule, so holding one
    is the evidence that extraction may proceed.
    """

    members: tuple[MemberSummary, ...]
    expanded_bytes: int
    compressed_bytes: int
    policy_version: int = ARCHIVE_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.members, tuple) or not all(
            isinstance(entry, MemberSummary) for entry in self.members
        ):
            raise ValueError("members must be a tuple of MemberSummary")
        for name in ("expanded_bytes", "compressed_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative int")

    @property
    def compression_ratio(self) -> float:
        """Expanded over compressed, defined as 1.0 for an empty archive."""

        if self.compressed_bytes == 0:
            return 1.0
        return self.expanded_bytes / self.compressed_bytes
