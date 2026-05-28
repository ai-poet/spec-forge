from pathlib import Path

from specforge.docs_scaffold import append_iteration_log, ensure_iteration_docs, ensure_project_docs, iteration_docs_root


def test_ensure_project_docs_creates_tree(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = ensure_project_docs(repo, project_name="demo", description="build a demo")
    assert (root / "00_convention.md").exists()
    assert (root / "01_project_goal.md").exists()
    assert (root / "02_iteration_log.md").exists()
    assert (root / "03_invariants" / "data_invariants.md").exists()
    assert (root / "04_decisions" / "ADR-001-langgraph.md").exists()
    assert (root / "system_design").is_dir()


def test_ensure_iteration_docs_creates_iteration_folder(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    iteration_root = ensure_iteration_docs(repo, "iteration_001")
    assert iteration_root == iteration_docs_root(repo, "iteration_001")
    assert (iteration_root / "tests" / "unit").is_dir()
    assert (iteration_root / "clarifications").is_dir()


def test_append_iteration_log(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    append_iteration_log(repo, docs_slug="iteration_001", event="iteration.started", detail="planning")
    log = (repo / "docs" / "02_iteration_log.md").read_text(encoding="utf-8")
    assert "iteration_001" in log
    assert "iteration.started" in log
