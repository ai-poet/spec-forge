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
            "discovery_context": "Round 1 Q: scope?\nRound 1 A: MVP",
            "framework_conventions": "",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
        },
    )
    assert "## SpecForge stage: planner_discovery" in text
    assert "One question per turn" in text
    assert "Round 1 Q: scope?" in text


def test_compose_prd_planner_includes_context_manifest_anchor() -> None:
    text = compose_stage_prompt(
        "prd_planner",
        variables={
            "schema_hint": "{prd:string}",
            "brief": "Build feature X",
            "requirements_brief": "MVP scope for feature X",
            "discovery_qa": "(none)",
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
    assert "modification_plan" not in text


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


def test_compose_unknown_stage_raises() -> None:
    with pytest.raises(FileNotFoundError):
        list_stage_modules("not_a_stage")  # type: ignore[arg-type]
