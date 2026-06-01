from __future__ import annotations

from datetime import date
from pathlib import Path


def docs_slug_for_sequence(sequence: int) -> str:
    return f"iteration_{sequence:03d}"


def project_docs_root(repo_root: Path) -> Path:
    return repo_root / "docs"


def iteration_docs_root(repo_root: Path, docs_slug: str) -> Path:
    return project_docs_root(repo_root) / "system_design" / docs_slug


def ensure_project_docs(repo_root: Path, *, project_name: str, description: str | None = None) -> Path:
    root = project_docs_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "system_design").mkdir(exist_ok=True)

    _write_if_missing(
        root / "00_convention.md",
        _convention_template(),
    )
    _write_if_missing(
        root / "01_project_goal.md",
        _project_goal_template(project_name, description or ""),
    )
    _write_if_missing(
        root / "02_iteration_log.md",
        _iteration_log_template(),
    )

    (root / "spec").mkdir(exist_ok=True)

    ensure_project_skills(repo_root)

    return root


def ensure_project_skills(repo_root: Path) -> Path:
    """Create empty per-stage skill override directories (content is team-maintained)."""
    skills_root = repo_root / ".specforge" / "skills"
    for stage in ("planner", "coder", "tester"):
        (skills_root / stage).mkdir(parents=True, exist_ok=True)
    return skills_root


def ensure_iteration_docs(repo_root: Path, docs_slug: str) -> Path:
    ensure_project_docs(repo_root, project_name=repo_root.name)
    iteration_root = iteration_docs_root(repo_root, docs_slug)
    (iteration_root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "ui").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "adversarial").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "ui" / "recordings").mkdir(parents=True, exist_ok=True)
    (iteration_root / "clarifications").mkdir(parents=True, exist_ok=True)
    (iteration_root / "context").mkdir(parents=True, exist_ok=True)
    return iteration_root


def append_iteration_log(repo_root: Path, *, docs_slug: str, event: str, detail: str) -> Path:
    ensure_project_docs(repo_root, project_name=repo_root.name)
    log_path = project_docs_root(repo_root) / "02_iteration_log.md"
    today = date.today().isoformat()
    entry = f"\n## {today} · {docs_slug}\n\n- **Event:** {event}\n- **Detail:** {detail}\n"
    if log_path.exists():
        log_path.write_text(log_path.read_text(encoding="utf-8").rstrip() + entry + "\n", encoding="utf-8")
    else:
        log_path.write_text(_iteration_log_template() + entry + "\n", encoding="utf-8")
    return log_path


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _convention_template() -> str:
    return """---
doc: convention
status: draft
owner: user
---

# Project Conventions

Replace this stub with **this repository's** layout (source roots, test directories, import style).
Planner should update this file on the first iteration when it is still generic.

Keep SpecForge write zones: Coder → source only; Planner → protected tests; Tester → verify docs and `tests/adversarial/`.
"""


def _project_goal_template(project_name: str, description: str) -> str:
    body = description.strip() or "Describe the project goal and success criteria here."
    return f"""---
doc: project_goal
status: draft
owner: user
---

# {project_name}

{body}
"""


def _iteration_log_template() -> str:
    return """---
doc: iteration_log
status: active
owner: user
---

# Iteration Log

Program-appended audit trail for pipeline runs. Agent-authored docs live under `system_design/iteration_NNN/`.
"""
