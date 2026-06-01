from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

CliProvider = Literal["claude", "codex"]
CliStage = Literal["planner", "planner_discovery", "planner_clarification", "coder", "tester"]

DEFAULT_CLI_BINDINGS: dict[CliStage, CliProvider] = {
    "planner": "claude",
    "planner_discovery": "claude",
    "planner_clarification": "claude",
    "coder": "claude",
    "tester": "claude",
}


def resolve_cli_provider(bindings: Optional[dict[str, str]], stage: CliStage) -> CliProvider:
    if bindings:
        value = bindings.get(stage)
        if value in ("claude", "codex"):
            return value  # type: ignore[return-value]
    return DEFAULT_CLI_BINDINGS[stage]


def parse_cli_bindings(raw: Optional[str]) -> Optional[dict[str, str]]:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): str(value) for key, value in payload.items() if value in ("claude", "codex")}


def serialize_cli_bindings(bindings: Optional[dict[str, str]]) -> Optional[str]:
    if not bindings:
        return None
    cleaned = {key: bindings[key] for key in DEFAULT_CLI_BINDINGS if bindings.get(key) in ("claude", "codex")}
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _claude_command(prompt: str, schema: str | Path) -> list[str]:
    schema_arg = str(schema)
    return [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--permission-mode",
        "bypassPermissions",
        "--verbose",
        "--include-partial-messages",
        "--include-hook-events",
        "--json-schema",
        schema_arg,
        prompt,
    ]


def _codex_command(prompt: str, schema_file: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--dangerously-bypass-approvals-and-sandbox",
        "--output-schema",
        str(schema_file),
        "--skip-git-repo-check",
        prompt,
    ]


def build_planner_command(*, provider: CliProvider, prompt: str, schema_inline: str, schema_file: Path) -> list[str]:
    if provider == "codex":
        return _codex_command(prompt, schema_file)
    return _claude_command(prompt, schema_inline)


def build_planner_discovery_command(*, provider: CliProvider, prompt: str, schema_inline: str, schema_file: Path) -> list[str]:
    if provider == "codex":
        return _codex_command(prompt, schema_file)
    return _claude_command(prompt, schema_inline)


def build_planner_clarification_command(*, provider: CliProvider, prompt: str, schema_inline: str, schema_file: Path) -> list[str]:
    if provider == "codex":
        return _codex_command(prompt, schema_file)
    return _claude_command(prompt, schema_inline)


def build_coder_command(*, provider: CliProvider, prompt: str, schema_inline: str, schema_file: Path) -> list[str]:
    if provider == "codex":
        return _codex_command(prompt, schema_file)
    return _claude_command(prompt, schema_inline)


def build_tester_command(*, provider: CliProvider, prompt: str, schema_inline: str, schema_file: Path) -> list[str]:
    if provider == "codex":
        return _codex_command(prompt, schema_file)
    return _claude_command(prompt, schema_inline)
