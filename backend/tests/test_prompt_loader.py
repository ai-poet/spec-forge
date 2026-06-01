from __future__ import annotations

from specforge.prompt_loader import render_prompt


def test_render_coder_prompt_includes_placeholders() -> None:
    text = render_prompt(
        "coder",
        docs_root="/tmp/iter",
        schema_hint="{changed_paths:[]}",
        failure_notes="none",
        framework_conventions="",
        convention_excerpt="",
        context_manifest="- system_design.md: design\n",
        runtime_notes="",
    )
    assert "/tmp/iter" in text
    assert "system_design.md" in text
