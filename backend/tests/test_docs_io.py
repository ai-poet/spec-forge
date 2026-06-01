from pathlib import Path

from specforge.documents.docs_io import checksum, checksum_paths


def test_checksum(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    assert checksum(path)

