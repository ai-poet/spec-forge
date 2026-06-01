from pathlib import Path

from specforge.documents.docs_scaffold import append_iteration_log, ensure_iteration_docs, ensure_project_docs, iteration_docs_root


def test_ensure_project_docs_creates_tree(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = ensure_project_docs(repo, project_name="demo", description="build a demo")
    assert (root / "00_convention.md").exists()
    assert (root / "01_project_goal.md").exists()
    assert (root / "02_iteration_log.md").exists()
    assert not (root / "03_invariants").exists()
    assert not (root / "04_decisions").exists()
    assert not (root / "spec-index.md").exists()
    assert (root / "spec").is_dir()
    assert (root / "iterations").is_dir()
    for stage in ("prd_planner", "test_planner", "coder", "code_tester"):
        assert (repo / ".specforge" / "skills" / stage).is_dir()
    convention = (root / "00_convention.md").read_text(encoding="utf-8")
    assert "Replace this stub" in convention
    assert "assert_text_match" not in convention


def test_ensure_iteration_docs_creates_iteration_folder(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    iteration_root = ensure_iteration_docs(repo, "iteration_001")
    assert iteration_root == iteration_docs_root(repo, "iteration_001")
    assert (iteration_root / "tests" / "unit").is_dir()
    assert (iteration_root / "clarifications").is_dir()
    assert (iteration_root / "discovery").is_dir()
    assert (iteration_root / "context").is_dir()
    assert not (iteration_root / "README.md").exists()


def test_append_iteration_log(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    append_iteration_log(repo, docs_slug="iteration_001", event="iteration.started", detail="planning")
    log = (repo / "docs" / "02_iteration_log.md").read_text(encoding="utf-8")
    assert "iteration_001" in log
    assert "iteration.started" in log
