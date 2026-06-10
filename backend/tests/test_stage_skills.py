from __future__ import annotations

from pathlib import Path

import pytest

from specforge.agents.prompt_loader import (
    compose_stage_prompt,
    compose_stage_prompt_modules,
    list_stage_modules,
    load_project_skill_extra,
)


def test_list_stage_modules_orders_skill_first_runtime_last() -> None:
    modules = list_stage_modules("prd_planner")
    assert modules[0] == "SKILL.md"
    assert modules[-1] == "runtime.md"
    assert "context-manifest.md" in modules


def test_compose_planner_discovery_includes_brief_context() -> None:
    text = compose_stage_prompt(
        "planner_discovery",
        variables={
            "schema_hint": "{status:ask|ready}",
            "brief": "Goal: feature X",
            "planner_context": "## Planner project context cache\nCached facts.",
            "discovery_context": "Round 1 Q: scope?\nRound 1 A: MVP",
            "framework_conventions": "",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
        },
    )
    assert "## SpecForge stage: planner_discovery" in text
    assert "Planner project context cache" in text
    assert "One question per turn" in text
    assert "Round 1 Q: scope?" in text
    assert "React + Vite" in text
    assert "frontend/**" in text
    assert "web/**" in text
    assert "backend/**" in text
    assert "Less Modules" in text
    assert "UI/UX usability" in text
    assert "fault-tolerant" in text
    assert "FastAPI" in text
    assert "HonoJS" in text
    assert "Supabase" in text
    assert "local SQLite" in text
    assert "其他（请说明）" in text
    assert "maintainability" in text
    assert "performance" in text
    assert "Electron" in text
    assert "Capacitor 7" in text


def test_compose_prd_planner_includes_context_manifest_anchor() -> None:
    text = compose_stage_prompt(
        "prd_planner",
        variables={
            "schema_hint": "{prd:string}",
            "brief": "Build feature X",
            "requirements_brief": "MVP scope for feature X",
            "discovery_qa": "(none)",
            "planner_context": "## Planner project context cache\nCached facts.",
            "framework_conventions": "Framework rules here.",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
        },
    )
    assert "## SpecForge stage: prd_planner" in text
    assert "context_for_coder" in text
    assert "context/for_tester.jsonl" in text
    assert "Build feature X" in text
    assert "Planner project context cache" in text
    assert "## Problem, Goals, and Scope" in text
    assert "## Completion Contract" in text
    assert "`Objective`, `Done When`, and 1-3 acceptance points" in text
    assert "Use layered strictness" in text
    assert "Blocked If" in text
    assert "high-risk" in text
    assert "## Technical Stack" in text
    assert "## Development Conventions" in text
    assert "## Project Structure and Change Targets" in text
    assert "candidate/suggested files or modules to modify or create" in text
    assert "`modify`, `create`, `remove`, `observe only`, or `N/A`" in text
    assert "advisory candidate surfaces" in text
    assert "Coder must inspect the current repository" in text
    assert "may deviate from the candidate list" in text
    assert "context_for_coder` and `context_for_tester` manifests" in text
    assert "not a line-by-line implementation checklist" in text
    assert "docs/00_convention.md" in text
    assert "React + Vite" in text
    assert "Less Modules" in text
    assert "UI/UX usability" in text
    assert "fault-tolerant" in text
    assert "transport routes/controllers" in text
    assert "application services/use cases" in text
    assert "flat backend directories" in text
    assert "layer- or feature-oriented folder structure" in text
    assert "APIRouter" in text
    assert "app.route()" in text
    assert "AppType" in text
    assert "local SQLite" in text
    assert "exception to the `backend/**` rule" in text
    assert "supabase/migrations" in text
    assert "supabase/functions" in text
    assert "supabase/tests" in text
    assert "maintainability" in text
    assert "performance" in text
    assert "main/preload/renderer" in text
    assert "Capacitor 7" in text
    assert "frontend/backend separation" in text
    assert "explicit API contracts" in text
    assert "## Functional Requirements" in text
    assert "## Non-Functional Requirements" in text
    assert "## API and Data Contracts" in text
    assert "## Testing and Acceptance Strategy" in text
    assert "## Risks and Locked Decisions" in text
    assert "Implementation-lock decisions" in text
    assert "source of truth/data store" in text
    assert "async/background processing model" in text
    assert "permission/security boundary" in text
    assert "performance/reliability targets" in text
    assert "authoritative pre-build contract" in text
    assert "Component/status map" in text
    assert "Boundary I/O" in text
    assert "`Trigger`, `Reads`, `Mechanism`, `Writes`, `Persistence`, `Failure/Retry`, and `Verification`" in text
    assert "system-boundary inputs and outputs" in text
    assert "Delta/override discipline" in text
    assert "durable vs transient state" in text
    assert "explicit NOT-included items" in text
    assert "generated docs, raw logs, or telemetry signals" in text
    assert "modification_plan" not in text


def test_compose_test_planner_includes_planner_context() -> None:
    text = compose_stage_prompt(
        "test_planner",
        variables={
            "schema_hint": "{testing_plan:string}",
            "brief": "Build feature X",
            "requirements_brief": "MVP scope for feature X",
            "failure_notes": "(none)",
            "planner_context": "## Planner project context cache\nCached facts.",
            "framework_conventions": "",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
            "artifact_retry": "",
            "runtime_notes": "",
        },
    )
    assert "## SpecForge stage: test_planner" in text
    assert "Planner project context cache" in text
    assert "Read `prd.md`" in text
    assert "## Acceptance Coverage" in text
    assert "maps the PRD's acceptance point(s) to evidence" in text
    assert "`N/A — reason`" in text
    assert "PRD's `Done When` conditions" in text


def test_compose_coder_includes_manifest_and_docs_root() -> None:
    text = compose_stage_prompt(
        "coder",
        variables={
            "docs_root": "/tmp/iter",
            "schema_hint": "{changed_paths:[]}",
            "failure_notes": "(none)",
            "framework_conventions": "",
            "convention_excerpt": "",
            "context_manifest": "- prd.md: design\n",
            "runtime_notes": "",
        },
    )
    assert "/tmp/iter" in text
    assert "prd.md" in text
    assert "src/**" in text
    assert "advisory planning context, not as a binding file-edit checklist" in text
    assert "inspect the current repository structure" in text
    assert "choose the final implementation surface" in text
    assert "## Coder execution discipline" in text
    assert "Preflight before editing" in text
    assert "Acceptance-driven implementation" in text
    assert "Deviation discipline" in text
    assert "Blast-radius control" in text
    assert "Clarify instead of guessing" in text
    assert "Artifact summary expectations" in text


def test_project_extra_appended_when_present(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    extra_dir = repo / ".specforge" / "skills" / "coder"
    extra_dir.mkdir(parents=True)
    (extra_dir / "extra.md").write_text("Use pnpm only.", encoding="utf-8")

    text = compose_stage_prompt(
        "coder",
        repo_root=repo,
        variables={
            "docs_root": "/iter",
            "schema_hint": "{}",
            "failure_notes": "",
            "framework_conventions": "",
            "convention_excerpt": "",
            "context_manifest": "",
            "runtime_notes": "",
        },
    )
    assert "Use pnpm only." in text
    modules = compose_stage_prompt_modules("coder", repo_root=repo)
    assert "extra.md" in modules


def test_load_project_skill_extra_missing_returns_none(tmp_path: Path) -> None:
    assert load_project_skill_extra(tmp_path, "prd_planner") is None


def test_compose_code_tester_includes_verify_and_execution_mode() -> None:
    text = compose_stage_prompt(
        "code_tester",
        variables={
            "repo_root": "/proj",
            "docs_root": "/proj/docs/iter",
            "schema_hint": "{passed:boolean}",
            "test_command_section": "Configured test command: pytest.",
            "build_command_section": "",
            "retry_notes_section": "",
            "framework_conventions": "",
            "convention_excerpt": "",
            "context_manifest": "",
            "runtime_notes": "",
            "execution_mode": "Run verification and inspect user-facing behavior.",
        },
    )
    assert "tests/adversarial" in text
    assert "pytest." in text
    assert "Run verification" in text


def test_compose_ui_tester_includes_tool_routing() -> None:
    text = compose_stage_prompt(
        "ui_tester",
        variables={
            "repo_root": "/proj",
            "docs_root": "/proj/docs/iter",
            "schema_hint": "{passed:boolean}",
            "pwcli_wrapper": "/proj/backend/prompts/skills/playwright/scripts/playwright_cli.sh",
            "playwright_install_hint": "npx playwright-cli install-browser",
            "cua_install_hint": "install cua-driver",
            "code_tester_artifact_json": '{"passed": true}',
            "testing_plan_section": "### MT-01: Web smoke",
            "prd_section": "# PRD\n\nWeb smoke acceptance.",
            "cua_session_section": "CuaDriver session: available",
        },
    )
    assert "playwright-cli" in text
    assert "cua-driver" in text
    assert "MT-01: Web smoke" in text
    assert "Never return `passed: true` with P0/P1 defects." in text
    assert "Tool or environment problems" in text


def test_compose_unknown_stage_raises() -> None:
    with pytest.raises(FileNotFoundError):
        list_stage_modules("not_a_stage")  # type: ignore[arg-type]
