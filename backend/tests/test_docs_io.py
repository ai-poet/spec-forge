from pathlib import Path

from specforge.documents.docs_io import checksum, checksum_paths, compare_planning_integrity, planning_integrity_manifest


def test_checksum(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    assert checksum(path)


def write_planning_docs(root: Path) -> None:
    (root / "context").mkdir(parents=True, exist_ok=True)
    (root / "prd.md").write_text("# PRD\n", encoding="utf-8")
    (root / "testing_plan.md").write_text("# Testing Plan\n", encoding="utf-8")
    (root / "context" / "for_coder.jsonl").write_text('{"file":"prd.md"}\n', encoding="utf-8")
    (root / "context" / "for_tester.jsonl").write_text('{"file":"prd.md"}\n', encoding="utf-8")


def test_planning_integrity_detects_modified_document(tmp_path: Path):
    write_planning_docs(tmp_path)
    baseline = planning_integrity_manifest(tmp_path)

    (tmp_path / "testing_plan.md").write_text("# Tampered\n", encoding="utf-8")

    assert compare_planning_integrity(tmp_path, baseline) == [
        "modified planning document: testing_plan.md",
    ]


def test_planning_integrity_detects_missing_context_manifest(tmp_path: Path):
    write_planning_docs(tmp_path)
    baseline = planning_integrity_manifest(tmp_path)

    (tmp_path / "context" / "for_coder.jsonl").unlink()

    assert compare_planning_integrity(tmp_path, baseline) == [
        "missing planning document: context/for_coder.jsonl",
    ]
