from __future__ import annotations

from pathlib import Path

from specforge.policy.artifact_gate import read_convention_excerpt, read_framework_conventions, read_spec_index


def test_read_framework_conventions_returns_rules() -> None:
    text = read_framework_conventions()
    assert "Write zones" in text
    assert "Do not create `tests/ui/*.json` specs" in text
    assert "React + Vite" in text
    assert "Less Modules" in text
    assert "UI/UX usability" in text
    assert "visual polish" in text
    assert "fault-tolerant" in text
    assert "routes/controllers" in text
    assert "application services/use cases" in text
    assert "APIRouter" in text
    assert "app.route()" in text
    assert "AppType" in text
    assert "supabase/migrations" in text
    assert "supabase/functions" in text
    assert "supabase/tests" in text
    assert "extensibility" in text
    assert "maintainability" in text
    assert "performance" in text
    assert "Electron" in text
    assert "Capacitor 7" in text


def test_read_spec_index_missing_returns_empty(tmp_path: Path) -> None:
    assert read_spec_index(tmp_path) == ""


def test_read_convention_excerpt_does_not_pull_missing_spec_index(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "00_convention.md").write_text("# Conv\n\nsrc/** only\n", encoding="utf-8")
    text = read_convention_excerpt(tmp_path)
    assert "src/**" in text
    assert "Spec index" not in text
