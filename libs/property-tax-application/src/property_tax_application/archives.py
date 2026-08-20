"""What an archive must satisfy before anything is extracted from it.

Inspection precedes extraction, and that ordering is the whole design. An
archive that is going to be refused should be refused while it is still a
listing — before a single byte lands anywhere, before a parser is handed a
member, and before a release is marked as anything but quarantined.

The ordering is only worth something if it cannot be skipped, so extraction
consumes a handle that can exist only where a whole-archive judgement passed.
Checking the one member a caller asked for is not the same rule: an archive
holding a traversal entry is a hostile archive, and handing back its innocent
sibling is answering a question nobody asked.

The limits are stated as data rather than as code so a county whose export
legitimately expands to eleven gigabytes can be admitted by policy rather than
by weakening a rule for everyone.

Nothing here reads an archive. It is the vocabulary a refusal is expressed in
and the policy an adapter enforces, so both live where a caller can see them.
"""

from __future__ import annotations

import math
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

#: Bytes allowed per central-directory entry when bounding a directory read.
#: A record is 46 bytes plus the name, and this leaves room for a long name,
#: extra fields, and a comment without letting the directory become the bomb.
DIRECTORY_ENTRY_ALLOWANCE: int = 4096


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
    #: More entries than the policy admits, or a directory too large to read.
    TOO_MANY_MEMBERS = "too_many_members"
    #: One member expands beyond the per-member ceiling.
    MEMBER_TOO_LARGE = "member_too_large"
    #: The archive expands beyond the total ceiling.
    EXPANSION_TOO_LARGE = "expansion_too_large"
    #: Expanded over compressed exceeds the ceiling, for one member or for the
    #: archive as a whole.  Both are checked: an aggregate stays respectable
    #: while a bomb hides behind an incompressible sibling.
    COMPRESSION_RATIO_TOO_HIGH = "compression_ratio_too_high"
    #: A member is encrypted, so its bytes cannot be judged before extraction.
    ENCRYPTED_MEMBER = "encrypted_member"
    #: A member uses a compression method the policy does not admit.
    UNSUPPORTED_COMPRESSION = "unsupported_compression"
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
    them rather than at them. Measured: Denton's 2025 certified export is
    roughly 413 MB compressed and 11.5 GB expanded across 21 members, one of
    them 5.3 GB — a ratio near 28. Collin's is about 87 MB compressed and
    955 MB expanded, near 11.

    Two ratio ceilings rather than one, because they answer different
    questions. The aggregate bounds what a download can become on disk. The
    per-member ceiling catches a single anomalous member, which an aggregate
    cannot see: measured, a 4 MB zero-filled member beside a 1 MB
    incompressible sibling keeps the archive at an unremarkable 4.98 while that
    member alone expands 1,027-fold.

    The per-member ceiling is the looser of the two, because a single member is
    where legitimate data compresses best. Measured across fixed-width layouts
    by padding fraction: 10.8 at 73% padding, 32.6 at 91%, 55.1 at 96%, and
    112.0 for a row of nothing but blanks. Bombs begin far above that — 411 for
    repeated identical rows, 1,027 for zeros. A per-member ceiling of 200
    admits every layout a county could plausibly publish and still refuses
    both.
    """

    max_members: int = 256
    max_member_bytes: int = 16 * 1024**3
    max_expanded_bytes: int = 32 * 1024**3
    max_compression_ratio: float = 100.0
    max_member_compression_ratio: float = 200.0
    allowed_suffixes: frozenset[str] = frozenset(
        {".txt", ".csv", ".dat", ".tsv", ".mdb", ".accdb", ".xlsx", ".ods", ".xml", ".json"}
    )
    #: Stored and deflated only. Bzip2 and LZMA are valid ZIP but no county
    #: publishes them, and their reachable ratios would make a ratio ceiling
    #: chosen against deflate meaningless.
    allowed_compression_methods: frozenset[int] = frozenset({0, 8})
    policy_version: int = ARCHIVE_POLICY_VERSION

    def __post_init__(self) -> None:
        for name in ("max_members", "max_member_bytes", "max_expanded_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        for name in ("max_compression_ratio", "max_member_compression_ratio"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"{name} must be a real number")
            # Finite by name.  A NaN ceiling passes every comparison it is put
            # on the right of, so it does not raise the limit — it removes it,
            # while still reading as a configured bound.  Measured: NaN admits
            # a ratio-1,027 bomb without a word.
            if not math.isfinite(value) or value <= 1:
                raise ValueError(f"{name} must be finite and greater than 1")
        if self.max_member_compression_ratio < self.max_compression_ratio:
            raise ValueError(
                "max_member_compression_ratio must not be stricter than max_compression_ratio"
            )
        # Frozen by construction rather than by request.  A caller who hands in
        # a set keeps a reference to it, and a policy that can gain `.exe`
        # after it was validated was never a policy.
        for name, expected in (("allowed_suffixes", str), ("allowed_compression_methods", int)):
            value = getattr(self, name)
            if isinstance(value, str) or not isinstance(value, frozenset | set):
                raise ValueError(f"{name} must be a set of {expected.__name__}")
            frozen = frozenset(value)
            if not frozen:
                raise ValueError(f"{name} must name at least one entry")
            if any(not isinstance(entry, expected) or isinstance(entry, bool) for entry in frozen):
                raise ValueError(f"{name} must contain only {expected.__name__}")
            object.__setattr__(self, name, frozen)
        if any(not s.startswith(".") or s != s.lower() for s in self.allowed_suffixes):
            raise ValueError("allowed_suffixes must be lowercase and begin with a dot")
        if any(method < 0 for method in self.allowed_compression_methods):
            raise ValueError("allowed_compression_methods must be non-negative")
        if self.policy_version != ARCHIVE_POLICY_VERSION:
            raise ValueError(f"policy_version must be {ARCHIVE_POLICY_VERSION}")

    @property
    def max_directory_bytes(self) -> int:
        """How large a central directory may be before it is read at all.

        Derived from `max_members` rather than configured beside it, so the two
        cannot disagree — a directory bound that admitted more entries than the
        member limit would be a limit that never binds.
        """

        return self.max_members * DIRECTORY_ENTRY_ALLOWANCE


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

    @property
    def compression_ratio(self) -> float:
        """Expanded over compressed, with the degenerate cases named.

        A member that declares zero compressed bytes while claiming expanded
        ones is not a member that compresses well; it is a member whose ratio
        is unbounded, and returning infinity is what lets one comparison refuse
        it rather than a special case elsewhere forgetting to.
        """

        if self.compressed_bytes == 0:
            return 1.0 if self.declared_bytes == 0 else math.inf
        return self.declared_bytes / self.compressed_bytes


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
            return 1.0 if self.expanded_bytes == 0 else math.inf
        return self.expanded_bytes / self.compressed_bytes
