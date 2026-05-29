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
    (root / "03_invariants").mkdir(exist_ok=True)
    (root / "04_decisions").mkdir(exist_ok=True)
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
    _write_if_missing(
        root / "03_invariants" / "data_invariants.md",
        _data_invariants_template(),
    )
    _write_if_missing(
        root / "03_invariants" / "security_invariants.md",
        _security_invariants_template(),
    )
    _write_if_missing(
        root / "03_invariants" / "performance_budgets.md",
        _performance_budgets_template(),
    )

    for filename, body in _adr_templates().items():
        _write_if_missing(root / "04_decisions" / filename, body)

    return root


def ensure_iteration_docs(repo_root: Path, docs_slug: str) -> Path:
    ensure_project_docs(repo_root, project_name=repo_root.name)
    iteration_root = iteration_docs_root(repo_root, docs_slug)
    (iteration_root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "ui").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "adversarial").mkdir(parents=True, exist_ok=True)
    (iteration_root / "tests" / "ui" / "recordings").mkdir(parents=True, exist_ok=True)
    (iteration_root / "clarifications").mkdir(parents=True, exist_ok=True)
    return iteration_root


def append_iteration_log(repo_root: Path, *, docs_slug: str, event: str, detail: str) -> None:
    ensure_project_docs(repo_root, project_name=repo_root.name)
    log_path = project_docs_root(repo_root) / "02_iteration_log.md"
    today = date.today().isoformat()
    entry = f"\n## {today} · {docs_slug}\n\n- **Event:** {event}\n- **Detail:** {detail}\n"
    if log_path.exists():
        log_path.write_text(log_path.read_text(encoding="utf-8").rstrip() + entry + "\n", encoding="utf-8")
    else:
        log_path.write_text(_iteration_log_template() + entry + "\n", encoding="utf-8")


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _convention_template() -> str:
    return """---
doc: convention
status: approved
created: 2026-05-28
owner: user
---

# Documentation Conventions

- All docs are plain markdown with YAML frontmatter.
- Links use relative paths, not wikilinks.
- Planner writes specs and protected tests; Coder writes `src/`; Tester writes verify reports and adversarial tests.
- Each iteration lives under `docs/system_design/iteration_NNN/`.
"""


def _project_goal_template(project_name: str, description: str) -> str:
    body = description.strip() or "Describe the project goal and success criteria here."
    return f"""---
doc: project_goal
status: draft
created: 2026-05-28
owner: user
checkpoint_a_until: 5
checkpoint_b_until: 5
---

# {project_name}

{body}
"""


def _iteration_log_template() -> str:
    return """---
doc: iteration_log
status: active
created: 2026-05-28
owner: user
---

# Iteration Log

Progressive record of pipeline iterations for this project.
"""


def _data_invariants_template() -> str:
    return """---
doc: invariant
status: draft
created: 2026-05-28
owner: user
---

# Data Invariants

- Document schema and data-shape constraints that must never be violated.
"""


def _security_invariants_template() -> str:
    return """---
doc: invariant
status: draft
created: 2026-05-28
owner: user
---

# Security Invariants

- Secrets never committed to git.
- Agent CLIs must not write outside allowed directories.
"""


def _performance_budgets_template() -> str:
    return """---
doc: invariant
status: draft
created: 2026-05-28
owner: user
---

# Performance Budgets

- Define latency, memory, and throughput budgets for critical paths.
"""


def _adr_templates() -> dict[str, str]:
    return {
        "ADR-001-langgraph.md": """---
doc: adr
status: accepted
created: 2026-05-28
owner: user
---

# ADR-001: LangGraph for Orchestration

Use LangGraph with SQLite checkpointer for typed state, HITL interrupts, and resumable pipelines.
""",
        "ADR-002-claude-code-sdk.md": """---
doc: adr
status: accepted
created: 2026-05-28
owner: user
---

# ADR-002: Claude Code CLI for Planner and Coder

Planner and Coder run as fresh Claude Code CLI sessions with JSON schema artifacts.
""",
        "ADR-003-cua-for-ui.md": """---
doc: adr
status: accepted
created: 2026-05-28
owner: user
---

# ADR-003: Cua Driver for UI Verification

UI tests are executed by Tester via CuaDriver, not as an independent LangGraph node.
When Cua is unavailable, web trajectories fall back to Playwright; native trajectories remain skipped with warning.
""",
        "ADR-004-model-family-split.md": """---
doc: adr
status: accepted
created: 2026-05-28
owner: user
---

# ADR-004: Split Model Families

Planner/Coder use Claude; Tester uses Codex to reduce planner-tester collusion.
""",
        "ADR-005-local-md-not-obsidian.md": """---
doc: adr
status: accepted
created: 2026-05-28
owner: user
---

# ADR-005: Local Markdown, Not Obsidian

Docs live in git as plain markdown; viewers can be added later without migration.
""",
        "ADR-006-relative-path-links.md": """---
doc: adr
status: accepted
created: 2026-05-28
owner: user
---

# ADR-006: Relative Path Links

Cross-doc links use relative file paths for portability.
""",
    }
