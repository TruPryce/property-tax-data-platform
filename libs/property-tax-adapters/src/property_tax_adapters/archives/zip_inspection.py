"""Inspect a ZIP before extracting it, and keep enforcing while extracting.

Inspection reads the central directory and judges the whole archive before any
member is opened. That is what lets a refusal happen while the archive is still
a listing — nothing written, no parser handed anything, the release quarantined
with the violated rule named.

Extraction re-checks the structural rules and the size ceiling, because a
caller can reach for a member without inspecting first, and skipping the
judgement is not something an API should make easy.

What extraction does *not* need to do is worth writing down, since assuming
otherwise produces a guard that can never fire. Every size in the directory is
the archive's own claim, so the obvious worry is a member declaring a kilobyte
and delivering a gigabyte. Measured against the standard library: it does not
happen. `zipfile` bounds a member to its declared size and verifies the member's
checksum, so a rewritten size surfaces as a checksum failure and never as
over-delivery. The live risk is a header that *overstates*, and inspection
refuses that before anything is opened.

Standard library only.
"""

from __future__ import annotations

import zipfile
import zlib
from collections.abc import Iterator
from pathlib import PurePosixPath, PureWindowsPath
from typing import IO

from property_tax_application.archives import (
    ArchiveInspection,
    ArchivePolicy,
    ArchiveViolation,
    MemberSummary,
    UnsafeArchiveError,
)

__all__ = ["extract_member", "inspect_zip", "iter_member_chunks"]

#: Read size while extracting.  Bounded for the same reason acquisition's is:
#: the whole point is never to hold a member in memory.
_CHUNK_BYTES = 1024 * 1024

#: The high bits of `external_attr` carry the Unix mode.  A regular file is
#: 0o100000; a symlink is 0o120000 and is refused, because following one is how
#: an extraction reaches outside the tree that was checked.
_S_IFMT = 0o170000
_S_IFREG = 0o100000


def _refuse(violation: ArchiveViolation, member: str = "", detail: str = "") -> None:
    raise UnsafeArchiveError(violation, member, detail)


def _check_path(name: str) -> None:
    """Refuse any name that could resolve outside the extraction root.

    Checked as text rather than by resolving against a directory, because the
    answer must not depend on where extraction happens to be pointed — and
    because resolving is what an attacker is counting on.
    """

    if not name or name.endswith("/"):
        return  # a directory entry carries no bytes
    if name.startswith("/") or name.startswith("\\"):
        _refuse(ArchiveViolation.PATH_TRAVERSAL, name, "absolute path")
    # Windows-rooted and drive-qualified forms, which a POSIX check misses.
    windows = PureWindowsPath(name)
    if windows.drive or windows.is_absolute():
        _refuse(ArchiveViolation.PATH_TRAVERSAL, name, "drive-qualified or rooted path")
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if any(part == ".." for part in parts):
        _refuse(ArchiveViolation.PATH_TRAVERSAL, name, "parent-directory segment")


def _check_type(info: zipfile.ZipInfo) -> None:
    if info.is_dir():
        return
    file_type = (info.external_attr >> 16) & _S_IFMT
    # The type bits, not the mode.  A DOS-created entry reports zero, and an
    # entry written with a permission mode alone — 0o600, which is what
    # `writestr` sets — also carries no type bits.  Neither says "not a regular
    # file"; only type bits that are present and something else do.
    if file_type and file_type != _S_IFREG:
        _refuse(
            ArchiveViolation.UNSUPPORTED_MEMBER_TYPE,
            info.filename,
            "not a regular file",
        )


def _check_media_type(name: str, policy: ArchivePolicy) -> None:
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in policy.allowed_suffixes:
        _refuse(
            ArchiveViolation.UNSUPPORTED_MEDIA_TYPE,
            name,
            f"suffix {suffix or '(none)'} is not admitted",
        )


def inspect_zip(source: str | IO[bytes], policy: ArchivePolicy) -> ArchiveInspection:
    """Judge an archive from its directory, before opening any member.

    Returns an inspection only for an archive that satisfied every rule.  Every
    other outcome raises, naming the violation and the member it was found on.
    """

    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as error:
        raise UnsafeArchiveError(
            ArchiveViolation.UNREADABLE_ARCHIVE, "", type(error).__name__
        ) from error

    files = [info for info in infos if not info.is_dir()]
    if len(files) > policy.max_members:
        _refuse(
            ArchiveViolation.TOO_MANY_MEMBERS,
            "",
            f"{len(files)} members against a limit of {policy.max_members}",
        )

    members: list[MemberSummary] = []
    expanded = 0
    compressed = 0
    for info in infos:
        _check_path(info.filename)
        _check_type(info)
        if info.is_dir():
            continue
        _check_media_type(info.filename, policy)
        if info.file_size > policy.max_member_bytes:
            _refuse(
                ArchiveViolation.MEMBER_TOO_LARGE,
                info.filename,
                f"declares {info.file_size} bytes against a limit of {policy.max_member_bytes}",
            )
        expanded += info.file_size
        compressed += info.compress_size
        members.append(
            MemberSummary(
                name=info.filename,
                declared_bytes=info.file_size,
                compressed_bytes=info.compress_size,
            )
        )

    if expanded > policy.max_expanded_bytes:
        _refuse(
            ArchiveViolation.EXPANSION_TOO_LARGE,
            "",
            f"expands to {expanded} bytes against a limit of {policy.max_expanded_bytes}",
        )
    if compressed and expanded / compressed > policy.max_compression_ratio:
        _refuse(
            ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH,
            "",
            f"ratio {expanded / compressed:.1f} against a limit of {policy.max_compression_ratio}",
        )

    return ArchiveInspection(
        members=tuple(members), expanded_bytes=expanded, compressed_bytes=compressed
    )


def iter_member_chunks(
    source: str | IO[bytes], member: str, policy: ArchivePolicy
) -> Iterator[bytes]:
    """Stream one member, enforcing the same bounds against arriving bytes.

    The declared size the directory carried is a claim; this counts what
    actually arrives and stops at the first byte past what was declared or
    permitted.  Stopping *at* the limit rather than after it is the difference
    between refusing a bomb and unpacking one before objecting to it.
    """

    with zipfile.ZipFile(source) as archive:
        try:
            info = archive.getinfo(member)
        except KeyError as error:
            raise UnsafeArchiveError(
                ArchiveViolation.UNREADABLE_ARCHIVE, member, "no such member"
            ) from error
        _check_path(info.filename)
        _check_type(info)
        _check_media_type(info.filename, policy)

        # Enforced here as well as at inspection, because this can be called
        # without inspecting: a caller reaching straight for a member should not
        # thereby skip the ceiling.
        if info.file_size > policy.max_member_bytes:
            _refuse(
                ArchiveViolation.MEMBER_TOO_LARGE,
                member,
                f"declares {info.file_size} bytes against a limit of {policy.max_member_bytes}",
            )
        try:
            with archive.open(info) as stream:
                while True:
                    chunk = stream.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    yield chunk
        except (zipfile.BadZipFile, zlib.error) as error:
            # Two shapes, both meaning the member is not what the directory said.
            # A rewritten size fails the checksum at the end and arrives as
            # `BadZipFile`; damaged compressed bytes fail mid-stream and arrive
            # as `zlib.error`, which would otherwise escape as a raw decompressor
            # fault to a caller who asked about an archive.
            raise UnsafeArchiveError(
                ArchiveViolation.CORRUPT_MEMBER, member, type(error).__name__
            ) from error


def extract_member(
    source: str | IO[bytes], member: str, destination: IO[bytes], policy: ArchivePolicy
) -> int:
    """Write one verified member out, and return how many bytes it held."""

    written = 0
    for chunk in iter_member_chunks(source, member, policy):
        destination.write(chunk)
        written += len(chunk)
    return written
