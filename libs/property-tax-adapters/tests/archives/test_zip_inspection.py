"""Archive inspection, and the bounds that keep applying while extracting.

Every archive here is built in the test that uses it. Nothing is committed, and
no county archive is read — the shapes that matter are structural, and a
structure can be constructed.
"""

from __future__ import annotations

import io
import random
import zipfile

import pytest
from property_tax_adapters.archives import extract_member, inspect_zip, iter_member_chunks
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
        list(iter_member_chunks(archive, "roll.txt", policy()))

    assert raised.value.violation is ArchiveViolation.CORRUPT_MEMBER
    assert raised.value.member == "roll.txt"


def test_a_rewritten_size_never_yields_more_than_it_declared() -> None:
    """Nothing beyond the declared size is handed to a caller, even before the
    checksum fails."""

    payload = ROW * 4_000
    archive = understating_archive(declared=64, actual=payload)
    delivered = 0

    with pytest.raises(UnsafeArchiveError):
        for chunk in iter_member_chunks(archive, "roll.txt", policy()):
            delivered += len(chunk)

    assert delivered <= 64, f"{delivered} bytes were delivered against a declared 64"


def test_a_truncated_archive_is_a_corrupt_member_not_a_crash() -> None:
    """A caller should get this vocabulary, not a zipfile exception."""

    archive = build({"roll.txt": rows(500)})
    data = bytearray(archive.getvalue())
    # Corrupt the compressed payload without touching the directory.
    data[60:80] = b"\x00" * 20

    with pytest.raises(UnsafeArchiveError) as raised:
        list(iter_member_chunks(io.BytesIO(bytes(data)), "roll.txt", policy()))

    assert raised.value.violation is ArchiveViolation.CORRUPT_MEMBER


def test_a_member_overstating_its_size_is_refused_without_inspection() -> None:
    """Extraction enforces the ceiling too, since it can be called on its own."""

    archive = build({"roll.txt": ROW * 400})

    with pytest.raises(UnsafeArchiveError) as raised:
        list(iter_member_chunks(archive, "roll.txt", policy(max_member_bytes=100)))

    assert raised.value.violation is ArchiveViolation.MEMBER_TOO_LARGE


def test_a_conforming_member_extracts_whole() -> None:
    payload = ROW * 3_000
    archive = build({"roll.txt": payload})
    sink = io.BytesIO()

    written = extract_member(archive, "roll.txt", sink, policy())

    assert written == len(payload)
    assert sink.getvalue() == payload


def test_extraction_re_checks_the_structural_rules() -> None:
    """A caller reaching straight for a member does not skip the judgement."""

    archive = build({"payload.exe": ROW})

    with pytest.raises(UnsafeArchiveError) as raised:
        list(iter_member_chunks(archive, "payload.exe", policy()))

    assert raised.value.violation is ArchiveViolation.UNSUPPORTED_MEDIA_TYPE


def test_a_member_that_is_not_there_is_named_as_such() -> None:
    with pytest.raises(UnsafeArchiveError) as raised:
        list(iter_member_chunks(build({"roll.txt": ROW}), "absent.txt", policy()))

    assert raised.value.violation is ArchiveViolation.UNREADABLE_ARCHIVE


def test_extraction_never_holds_the_member_whole() -> None:
    """Chunked for the same reason acquisition is: size must not become memory."""

    payload = rows(60_000)
    sizes = [
        len(chunk)
        for chunk in iter_member_chunks(build({"roll.txt": payload}), "roll.txt", policy())
    ]

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
    assert len(ArchiveViolation) == 9


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
        ({"allowed_suffixes": frozenset()}, "at least one suffix"),
        ({"allowed_suffixes": frozenset({"txt"})}, "begin with a dot"),
        ({"allowed_suffixes": frozenset({".TXT"})}, "lowercase"),
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
