from __future__ import annotations

from pathlib import Path


_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt_template(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt(name: str, **variables: str) -> str:
    template = load_prompt_template(name)
    try:
        return template.format(**variables)
    except KeyError as exc:
        raise ValueError(f"missing prompt variable for {name}: {exc}") from exc
