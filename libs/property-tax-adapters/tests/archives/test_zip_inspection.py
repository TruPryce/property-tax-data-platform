"""Archive inspection, and the bounds that keep applying while extracting.

Every archive here is built in the test that uses it. Nothing is committed, and
no county archive is read — the shapes that matter are structural, and a
structure can be constructed.
"""

from __future__ import annotations

import io
import os
import random
import resource
import struct
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from property_tax_adapters.archives import (
    VerifiedArchive,
    inspect_zip,
    open_archive,
    zip_inspection,
)
from property_tax_application.archives import (
    ARCHIVE_POLICY_VERSION,
    ArchiveInspection,
    ArchivePolicy,
    ArchiveViolation,
    MemberSummary,
    UnsafeArchiveError,
)

ROW = b"00000001|123456|RESIDENTIAL\n"


def rows(count: int, *, seed: int = 11) -> bytes:
    """Appraisal-shaped text, which is not the same thing as repeated text.

    Measured: two thousand identical rows deflate at a ratio near 308 and would
    be refused as a bomb, while varied rows land near 3.8 and the counties
    themselves near 11 and 28. A fixture built from repetition tests the
    compressor, not the rule.
    """

    generator = random.Random(seed)
    kinds = ("RESIDENTIAL", "COMMERCIAL", "AGRICULTURAL", "EXEMPT")
    return b"".join(
        f"{index:08d}|{generator.randrange(20_000, 900_000)}|{generator.choice(kinds)}\n".encode()
        for index in range(count)
    )


class _Interrupting:
    """A handle whose member stream stops partway, standing in for a signal."""

    def __init__(self, handle: VerifiedArchive, stream) -> None:  # noqa: ANN001
        self._handle = handle
        self._stream = stream

    def iter_member_chunks(self, member: str):  # noqa: ANN202, ARG002
        return self._stream


def flagged(*, flag: int | None = None, method: int | None = None) -> io.BytesIO:
    """An archive whose member claims to be encrypted or oddly compressed.

    Written after the fact, because `zipfile` will not produce either.
    """

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = zipfile.ZipInfo("m.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, ROW * 40)
    data = bytearray(buf.getvalue())
    central = data.rindex(b"PK\x01\x02")
    local = data.index(b"PK\x03\x04")
    if flag is not None:
        struct.pack_into("<H", data, central + 8, flag)
        struct.pack_into("<H", data, local + 6, flag)
    if method is not None:
        struct.pack_into("<H", data, central + 10, method)
        struct.pack_into("<H", data, local + 8, method)
    return io.BytesIO(bytes(data))


def build(members: dict[str, bytes], *, attrs: dict[str, int] | None = None) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            info = zipfile.ZipInfo(name)
            # ZipInfo defaults to ZIP_STORED regardless of the ZipFile's mode,
            # so without this every archive here would be uncompressed and every
            # ratio would be 1.0 — which silently makes a bomb test prove nothing.
            info.compress_type = zipfile.ZIP_DEFLATED
            if attrs and name in attrs:
                info.external_attr = attrs[name]
            archive.writestr(info, payload)
    buf.seek(0)
    return buf


def policy(**overrides) -> ArchivePolicy:  # noqa: ANN003
    return ArchivePolicy(**overrides)


@contextmanager
def opened(source: io.BytesIO, pol: ArchivePolicy | None = None):  # noqa: ANN201
    """Extraction goes through a handle, so the tests do too.

    There is no member-at-a-time entry point to test any more, which is the
    point: the judgement is not a step a caller can decline.
    """

    with open_archive(source, pol or policy()) as handle:
        yield handle


def chunks_of(source: io.BytesIO, member: str, pol: ArchivePolicy | None = None) -> list[bytes]:
    with opened(source, pol) as handle:
        return list(handle.iter_member_chunks(member))


# --------------------------------------------------------------------------
# The accepting case
# --------------------------------------------------------------------------


def test_a_conforming_archive_is_inspected_and_summarized() -> None:
    payload = rows(2_000)
    layout = rows(50, seed=3)
    archive = build({"roll.txt": payload, "layout.csv": layout})

    result = inspect_zip(archive, policy())

    assert isinstance(result, ArchiveInspection)
    assert {member.name for member in result.members} == {"roll.txt", "layout.csv"}
    assert result.expanded_bytes == len(payload) + len(layout)
    assert result.compressed_bytes < result.expanded_bytes
    assert result.compression_ratio < ArchivePolicy().max_compression_ratio
    assert result.policy_version == ARCHIVE_POLICY_VERSION


def test_a_directory_entry_carries_no_member() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("nested/", b"")
        archive.writestr("nested/roll.txt", ROW)

    result = inspect_zip(buf, policy())

    assert [member.name for member in result.members] == ["nested/roll.txt"]


def test_an_empty_archive_has_a_defined_ratio() -> None:
    """Nothing over nothing is not a division to perform."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass

    result = inspect_zip(buf, policy())

    assert result.members == ()
    assert result.compression_ratio == 1.0


def test_something_that_is_not_an_archive_is_refused_as_such() -> None:
    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(io.BytesIO(b"not a zip at all"), policy())

    assert raised.value.violation is ArchiveViolation.UNREADABLE_ARCHIVE


# --------------------------------------------------------------------------
# Traversal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "nested/../../escape.txt",
        "/etc/passwd.txt",
        "..\\escape.txt",
        "nested\\..\\..\\escape.txt",
        "C:\\windows\\system.txt",
        "\\\\server\\share\\file.txt",
    ],
    ids=["parent", "nested-parent", "absolute", "windows-parent", "windows-nested", "drive", "unc"],
)
def test_a_member_that_could_escape_the_root_is_refused(name: str) -> None:
    """Judged as text, so the answer does not depend on where extraction points.

    Resolving against a directory to find out is exactly what the attempt is
    counting on.
    """

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({name: ROW}), policy())

    assert raised.value.violation is ArchiveViolation.PATH_TRAVERSAL
    assert raised.value.member == name


def test_a_nested_path_that_stays_inside_is_admitted() -> None:
    result = inspect_zip(build({"exports/2026/roll.txt": ROW}), policy())

    assert [member.name for member in result.members] == ["exports/2026/roll.txt"]


def test_a_dot_segment_alone_is_not_traversal() -> None:
    result = inspect_zip(build({"./roll.txt": ROW}), policy())

    assert len(result.members) == 1


# --------------------------------------------------------------------------
# Member types
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "mode"),
    [("symlink", 0o120777), ("fifo", 0o010644), ("block device", 0o060644), ("socket", 0o140644)],
)
def test_a_member_that_is_not_a_regular_file_is_refused(label: str, mode: int) -> None:
    """Following a link is how extraction reaches outside the tree it checked."""

    archive = build({"roll.txt": ROW}, attrs={"roll.txt": mode << 16})

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(archive, policy())

    assert raised.value.violation is ArchiveViolation.UNSUPPORTED_MEMBER_TYPE, label


@pytest.mark.parametrize(
    ("label", "attr"),
    [("dos entry", 0), ("permission mode only", 0o600 << 16), ("regular file", 0o100644 << 16)],
)
def test_an_entry_without_contrary_type_bits_is_admitted(label: str, attr: int) -> None:
    """A permission mode is not a claim about the entry's type.

    `writestr` sets 0o600 and a DOS-built archive sets nothing; reading either
    as "not a regular file" refuses ordinary archives.
    """

    result = inspect_zip(build({"roll.txt": ROW}, attrs={"roll.txt": attr}), policy())

    assert len(result.members) == 1, label


# --------------------------------------------------------------------------
# Media types
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["payload.exe", "script.sh", "library.so", "noextension"])
def test_a_member_outside_the_suffix_allowlist_is_refused(name: str) -> None:
    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({name: ROW}), policy())

    assert raised.value.violation is ArchiveViolation.UNSUPPORTED_MEDIA_TYPE
    assert raised.value.member == name


def test_the_allowlist_covers_what_the_counties_actually_publish() -> None:
    """Measured shapes: delimited text, PACS fixed-width, Access, and layouts."""

    admitted = ArchivePolicy().allowed_suffixes

    for suffix in (".txt", ".csv", ".dat", ".mdb", ".xlsx", ".ods"):
        assert suffix in admitted, suffix


def test_a_suffix_is_matched_case_insensitively() -> None:
    result = inspect_zip(build({"ROLL.TXT": ROW}), policy())

    assert len(result.members) == 1


# --------------------------------------------------------------------------
# Counts, expansion, and ratio
# --------------------------------------------------------------------------


def test_too_many_members_is_refused() -> None:
    archive = build({f"member{index:03d}.txt": ROW for index in range(9)})

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(archive, policy(max_members=8))

    assert raised.value.violation is ArchiveViolation.TOO_MANY_MEMBERS


def test_a_member_declaring_more_than_the_ceiling_is_refused() -> None:
    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({"roll.txt": ROW * 100}), policy(max_member_bytes=100))

    assert raised.value.violation is ArchiveViolation.MEMBER_TOO_LARGE
    assert raised.value.member == "roll.txt"


def test_total_expansion_beyond_the_ceiling_is_refused() -> None:
    """No single member need be oversized for the archive to be."""

    archive = build({f"m{index}.txt": ROW * 40 for index in range(6)})

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(archive, policy(max_member_bytes=10_000, max_expanded_bytes=2_000))

    assert raised.value.violation is ArchiveViolation.EXPANSION_TOO_LARGE


def test_a_compression_bomb_is_refused_on_its_ratio() -> None:
    """Highly compressible filler is what a bomb is; the ratio is what shows it."""

    bomb = build({"roll.txt": b"\0" * 4_000_000})
    inspection_policy = policy(max_expanded_bytes=64 * 1024**3, max_member_bytes=32 * 1024**3)

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(bomb, inspection_policy)

    assert raised.value.violation is ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH


def test_the_measured_county_ratios_stay_admitted() -> None:
    """Denton is near 28 and Collin near 11; the ceiling has to clear both.

    A limit set at what a bomb needs would refuse the exports this platform
    exists to read.
    """

    ceiling = ArchivePolicy().max_compression_ratio

    assert ceiling > 28, "Denton's measured expansion would be refused"
    assert ceiling > 11, "Collin's measured expansion would be refused"


# --------------------------------------------------------------------------
# The header is a claim, so extraction re-checks it
# --------------------------------------------------------------------------


def understating_archive(declared: int, actual: bytes) -> io.BytesIO:
    """An archive whose directory understates what a member holds.

    Built by rewriting the size fields after the fact, which is what a hostile
    archive does and what a trusting inspector believes.
    """

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("roll.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, actual)
    data = bytearray(buf.getvalue())
    real = len(actual).to_bytes(4, "little")
    claimed = declared.to_bytes(4, "little")
    start = 0
    while (found := data.find(real, start)) != -1:
        data[found : found + 4] = claimed
        start = found + 4
    return io.BytesIO(bytes(data))


def test_a_reader_bounds_a_member_to_its_declared_size() -> None:
    """The premise behind not guarding against over-delivery.

    Measured rather than assumed: with the header rewritten to understate,
    `zipfile` stops at the declared size and the member's own checksum fails.
    A guard counting bytes for an over-delivery that cannot happen would be a
    branch no input reaches.
    """

    payload = ROW * 4_000
    archive = understating_archive(declared=64, actual=payload)

    inspection = inspect_zip(archive, policy())
    assert inspection.members[0].declared_bytes == 64, "the premise failed: the lie did not take"

    archive.seek(0)
    with pytest.raises(UnsafeArchiveError) as raised:
        chunks_of(archive, "roll.txt")

    assert raised.value.violation is ArchiveViolation.CORRUPT_MEMBER
    assert raised.value.member == "roll.txt"


def test_a_rewritten_size_never_yields_more_than_it_declared() -> None:
    """Nothing beyond the declared size is handed to a caller, even before the
    checksum fails."""

    payload = ROW * 4_000
    archive = understating_archive(declared=64, actual=payload)
    delivered = 0

    with pytest.raises(UnsafeArchiveError), opened(archive) as handle:
        for chunk in handle.iter_member_chunks("roll.txt"):
            delivered += len(chunk)

    assert delivered <= 64, f"{delivered} bytes were delivered against a declared 64"


def test_a_truncated_archive_is_a_corrupt_member_not_a_crash() -> None:
    """A caller should get this vocabulary, not a zipfile exception."""

    archive = build({"roll.txt": rows(500)})
    data = bytearray(archive.getvalue())
    # Corrupt the compressed payload without touching the directory.
    data[60:80] = b"\x00" * 20

    with pytest.raises(UnsafeArchiveError) as raised:
        chunks_of(io.BytesIO(bytes(data)), "roll.txt")

    assert raised.value.violation is ArchiveViolation.CORRUPT_MEMBER


def test_a_member_overstating_its_size_is_refused_before_the_handle_exists() -> None:
    """The ceiling is a whole-archive rule, so it is applied opening the archive."""

    archive = build({"roll.txt": rows(400)})

    with pytest.raises(UnsafeArchiveError) as raised:
        chunks_of(archive, "roll.txt", policy(max_member_bytes=100))

    assert raised.value.violation is ArchiveViolation.MEMBER_TOO_LARGE


def test_a_conforming_member_extracts_whole(tmp_path: Path) -> None:
    payload = rows(3_000)
    archive = build({"roll.txt": payload})
    target = tmp_path / "roll.txt"

    with opened(archive) as handle:
        written = handle.extract_member("roll.txt", target)

    assert written == len(payload)
    assert target.read_bytes() == payload
    assert [entry.name for entry in tmp_path.iterdir()] == ["roll.txt"]


def test_extraction_re_checks_the_structural_rules() -> None:
    """A caller reaching straight for a member does not skip the judgement."""

    archive = build({"payload.exe": ROW})

    with pytest.raises(UnsafeArchiveError) as raised:
        chunks_of(archive, "payload.exe")

    assert raised.value.violation is ArchiveViolation.UNSUPPORTED_MEDIA_TYPE


def test_a_member_that_is_not_there_is_named_as_such() -> None:
    with pytest.raises(UnsafeArchiveError) as raised:
        chunks_of(build({"roll.txt": ROW}), "absent.txt")

    assert raised.value.violation is ArchiveViolation.UNREADABLE_ARCHIVE


def test_extraction_never_holds_the_member_whole() -> None:
    """Chunked for the same reason acquisition is: size must not become memory."""

    payload = rows(60_000)
    sizes = [len(chunk) for chunk in chunks_of(build({"roll.txt": payload}), "roll.txt")]

    assert len(sizes) > 1, "the member arrived in one piece"
    assert max(sizes) <= 1024 * 1024


# --------------------------------------------------------------------------
# The refusal itself
# --------------------------------------------------------------------------


def test_a_refusal_names_the_rule_it_broke() -> None:
    """The requirement is that the violated rule is recorded, not just a failure."""

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({"../escape.txt": ROW}), policy())

    assert raised.value.violation is ArchiveViolation.PATH_TRAVERSAL
    assert raised.value.member == "../escape.txt"
    assert raised.value.violation.value in str(raised.value)


def test_a_refusal_quotes_no_member_content() -> None:
    """Quoting bytes from something judged hostile makes an inspector an amplifier."""

    secret = b"SECRET-ARCHIVE-CONTENT" * 100

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({"payload.exe": secret}), policy())

    assert "SECRET-ARCHIVE-CONTENT" not in str(raised.value)
    assert "SECRET-ARCHIVE-CONTENT" not in repr(raised.value)


def test_the_violation_vocabulary_is_closed() -> None:
    assert len(ArchiveViolation) == 11


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_members": 0}, "positive int"),
        ({"max_members": True}, "positive int"),
        ({"max_member_bytes": -1}, "positive int"),
        ({"max_compression_ratio": 1}, "greater than 1"),
        ({"max_compression_ratio": 0.5}, "greater than 1"),
        ({"allowed_suffixes": frozenset()}, "at least one entry"),
        ({"allowed_suffixes": frozenset({"txt"})}, "begin with a dot"),
        ({"allowed_suffixes": frozenset({".TXT"})}, "lowercase"),
        ({"max_compression_ratio": float("nan")}, "finite"),
        ({"max_compression_ratio": float("inf")}, "finite"),
        ({"max_member_compression_ratio": float("nan")}, "finite"),
        ({"max_member_compression_ratio": 2.0, "max_compression_ratio": 50.0}, "not be stricter"),
        ({"allowed_compression_methods": frozenset()}, "at least one entry"),
        ({"allowed_suffixes": ".txt"}, "must be a set"),
    ],
    ids=[
        "zero-members",
        "bool-members",
        "negative-bytes",
        "ratio-one",
        "ratio-below-one",
        "no-suffixes",
        "dotless-suffix",
        "uppercase-suffix",
        "nan-ratio",
        "infinite-ratio",
        "nan-member-ratio",
        "member-ratio-stricter-than-aggregate",
        "no-compression-methods",
        "suffixes-as-a-string",
    ],
)
def test_an_unusable_policy_is_refused_at_construction(overrides: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ArchivePolicy(**overrides)


def test_a_member_summary_describes_declared_sizes_not_verified_ones() -> None:
    summary = MemberSummary(name="roll.txt", declared_bytes=10, compressed_bytes=4)

    assert summary.declared_bytes == 10
    with pytest.raises(ValueError, match="non-negative"):
        MemberSummary(name="roll.txt", declared_bytes=-1, compressed_bytes=0)


def test_repeated_rows_are_a_bomb_and_varied_rows_are_not() -> None:
    """The fixture distinction, asserted so it cannot quietly revert.

    Building a "conforming" archive out of identical rows produces a ratio near
    308, which the policy correctly refuses — and which would look like the
    limit being too strict rather than the sample being unrepresentative.
    """

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({"roll.txt": ROW * 2_000}), policy())
    assert raised.value.violation is ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH

    varied = inspect_zip(build({"roll.txt": rows(2_000)}), policy())
    assert varied.compression_ratio < 10, "appraisal-shaped text should compress modestly"


# --------------------------------------------------------------------------
# Bypasses found by adversarial probing of the first implementation
#
# Each of these passed before the handle, the preflight, the per-member ratio,
# and the staged write existed. They are kept as tests rather than as notes
# because a bypass that was closed once is the kind that returns.
# --------------------------------------------------------------------------


def test_a_clean_member_is_not_served_from_a_hostile_archive() -> None:
    """The bypass the handle exists to close.

    Asking for `safe.txt` used to succeed while `../escape.txt` sat beside it,
    because extraction validated the member it was handed rather than the
    archive it came from. An archive holding a traversal entry is hostile, and
    its innocent siblings are not a separate question.
    """

    archive = build({"safe.txt": rows(200), "../escape.txt": rows(200, seed=2)})

    with pytest.raises(UnsafeArchiveError) as raised:
        chunks_of(archive, "safe.txt")

    assert raised.value.violation is ArchiveViolation.PATH_TRAVERSAL
    assert raised.value.member == "../escape.txt"


def test_a_handle_is_the_only_way_to_reach_a_member() -> None:
    """There is no source-taking extraction entry point left to bypass."""

    import property_tax_adapters.archives as package

    assert not hasattr(package, "extract_member")
    assert not hasattr(package, "iter_member_chunks")
    assert set(package.__all__) == {"VerifiedArchive", "inspect_zip", "open_archive"}
    exposed = {name for name in dir(VerifiedArchive) if not name.startswith("_")}
    assert exposed == {"extract_member", "inspection", "iter_member_chunks", "policy"}


def test_a_directory_entry_is_judged_for_traversal() -> None:
    """`../` carries no bytes, and was therefore skipped entirely."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(zipfile.ZipInfo("../"), b"")
        archive.writestr(zipfile.ZipInfo("roll.txt"), ROW)
    buf.seek(0)

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(buf, policy())

    assert raised.value.violation is ArchiveViolation.PATH_TRAVERSAL
    assert raised.value.member == "../"


def test_directory_entries_count_toward_the_member_limit() -> None:
    """Ten directory entries and one file used to pass `max_members=1`."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for index in range(10):
            archive.writestr(zipfile.ZipInfo(f"d{index}/"), b"")
        archive.writestr(zipfile.ZipInfo("roll.txt"), ROW)
    buf.seek(0)

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(buf, policy(max_members=1))

    assert raised.value.violation is ArchiveViolation.TOO_MANY_MEMBERS


def test_a_vast_directory_is_refused_before_it_is_parsed(tmp_path: Path) -> None:
    """Counting members is too late if counting them is the cost.

    `ZipFile` reads the whole central directory in one call and walks it by
    declared byte length, so the member limit was consulted only after the
    memory had been spent. Measured at 594 bytes resident per entry: counting
    50,000 of them cost 26 MB, and the same refusal now costs nothing.
    """

    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for index in range(50_000):
            handle.writestr(zipfile.ZipInfo(f"{index}.txt"), b"")

    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(archive, policy())
    growth = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) * 1024

    assert raised.value.violation is ArchiveViolation.TOO_MANY_MEMBERS
    assert "central directory" in raised.value.detail
    assert growth < 8 * 1024 * 1024, f"the refusal cost {growth / 1e6:.1f} MB"


def test_the_directory_bound_is_derived_from_the_member_limit() -> None:
    """Two independent knobs could disagree; one derived from the other cannot."""

    assert policy(max_members=8).max_directory_bytes < policy(max_members=256).max_directory_bytes
    assert policy(max_members=256).max_directory_bytes == 256 * 4096


def test_a_bomb_hiding_behind_an_incompressible_sibling_is_refused() -> None:
    """The measured case: aggregate 4.98, and one member expanding 1,027-fold."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        bomb = zipfile.ZipInfo("bomb.txt")
        bomb.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(bomb, b"\0" * 4_000_000)
        noise = zipfile.ZipInfo("noise.dat")
        noise.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(noise, os.urandom(1_000_000))
    buf.seek(0)

    aggregate = 5_000_000 / (3_892 + 1_000_310)
    assert aggregate < ArchivePolicy().max_compression_ratio, "the premise: the archive looks fine"

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(buf, policy())

    assert raised.value.violation is ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH
    assert raised.value.member == "bomb.txt"


def test_a_member_declaring_zero_compressed_bytes_is_refused() -> None:
    """An unbounded ratio is not a good one; division used to skip it entirely."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = zipfile.ZipInfo("x.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, b"\0" * 2_000_000)
    data = bytearray(buf.getvalue())
    struct.pack_into("<I", data, data.rindex(b"PK\x01\x02") + 20, 0)
    struct.pack_into("<I", data, data.index(b"PK\x03\x04") + 18, 0)

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(io.BytesIO(bytes(data)), policy())

    assert raised.value.violation is ArchiveViolation.COMPRESSION_RATIO_TOO_HIGH
    assert "unbounded" in raised.value.detail


def test_the_two_ratio_ceilings_bracket_measured_data_and_measured_bombs() -> None:
    """Both limits are chosen from measurement, and the numbers are recorded.

    Fixed-width layouts by padding fraction: 10.8 at 73%, 32.6 at 91%, 55.1 at
    96%, and 112.0 for a row of nothing but blanks. Bombs: 411 for repeated
    identical rows, 1,027 for zeros. The counties themselves: Denton 28,
    Collin 11.
    """

    aggregate = ArchivePolicy().max_compression_ratio
    per_member = ArchivePolicy().max_member_compression_ratio

    assert aggregate > 28, "Denton's measured expansion would be refused"
    assert aggregate > 11, "Collin's measured expansion would be refused"
    assert per_member > 112, "a legitimate all-blank row would be refused"
    assert per_member < 411, "repeated identical rows would be admitted"
    assert per_member >= aggregate, "the looser bound is the per-member one"


def test_a_corrupt_member_leaves_nothing_at_the_destination(tmp_path: Path) -> None:
    """Measured before staging: 2,097,152 bytes written, then the refusal.

    Whatever read the destination next would have been reading a prefix of
    something the archive could not vouch for.
    """

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = zipfile.ZipInfo("roll.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, os.urandom(3_000_000))
    data = bytearray(buf.getvalue())
    data[1_500_000:1_500_200] = b"\xff" * 200

    target = tmp_path / "roll.txt"
    with pytest.raises(UnsafeArchiveError) as raised, opened(io.BytesIO(bytes(data))) as handle:
        handle.extract_member("roll.txt", target)

    assert raised.value.violation is ArchiveViolation.CORRUPT_MEMBER
    assert not target.exists()
    assert list(tmp_path.iterdir()) == [], "a partial file was left behind"


def test_a_failed_commit_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Abort is not only for refusals.

    The member read cleanly and the staged bytes are all correct; it is the
    move into place that fails. Nothing should survive that either, and a
    staged file named after the destination would be the worst thing to leave
    behind — it looks like the extraction it is not.
    """

    archive = build({"roll.txt": rows(20_000)})
    target = tmp_path / "roll.txt"

    def refuse_to_replace(source: object, destination: object) -> None:
        raise OSError("cross-device link")

    monkeypatch.setattr(zip_inspection.os, "replace", refuse_to_replace)

    with pytest.raises(OSError, match="cross-device"), opened(archive) as handle:
        handle.extract_member("roll.txt", target)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == [], "a staged file was left behind"


def test_an_interrupted_extraction_leaves_nothing_behind(tmp_path: Path) -> None:
    """A BaseException is not an exception, and `except Exception` would miss it."""

    archive = build({"roll.txt": rows(20_000)})
    target = tmp_path / "roll.txt"

    with pytest.raises(KeyboardInterrupt), opened(archive) as handle:
        stream = handle.iter_member_chunks("roll.txt")

        def interrupted():  # noqa: ANN202
            yield next(iter(stream))
            raise KeyboardInterrupt

        handle.__class__.extract_member(_Interrupting(handle, interrupted()), "roll.txt", target)

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_extraction_replaces_the_destination_only_on_success(tmp_path: Path) -> None:
    """An existing file is not truncated by an extraction that then fails."""

    target = tmp_path / "roll.txt"
    target.write_bytes(b"the previous release\n")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = zipfile.ZipInfo("roll.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, os.urandom(2_000_000))
    data = bytearray(buf.getvalue())
    data[1_000_000:1_000_200] = b"\xff" * 200

    with pytest.raises(UnsafeArchiveError), opened(io.BytesIO(bytes(data))) as handle:
        handle.extract_member("roll.txt", target)

    assert target.read_bytes() == b"the previous release\n"


def test_a_mutable_suffix_set_cannot_be_widened_after_validation() -> None:
    """A policy that can gain `.exe` after it was checked was never a policy."""

    supplied = {".txt"}
    pol = ArchivePolicy(allowed_suffixes=supplied)
    supplied.add(".exe")

    assert isinstance(pol.allowed_suffixes, frozenset)
    assert ".exe" not in pol.allowed_suffixes

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(build({"payload.exe": ROW}), pol)
    assert raised.value.violation is ArchiveViolation.UNSUPPORTED_MEDIA_TYPE


def test_a_nan_ceiling_cannot_stand_in_for_a_limit() -> None:
    """NaN does not raise a bound, it removes one, while still reading as a bound.

    Measured: it admitted a ratio-1,027 bomb without a word.
    """

    with pytest.raises(ValueError, match="finite"):
        ArchivePolicy(max_compression_ratio=float("nan"))


def test_an_encrypted_member_is_named_rather_than_crashing() -> None:
    """`open()` raises a bare RuntimeError, outside the refusal vocabulary."""

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(flagged(flag=0x1), policy())

    assert raised.value.violation is ArchiveViolation.ENCRYPTED_MEMBER


@pytest.mark.parametrize("method", [6, 12, 14, 99], ids=["imploded", "bzip2", "lzma", "aes"])
def test_a_compression_method_off_the_allowlist_is_refused(method: int) -> None:
    """Bzip2 and LZMA are valid ZIP, and reach ratios a deflate-derived ceiling
    was never chosen against."""

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(flagged(method=method), policy())

    assert raised.value.violation is ArchiveViolation.UNSUPPORTED_COMPRESSION


def test_the_preflight_reads_the_directory_size_not_its_offset() -> None:
    """The two fields are adjacent, and reading the wrong one refuses real data.

    A 3 MB archive's directory *offset* is about 3 MB, far past any sane bound
    on a directory's *size* — so this defect refuses legitimate exports rather
    than admitting bombs, which is the kind that reaches production looking
    like a strict policy.
    """

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = zipfile.ZipInfo("roll.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, os.urandom(3_000_000))
    buf.seek(0)

    result = inspect_zip(buf, policy())

    assert len(result.members) == 1
    assert len(buf.getvalue()) > policy().max_directory_bytes, (
        "the premise: the directory's offset exceeds the bound on its size"
    )


def test_an_ambiguous_end_record_is_refused_rather_than_resolved() -> None:
    """The preflight and `zipfile` must read the same record.

    `zipfile` takes the last signature match unconditionally. A preflight that
    resolved a quoted signature more cleverly would bound one directory while
    another was parsed, so an archive where the record and the bytes after it
    disagree is refused here instead.
    """

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = zipfile.ZipInfo("roll.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, ROW * 4)
        archive.comment = b"PK\x05\x06" + b"Z" * 40

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(io.BytesIO(buf.getvalue()), policy())

    assert raised.value.violation is ArchiveViolation.UNREADABLE_ARCHIVE


def test_a_zip64_end_record_is_read_for_its_own_counts() -> None:
    """Zip64 moves the real numbers out of a record whose fields saturate."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", allowZip64=True) as archive:
        for index in range(2):
            info = zipfile.ZipInfo(f"m{index}.txt")
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, rows(100, seed=index))
    raw = buf.getvalue()

    eocd_at = raw.rindex(b"PK\x05\x06")
    head, tail = raw[:eocd_at], bytearray(raw[eocd_at:])
    directory_at = raw.index(b"PK\x01\x02")
    entries = raw.count(b"PK\x01\x02")
    record = struct.pack(
        "<4sQHHIIQQQQ",
        b"PK\x06\x06",
        44,
        45,
        45,
        0,
        0,
        entries,
        entries,
        eocd_at - directory_at,
        directory_at,
    )
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, len(head), 1)
    struct.pack_into("<H", tail, 8, 0xFFFF)
    struct.pack_into("<H", tail, 10, 0xFFFF)
    struct.pack_into("<I", tail, 12, 0xFFFFFFFF)
    struct.pack_into("<I", tail, 16, 0xFFFFFFFF)
    zip64 = io.BytesIO(head + record + locator + bytes(tail))

    assert len(inspect_zip(zip64, policy()).members) == 2

    zip64.seek(0)
    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(zip64, policy(max_members=1))
    assert raised.value.violation is ArchiveViolation.TOO_MANY_MEMBERS


def test_a_lying_entry_count_is_caught_by_the_recount() -> None:
    """Why the count is checked twice, and why the second check is not decorative.

    The preflight reads the entry count the end record declares, and that
    number is the archive's own claim. `zipfile` does not rely on it — it walks
    the directory by declared byte length — so an archive that understates the
    count slips past the preflight and is parsed in full anyway. Measured: an
    end record claiming one entry, thirteen parsed.

    The directory-size bound still holds, so the allocation stays bounded; it
    is the member limit that needs applying again to what was actually there.
    """

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for index in range(12):
            archive.writestr(zipfile.ZipInfo(f"d{index}/"), b"")
        info = zipfile.ZipInfo("roll.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, rows(40))
    data = bytearray(buf.getvalue())
    end_record = data.rindex(b"PK\x05\x06")
    struct.pack_into("<H", data, end_record + 8, 1)
    struct.pack_into("<H", data, end_record + 10, 1)

    with zipfile.ZipFile(io.BytesIO(bytes(data))) as parsed:
        assert len(parsed.infolist()) == 13, "the premise: the lie did not take"

    with pytest.raises(UnsafeArchiveError) as raised:
        inspect_zip(io.BytesIO(bytes(data)), policy(max_members=4))

    assert raised.value.violation is ArchiveViolation.TOO_MANY_MEMBERS
    assert "13 entries" in raised.value.detail
