from __future__ import annotations

from pathlib import Path

from specforge.documents.docs_io import checksum
from specforge.policy.context_cache import CONTEXT_INDEX, format_planner_context, enrich_manifest_lines
from specforge.policy.context_manifest import ManifestLine, read_jsonl, write_jsonl


def test_enrich_manifest_adds_hash_and_summary_for_iteration_doc(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "iterations" / "iteration_001"
    docs_root.mkdir(parents=True)
    prd = docs_root / "prd.md"
    prd.write_text("# PRD\n\nShip the faster planning cache.\n", encoding="utf-8")

    [line] = enrich_manifest_lines(repo_root, docs_root, [ManifestLine(file="prd.md", reason="Approved PRD")])

    assert line.sha256 == checksum(prd)
    assert line.summary.startswith("PRD Ship the faster planning cache.")
    assert line.freshness == "fresh"
    assert (repo_root / CONTEXT_INDEX).exists()


def test_enrich_manifest_marks_source_without_summary_as_missing_summary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "iterations" / "iteration_001"
    src = repo_root / "src" / "app.py"
    docs_root.mkdir(parents=True)
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'ok'\n", encoding="utf-8")

    [line] = enrich_manifest_lines(repo_root, docs_root, [ManifestLine(file="src/app.py", reason="Entry point")])

    assert line.sha256 == checksum(src)
    assert line.summary == ""
    assert line.symbols == ["main"]
    assert line.public_api == ["main"]
    assert line.freshness == "missing-summary"


def test_enrich_manifest_reuses_cached_summary_when_hash_matches(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "iterations" / "iteration_001"
    src = repo_root / "src" / "app.py"
    docs_root.mkdir(parents=True)
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [
            ManifestLine(
                file="src/app.py",
                reason="Cached reason",
                summary="Cached source summary",
                sha256=checksum(src),
                freshness="fresh",
            )
        ],
    )

    [line] = enrich_manifest_lines(repo_root, docs_root, [ManifestLine(file="src/app.py", reason="Entry point")])

    assert line.summary == "Cached source summary"
    assert line.freshness == "fresh"


def test_enrich_manifest_marks_cached_summary_changed_when_hash_differs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "iterations" / "iteration_001"
    src = repo_root / "src" / "app.py"
    docs_root.mkdir(parents=True)
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'old'\n", encoding="utf-8")
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [
            ManifestLine(
                file="src/app.py",
                reason="Cached reason",
                summary="Cached source summary",
                sha256=checksum(src),
                freshness="fresh",
            )
        ],
    )
    src.write_text("def main():\n    return 'new'\n", encoding="utf-8")

    [line] = enrich_manifest_lines(repo_root, docs_root, [ManifestLine(file="src/app.py", reason="Entry point")])

    assert line.sha256 == checksum(src)
    assert line.summary == "Cached source summary"
    assert line.freshness == "changed"
    [cached] = read_jsonl(repo_root / CONTEXT_INDEX)
    assert cached.sha256 != checksum(src)
    assert cached.freshness == "changed"


def test_changed_manifest_line_stays_changed_on_next_enrich(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "iterations" / "iteration_001"
    src = repo_root / "src" / "app.py"
    docs_root.mkdir(parents=True)
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'old'\n", encoding="utf-8")
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [
            ManifestLine(
                file="src/app.py",
                reason="Cached reason",
                summary="Cached source summary",
                sha256=checksum(src),
                freshness="fresh",
            )
        ],
    )
    src.write_text("def main():\n    return 'new'\n", encoding="utf-8")

    [changed] = enrich_manifest_lines(repo_root, docs_root, [ManifestLine(file="src/app.py", reason="Entry point")])
    [line] = enrich_manifest_lines(repo_root, docs_root, [changed])

    assert line.summary == "Cached source summary"
    assert line.freshness == "changed"


def test_enrich_manifest_marks_missing_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs_root = repo_root / "docs" / "iterations" / "iteration_001"
    docs_root.mkdir(parents=True)

    [line] = enrich_manifest_lines(repo_root, docs_root, [ManifestLine(file="src/missing.py", reason="Missing")])

    assert line.freshness == "missing"
    assert line.sha256 is None


def test_format_planner_context_empty_cache(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    text = format_planner_context(repo_root)

    assert "No cached project context yet" in text


def test_format_planner_context_includes_fresh_cached_entry(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    src = repo_root / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [
            ManifestLine(
                file="src/app.py",
                reason="Application entry",
                summary="Cached app summary",
                sha256=checksum(src),
                freshness="fresh",
            )
        ],
    )

    text = format_planner_context(repo_root)

    assert "Planner project context cache" in text
    assert "file: src/app.py" in text
    assert "freshness: fresh" in text
    assert "Cached app summary" in text


def test_format_planner_context_marks_changed_entry(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    src = repo_root / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'old'\n", encoding="utf-8")
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [
            ManifestLine(
                file="src/app.py",
                reason="Application entry",
                summary="Old app summary",
                sha256=checksum(src),
                freshness="fresh",
            )
        ],
    )
    src.write_text("def main():\n    return 'new'\n", encoding="utf-8")

    text = format_planner_context(repo_root)

    assert "file: src/app.py" in text
    assert "freshness: changed" in text
    assert "Old app summary" in text


def test_format_planner_context_marks_missing_entry(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [ManifestLine(file="src/missing.py", reason="Missing source", summary="Old summary", sha256="abc", freshness="fresh")],
    )

    text = format_planner_context(repo_root)

    assert "file: src/missing.py" in text
    assert "freshness: missing" in text


def test_format_planner_context_marks_missing_summary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    src = repo_root / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    write_jsonl(
        repo_root / CONTEXT_INDEX,
        [ManifestLine(file="src/app.py", reason="Application entry", sha256=checksum(src), freshness="missing-summary")],
    )

    text = format_planner_context(repo_root)

    assert "file: src/app.py" in text
    assert "freshness: missing-summary" in text
    assert "no cached summary" in text


def test_format_planner_context_includes_stable_project_docs(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    docs = repo_root / "docs"
    docs.mkdir(parents=True)
    (docs / "00_convention.md").write_text("# Conventions\n\nUse src for application code.\n", encoding="utf-8")

    text = format_planner_context(repo_root)

    assert "file: docs/00_convention.md" in text
    assert "Use src for application code." in text


def test_format_planner_context_respects_limits(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    lines: list[ManifestLine] = []
    for index in range(10):
        path = repo_root / "src" / f"file_{index}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"def item_{index}():\n    return {index}\n", encoding="utf-8")
        lines.append(
            ManifestLine(
                file=f"src/file_{index}.py",
                reason="Many files",
                summary="x" * 80,
                sha256=checksum(path),
                freshness="fresh",
            )
        )
    write_jsonl(repo_root / CONTEXT_INDEX, lines)

    text = format_planner_context(repo_root, max_entries=3, max_chars=700)

    assert text.count("- file:") <= 3
    assert len(text) <= 700
