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
