"""Tests for the source-artifact repository guard."""

from pathlib import Path

from scripts.check_repository_artifacts import MAX_FILE_BYTES, violations_for_path


def _messages(root: Path, relative: str, content: bytes = b"safe") -> list[str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return violations_for_path(path, set(), root)


def test_accepts_normal_repository_text(tmp_path: Path) -> None:
    assert _messages(tmp_path, "docs/source-contract.md") == []


def test_rejects_prohibited_source_extension(tmp_path: Path) -> None:
    messages = _messages(tmp_path, "fixtures/accounts.csv")
    assert any("prohibited source-artifact extension: .csv" in message for message in messages)


def test_rejects_disguised_archive_by_magic(tmp_path: Path) -> None:
    messages = _messages(tmp_path, "fixtures/harmless.bin", b"PK\x03\x04synthetic")
    assert any("prohibited content signature: ZIP container" in message for message in messages)


def test_rejects_prohibited_data_directory(tmp_path: Path) -> None:
    messages = _messages(tmp_path, "docs/data/notes.md")
    assert any("prohibited source-data directory: data" in message for message in messages)


def test_rejects_file_inside_geodatabase(tmp_path: Path) -> None:
    messages = _messages(tmp_path, "fixtures/parcels.gdb/a00000001.gdbtable")
    assert any("prohibited geodatabase directory" in message for message in messages)


def test_rejects_large_unknown_file(tmp_path: Path) -> None:
    messages = _messages(tmp_path, "fixtures/release.bin", b"x" * (MAX_FILE_BYTES + 1))
    assert any("limit is" in message for message in messages)


def test_exact_allowlist_exception_is_narrow(tmp_path: Path) -> None:
    path = tmp_path / "tests/fixtures/synthetic.csv"
    path.parent.mkdir(parents=True)
    path.write_text("synthetic,value\nexample,1\n", encoding="utf-8")

    assert violations_for_path(path, {"tests/fixtures/synthetic.csv"}, tmp_path) == []
    other = tmp_path / "tests/fixtures/other.csv"
    other.write_text("not,allowed\n", encoding="utf-8")
    assert violations_for_path(other, {"tests/fixtures/synthetic.csv"}, tmp_path)
