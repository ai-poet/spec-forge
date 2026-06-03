from __future__ import annotations

from specforge.agents.prompt_loader import compose_stage_prompt


def test_render_coder_prompt_includes_placeholders() -> None:
    text = compose_stage_prompt(
        "coder",
        variables={
            "docs_root": "/tmp/iter",
            "schema_hint": "{changed_paths:[]}",
            "failure_notes": "none",
            "framework_conventions": "",
            "convention_excerpt": "",
            "context_manifest": "- prd.md: design\n",
            "runtime_notes": "",
        },
    )
    assert "/tmp/iter" in text
    assert "prd.md" in text


def test_planning_prompts_include_planner_context() -> None:
    planner_context = "## Planner project context cache\nCached project facts."
    discovery = compose_stage_prompt(
        "planner_discovery",
        variables={
            "schema_hint": "{status:ready}",
            "brief": "Goal",
            "planner_context": planner_context,
            "discovery_context": "",
            "framework_conventions": "",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
        },
    )
    prd = compose_stage_prompt(
        "prd_planner",
        variables={
            "schema_hint": "{prd:string}",
            "brief": "Goal",
            "requirements_brief": "Brief",
            "discovery_qa": "(none)",
            "planner_context": planner_context,
            "framework_conventions": "",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
        },
    )
    tests = compose_stage_prompt(
        "test_planner",
        variables={
            "schema_hint": "{testing_plan:string}",
            "brief": "Goal",
            "requirements_brief": "Brief",
            "failure_notes": "(none)",
            "planner_context": planner_context,
            "framework_conventions": "",
            "convention_excerpt": "",
            "workflow_state": "",
            "session_continuation": "",
        },
    )

    assert "Cached project facts." in discovery
    assert "Cached project facts." in prd
    assert "Cached project facts." in tests
