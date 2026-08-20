"""Inspect a ZIP before extracting it, and keep enforcing while extracting.

Three stages, in an order chosen so each one is cheap enough to survive what
the next one would not.

The first reads the end-of-central-directory record and nothing else. It exists
because the obvious place to count members is already too late: `ZipFile` reads
the entire central directory into memory in one call and walks it by declared
byte length, so an archive that declares a vast directory has spent the memory
before any member limit is consulted. Measured at 594 bytes of resident memory
per entry, a 19 MB archive of empty entries costs 119 MB to *count*. So the
directory's declared size is bounded before it is read at all.

The second judges the whole archive from its directory. Every entry, including
the ones carrying no bytes: a directory entry named `../` is a traversal
attempt whether or not anything follows it, and an entry that costs nothing to
store still costs something to hold.

The third streams a member, and can only be reached through a handle the second
stage produced. That is the point of the handle. Validating the member a caller
happens to ask for is a different, weaker rule — an archive holding a traversal
entry is a hostile archive, and answering questions about its innocent siblings
is not a service worth offering. Measured before the handle existed: requesting
`safe.txt` from an archive containing `../escape.txt` succeeded.

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

import contextlib
import os
import struct
import tempfile
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import IO

from property_tax_application.archives import (
    ArchiveInspection,
    ArchivePolicy,
    ArchiveViolation,
    MemberSummary,
    UnsafeArchiveError,
)

__all__ = ["VerifiedArchive", "inspect_zip", "open_archive"]

#: Read size while extracting.  Bounded for the same reason acquisition's is:
#: the whole point is never to hold a member in memory.
_CHUNK_BYTES = 1024 * 1024

#: The high bits of `external_attr` carry the Unix mode.  A regular file is
#: 0o100000; a symlink is 0o120000 and is refused, because following one is how
#: an extraction reaches outside the tree that was checked.
_S_IFMT = 0o170000
_S_IFREG = 0o100000

#: Bit 0 of the general-purpose flags marks a member as encrypted.
_FLAG_ENCRYPTED = 0x1

_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_BYTES = 22
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_LOCATOR_BYTES = 20
_ZIP64_EOCD_SIGNATURE = b"PK\x06\x06"
_ZIP64_EOCD_BYTES = 56
#: The comment that may follow the record, and so how far back it can sit.
_MAX_COMMENT_BYTES = 0xFFFF
_UINT16_MAX = 0xFFFF
_UINT32_MAX = 0xFFFFFFFF


def _refuse(violation: ArchiveViolation, member: str = "", detail: str = "") -> None:
    raise UnsafeArchiveError(violation, member, detail)


def _check_path(name: str) -> None:
    """Refuse any name that could resolve outside the extraction root.

    Checked as text rather than by resolving against a directory, because the
    answer must not depend on where extraction happens to be pointed — and
    because resolving is what an attacker is counting on.

    Applied to every entry, carrying bytes or not. A directory entry is still a
    name something will be created at, and exempting the entries that hold no
    content is how `../` walks past a traversal check.
    """

    if not name:
        _refuse(ArchiveViolation.PATH_TRAVERSAL, name, "empty member name")
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


def _check_readable(info: zipfile.ZipInfo, policy: ArchivePolicy) -> None:
    """Refuse what could not be judged, before anything tries to read it.

    Both of these otherwise surface from `open()` as a bare `RuntimeError` or
    `NotImplementedError`, outside the vocabulary a caller is told refusals come
    in. Measured: both escaped.
    """

    if info.flag_bits & _FLAG_ENCRYPTED:
        _refuse(ArchiveViolation.ENCRYPTED_MEMBER, info.filename, "member is encrypted")
    if info.compress_type not in policy.allowed_compression_methods:
        _refuse(
            ArchiveViolation.UNSUPPORTED_COMPRESSION,
            info.filename,
            f"compression method {info.compress_type} is not admitted",
        )


def _check_member_ratio(summary: MemberSummary, policy: ArchivePolicy) -> None:
    """Judge one member's own expansion, which an aggregate cannot see.

    Measured: a 4 MB zero-filled member beside a 1 MB incompressible sibling
    leaves the archive at an aggregate 4.98 while that member expands 1,027-fold.
    """

    ratio = summary.compression_ratio
    if ratio > policy.max_member_compression_ratio:
        described = "unbounded" if summary.compressed_bytes == 0 else f"{ratio:.1f}"
        _refuse(
            ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH,
            summary.name,
            f"member ratio {described} against a limit of {policy.max_member_compression_ratio}",
        )


@contextlib.contextmanager
def _reader(source: str | os.PathLike[str] | IO[bytes]) -> Iterator[IO[bytes]]:
    """A seekable binary view of the source, however it was supplied."""

    if isinstance(source, str | os.PathLike):
        try:
            handle = open(source, "rb")  # noqa: SIM115 - closed by the context manager
        except OSError as error:
            raise UnsafeArchiveError(
                ArchiveViolation.UNREADABLE_ARCHIVE, "", type(error).__name__
            ) from error
        try:
            yield handle
        finally:
            handle.close()
    else:
        yield source


def _find_eocd(tail: bytes) -> int:
    """Locate the record, reading the same one `zipfile` will.

    A trailing comment can contain the signature, so "the last match" and "the
    real record" are not always the same offset. `zipfile` takes the last match
    unconditionally, and a preflight that resolved the ambiguity more cleverly
    would end up bounding a directory other than the one about to be parsed —
    the bound and the parse have to be looking at the same record for the bound
    to mean anything.

    So this takes the last match too, and then requires the record to account
    for the bytes that follow it. An archive where those disagree is refused
    here rather than resolved differently in two places. Measured: `zipfile`
    also fails on such an archive, but the refusal should not depend on that.
    """

    found = tail.rfind(_EOCD_SIGNATURE)
    if found < 0 or found + _EOCD_BYTES > len(tail):
        return -1
    (comment_length,) = struct.unpack_from("<H", tail, found + 20)
    if found + _EOCD_BYTES + comment_length != len(tail):
        return -1
    return found


def _preflight(reader: IO[bytes], policy: ArchivePolicy) -> None:
    """Bound the central directory before anything reads it.

    This is the only check that can precede allocation, because every later one
    needs a parsed directory and parsing is itself the cost being bounded.
    """

    try:
        reader.seek(0, os.SEEK_END)
        size = reader.tell()
        span = min(size, _EOCD_BYTES + _MAX_COMMENT_BYTES)
        reader.seek(size - span)
        tail = reader.read(span)
    except OSError as error:
        raise UnsafeArchiveError(
            ArchiveViolation.UNREADABLE_ARCHIVE, "", type(error).__name__
        ) from error

    position = _find_eocd(tail)
    if position < 0:
        _refuse(ArchiveViolation.UNREADABLE_ARCHIVE, "", "no end-of-central-directory record")
    # Offset 10 is the total entry count and offset 12 the directory's size in
    # bytes.  The field after it is the directory's *offset*, which for any
    # sizeable archive is far larger than any bound worth setting on a size —
    # reading the wrong one refuses real exports rather than admitting bombs.
    entries, directory_bytes = struct.unpack_from("<HI", tail, position + 10)

    # Zip64 moves the real numbers out of a record whose fields saturate.
    if entries == _UINT16_MAX or directory_bytes == _UINT32_MAX:
        locator = position - _ZIP64_LOCATOR_BYTES
        if locator >= 0 and tail[locator : locator + 4] == _ZIP64_LOCATOR_SIGNATURE:
            (record_offset,) = struct.unpack_from("<Q", tail, locator + 8)
            try:
                reader.seek(record_offset)
                record = reader.read(_ZIP64_EOCD_BYTES)
            except OSError as error:
                raise UnsafeArchiveError(
                    ArchiveViolation.UNREADABLE_ARCHIVE, "", type(error).__name__
                ) from error
            if len(record) == _ZIP64_EOCD_BYTES and record[:4] == _ZIP64_EOCD_SIGNATURE:
                entries, directory_bytes = struct.unpack_from("<QQ", record, 32)

    if directory_bytes > policy.max_directory_bytes:
        _refuse(
            ArchiveViolation.TOO_MANY_MEMBERS,
            "",
            f"central directory declares {directory_bytes} bytes "
            f"against a limit of {policy.max_directory_bytes}",
        )
    if entries > policy.max_members:
        _refuse(
            ArchiveViolation.TOO_MANY_MEMBERS,
            "",
            f"{entries} entries against a limit of {policy.max_members}",
        )
    reader.seek(0)


def _judge(infos: list[zipfile.ZipInfo], policy: ArchivePolicy) -> ArchiveInspection:
    """Apply every rule to a parsed directory, and summarize what survived."""

    # Counted over every entry.  Directory entries cost memory and carry names
    # that get created, so a limit that ignored them would be a limit an
    # archive could pad its way around: measured, ten directory entries and a
    # traversal passed a policy of max_members=1.
    if len(infos) > policy.max_members:
        _refuse(
            ArchiveViolation.TOO_MANY_MEMBERS,
            "",
            f"{len(infos)} entries against a limit of {policy.max_members}",
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
        _check_readable(info, policy)
        if info.file_size > policy.max_member_bytes:
            _refuse(
                ArchiveViolation.MEMBER_TOO_LARGE,
                info.filename,
                f"declares {info.file_size} bytes against a limit of {policy.max_member_bytes}",
            )
        summary = MemberSummary(
            name=info.filename,
            declared_bytes=info.file_size,
            compressed_bytes=info.compress_size,
        )
        _check_member_ratio(summary, policy)
        expanded += info.file_size
        compressed += info.compress_size
        members.append(summary)

    if expanded > policy.max_expanded_bytes:
        _refuse(
            ArchiveViolation.EXPANSION_TOO_LARGE,
            "",
            f"expands to {expanded} bytes against a limit of {policy.max_expanded_bytes}",
        )
    inspection = ArchiveInspection(
        members=tuple(members), expanded_bytes=expanded, compressed_bytes=compressed
    )
    if inspection.compression_ratio > policy.max_compression_ratio:
        _refuse(
            ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH,
            "",
            f"ratio {inspection.compression_ratio:.1f} against a limit "
            f"of {policy.max_compression_ratio}",
        )
    return inspection


def inspect_zip(
    source: str | os.PathLike[str] | IO[bytes], policy: ArchivePolicy
) -> ArchiveInspection:
    """Judge an archive from its directory, before opening any member.

    Returns an inspection only for an archive that satisfied every rule.  Every
    other outcome raises, naming the violation and the member it was found on.
    """

    with _reader(source) as reader:
        _preflight(reader, policy)
        try:
            with zipfile.ZipFile(reader) as archive:
                infos = archive.infolist()
        except (zipfile.BadZipFile, OSError, ValueError) as error:
            raise UnsafeArchiveError(
                ArchiveViolation.UNREADABLE_ARCHIVE, "", type(error).__name__
            ) from error
        return _judge(infos, policy)


@dataclass(frozen=True, slots=True)
class VerifiedArchive:
    """An open archive that a whole-archive judgement already passed.

    Only `open_archive` constructs one, and it does so only after inspection
    returned, so possession is the evidence. Extraction takes this rather than a
    source for exactly that reason: there is no argument a caller can pass that
    skips the judgement, instead of a check that has to be remembered at every
    entry point.
    """

    inspection: ArchiveInspection
    policy: ArchivePolicy
    _archive: zipfile.ZipFile

    def _member(self, member: str) -> zipfile.ZipInfo:
        try:
            info = self._archive.getinfo(member)
        except KeyError as error:
            raise UnsafeArchiveError(
                ArchiveViolation.UNREADABLE_ARCHIVE, member, "no such member"
            ) from error
        if info.is_dir():
            _refuse(ArchiveViolation.UNSUPPORTED_MEMBER_TYPE, member, "member is a directory")
        # Re-applied against the entry this call resolved, so the rules hold
        # against what is about to be read rather than against a name that
        # matched something else during inspection.
        _check_path(info.filename)
        _check_type(info)
        _check_media_type(info.filename, self.policy)
        _check_readable(info, self.policy)
        if info.file_size > self.policy.max_member_bytes:
            _refuse(
                ArchiveViolation.MEMBER_TOO_LARGE,
                member,
                f"declares {info.file_size} bytes "
                f"against a limit of {self.policy.max_member_bytes}",
            )
        return info

    def iter_member_chunks(self, member: str) -> Iterator[bytes]:
        """Stream one member, in bounded chunks, never materializing it.

        Refusals raise here rather than on first iteration: a generator that
        defers its checks until someone pulls from it reports a hostile archive
        at the point the bytes were wanted, not at the point it was asked for.
        """

        info = self._member(member)
        return self._stream(info)

    def _stream(self, info: zipfile.ZipInfo) -> Iterator[bytes]:
        try:
            with self._archive.open(info) as stream:
                while True:
                    chunk = stream.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    yield chunk
        except (zipfile.BadZipFile, zlib.error, EOFError) as error:
            # A rewritten size fails the checksum at the end and arrives as
            # `BadZipFile`; damaged compressed bytes fail mid-stream as
            # `zlib.error`; a truncated container runs out as `EOFError`.  All
            # three mean the member is not what the directory said, and none of
            # them should reach a caller as a raw decompressor fault.
            raise UnsafeArchiveError(
                ArchiveViolation.CORRUPT_MEMBER, info.filename, type(error).__name__
            ) from error
        except (RuntimeError, NotImplementedError) as error:
            raise UnsafeArchiveError(
                ArchiveViolation.UNREADABLE_ARCHIVE, info.filename, type(error).__name__
            ) from error

    def extract_member(self, member: str, destination: str | os.PathLike[str]) -> int:
        """Write one member out, all of it or none of it, and return its size.

        Bytes go to a temporary file beside the destination and are moved into
        place only once the member has been read through to its checksum. A
        member that fails partway leaves nothing at the destination path.

        Measured before this: a corrupt 3 MB member wrote 2,097,152 bytes to the
        caller's stream and *then* refused. Whatever read those bytes next would
        have been reading a prefix of something the archive could not vouch for.
        """

        target = Path(destination)
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - moved or removed below
            dir=target.parent, prefix=f".{target.name}.", suffix=".partial", delete=False
        )
        staged = Path(handle.name)
        written = 0
        try:
            with handle:
                for chunk in self.iter_member_chunks(member):
                    handle.write(chunk)
                    written += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staged, target)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
        return written


@contextlib.contextmanager
def open_archive(
    source: str | os.PathLike[str] | IO[bytes], policy: ArchivePolicy
) -> Iterator[VerifiedArchive]:
    """Judge an archive whole, and yield a handle only if it passed."""

    with _reader(source) as reader:
        _preflight(reader, policy)
        try:
            archive = zipfile.ZipFile(reader)
        except (zipfile.BadZipFile, OSError, ValueError) as error:
            raise UnsafeArchiveError(
                ArchiveViolation.UNREADABLE_ARCHIVE, "", type(error).__name__
            ) from error
        with archive:
            inspection = _judge(archive.infolist(), policy)
            yield VerifiedArchive(inspection=inspection, policy=policy, _archive=archive)
