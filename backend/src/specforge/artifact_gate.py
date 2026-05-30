from __future__ import annotations

import subprocess
from pathlib import Path


def run_project_commands(repo_root: Path, *, build_command: str | None, test_command: str | None) -> tuple[bool, str]:
    for label, command in (("build", build_command), ("test", test_command)):
        if not command or not command.strip():
            continue
        result = subprocess.run(
            command,
            shell=True,
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            output = (result.stderr or result.stdout or "").strip()
            summary = output.splitlines()[-1] if output else f"{label} command failed"
            return False, f"{label} command failed ({command}): {summary}"
    return True, ""


def read_convention_excerpt(repo_root: Path, *, max_chars: int = 1800) -> str:
    path = repo_root / "docs" / "00_convention.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
