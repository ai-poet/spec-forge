from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..context_profiles import stage_profile_prompt

StageName = Literal[
    "prd_planner",
    "test_planner",
    "planner_discovery",
    "planner_clarification",
    "coder",
    "code_tester",
    "ui_tester",
    "log_summarizer",
    "artifact_comparator",
]

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_STAGES_DIR = _PROMPTS_DIR / "stages"
_PROJECT_SKILLS_DIR = ".specforge/skills"
_ARTIFACT_CONTRACT = """## Final Artifact Contract
At the end of your final response, output exactly one SpecForge artifact block:

<specforge_artifact>
{ ...valid JSON matching the stage contract... }
</specforge_artifact>

Rules:
- Put the complete JSON artifact inside the tags.
- Do not wrap the artifact JSON in Markdown fences inside the tags.
- Do not write anything after </specforge_artifact>.
- If you need to explain work, do it before the artifact block."""


def list_stage_modules(stage: StageName) -> list[str]:
    stage_dir = _STAGES_DIR / stage
    if not stage_dir.is_dir():
        raise FileNotFoundError(f"stage skills not found: {stage_dir}")
    names = sorted(p.name for p in stage_dir.glob("*.md"))
    ordered: list[str] = []
    if "SKILL.md" in names:
        ordered.append("SKILL.md")
    for name in names:
        if name not in {"SKILL.md", "runtime.md"}:
            ordered.append(name)
    if "runtime.md" in names:
        ordered.append("runtime.md")
    return ordered


def load_stage_module(stage: StageName, module: str) -> str:
    path = _STAGES_DIR / stage / module
    if not path.exists():
        raise FileNotFoundError(f"stage module not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_project_skill_extra(repo_root: Path | None, stage: StageName) -> str | None:
    if repo_root is None:
        return None
    path = repo_root / _PROJECT_SKILLS_DIR / stage / "extra.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


def compose_stage_prompt(
    stage: StageName,
    *,
    repo_root: Path | None = None,
    variables: dict[str, str] | None = None,
) -> str:
    """Assemble built-in stage skills, optional project extra, and runtime variables."""
    vars_map = variables or {}
    vars_map.setdefault("artifact_retry", "")
    vars_map.setdefault("runtime_notes", "")
    modules = list_stage_modules(stage)
    skill_chunks: list[str] = []
    runtime_template: str | None = None

    for module in modules:
        content = load_stage_module(stage, module)
        if module == "runtime.md":
            runtime_template = content
        else:
            skill_chunks.append(_format_template(content, stage, **vars_map))

    parts: list[str] = [f"## SpecForge stage: {stage}"]
    if skill_chunks:
        parts.append("\n\n---\n\n".join(skill_chunks))

    profile = stage_profile_prompt(repo_root, stage)
    if profile:
        parts.append(profile)

    extra = load_project_skill_extra(repo_root, stage)
    if extra:
        parts.append(extra)

    parts.append("## Runtime context")
    if runtime_template is not None:
        parts.append(_format_template(runtime_template, stage, **vars_map))
    elif vars_map:
        parts.append(_join_variable_sections(vars_map))
    parts.append(_ARTIFACT_CONTRACT)
    return "\n\n".join(parts)


def compose_stage_prompt_modules(
    stage: StageName,
    *,
    repo_root: Path | None = None,
) -> list[str]:
    """Return module filenames that would be loaded (including extra.md if present)."""
    modules = list(list_stage_modules(stage))
    if load_project_skill_extra(repo_root, stage):
        modules.append("extra.md")
    return modules


def _join_variable_sections(variables: dict[str, str]) -> str:
    sections: list[str] = []
    for key, value in variables.items():
        if value:
            sections.append(value)
    return "\n\n".join(sections)


def _format_template(template: str, name: str, **variables: str) -> str:
    try:
        return template.format(**variables)
    except KeyError as exc:
        raise ValueError(f"missing prompt variable for {name}: {exc}") from exc
